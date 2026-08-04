import asyncio, sys, logging, shutil, json

from ..core.llm import run_tool_loop
from ..memory.session import Session
from ..memory.profile import profile
from ..memory.summarizer import summarize_conversation, extract_user_info
from ..personality import build_system
from ..core.config import USER_NAME, config, CONFIG_FILE
from ..tools.registry import registry
from ..tools.proactive import get_engine as get_proactive
from ..core.ratelimit import ratelimiter
from ..core.tier_config import tier_config
from ..core.updater import get_current_version

logger = logging.getLogger("xens.chat")

_CYAN = "\033[36m"
_YELLOW = "\033[33m"
_GREEN = "\033[92m"
_RED = "\033[91m"
_GRAY = "\033[90m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _mask(key: str) -> str:
    if not key:
        return "(not set)"
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "…" + key[-4:]


class ConsoleChat:
    def __init__(self, session=None):
        self._session = session or Session("default")

    def _build_messages(self):
        profile.load()
        memory_ctx = profile.get_memory_context()
        system = build_system(memory_context=memory_ctx)
        messages = [{"role": "system", "content": system}]
        ctx = self._session.get_context(25)
        for m in ctx:
            messages.append({"role": m["role"], "content": m["content"]})
        return messages

    def _banner(self):
        tier = registry.get_tier()
        used, limit = ratelimiter.get_usage(tier)
        providers = self._provider_status()
        print(f"\n  {_BOLD}Xens Assistant CLI v{get_current_version()}{_RESET}")
        print(f"  {_GRAY}Tools:{_RESET} {registry.count}/{registry.count_total}  "
              f"{_GRAY}Tier:{_RESET} {tier}  {_GRAY}Usage:{_RESET} {used}/{limit} req")
        print(f"  {_GRAY}Providers:{_RESET} {providers}")
        print(f"  {_GRAY}Config:{_RESET} {CONFIG_FILE}")
        print(f"  {_GRAY}Tip:{_RESET} type /help for commands\n")

    def _provider_status(self) -> str:
        parts = []
        for name in ("mistral", "openai", "openrouter"):
            cfg = config.get("llm", {}).get(name, {})
            if cfg.get("api_key"):
                parts.append(f"{name}({_mask(cfg['api_key'])})")
        if not parts:
            parts.append(f"{_RED}no API keys — chat disabled, /test works{_RESET}")
        return ", ".join(parts)

    async def run(self):
        name = profile.name or USER_NAME or "there"
        messages = self._build_messages()
        self._banner()

        if not self._session.messages:
            welcome = f"Hey {name}. Good to see you. What are we working on today?"
            print(f"\n  {_CYAN}Xens:{_RESET} {welcome}\n")
            self._session.add("assistant", welcome)
            messages.append({"role": "assistant", "content": welcome})
        else:
            count = profile.interaction_count + 1
            print(f"\n  {_CYAN}Xens{_RESET} — {count} interactions so far.\n")

        while True:
            sug = get_proactive().pop_suggestion()
            if sug:
                print(f"  {_YELLOW}💡 {sug['message']}{_RESET}")
            try:
                raw = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input(f"  {_YELLOW}You [{registry.get_tier()}]:{_RESET} ").strip()
                )
            except (EOFError, KeyboardInterrupt):
                print(f"\n  {_CYAN}Xens:{_RESET} Later, {name}.\n")
                self._session.flush()
                profile.flush()
                break

            if not raw:
                continue

            if raw.lower() in ("exit", "quit", "bye"):
                print(f"  {_CYAN}Xens:{_RESET} Later, {name}.\n")
                self._session.flush()
                profile.flush()
                break

            if raw.startswith("/"):
                await self._handle_command(raw, messages)
                continue

            profile.record_interaction()
            self._session.add("user", raw)
            messages.append({"role": "user", "content": raw})

            tier = registry.get_tier()
            full = ""
            try:
                async for chunk in run_tool_loop(messages, tier=tier):
                    if isinstance(chunk, dict):
                        if chunk["type"] == "content":
                            full += chunk["content"]
                            print(chunk["content"], end="", flush=True)
                        elif chunk["type"] == "tool_call":
                            name_t = chunk["name"]
                            args = chunk.get("args", {})
                            arg_str = ", ".join(f"{k}={v}" for k, v in args.items() if v is not None)
                            print(f"\n  {_GRAY}⚡ {name_t}({arg_str}){_RESET}", flush=True)
                        elif chunk["type"] == "tool_result":
                            name_t = chunk["name"]
                            ok = chunk.get("success", False)
                            icon = f"{_GREEN}✓{_RESET}" if ok else f"{_RED}✗{_RESET}"
                            print(f"  {_GRAY}{icon} {name_t}{_RESET}", flush=True)
                        elif chunk["type"] == "screenshot":
                            print(f"  {_GRAY}📷 screenshot ({chunk.get('width','?')}x{chunk.get('height','?')}){_RESET}", flush=True)
                        elif chunk["type"] == "error":
                            print(f"\n  {_RED}Error: {chunk['content']}{_RESET}", flush=True)
                    elif isinstance(chunk, str):
                        full += chunk
                        print(chunk, end="", flush=True)
            except Exception as e:
                logger.error(f"Tool loop error: {e}")
                print(f"\n  {_RED}Error generating response.{_RESET}")
                continue
            print()

            if full:
                self._session.add("assistant", full)
                self._session.flush()

            msgs = len(self._session.messages)
            if msgs > 0 and msgs % 8 == 0:
                asyncio.ensure_future(summarize_conversation(messages))
            asyncio.ensure_future(extract_user_info(messages))

    async def _handle_command(self, raw, messages):
        parts = raw[1:].split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd == "clear":
            self._session.clear()
            messages.clear()
            messages.append(self._build_messages()[0])
            print(f"  {_CYAN}Xens:{_RESET} Conversation cleared.\n")

        elif cmd == "profile":
            profile.load()
            ctx = profile.get_memory_context()
            print(f"  {_CYAN}Profile:{_RESET}\n{ctx}\n")

        elif cmd == "tier":
            if args:
                try:
                    registry.set_tier(args[0])
                    used, limit = ratelimiter.get_usage(args[0])
                    print(f"  {_CYAN}Tier set:{_RESET} {args[0]} — {used}/{limit} requests today\n")
                except ValueError as e:
                    print(f"  {_RED}{e}{_RESET}\n")
            else:
                tier = registry.get_tier()
                used, limit = ratelimiter.get_usage(tier)
                print(f"  {_CYAN}Tier:{_RESET} {tier} — {used}/{limit} requests today\n"
                      f"  {_GRAY}Valid tiers: {', '.join(sorted(tier_config.tiers))}{_RESET}\n")

        elif cmd == "limits":
            print(f"  {_CYAN}Daily usage:{_RESET}")
            for t in tier_config.tiers:
                used, limit = ratelimiter.get_usage(t)
                bar_w = 20
                filled = int(bar_w * used / limit) if limit else 0
                bar = "█" * filled + "░" * (bar_w - filled)
                print(f"    {t:<9} {bar} {used}/{limit}")
            print()

        elif cmd == "providers":
            print(f"  {_CYAN}Providers:{_RESET}")
            for name in ("mistral", "openai", "openrouter"):
                cfg = config.get("llm", {}).get(name, {})
                if cfg.get("api_key"):
                    print(f"    {name:<11} {_GREEN}configured{_RESET} (key {_mask(cfg['api_key'])})")
                else:
                    print(f"    {name:<11} {_RED}no API key{_RESET}")
            print(f"  {_GRAY}Models per tier (tier_config.json):{_RESET}")
            for t in tier_config.tiers:
                models = ", ".join(f"{m['provider']}:{m['model']}" for m in tier_config.get_models(t))
                print(f"    {t:<9} {models}")
            print()

        elif cmd == "config":
            print(f"  {_CYAN}Config file:{_RESET} {CONFIG_FILE}")
            print(f"  {_GRAY}Config dir:{_RESET} {CONFIG_FILE.parent}")
            print(f"  {_GRAY}Tier config:{_RESET} {tier_config.source}")
            print(f"  {_GRAY}Usage file:{_RESET} {ratelimiter._load.__globals__['USAGE_FILE']}")
            print()

        elif cmd == "tools":
            names = registry.tool_names
            query = args[0] if args else None
            if query:
                names = [n for n in names if query.lower() in n.lower()]
            if not names:
                print(f"  {_YELLOW}No tools match '{query or ''}'.{_RESET}\n")
            else:
                cols = shutil.get_terminal_size((100, 24)).columns
                width = max(len(n) for n in names) + 2
                per_row = max(1, cols // width)
                print(f"  {_CYAN}Tools ({len(names)}):{_RESET}")
                for i in range(0, len(names), per_row):
                    print("  " + "".join(n.ljust(width) for n in names[i:i + per_row]))
                print()

        elif cmd == "test":
            if not args:
                print(f"  {_YELLOW}Usage: /test <tool> [json args]{_RESET}\n"
                      f"  {_GRAY}Example: /test system_info{_RESET}\n"
                      f"  {_GRAY}Example: /test write_file '{{\"path\": \"prueba.txt\", \"content\": \"hola\"}}'{_RESET}\n")
            else:
                tool = args[0]
                raw_args = " ".join(args[1:]) if len(args) > 1 else "{}"
                try:
                    parsed_args = json.loads(raw_args) if raw_args.strip() else {}
                    if not isinstance(parsed_args, dict):
                        raise ValueError("args must be a JSON object")
                except Exception as e:
                    print(f"  {_RED}Invalid JSON args: {e}{_RESET}\n")
                    return
                if tool not in registry._tools:
                    print(f"  {_RED}Tool '{tool}' not found. Use /tools to list.{_RESET}\n")
                    return
                if tool not in registry.tool_names and not registry._tools[tool].get("internal"):
                    print(f"  {_RED}Tool '{tool}' not available in tier '{registry.get_tier()}'{_RESET}\n")
                    return
                print(f"  {_GRAY}⚡ Testing {tool}({json.dumps(parsed_args, ensure_ascii=False)}){_RESET}", flush=True)
                try:
                    output = await registry.execute(tool, parsed_args)
                    text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
                    print(f"  {_GRAY}Result ({len(text)} chars):{_RESET}")
                    print("  " + text[:4000] + ("…" if len(text) > 4000 else ""))
                    print()
                except Exception as e:
                    print(f"  {_RED}Execution error: {e}{_RESET}\n")

        elif cmd in ("help", "?"):
            print(f"""
  {_BOLD}Commands:{_RESET}
  {_GRAY}/clear{_RESET}           Reset conversation
  {_GRAY}/profile{_RESET}         Show what Xens remembers about you
  {_GRAY}/tools [query]{_RESET}   List available tools (filter optional)
  {_GRAY}/test <tool> [json]{_RESET} Execute a tool directly (no LLM)
  {_GRAY}/tier [name]{_RESET}     Show or switch tier (free/pro/premium)
  {_GRAY}/limits{_RESET}          Show daily usage for all tiers
  {_GRAY}/providers{_RESET}       Show configured providers and models
  {_GRAY}/config{_RESET}          Show config file locations
  {_GRAY}/help, /?{_RESET}        This help
  {_GRAY}exit, quit{_RESET}       Close

  {_BOLD}Examples:{_RESET}
    /test system_info
    /test write_file {{"path": "prueba.txt", "content": "hola"}}
    /tools spotify
    /tier pro
""")
        else:
            print(f"  {_YELLOW}Unknown command: /{cmd}. Type /help.{_RESET}\n")
