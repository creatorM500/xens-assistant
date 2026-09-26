"""scripts/sign_exe.py — Firma el exe con certificado (SmartScreen).

Sin certificado NO firma (exit 2 con instrucciones); el build sigue
funcionando sin firma. Ver docs/SIGNING.md para conseguir el certificado.

Uso:
    python scripts/sign_exe.py dist/Ainslup.exe
    python scripts/sign_exe.py dist/Ainslup.exe --pfx ruta/cert.pfx

El PFX puede venir de:
    - archivo: --pfx ... (+ AINSLUP_SIGN_PASSWORD o prompt)
    - Azure Trusted Signing: variables AINSLUP_AZURE_* (ver docs/SIGNING.md)
"""
import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _signtool() -> str | None:
    for name in ("signtool.exe",):
        p = shutil.which(name)
        if p:
            return p
    # SDKs típicos de Windows
    cands = list(Path(r"C:\Program Files (x86)\Windows Kits\10\bin").glob("*/x64/signtool.exe"))
    return str(cands[-1]) if cands else None


def main() -> int:
    if len(sys.argv) < 2:
        print("Uso: python scripts/sign_exe.py <exe> [--pfx cert.pfx]")
        return 2
    exe = Path(sys.argv[1])
    if not exe.is_file():
        print(f"No existe: {exe}")
        return 2
    pfx = ""
    if "--pfx" in sys.argv:
        pfx = sys.argv[sys.argv.index("--pfx") + 1]
    password = os.environ.get("AINSLUP_SIGN_PASSWORD") or ""
    signtool = _signtool()
    if not signtool:
        print("! signtool.exe no encontrado (instala Windows SDK). Ver docs/SIGNING.md")
        return 2
    if not pfx:
        print("! Sin certificado: nada que firmar. Ver docs/SIGNING.md para conseguirlo.")
        return 2
    if not password:
        password = getpass.getpass("Password del PFX: ")
    cmd = [signtool, "sign", "/fd", "SHA256", "/tr", "http://timestamp.digicert.com",
           "/td", "SHA256", "/f", pfx, "/p", password, str(exe)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    print(r.stdout[-500:] if r.stdout else "")
    if r.returncode != 0:
        print(r.stderr[-1000:] if r.stderr else "")
        return 1
    print(f"Firmado: {exe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
