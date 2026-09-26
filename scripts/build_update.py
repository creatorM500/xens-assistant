"""
scripts/build_update.py — Empaqueta el cliente en ZIP y lo publica en Supabase Storage.

Genera xens-latest.zip (arbol completo del app) + version.json y los sube a un
bucket publico ('xens-updates'). El cliente (core/updater.py) consulta
version.json y, si hay version nueva, descarga el ZIP y lo aplica solo.

Credenciales: ~/.ainslup/supabase.json ({"service_role", "project_ref", ...})
  o entorno:  XENS_SERVICE_ROLE, XENS_PROJECT_REF

Uso:
    python scripts/build_update.py                 # version = YYYYMMDD.HHMMSS
    python scripts/build_update.py --version v1.1  # version explicita
    python scripts/build_update.py --no-upload     # solo genera el ZIP local
"""
import argparse, hashlib, io, json, os, sys, zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

APP_DIR = Path(__file__).resolve().parents[1]
BUCKET = "xens-updates"
ZIP_NAME = "xens-latest.zip"

EXCLUDE_DIRS = {".git", "__pycache__", "build", "dist", "venv", ".venv",
                "_update_new", "_update_backup", "_update_build", "_update_verify",
                "node_modules", "target", "binaries", "dist-portable",
                ".pytest_cache", "gen", ".temp"}
EXCLUDE_FILES = {"version.txt", ".gitignore", "Ainslup.spec", "tools_temp.txt",
                 "build_err.txt", "README.md",
                 # Secretos/estado local: JAMÁS se publican en el feed.
                 "staging_keys.json", "staging_dbpass.txt", "supabase.json"}
EXCLUDE_SUFFIXES = {".pyc", ".log", ".zip", ".exe"}


def _creds() -> dict:
    env_sr = os.environ.get("XENS_SERVICE_ROLE")
    if env_sr:
        return {"service_role": env_sr,
                "project_ref": os.environ.get("XENS_PROJECT_REF", "tzlbgoydgptlhspzdhfu")}
    try:
        data = json.loads((Path.home() / ".ainslup" / "supabase.json").read_text(encoding="utf-8"))
        if data.get("service_role"):
            return data
    except Exception as e:
        print(f"! No credentials: {e}")
    sys.exit("Set XENS_SERVICE_ROLE or create ~/.ainslup/supabase.json")


def _storage(creds: dict) -> str:
    return f"https://{creds['project_ref']}.supabase.co/storage/v1"


def _headers(creds: dict) -> dict:
    return {"Authorization": f"Bearer {creds['service_role']}",
            "apikey": creds["service_role"]}


def split_exe_parts(data: bytes, exe_name: str, version: str,
                    chunk: int = 40 * 1024 * 1024) -> tuple[list, dict]:
    """Parte el exe para el límite ~50 MB/archivo de Storage (puro, testeable).

    Devuelve ([(nombre_parte, bytes)], manifest_exe). Si cabe en un chunk,
    parts queda vacío y el manifest apunta al archivo único.
    """
    if len(data) > chunk:
        parts = [(f"{exe_name}.part{i // chunk + 1}", data[i:i + chunk])
                 for i in range(0, len(data), chunk)]
        entry = {"version": version, "file": exe_name,
                 "parts": [n for n, _ in parts],
                 "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        return parts, entry
    entry = {"version": version, "file": exe_name,
             "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    return [], entry


def _build_zip(version: str) -> bytes:
    buf = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(APP_DIR.rglob("*")):
            rel = p.relative_to(APP_DIR)
            if any(part in EXCLUDE_DIRS for part in rel.parts):
                continue
            # Datos locales legacy: nunca se publican ni se pisan.
            if len(rel.parts) >= 2 and rel.parts[:2] == ("server", "data"):
                continue
            if p.is_file():
                if p.suffix in EXCLUDE_SUFFIXES or p.name in EXCLUDE_FILES:
                    continue
                # Helpers de staging (dev local, nunca al feed).
                if p.name.startswith("staging_"):
                    continue
                zf.write(p, str(rel))
                count += 1
        zf.writestr("version.txt", version)
        count += 1
    print(f"ZIP: {count} files, {buf.tell()/1024:.1f} KB")
    return buf.getvalue()


def _staging_creds() -> Optional[dict]:
    """Credenciales del proyecto staging (staging_keys.json local)."""
    try:
        data = json.loads((APP_DIR / "staging_keys.json").read_text(encoding="utf-8"))
        if data.get("service_role") and data.get("project_ref"):
            return {"service_role": data["service_role"],
                    "project_ref": data["project_ref"]}
    except Exception:
        pass
    return None


def _ensure_bucket(creds: dict, bucket: str = BUCKET) -> None:
    base = _storage(creds)
    h = _headers(creds)
    r = httpx.post(f"{base}/bucket", headers=h, json={
        "id": bucket, "name": bucket, "public": True}, timeout=30)
    if r.status_code == 200:
        print(f"Bucket '{bucket}' created (public)")
        return
    if r.status_code == 400 and "exists" in r.text.lower():
        r2 = httpx.put(f"{base}/bucket/{bucket}", headers=h,
                       json={"public": True}, timeout=30)
        if r2.status_code not in (200, 201):
            print(f"! Could not make bucket public: {r2.status_code} {r2.text[:200]}")
        else:
            print(f"Bucket '{bucket}' already exists (public)")
        return
    sys.exit(f"Bucket error {r.status_code}: {r.text[:300]}")


def _upload(creds: dict, bucket: str, path: str, content: bytes, content_type: str, timeout: int = 120) -> None:
    h = _headers(creds)
    h["Content-Type"] = content_type
    r = httpx.put(f"{_storage(creds)}/object/{bucket}/{path}",
                  headers=h, content=content, timeout=timeout)
    if r.status_code != 200:
        sys.exit(f"Upload {path} failed {r.status_code}: {r.text[:300]}")
    print(f"Uploaded {path} ({len(content)/1024:.1f} KB)")


def main():
    ap = argparse.ArgumentParser(description="Build + publish Ainslup update ZIP")
    ap.add_argument("--version", default="", help="version string (default: YYYYMMDD.HHMMSS)")
    ap.add_argument("--no-upload", action="store_true", help="only build locally")
    ap.add_argument("--exe", default="", help="ruta al Ainslup.exe frozen para publicar update de exe (beta)")
    ap.add_argument("--exe-name", default="Ainslup-beta.exe", help="nombre del exe en el feed")
    ap.add_argument("--no-exe", action="store_true", help="publica solo ZIP+manifest (el exe ya está subido)")
    ap.add_argument("--bucket", default=BUCKET, help="bucket de Storage (staging: xens-updates-staging)")
    args = ap.parse_args()

    version = args.version or datetime.now().strftime("%Y%m%d.%H%M%S")
    print(f"Building update v{version}")

    zip_bytes = _build_zip(version)
    sha256 = hashlib.sha256(zip_bytes).hexdigest()
    manifest = {"version": version, "zip": ZIP_NAME, "sha256": sha256}

    exe_bytes = b""
    exe_parts: list[tuple[str, bytes]] = []
    skip_exe_upload = bool(args.no_exe)
    if args.exe:
        exe_path = Path(args.exe)
        if not exe_path.is_file():
            sys.exit(f"Exe not found: {exe_path}")
        exe_bytes = exe_path.read_bytes()
        exe_parts, manifest["exe"] = split_exe_parts(exe_bytes, args.exe_name, version)
        print(f"EXE: {len(exe_bytes)/1024/1024:.1f} MB -> "
              f"{len(exe_parts) if exe_parts else 1} archivo(s)")

    manifest_bytes = json.dumps(manifest, indent=2).encode()

    out = APP_DIR / "_update_build"
    out.mkdir(exist_ok=True)
    (out / ZIP_NAME).write_bytes(zip_bytes)
    (out / "version.json").write_bytes(manifest_bytes)
    print(f"Local artifacts in {out}")

    if args.no_upload:
        return

    bucket = args.bucket
    if bucket != BUCKET:
        creds = _staging_creds()
        if not creds:
            sys.exit("Staging: falta staging_keys.json (ver docs/STAGING)")
    else:
        creds = _creds()
    _ensure_bucket(creds, bucket)
    _upload(creds, bucket, ZIP_NAME, zip_bytes, "application/zip")
    if skip_exe_upload:
        print("EXE: se conserva el manifest (partes ya publicadas, no se resuben)")
    elif exe_parts:
        for name, part in exe_parts:
            _upload(creds, bucket, name, part, "application/octet-stream", timeout=600)
    elif exe_bytes:
        _upload(creds, bucket, args.exe_name, exe_bytes, "application/octet-stream", timeout=600)
    _upload(creds, bucket, "version.json", manifest_bytes, "application/json")
    print(f"Feed: {_storage(creds).replace('/storage/v1', '/storage/v1/object/public')}/{bucket}")


if __name__ == "__main__":
    main()
