import asyncio
import json
import os
from .registry import register

_TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")


async def _send_via_cdp(expression: str) -> str:
    try:
        from tools.browser import _connect, _send
        conn = await _connect()
        if not conn:
            return "Error: Chrome no conectado"
        ws, sid = conn
        try:
            result = await _send(ws, sid, "Runtime.evaluate", {"expression": expression})
            return result.get("result", {}).get("value", "OK")
        finally:
            await ws.close()
    except ImportError:
        return "Error: browser.py no disponible"


def _run(coro):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@register(
    name="whatsapp_send",
    description="Enviar mensaje de WhatsApp a un contacto via WhatsApp Web",
    parameters={
        "type": "object",
        "properties": {
            "contact": {"type": "string", "description": "Nombre del contacto"},
            "message": {"type": "string", "description": "Mensaje a enviar"},
        },
        "required": ["contact", "message"],
    },
    tier="premium",
)
def whatsapp_send(contact: str, message: str) -> str:
    msg_escaped = message.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    contact_escaped = contact.replace("'", "\\'")
    js = f"""
    (() => {{
        const searchBox = document.querySelector('div[contenteditable="true"][data-tab="3"]');
        if (!searchBox) return 'Error: No se encontro WhatsApp';
        searchBox.focus();
        searchBox.innerText = '';
        searchBox.dispatchEvent(new Event('input', {{bubbles:true}}));
        document.execCommand('insertText', false, '{contact_escaped}');
        setTimeout(() => {{
            const chat = document.querySelector('span[title*="{contact_escaped}"]');
            if (chat) chat.click();
        }}, 1000);
        setTimeout(() => {{
            const input = document.querySelector('div[contenteditable="true"][data-tab="10"]');
            if (!input) return;
            input.focus();
            document.execCommand('insertText', false, '{msg_escaped}');
            input.dispatchEvent(new Event('input', {{bubbles:true}}));
            const sendBtn = document.querySelector('span[data-icon="send"]');
            if (sendBtn) sendBtn.click();
        }}, 2000);
        return 'Enviado';
    }})()
    """
    return _run(_send_via_cdp(js))


@register(
    name="telegram_send",
    description="Enviar mensaje de Telegram via Bot API",
    parameters={
        "type": "object",
        "properties": {
            "chat_id": {"type": "string", "description": "Chat ID de Telegram"},
            "message": {"type": "string", "description": "Mensaje a enviar"},
        },
        "required": ["chat_id", "message"],
    },
    tier="premium",
)
def telegram_send(chat_id: str, message: str) -> str:
    if not _TELEGRAM_TOKEN:
        return "Error: TELEGRAM_BOT_TOKEN no configurado"
    try:
        import urllib.request
        data = json.dumps({"chat_id": chat_id, "text": message}).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{_TELEGRAM_TOKEN}/sendMessage",
            data=data, headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return f"Mensaje enviado a Telegram ({chat_id})"
    except Exception as e:
        return f"Error Telegram: {e}"


@register(
    name="configure_telegram",
    description="Configurar token de bot de Telegram",
    parameters={
        "type": "object",
        "properties": {
            "token": {"type": "string", "description": "Token del bot de Telegram"},
        },
        "required": ["token"],
    },
    tier="premium",
)
def configure_telegram(token: str) -> str:
    global _TELEGRAM_TOKEN
    _TELEGRAM_TOKEN = token
    os.environ["TELEGRAM_BOT_TOKEN"] = token
    return "Token de Telegram configurado"
