import asyncio, sys, logging, os, threading, argparse

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except:
        pass

from .core.config import PORT, config
from .core.chat import ConsoleChat
from .core.utils import shutdown_all
from .memory.session import Session
from .web.server import WebServer
from .tools.registry import registry, discover_tools
from .core.updater import (auto_update_zip, get_current_version, is_git_repo,
                           set_update_url, update_via_git)
from .core import license as lic

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("xens")


def _setup_file_logging():
    """Log a archivo: en modo app no hay consola visible y los crashes
    quedaban ciegos. Guarda en ~/.xens/logs/xens-YYYYMMDD.log + excepciones
    no capturadas (hilo principal y threads)."""
    try:
        from pathlib import Path
        logdir = Path.home() / ".xens" / "logs"
        logdir.mkdir(parents=True, exist_ok=True)
        import time
        fh = logging.FileHandler(logdir / f"xens-{time.strftime('%Y%m%d')}.log", encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logging.getLogger().addHandler(fh)

        def _hook(etype, value, tb):
            logging.getLogger("xens.crash").exception("Uncaught", exc_info=(etype, value, tb))
        import sys as _sys
        _sys.excepthook = _hook

        def _thread_hook(args):
            logging.getLogger("xens.crash").exception(
                "Uncaught thread", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        import threading as _th
        _th.excepthook = _thread_hook
        return str(logdir)
    except Exception as e:
        logger.warning(f"File logging desactivado: {e}")
        return ""


LOG_DIR = _setup_file_logging()

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

async def _run_web(session):
    """UI-only mode: serves the web interface and stays alive (no console chat)."""
    web = WebServer(session)
    await web.start()
    try:
        stop = asyncio.Event()
        await stop.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await web.stop()
        await shutdown_all()

def _run_app(session):
    """Modo app nativa: servidor en segundo plano + ventana WebView2.

    Un solo exe, doble clic y se abre XENS. Al cerrar la ventana termina todo.
    """
    from .web.server import WebServer as _WS

    started = threading.Event()
    holder: dict = {}

    def _serve():
        async def _boot():
            web = _WS(session)
            await web.start()
            holder["web"] = web
            started.set()
            try:
                stop = asyncio.Event()
                await stop.wait()
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass
        try:
            asyncio.run(_boot())
        finally:
            try:
                web = holder.get("web")
                if web is not None:
                    asyncio.run(web.stop())
            except Exception:
                pass

    t = threading.Thread(target=_serve, daemon=True, name="xens-server")
    t.start()
    if not started.wait(timeout=30):
        logger.warning("Web server tardó en arrancar; abro la ventana igual")
    try:
        from .web.app_window import open_app_window
        from .core.config import PORT as _PORT
        open_app_window(f"http://127.0.0.1:{_PORT}")
    finally:
        try:
            from .core.utils import shutdown_all as _sd
            asyncio.run(_sd())
        except Exception:
            pass
        os._exit(0)

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
    if LOG_DIR:
        print(f"  logs: {LOG_DIR} (manda el .log si algo falla)")
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
    parser.add_argument("--headless", action="store_true", help="UI-only mode: web server without console chat")
    parser.add_argument("--app", action="store_true", help="Native app mode: server + WebView2 window (single exe)")
    parser.add_argument("--tier", choices=["free", "pro", "premium"], help="Override tier (default free)")
    parser.add_argument("--version", action="version", version=get_current_version())
    args = parser.parse_args()

    # Doble clic al exe = modo app nativa (ventana). En terminal se puede
    # forzar consola con --no-web / --headless / --check.
    if getattr(sys, "frozen", False) and not (args.app or args.headless or args.no_web or args.check):
        args.app = True

    _register_tools()

    if args.tier:
        registry.set_tier(args.tier)
        logger.info("Tier overridden to '%s'", args.tier)
    else:
        # Cero-config: sin licencia, auto-activa el Free online (sin pedir nada).
        # Si no hay internet, se sigue en trial local.
        try:
            if lic.get_state()["status"] not in ("licensed", "unlocked"):
                r = lic.ensure_free_license()
                if r.get("success"):
                    print("  plan: Free activado automáticamente (5.000 Xens Credits/mes).")
        except Exception as e:
            logger.warning(f"Free auto-provision failed: {e}")
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
    if not API_KEY and not lic.get_state().get("online"):
        print("\n  \033[33mWarning:\033[0m No API key found and no online plan. Chat will not work.")
        print("  Connect to the internet once so your Free plan activates automatically,")
        print("  or set MISTRAL_API_KEY / add one to ~/.xens/config.json.")
        print("  You can still test tools: /tools, /test <tool> [args]\n")

    # Check for updates in background (git repos use git pull; others use ZIP feed)
    if os.environ.get("XENS_AUTO_UPDATE", "1") == "1":
        update_url = (
            os.environ.get("XENS_UPDATE_URL")
            or (config.get("updater", {}) or {}).get("url", "").strip()
            or "https://tzlbgoydgptlhspzdhfu.supabase.co/storage/v1/object/public/xens-updates"
        )
        set_update_url(update_url)
        threading.Thread(target=_check_updates, daemon=True).start()

    session = Session("default")

    logger.info(f"Xens Assistant v{get_current_version()} starting — {registry.count}/{registry.count_total} tools available (tier: {registry.get_tier()})")

    try:
        if args.app:
            logger.info("Native app mode — ventana XENS")
            _run_app(session)
        elif args.headless:
            logger.info(f"Headless UI mode — Web UI at http://127.0.0.1:{PORT}")
            asyncio.run(_run_web(session))
        elif args.no_web:
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
    try:
        if is_git_repo():
            result = update_via_git()
            channel = "git"
        else:
            result = asyncio.run(auto_update_zip())
            channel = "zip"
            # El loop del thread ya murió: cerrar el AsyncClient huérfano
            from .core.utils import close_closed_loop_clients
            close_closed_loop_clients()
        if result.startswith(("OK:", "Updated", "Up to date")):
            logger.info(f"Auto-update ({channel}): {result}")
        else:
            logger.warning(f"Auto-update ({channel}): {result}")
    except Exception as e:
        logger.warning(f"Auto-update: {e}")

if __name__ == "__main__":
    main()
