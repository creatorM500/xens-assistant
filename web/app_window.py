"""web/app_window.py — Ventana nativa (WebView2) dentro del propio exe.

Doble clic a Ainslup.exe --app y se abre la ventana de AINSLUP sin navegador.
El servidor local ya debe estar corriendo (lo arranca __main__ antes).
"""
import logging
import threading
import time

logger = logging.getLogger("xens.window")


def wait_for_server(url: str, timeout: float = 30.0) -> bool:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/api/version", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def open_app_window(url: str = "http://127.0.0.1:18000", title: str = "AINSLUP") -> None:
    """Bloquea hasta cerrar la ventana. Llamar en el hilo principal."""
    try:
        import webview
    except ImportError:
        logger.warning("pywebview no instalado: abre %s en el navegador", url)
        return
    if not wait_for_server(url):
        logger.warning("El servidor no respondió en %s; abro la ventana igual", url)
    try:
        webview.create_window(
            title, url, width=1280, height=800, min_size=(900, 600),
            text_select=True,
        )
        webview.start()
    except Exception as e:
        logger.warning("No se pudo abrir la ventana nativa (%s); usa el navegador en %s", e, url)


def open_app_window_bg(url: str = "http://127.0.0.1:18000") -> threading.Thread:
    t = threading.Thread(target=open_app_window, args=(url,), daemon=True, name="xens-window")
    t.start()
    return t
