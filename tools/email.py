from .registry import register
"""
email.py — Email client via IMAP/SMTP.
Passwords stored in Windows Credential Manager (OS-level encryption).
Ported from Xens Omni email_client.py — cleaner paths and JSON returns.
"""
import ctypes, ctypes.wintypes, email, imaplib, json, logging, os, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Optional

logger = logging.getLogger("xens.tools.email")

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
CRED_TARGET = "XensEmail"

class _CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", ctypes.wintypes.DWORD),
        ("Type", ctypes.wintypes.DWORD),
        ("TargetName", ctypes.wintypes.LPCWSTR),
        ("Comment", ctypes.wintypes.LPCWSTR),
        ("LastWritten", ctypes.wintypes.FILETIME),
        ("CredentialBlobSize", ctypes.wintypes.DWORD),
        ("CredentialBlob", ctypes.wintypes.LPBYTE),
        ("Persist", ctypes.wintypes.DWORD),
        ("AttributeCount", ctypes.wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", ctypes.wintypes.LPCWSTR),
        ("UserName", ctypes.wintypes.LPCWSTR),
    ]

def _cred_write(target: str, username: str, password: str) -> bool:
    try:
        cred = _CREDENTIAL()
        cred.Flags = 0
        cred.Type = CRED_TYPE_GENERIC
        cred.TargetName = target
        cred.UserName = username
        cred.Persist = CRED_PERSIST_LOCAL_MACHINE
        blob = password.encode("utf-16-le")
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes.cast(ctypes.create_string_buffer(blob), ctypes.wintypes.LPBYTE)
        cred.AttributeCount = 0
        cred.Attributes = None
        result = ctypes.windll.advapi32.CredWriteW(ctypes.byref(cred), 0)
        if result == 0:
            raise ctypes.WinError()
        return True
    except Exception:
        return False

def _cred_read(target: str) -> Optional[tuple[str, str]]:
    try:
        pcred = ctypes.POINTER(_CREDENTIAL)()
        result = ctypes.windll.advapi32.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pcred))
        if result == 0:
            return None
        cred = pcred.contents
        blob_size = cred.CredentialBlobSize
        if blob_size > 0 and cred.CredentialBlob:
            blob = ctypes.string_at(cred.CredentialBlob, blob_size)
            password = blob.decode("utf-16-le").rstrip("\x00")
        else:
            password = ""
        username = cred.UserName or ""
        ctypes.windll.advapi32.CredFree(pcred)
        return (username, password)
    except Exception:
        return None

def _cred_delete(target: str) -> bool:
    try:
        result = ctypes.windll.advapi32.CredDeleteW(target, CRED_TYPE_GENERIC, 0)
        return result != 0
    except Exception:
        return False

_CFG_PATH = Path.home() / ".xens" / "email_config.json"

def _load_config() -> dict:
    try:
        if _CFG_PATH.exists():
            return json.loads(_CFG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_config(cfg: dict):
    try:
        _CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CFG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass

@register(name="configure_email", description="Configure email account. Password stored in Windows Credential Manager.", tier="free", internal=True)
def configure_email(imap_server: str, smtp_server: str, email_addr: str, password: str,
                    imap_port: int = 993, smtp_port: int = 587) -> str:
    ok = _cred_write(CRED_TARGET, email_addr, password)
    if not ok:
        return json.dumps({"error": "Failed to save password to Windows Credential Manager", "success": False})
    _save_config({
        "imap_server": imap_server, "imap_port": imap_port,
        "smtp_server": smtp_server, "smtp_port": smtp_port,
        "email": email_addr,
    })
    return json.dumps({"success": True, "message": f"Email configured: {email_addr}", "account": email_addr})

def _get_credentials() -> Optional[tuple]:
    cfg = _load_config()
    if not cfg.get("email"):
        return None
    cred = _cred_read(CRED_TARGET)
    if not cred:
        return None
    username, password = cred
    return (
        cfg.get("imap_server", ""), cfg.get("smtp_server", ""),
        cfg.get("email", username), password,
        cfg.get("imap_port", 993), cfg.get("smtp_port", 587),
    )

def _connect_imap() -> Optional[imaplib.IMAP4_SSL]:
    info = _get_credentials()
    if not info:
        return None
    imap_server, _, email_addr, password, imap_port, _ = info
    try:
        conn = imaplib.IMAP4_SSL(imap_server, imap_port)
        conn.login(email_addr, password)
        return conn
    except Exception:
        return None

@register(name="read_inbox", description="Read recent emails from inbox.", tier="free")
def read_inbox(limit: int = 10, folder: str = "INBOX") -> str:
    conn = _connect_imap()
    if not conn:
        return json.dumps({"error": "Email not configured. Use configure_email first.", "success": False})
    try:
        conn.select(folder)
        _, data = conn.search(None, "ALL")
        ids = data[0].split()[-limit:] if data[0] else []
        messages = []
        for mid in reversed(ids):
            _, msg_data = conn.fetch(mid, "(RFC822)")
            raw = msg_data[0][1] if msg_data else b""
            msg = email.message_from_bytes(raw)
            sender = msg.get("From", "?")
            subject = msg.get("Subject", "(no subject)")
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True)
                        body = body.decode("utf-8", errors="replace")[:200] if body else ""
                        break
            else:
                body = msg.get_payload(decode=True)
                body = body.decode("utf-8", errors="replace")[:200] if body else ""
            messages.append({"from": sender, "subject": subject, "body": body})
        conn.close()
        conn.logout()
        return json.dumps({"success": True, "folder": folder, "count": len(messages), "messages": messages})
    except Exception as e:
        return json.dumps({"error": f"Failed to read inbox: {e}", "success": False})

@register(name="search_email", description="Search emails by subject or body content.", tier="free")
def search_email(query: str, folder: str = "INBOX") -> str:
    conn = _connect_imap()
    if not conn:
        return json.dumps({"error": "Email not configured", "success": False})
    try:
        conn.select(folder)
        _, data = conn.search(None, f'SUBJECT "{query}"')
        ids = data[0].split()[-5:] if data[0] else []
        if not ids:
            _, data = conn.search(None, f'BODY "{query}"')
            ids = data[0].split()[-5:] if data[0] else []
        if not ids:
            return json.dumps({"success": True, "query": query, "results": [], "note": "No matches found"})
        results = []
        for mid in ids:
            _, msg_data = conn.fetch(mid, "(RFC822)")
            raw = msg_data[0][1] if msg_data else b""
            msg = email.message_from_bytes(raw)
            results.append({"from": msg.get("From", "?"), "subject": msg.get("Subject", "?")})
        conn.close()
        conn.logout()
        return json.dumps({"success": True, "query": query, "count": len(results), "results": results})
    except Exception as e:
        return json.dumps({"error": f"Search failed: {e}", "success": False})

@register(name="send_email", description="Send an email via the configured SMTP account.", tier="free")
def send_email(to: str, subject: str, body: str) -> str:
    info = _get_credentials()
    if not info:
        return json.dumps({"error": "Email not configured", "success": False})
    _, smtp_server, email_addr, password, _, smtp_port = info
    try:
        msg = MIMEMultipart()
        msg["From"] = email_addr
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(email_addr, password)
        server.send_message(msg)
        server.quit()
        return json.dumps({"success": True, "to": to, "subject": subject})
    except Exception as e:
        return json.dumps({"error": f"Failed to send email: {e}", "success": False})

@register(name="delete_email_credentials", description="Remove stored email credentials from Windows Credential Manager.", tier="free", internal=True)
def delete_credentials() -> str:
    if _cred_delete(CRED_TARGET):
        if _CFG_PATH.exists():
            _CFG_PATH.unlink()
        return json.dumps({"success": True, "message": "Email credentials removed"})
    return json.dumps({"success": False, "error": "No credentials found"})
