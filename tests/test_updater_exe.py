"""Tests: updater de exe (swap .bat, particionado, check en dev)."""
import hashlib
import importlib.util
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

from ainslup_assistant.core import updater as upd


def _build_update_mod():
    path = Path(__file__).resolve().parent.parent / "scripts" / "build_update.py"
    spec = importlib.util.spec_from_file_location("build_update_under_test", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_swap_bat_moves_relaunches_and_deletes_itself():
    exe = Path("C:/app/Ainslup.exe")
    staged = Path("C:/app/Ainslup.exe.new.exe")
    bat = upd.swap_bat_text(exe, staged)
    assert f'move /Y "{staged}" "{exe}"' in bat
    assert f'start "" "{exe}" --app' in bat
    assert 'del "%~f0"' in bat
    assert "timeout /t 2" in bat


def test_split_small_exe_single_file():
    bu = _build_update_mod()
    data = os.urandom(1024)
    parts, entry = bu.split_exe_parts(data, "Ainslup-beta.exe", "v1")
    assert parts == []
    assert entry["file"] == "Ainslup-beta.exe"
    assert entry["version"] == "v1"
    assert entry["sha256"] == hashlib.sha256(data).hexdigest()
    assert entry["bytes"] == len(data)
    assert "parts" not in entry


def test_split_big_exe_roundtrip():
    bu = _build_update_mod()
    data = os.urandom(90 * 1024 + 7)
    parts, entry = bu.split_exe_parts(data, "Ainslup-beta.exe", "v2", chunk=40 * 1024)
    assert len(parts) == 3
    assert entry["parts"] == [n for n, _ in parts]
    joined = b"".join(p for _, p in parts)
    assert joined == data
    assert hashlib.sha256(joined).hexdigest() == entry["sha256"]
    assert entry["bytes"] == len(data)
    for _, part in parts:
        assert len(part) <= 40 * 1024


async def test_check_exe_update_dev_reports_note():
    info = await upd.check_exe_update()
    # en dev (no frozen) no hay exe que actualizar: nota, sin red
    assert info.get("note") == "not frozen (dev)"
    assert info.get("exe_update") is False


def test_stage_swap_and_exit_dev_guard():
    assert upd.stage_exe_swap_and_exit() == "not frozen (dev)"
