"""Tests: WebSocket del servidor real (puerto efímero, LLM mockeado)."""
import asyncio
import json
import os
import sys

import aiohttp
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import ainslup_assistant.web.server as srv_mod
from ainslup_assistant.web.server import WebServer

TEST_PORT = 18791


async def _fake_run_tool_loop(messages, tier="free", uid=None, **kwargs):
    yield {"type": "content", "content": "hola-test"}


@pytest.fixture()
async def server(monkeypatch):
    monkeypatch.setattr(srv_mod, "PORT", TEST_PORT)
    monkeypatch.setattr(srv_mod, "run_tool_loop", _fake_run_tool_loop)
    # sin llamadas LLM ni estado real de licencia en el loop
    monkeypatch.setattr(srv_mod.lic, "gate_status",
                        lambda: {"allowed": True, "reason": "trial", "state": {}})
    monkeypatch.setattr(srv_mod.lic, "record_trial_use", lambda: None)
    monkeypatch.setattr(srv_mod.profile, "record_interaction", lambda: None)
    monkeypatch.setattr(srv_mod, "summarize_conversation",
                        lambda *a, **k: asyncio.sleep(0))
    monkeypatch.setattr(srv_mod, "extract_user_info",
                        lambda *a, **k: asyncio.sleep(0))
    ws_server = WebServer()
    await ws_server.start()
    yield ws_server
    await ws_server.stop()


async def _recv_of_type(ws, want, timeout=10):
    async with asyncio.timeout(timeout):
        while True:
            msg = await ws.receive()
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            data = json.loads(msg.data)
            if data.get("type") == want:
                return data


async def test_garbage_is_ignored_and_socket_stays_open(server):
    async with aiohttp.ClientSession() as sess:
        async with sess.ws_connect(f"ws://127.0.0.1:{TEST_PORT}/ws") as ws:
            await ws.send_str("esto no es json{{{")
            await ws.send_str(json.dumps({"type": "ping-pong-desconocido"}))
            await ws.send_str(json.dumps({"type": "message", "text": "hola",
                                          "requestId": "r1"}))
            done = await _recv_of_type(ws, "done")
            assert done.get("requestId") == "r1"


async def test_message_roundtrip_with_mocked_llm(server):
    async with aiohttp.ClientSession() as sess:
        async with sess.ws_connect(f"ws://127.0.0.1:{TEST_PORT}/ws") as ws:
            await ws.send_str(json.dumps({"type": "message", "text": "hola",
                                          "requestId": "r2"}))
            got_content = await _recv_of_type(ws, "content")
            assert "hola-test" in (got_content.get("content") or "")
            done = await _recv_of_type(ws, "done")
            assert done.get("requestId") == "r2"


async def test_check_exe_update_shape(server):
    async with aiohttp.ClientSession() as sess:
        async with sess.ws_connect(f"ws://127.0.0.1:{TEST_PORT}/ws") as ws:
            await ws.send_str(json.dumps({"type": "check_exe_update"}))
            msg = await _recv_of_type(ws, "exe_update")
            assert "exe_update" in msg


async def test_subscribe_requires_login(server):
    async with aiohttp.ClientSession() as sess:
        async with sess.post(f"http://127.0.0.1:{TEST_PORT}/api/paypal/subscribe",
                             json={"plan": "pro"}) as r:
            assert r.status == 401
            data = await r.json()
            assert data.get("error") == "login required"


async def test_paypal_cancel_page(server):
    async with aiohttp.ClientSession() as sess:
        async with sess.get(f"http://127.0.0.1:{TEST_PORT}/paypal/cancel") as r:
            assert r.status == 200
            text = await r.text()
            assert "AINSLUP" in text
