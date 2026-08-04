# -*- mode: python ; coding: utf-8 -*-
import glob
from pathlib import Path

PKG = Path(".")

hiddenimports = [
    "edge_tts",
    "websockets",
    "sounddevice",
    "spotipy",
    "mistralai",
    "pyautogui",
    "PIL.Image",
    "PIL.ImageFilter",
    "PIL.ImageGrab",
    "win32com.client",
    "pythoncom",
]

for p in ("tools", "core", "llm", "memory", "web", "ui"):
    for f in glob.glob(str(PKG / p / "*.py")):
        stem = Path(f).stem
        if stem == "__init__":
            continue
        hiddenimports.append(f"xens_assistant.{p}.{stem}")

a = Analysis(
    ["cli_entry.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch",
        "torchvision",
        "torchaudio",
        "transformers",
        "sentence_transformers",
        "safetensors",
        "tokenizers",
        "datasets",
        "huggingface_hub",
        "bitsandbytes",
        "accelerate",
        "numba",
        "llvmlite",
        "librosa",
        "soundfile",
        "soxr",
        "resampy",
        "scipy",
        "pandas",
        "pyarrow",
        "cv2",
        "numpy",
        "fsspec",
        "av",
        "clr",
        "pythonnet",
        "OpenGL",
        "webview",
        "pytest",
        "matplotlib",
        "sklearn",
        "PySide6",
        "PyQt5",
        "PyQt6",
        "tensorflow",
        "notebook",
        "IPython",
        "unittest",
        "test",
    ],
    noarchive=False,
    optimize=0,
)
a.datas += [("version.txt", str(Path("version.txt")), "DATA")]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Xens",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
