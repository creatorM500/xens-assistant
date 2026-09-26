import asyncio, sys, logging, shutil, json, time, inspect, queue, threading

from ..core.llm import run_tool_loop
from ..memory.session import Session
from ..memory.profile import profile
from ..memory.summarizer import summarize_conversation, extract_user_info
from ..personality import build_system
from ..core.config import USER_NAME, config, CONFIG_FILE, save as save_config
from ..tools.registry import registry
from ..tools.proactive import get_engine as get_proactive
from ..core.ratelimit import ratelimiter
from ..core.tier_config import tier_config
from ..core.updater import get_current_version
from ..core import license as lic

logger = logging.getLogger("xens.chat")

_CYAN = "\033[36m"
_YELLOW = "\033[33m"
_GREEN = "\033[92m"
_RED = "\033[91m"
_GRAY = "\033[90m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


class _ConsoleInput(threading.Thread):
    """Lee stdin desde un thread daemon para que Ctrl+C/exit no cuelguen la salida.

    run_in_executor + input() deja un thread bloqueado en input() al salir, y
    asyncio.run() espera a que el executor muera -> la app se congela al cerrar.
    """

    def __init__(self):
        super().__init__(daemon=True, name="xens-console-input")
        self._q: "queue.Queue[str]" = queue.Queue()
        self.start()

    def run(self):
        while True:
            prompt = self._q.get()
            try:
                line = input(prompt)
            except EOFError:
                line = ""
            self._q.task_done()
            _console_lines.put((prompt, line))

    async def readline(self, prompt: str):
        self._q.put(prompt)
        return await asyncio.to_thread(_console_lines.get)


_console_lines: "queue.Queue[tuple[str, str]]" = queue.Queue()
_console_input = _ConsoleInput()


def _mask(key: str) -> str:
    if not key:
        return "(not set)"
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "…" + key[-4:]


class ConsoleChat:
    def __init__(self, session=None):
        self._session = session or Session("default")
        self._started = time.monotonic()
        self._last_call = None
        self._last_output = None

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
        print(f"\n  {_BOLD}Ainslup Assistant CLI v{get_current_version()}{_RESET}")
        print(f"  {_GRAY}License:{_RESET} {lic.format_status_line()}  "
              f"{_GRAY}Tools:{_RESET} {registry.count}/{registry.count_total}  "
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

    def _sample_args(self, entry) -> dict:
        """Build sample/auto args from a tool's JSON schema (defaults win over typed placeholders)."""
        params = entry.get("parameters", {})
        props = params.get("properties", {})
        required = params.get("required", [])
        args = {}
        for key, prop in props.items():
            if "default" in prop:
                args[key] = prop["default"]
                continue
            if key in required:
                ptype = prop.get("type", "string")
                if ptype == "string":
                    args[key] = "test"
                elif ptype == "integer":
                    args[key] = 1
                elif ptype == "number":
                    args[key] = 1.0
                elif ptype == "boolean":
                    args[key] = True
                elif ptype == "array":
                    args[key] = []
                elif ptype == "object":
                    args[key] = {}
        return args

    def _format_tool_info(self, name: str, entry: dict) -> str:
        """Render a full tool card (schema, defaults, tier, timeout, source)."""
        lines = []
        tier = entry.get("tier", "free")
        avail = "✓ available" if registry._is_available(name) else f"✗ needs tier '{tier}'"
        lines.append(f"  {_CYAN}Tool: {name}{_RESET} — {avail}")
        lines.append(f"  {_GRAY}Description:{_RESET} {entry.get('description') or '(none)'}")
        lines.append(f"  {_GRAY}Tier:{_RESET} {tier}  {_GRAY}Timeout:{_RESET} {entry.get('timeout', 60)}s  "
                     f"{_GRAY}Retry:{_RESET} {entry.get('retry_on_error', False)}  "
                     f"{_GRAY}Internal:{_RESET} {entry.get('internal', False)}")
        params = entry.get("parameters", {})
        props = params.get("properties", {})
        required = params.get("required", [])
        if props:
            lines.append(f"  {_GRAY}Parameters:{_RESET}")
            for key, prop in props.items():
                req = " *" if key in required else ""
                default_hint = ""
                ptype = prop.get("type", "?")
                dflt = prop.get("default")
                if dflt is not None:
                    default_hint = f"  {_GRAY}(default {json.dumps(dflt, ensure_ascii=False)}){_RESET}"
                enum_hint = ""
                if prop.get("enum"):
                    enum_hint = f"  {_GRAY}one of: {', '.join(map(str, prop['enum']))}{_RESET}"
                lines.append(f"      {key:<24} {ptype}{req}{default_hint}{enum_hint}")
        else:
            lines.append(f"  {_GRAY}Parameters:{_RESET} none")
        try:
            sig = inspect.signature(entry["handler"])
            real_defaults = {
                p.name: p.default
                for p in sig.parameters.values()
                if p.default is not inspect.Parameter.empty
            }
            if real_defaults:
                lines.append(f"  {_GRAY}Signature defaults:{_RESET} "
                             f"{', '.join(f'{k}={json.dumps(v, ensure_ascii=False)}' for k, v in real_defaults.items())}")
        except Exception:
            pass
        return "\n".join(lines) + "\n"

    async def run(self):
        name = profile.name or USER_NAME or "there"
        messages = self._build_messages()
        self._banner()

        if not self._session.messages:
            welcome = f"Hey {name}. Good to see you. What are we working on today?"
            print(f"\n  {_CYAN}Ainslup:{_RESET} {welcome}\n")
            self._session.add("assistant", welcome)
            messages.append({"role": "assistant", "content": welcome})
        else:
            count = profile.interaction_count + 1
            print(f"\n  {_CYAN}Ainslup{_RESET} — {count} interactions so far.\n")

        while True:
            sug = get_proactive().pop_suggestion()
            if sug:
                print(f"  {_YELLOW}💡 {sug['message']}{_RESET}")
            try:
                raw = await _console_input.readline(
                    f"  {_YELLOW}You [{registry.get_tier()}]:{_RESET} "
                )
            except (EOFError, KeyboardInterrupt):
                print(f"\n  {_CYAN}Ainslup:{_RESET} Later, {name}.\n")
                self._session.flush()
                profile.flush()
                break

            if not raw:
                continue

            if raw.lower() in ("exit", "quit", "bye"):
                print(f"  {_CYAN}Ainslup:{_RESET} Later, {name}.\n")
                self._session.flush()
                profile.flush()
                break

            if raw.startswith("/"):
                await self._handle_command(raw, messages)
                continue

            gate = lic.gate_status()
            if not gate["allowed"]:
                st = gate["state"]
                if st["status"] == "locked":
                    print(f"  {_RED}Trial used up ({st['trial_used']}/{st['trial_limit']}). Activate Ainslup to keep using it.{_RESET}")
                    print(f"  {_YELLOW}Type /activate <serial-key> (or contact the seller to buy one).{_RESET}\n")
                elif st["status"] == "expired":
                    print(f"  {_RED}Your license expired. Type /activate with a new key.{_RESET}\n")
                continue

            if gate["reason"] == "trial":
                lic.record_trial_use()

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
            print(f"  {_CYAN}Ainslup:{_RESET} Conversation cleared.\n")

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
                print(f"  {_YELLOW}Usage: /test <tool> [json args] [--raw]{_RESET}\n"
                      f"  {_GRAY}Example: /test system_info{_RESET}\n"
                      f"  {_GRAY}Example: /test write_file '{{\"path\": \"prueba.txt\", \"content\": \"hola\"}}'{_RESET}\n"
                      f"  {_GRAY}Example: /test open_url --help{_RESET}\n"
                      f"  {_GRAY}Flags: --help (show schema+defaults), --raw (compact output, no timing){_RESET}\n")
                return
            tool = args[0]
            flags = [a for a in args[1:] if a.startswith("--")]
            raw_args = " ".join(a for a in args[1:] if not a.startswith("--"))
            if tool not in registry._tools:
                print(f"  {_RED}Tool '{tool}' not found. Use /tools or /find to list.{_RESET}\n")
                return
            entry = registry._tools[tool]
            if "--help" in flags:
                print(self._format_tool_info(tool, entry))
                return
            try:
                parsed_args = json.loads(raw_args) if raw_args.strip() else {}
                if not isinstance(parsed_args, dict):
                    raise ValueError("args must be a JSON object")
            except Exception as e:
                print(f"  {_RED}Invalid JSON args: {e}{_RESET}\n")
                return
            if not parsed_args:
                parsed_args = self._sample_args(entry)
                if parsed_args:
                    print(f"  {_GRAY}Auto-args: {json.dumps(parsed_args, ensure_ascii=False)}{_RESET}")
            if "--raw" in flags:
                try:
                    output = await registry.execute(tool, parsed_args)
                    text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
                    print(text)
                    print()
                except Exception as e:
                    print(f"  {_RED}Execution error: {e}{_RESET}\n")
                return
            print(f"  {_GRAY}⚡ Testing {tool}({json.dumps(parsed_args, ensure_ascii=False)}){_RESET}", flush=True)
            t0 = time.monotonic()
            try:
                output = await registry.execute(tool, parsed_args)
            except Exception as e:
                print(f"  {_RED}Execution error: {e}{_RESET}\n")
                return
            dt_ms = (time.monotonic() - t0) * 1000
            text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
            self._last_call = (tool, parsed_args)
            self._last_output = text
            try:
                ok = json.loads(text).get("success", True)
            except Exception:
                ok = True
            icon = f"{_GREEN}✓{_RESET}" if ok else f"{_RED}✗{_RESET}"
            print(f"  {_GRAY}{icon} {tool} in {dt_ms:.0f}ms ({len(text)} chars){_RESET}")
            print("  " + text[:4000] + ("…" if len(text) > 4000 else ""))
            print()
            if len(text) > 4000:
                print(f"  {_GRAY}Result truncated — use /last to see it again.{_RESET}\n")

        elif cmd == "info":
            if not args:
                print(f"  {_YELLOW}Usage: /info <tool>{_RESET}\n")
                return
            tool = args[0]
            entry = registry._tools.get(tool)
            if not entry:
                print(f"  {_RED}Tool '{tool}' not found. Use /tools or /find to list.{_RESET}\n")
                return
            print(self._format_tool_info(tool, entry))

        elif cmd == "find":
            if not args:
                print(f"  {_YELLOW}Usage: /find <query>{_RESET}\n")
                return
            query = args[0].lower()
            matches = [
                entry for name, entry in registry._tools.items()
                if query in name.lower() or query in (entry.get("description") or "").lower()
            ]
            if not matches:
                print(f"  {_YELLOW}No tools match '{query}'.{_RESET}\n")
            else:
                print(f"  {_CYAN}Found {len(matches)} tool(s):{_RESET}")
                for name, entry in sorted(registry._tools.items()):
                    if query in name.lower() or query in (entry.get("description") or "").lower():
                        hide = " " if registry._is_available(name) else f" {_RED}T{entry.get('tier','free')}{_RESET}"
                        print(f"    {name:<28} {hide}")
                        print(f"      {_GRAY}{(entry.get('description') or '')[:110]}{_RESET}")
                print()

        elif cmd == "last":
            if not self._last_output:
                print(f"  {_YELLOW}No tool has been executed yet in this session. Use /test.{_RESET}\n")
            else:
                tool, args_out = self._last_call or ("?", {})
                print(f"  {_GRAY}Last result — {tool}({json.dumps(args_out, ensure_ascii=False)}):{_RESET}")
                print("  " + self._last_output)
                print()

        elif cmd == "retry":
            if not self._last_call:
                print(f"  {_YELLOW}No previous tool call. Use /test first.{_RESET}\n")
            else:
                tool, prev_args = self._last_call
                print(f"  {_GRAY}⚡ Re-running {tool}({json.dumps(prev_args, ensure_ascii=False)}){_RESET}", flush=True)
                t0 = time.monotonic()
                try:
                    output = await registry.execute(tool, prev_args)
                except Exception as e:
                    print(f"  {_RED}Execution error: {e}{_RESET}\n")
                    return
                dt_ms = (time.monotonic() - t0) * 1000
                text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
                self._last_output = text
                print(f"  {_GRAY}Result in {dt_ms:.0f}ms:{_RESET}")
                print("  " + text[:4000] + ("…" if len(text) > 4000 else ""))
                print()

        elif cmd == "bench":
            if not args:
                print(f"  {_YELLOW}Usage: /bench <tool> [times (default 5)] [json args]{_RESET}\n")
                return
            tool = args[0]
            n = 5
            try:
                n = int(args[1]) if len(args) > 1 and not args[1].startswith("{") else 5
            except ValueError:
                pass
            n = max(1, min(n, 20))
            raw_args = " ".join(a for a in args[1:] if not a.isdigit())
            try:
                parsed_args = json.loads(raw_args) if raw_args.strip() else {}
                if not isinstance(parsed_args, dict):
                    raise ValueError("args must be a JSON object")
            except Exception as e:
                print(f"  {_RED}Invalid JSON args: {e}{_RESET}\n")
                return
            if tool not in registry._tools:
                print(f"  {_RED}Tool '{tool}' not found. Use /tools or /find to list.{_RESET}\n")
                return
            if not parsed_args:
                parsed_args = self._sample_args(registry._tools[tool])
            times_ms = []
            ok_count = 0
            print(f"  {_GRAY}Benchmarking {tool} ×{n}...{_RESET}", flush=True)
            for i in range(n):
                t0 = time.monotonic()
                try:
                    output = await registry.execute(tool, parsed_args)
                    dt = (time.monotonic() - t0) * 1000
                    times_ms.append(dt)
                    text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
                    try:
                        ok = json.loads(text).get("success", True)
                    except Exception:
                        ok = True
                    if ok:
                        ok_count += 1
                    print(f"    run {i + 1}: {dt:.0f}ms {'✓' if ok else '✗'}")
                except Exception as e:
                    print(f"    run {i + 1}: error {e}")
            if times_ms:
                print(f"  {_GRAY}min {min(times_ms):.0f}ms  avg {sum(times_ms)/len(times_ms):.0f}ms  max {max(times_ms):.0f}ms  ok {ok_count}/{n}{_RESET}")
            print()

        elif cmd == "activate":
            if not args:
                print(f"  {_YELLOW}Usage: /activate <serial-key>{_RESET}\n"
                      f"  {_GRAY}Example: /activate AINSLUP-PRO-3650-00000000-04b596c1c950{_RESET}\n"
                      f"  {_GRAY}With a license server set, the key is validated online (Codex-style).{_RESET}\n")
                return
            raw_key = " ".join(args)
            st = lic.get_state()
            if st["status"] == "licensed":
                print(f"  {_YELLOW}Already activated ({st['tier']}). Use /deactivate first to change key.{_RESET}\n")
                return
            server_url = lic.get_server_url()
            if server_url:
                print(f"  {_GRAY}Contacting license server {server_url}...{_RESET}", flush=True)
                result = lic.activate_online(raw_key, server_url)
                if result["success"]:
                    registry.set_tier(result["tier"])
                    print(f"  {_GREEN}✓ Activated (online)! Tier: {result['tier'].upper()}.{_RESET}\n")
                    return
                if result.get("status") not in ("no_server", "unreachable"):
                    print(f"  {_RED}{result.get('error', 'Invalid key')}{_RESET}\n")
                    return
                print(f"  {_YELLOW}Server unavailable — falling back to offline key validation.{_RESET}")
            result = lic.activate(raw_key)
            if result["success"]:
                registry.set_tier(result["tier"])
                print(f"  {_GREEN}✓ Activated! Tier: {result['tier'].upper()} "
                      f"for {result['days'] or 'lifetime'} days.{_RESET}\n")
            else:
                print(f"  {_RED}{result.get('error', 'Invalid key')}{_RESET}\n")

        elif cmd in ("server", "set-server"):
            if not args:
                cur = lic.get_server_url()
                print(f"  {_CYAN}License server:{_RESET} {cur or '(not set — offline/modo local)'}")
                print(f"  {_GRAY}Set it with /server <url>   |   clear with /server off{_RESET}")
                print(f"  {_GRAY}Env override: XENS_SERVER_URL (takes priority){_RESET}\n")
            elif args[0].lower() in ("off", "none", "clear", "remove"):
                config["server"] = {"url": ""}
                save_config(config)
                print(f"  {_YELLOW}License server cleared (offline mode).{_RESET}\n")
            else:
                url = args[0].strip()
                if not url.startswith("http://") and not url.startswith("https://"):
                    url = "http://" + url
                config["server"] = {"url": url.rstrip("/")}
                save_config(config)
                print(f"  {_GREEN}License server set: {url.rstrip('/')}{_RESET}")
                print(f"  {_GRAY}Next /activate <serial> will validate online.{_RESET}\n")

        elif cmd == "deactivate":
            lic.deactivate()
            print(f"  {_YELLOW}License removed. Trial mode restarted.{_RESET}\n")

        elif cmd == "license":
            st = lic.get_state()
            print(f"  {_CYAN}License:{_RESET} {lic.format_status_line()}")
            print(f"    mode:      {st['mode']} ({'online' if st['online'] else 'offline'})")
            print(f"    hwid:      {st['hwid']}")
            if st["server_url"]:
                print(f"    server:    {st['server_url']}")
            if st["status"] == "licensed":
                print(f"    tier:      {st['tier']}")
                if st["online"]:
                    print(f"    token:     {'stored (validated by server on use)' if st.get('activated') else '(none)'}")
                else:
                    print(f"    key:       {st.get('key')}")
                if st.get("days_left") is not None:
                    print(f"    expires:   {st['days_left']} days left")
                else:
                    print(f"    expires:   lifetime")
                if st.get("name"):
                    print(f"    issued to: {st['name']}")
            else:
                print(f"    trial:     {st['trial_used']}/{st['trial_limit']}")
            print()

        elif cmd == "status":
            tier = registry.get_tier()
            used, limit = ratelimiter.get_usage(tier)
            uptime = time.monotonic() - self._started
            print(f"  {_CYAN}Ainslup status:{_RESET}")
            print(f"    version:   {get_current_version()}")
            print(f"    license:   {lic.format_status_line()}")
            print(f"    session:   {self._session.messages.__class__.__name__} ({len(self._session.messages)} messages)")
            print(f"    uptime:    {int(uptime // 60)}m {int(uptime % 60)}s")
            print(f"    tier:      {tier} — {used}/{limit} requests today")
            print(f"    tools:     {registry.count}/{registry.count_total} available ({registry.count_hidden} hidden)")
            print(f"    providers: {self._provider_status()}")
            print()

        elif cmd == "deps":
            import importlib
            print(f"  {_CYAN}Dependencies:{_RESET}")
            checks = ["httpx", "mistralai", "openai", "pyautogui", "PIL", "edge_tts", "requests", "websockets", "aiohttp", "yaml"]
            for mod in checks:
                try:
                    importlib.import_module(mod)
                    print(f"    {mod:<14} {_GREEN}OK{_RESET}")
                except ImportError:
                    print(f"    {mod:<14} {_RED}MISSING{_RESET}")
            print()

        elif cmd == "history":
            try:
                n = int(args[0]) if args else 10
            except ValueError:
                n = 10
            n = max(1, min(n, 100))
            msgs = self._session.messages
            print(f"  {_CYAN}Recent messages ({min(n, len(msgs))} of {len(msgs)}):{_RESET}")
            for m in msgs[-n:]:
                role = "You  " if m["role"] == "user" else "Ainslup "
                content = (m.get("content") or "").replace("\n", " ")[:120]
                print(f"    {role} {content}")
            print()

        elif cmd in ("help", "?"):
            print(f"""
  {_BOLD}Commands:{_RESET}
  {_GRAY}/clear{_RESET}           Reset conversation
  {_GRAY}/history [n]{_RESET}     Show last n conversation messages
  {_GRAY}/profile{_RESET}         Show what Ainslup remembers about you
  {_GRAY}/tools [query]{_RESET}   List available tools (filter optional)
  {_GRAY}/find <query>{_RESET}    Search tools by name or description
  {_GRAY}/info <tool>{_RESET}     Full tool card: schema, defaults, tier, timeout
  {_GRAY}/test <tool> [json]{_RESET} Execute a tool with auto-args, timing and ✓/✗
  {_GRAY}/bench <tool> [times]{_RESET} Performance benchmark (min/avg/max)
  {_GRAY}/last{_RESET}            Re-print last tool result (untrauncated)
  {_GRAY}/retry{_RESET}           Re-run the last tool call
  {_GRAY}/tier [name]{_RESET}     Show or switch tier (free/pro/premium)
  {_GRAY}/limits{_RESET}          Show daily usage for all tiers
  {_GRAY}/providers{_RESET}       Show configured providers and models
  {_GRAY}/status{_RESET}          Show version, uptime, tier, tools, providers
  {_GRAY}/license{_RESET}         Show license state (mode, tier, hwid, expiry, trial)
  {_GRAY}/activate <key>{_RESET}  Activate online (if server set) or offline serial
  {_GRAY}/deactivate{_RESET}      Remove the license (back to trial)
  {_GRAY}/server [url]{_RESET}    Show/set the license server URL (online mode)
  {_GRAY}/deps{_RESET}            Check dependency modules
  {_GRAY}/config{_RESET}          Show config file locations
  {_GRAY}/help, /?{_RESET}        This help
  {_GRAY}exit, quit{_RESET}       Close

  {_BOLD}Examples:{_RESET}
    /test open_url --help
    /test system_info --raw
    /test list_dir {{"path": "C:/"}} 
    /bench browser_list_tabs 3
    /find spotify
    /info write_file
""")
        else:
            print(f"  {_YELLOW}Unknown command: /{cmd}. Type /help.{_RESET}\n")
