import asyncio, sys, logging, os, threading, argparse

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except:
        pass

from .core.config import PORT
from .core.chat import ConsoleChat
from .core.utils import shutdown_all
from .memory.session import Session
from .web.server import WebServer
from .tools.registry import registry, discover_tools
from .core.updater import get_current_version, update_via_git
from .core import license as lic

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("xens")

def _register_tools():
    discovered = discover_tools()
    names = registry.tool_names
    logger.info(f"Registered {len(names)} tools ({discovered} auto-discovered)")

async def _run_both(session):
    web = WebServer(session)
    await web.start()
    chat = ConsoleChat(session)
    try:
        await chat.run()
    finally:
        await web.stop()
        await shutdown_all()

async def _run_cli(session):
    chat = ConsoleChat(session)
    try:
        await chat.run()
    finally:
        await shutdown_all()

def _check() -> int:
    """Diagnostics: print state and exit."""
    _register_tools()
    tier = registry.get_tier()
    print(f"Xens Assistant v{get_current_version()}")
    print(f"  tools: {registry.count}/{registry.count_total} available (tier: {tier}, {registry.count_hidden} hidden)")
    print(f"  platforms: windows={sys.platform == 'win32'}")
    missing = []
    for name in ("mistral", "openai", "openrouter"):
        from .core.config import config
        if not config.get("llm", {}).get(name, {}).get("api_key"):
            missing.append(name)
    if missing:
        print(f"  api keys: missing for {', '.join(missing)} (chat disabled, /test works)")
    else:
        print("  api keys: all configured")
    print(f"  license:  {lic.format_status_line()}")
    import importlib
    for mod in ("httpx", "mistralai", "openai", "pyautogui", "PIL", "edge_tts"):
        try:
            importlib.import_module(mod)
            print(f"  dep {mod}: OK")
        except ImportError:
            print(f"  dep {mod}: MISSING")
    return 0

def main():
    parser = argparse.ArgumentParser(prog="xens", description="Xens Assistant CLI")
    parser.add_argument("--check", action="store_true", help="Run diagnostics and exit")
    parser.add_argument("--no-web", action="store_true", help="Disable the web UI server")
    parser.add_argument("--tier", choices=["free", "pro", "premium"], help="Override tier (default free)")
    parser.add_argument("--version", action="version", version=get_current_version())
    args = parser.parse_args()

    _register_tools()

    if args.tier:
        registry.set_tier(args.tier)
        logger.info("Tier overridden to '%s'", args.tier)
    else:
        lic_state = lic.get_state()
        if lic_state["status"] in ("licensed", "unlocked"):
            registry.set_tier(lic.effective_tier())
            logger.info("License '%s' active — tier set to '%s'", lic_state["status"], registry.get_tier())
        if lic_state["status"] == "locked":
            print(f"\n  \033[31mXens is locked:\033[0m trial used up ({lic_state['trial_used']}/{lic_state['trial_limit']}).")
            print(f"  Type \033[33m/activate <serial-key>\033[0m to unlock (or contact the seller).\n")

    if args.check:
        sys.exit(_check())

    from .core.config import API_KEY
    if not API_KEY:
        print("\n  \033[33mWarning:\033[0m No API key found. Chat will not work.")
        print("  Set MISTRAL_API_KEY or add one to ~/.xens/config.json.")
        print("  You can still test tools: /tools, /test <tool> [args]\n")

    # Check for updates in background (git repos only)
    if os.environ.get("XENS_AUTO_UPDATE", "1") == "1":
        threading.Thread(target=_check_updates, daemon=True).start()

    session = Session("default")

    logger.info(f"Xens Assistant v{get_current_version()} starting — {registry.count}/{registry.count_total} tools available (tier: {registry.get_tier()})")

    try:
        if args.no_web:
            asyncio.run(_run_cli(session))
        else:
            logger.info(f"Web UI: http://127.0.0.1:{PORT}")
            asyncio.run(_run_both(session))
    except KeyboardInterrupt:
        logger.info("Shutting down.")


def on_authenticated(user_tier: str = "free"):
    """Called by backend/auth when user logs in. Sets available tools for their tier."""
    try:
        registry.set_tier(user_tier)
    except ValueError as e:
        logger.warning(f"Invalid tier '{user_tier}' from auth, defaulting to free")
        registry.set_tier("free")


def _check_updates():
    import time
    time.sleep(5)
    result = update_via_git()
    if result.startswith("OK"):
        logger.info(f"Auto-update: {result}")
    elif result != "Not a git repository" and result != "Git not installed":
        logger.warning(f"Auto-update: {result}")

if __name__ == "__main__":
    main()
