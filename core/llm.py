import json, logging

from ..core.config import API_KEY, MODEL, MAX_CONTEXT_TOKENS
from ..core.ratelimit import ratelimiter
from ..core.tier_config import tier_config
from ..tools.registry import registry
from ..tools.working_memory import working_memory
from ..tools.tool_search import _discovered_tools
from ..llm.factory import create_provider
from ..llm.base import Message

logger = logging.getLogger("xens.llm")

_WM_MARKER = "[WORKING MEMORY]"

CORE_TOOLS = {
    "read_file", "write_file", "list_dir", "grep_files",
    "web_search", "web_fetch",
    "run_command", "execute_code",
    "system_info",
    "screenshot", "read_screen",
    "speak", "listen",
    "list_categories", "get_tool_schemas",
}

_provider = None

def get_provider():
    global _provider
    if _provider is None:
        from ..core.config import config
        _provider = create_provider(config)
    return _provider

def _to_llm_messages(raw_messages):
    result = []
    for m in raw_messages:
        msg = Message(
            role=m.get("role", ""),
            content=m.get("content", ""),
            tool_calls=m.get("tool_calls"),
            tool_call_id=m.get("tool_call_id"),
            name=m.get("name"),
        )
        result.append(msg)
    return result

def _to_tool_schemas():
    available = set(registry.tool_names)
    include = CORE_TOOLS | _discovered_tools
    names = [n for n in include if n in available]
    return registry.get_schemas_by_names(names)

async def _trim_context(messages, provider, max_tokens=MAX_CONTEXT_TOKENS):
    token_counts = []
    for m in messages:
        text = json.dumps(m, ensure_ascii=False)
        token_counts.append(await provider.count_tokens(text))

    total = sum(token_counts)
    if total <= max_tokens:
        return

    to_keep = [messages[0]]
    keep_tokens = token_counts[0]

    for i in range(len(messages) - 1, 0, -1):
        if keep_tokens + token_counts[i] <= max_tokens:
            to_keep.insert(1, messages[i])
            keep_tokens += token_counts[i]

    dropped = len(messages) - len(to_keep)
    if dropped > 0:
        summary = {"role": "system", "content": f"[{dropped} mensajes anteriores omitidos por límite de contexto. Usa /profile para ver el resumen guardado.]"}
        st = await provider.count_tokens(json.dumps(summary, ensure_ascii=False))
        if keep_tokens + st <= max_tokens:
            to_keep.insert(1, summary)
            logger.info(f"Context trimmed: kept {len(to_keep)}, dropped {dropped}")
        else:
            logger.info(f"Context trimmed: kept {len(to_keep)}, dropped {dropped} (no room for summary)")

    messages.clear()
    messages.extend(to_keep)

def _refresh_working_memory(messages):
    snap = working_memory.snapshot()
    content = _WM_MARKER + "\n" + (json.dumps(snap, indent=2, ensure_ascii=False) if snap else "(vacia)")
    for m in messages:
        if m.get("role") == "system" and isinstance(m.get("content"), str) and m["content"].startswith(_WM_MARKER):
            m["content"] = content
            return
    messages.insert(1, {"role": "system", "content": content})

async def run_tool_loop(messages, max_iterations=5, tier="free"):
    provider = get_provider()

    allowed, remaining, limit, reset_sec = ratelimiter.check(tier)
    if not allowed:
        reset_h = reset_sec // 3600
        reset_m = (reset_sec % 3600) // 60
        msg = f"Daily limit reached ({limit}/{limit}). Resets in ~{reset_h}h{reset_m}m. Upgrade your plan for more."
        yield {"type": "error", "content": f"\n[Rate limit: {msg}]"}
        messages.append({"role": "system", "content": f"[RATE LIMITED: {msg}]"})
        return

    ratelimiter.record(tier)
    _refresh_working_memory(messages)
    await _trim_context(messages, provider)

    for iteration in range(max_iterations):
        llm_messages = _to_llm_messages(messages)
        tools = _to_tool_schemas()

        try:
            result = await provider.chat(llm_messages, tools=tools, tier=tier)
        except Exception as e:
            logger.error(f"LLM chat error: {e}")
            msg = f"Error del proveedor LLM: {e}. Por favor intenta de nuevo."
            messages.append({"role": "user", "content": msg})
            yield {"type": "error", "content": f"\n[Error LLM: {e}]"}
            continue

        if result.content:
            messages.append({"role": "assistant", "content": result.content})
            yield {"type": "content", "content": result.content}

        if not result.tool_calls:
            return

        assistant_msg = {
            "role": "assistant",
            "content": result.content or None,
            "tool_calls": result.tool_calls,
        }
        messages.append(assistant_msg)

        has_errors = False

        for tc_index, tc in enumerate(result.tool_calls):
            tc_id = tc.get("id", f"tc_{iteration}_{tc_index}")

            try:
                name = tc["function"]["name"]
            except (KeyError, TypeError):
                name = "?"
                msg = f"Tool call malformada: falta function.name. Raw: {json.dumps(tc)}"
                yield {"type": "error", "content": msg}
                messages.append({"role": "tool", "tool_call_id": tc_id, "name": "", "content": json.dumps({"error": msg, "success": False})})
                has_errors = True
                continue

            raw_args = ""
            args = {}
            try:
                raw_args = tc["function"].get("arguments", "")
                args = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError as e:
                yield {"type": "tool_call", "name": name, "args": {}}
                msg = f"Error decodificando argumentos de '{name}': {e}. Argumentos raw: {raw_args}. Corrige el JSON."
                messages.append({"role": "tool", "tool_call_id": tc_id, "name": name, "content": json.dumps({"error": msg, "success": False})})
                has_errors = True
                continue

            arg_str = ", ".join(f"{k}={v}" for k, v in args.items() if v is not None)
            yield {"type": "tool_call", "name": name, "args": args}

            try:
                output = await registry.execute(name, args)
            except Exception as e:
                output = json.dumps({"error": f"Error ejecutando '{name}': {e}", "success": False})

            content = output if isinstance(output, str) else json.dumps(output)

            parsed = None
            is_success = True
            try:
                parsed = json.loads(content) if isinstance(content, str) else content
                if isinstance(parsed, dict):
                    is_success = parsed.get("success", False)
                    yield {"type": "tool_result", "name": name, "success": is_success}
                    if "screenshot" in parsed:
                        yield {"type": "screenshot", "base64": parsed["screenshot"]["base64"],
                               "width": parsed["screenshot"]["width"], "height": parsed["screenshot"]["height"]}
                else:
                    yield {"type": "tool_result", "name": name}
            except Exception:
                is_success = False
                yield {"type": "tool_result", "name": name}

            if not is_success:
                has_errors = True

            stored = content
            if isinstance(parsed, dict) and "screenshot" in parsed:
                safe = dict(parsed)
                del safe["screenshot"]
                stored = json.dumps(safe)
            messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "name": name,
                "content": stored,
            })

        if has_errors:
            yield {"type": "content", "content": "\n"}

        _refresh_working_memory(messages)

    async for chunk in provider.chat_stream(_to_llm_messages(messages), tier=tier):
        yield {"type": "content", "content": chunk}
