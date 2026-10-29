import json
import asyncio

from core import security


def test_dangerous_command_is_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(security, "_CONFIG", tmp_path / "permissions.json")
    monkeypatch.setattr(security, "_AUDIT", tmp_path / "audit.jsonl")
    ok, reason = asyncio.run(security.authorize("run_command", {"command": "del important.txt"}, "dangerous"))
    assert not ok
    assert "bloqueado" in reason
    assert "blocked" in (tmp_path / "audit.jsonl").read_text()


def test_safe_mode_simulates(tmp_path, monkeypatch):
    monkeypatch.setattr(security, "_CONFIG", tmp_path / "permissions.json")
    monkeypatch.setattr(security, "_AUDIT", tmp_path / "audit.jsonl")
    security.set_settings(safe_mode=True)
    ok, reason = asyncio.run(security.authorize("write_file", {"path": "x", "content": "x"}, "confirm"))
    assert ok and reason == "SIMULATED"


def test_confirmation_handler_can_approve(tmp_path, monkeypatch):
    monkeypatch.setattr(security, "_CONFIG", tmp_path / "permissions.json")
    monkeypatch.setattr(security, "_AUDIT", tmp_path / "audit.jsonl")
    async def approve(*args):
        return True
    token = security.set_confirmation_handler(approve)
    try:
        ok, _ = asyncio.run(security.authorize("send_email", {}, "confirm"))
        assert ok
    finally:
        security.reset_confirmation_handler(token)
