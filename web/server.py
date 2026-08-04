import asyncio, json, logging
from pathlib import Path

import aiohttp
from aiohttp import web

from ..core.config import PORT
from ..core.llm import run_tool_loop
from ..memory.session import Session
from ..memory.profile import profile
from ..memory.summarizer import summarize_conversation, extract_user_info
from ..personality import build_system
from ..tools.registry import registry

logger = logging.getLogger("xens.web")
HERE = Path(__file__).parent

class WebServer:
    def __init__(self, session=None):
        self._session = session or Session("web")

    def _build_messages(self):
        profile.load()
        memory_ctx = profile.get_memory_context()
        system = build_system(memory_context=memory_ctx)
        messages = [{"role": "system", "content": system}]
        for m in self._session.get_context(25):
            messages.append({"role": m["role"], "content": m["content"]})
        return messages

    async def _handle_ws(self, request):
        ws = web.WebSocketResponse(max_msg_size=5 * 1024 * 1024)
        await ws.prepare(request)
        messages = self._build_messages()

        heartbeat_task = asyncio.ensure_future(self._heartbeat(ws))

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue

                    if data.get("type") == "message":
                        text = data.get("text", "").strip()
                        if not text:
                            continue
                        profile.record_interaction()
                        self._session.add("user", text)
                        messages.append({"role": "user", "content": text})

                        full = ""
                        tier = registry.get_tier()
                        try:
                            async for chunk in run_tool_loop(messages, tier=tier):
                                if isinstance(chunk, dict):
                                    await ws.send_json(chunk)
                                    if chunk["type"] == "content":
                                        full += chunk["content"]
                                elif isinstance(chunk, str):
                                    full += chunk
                                    await ws.send_json({"type": "content", "content": chunk})
                        except Exception as e:
                            logger.error(f"Tool loop error: {e}")
                            await ws.send_json({"type": "error", "content": "Failed to generate response"})
                            continue

                        if full:
                            self._session.add("assistant", full)

                        msgs_count = len(self._session.messages)
                        if msgs_count > 0 and msgs_count % 8 == 0:
                            asyncio.ensure_future(summarize_conversation(messages))
                        asyncio.ensure_future(extract_user_info(messages))

                        await ws.send_json({"type": "done"})

                    elif data.get("type") == "clear":
                        self._session.clear()
                        messages = self._build_messages()
                        await ws.send_json({"type": "cleared"})

                    elif data.get("type") == "get_profile":
                        profile.load()
                        ctx = profile.get_memory_context()
                        await ws.send_json({"type": "profile", "content": ctx})

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WS error: {ws.exception()}")

        finally:
            heartbeat_task.cancel()

        return ws

    async def _heartbeat(self, ws):
        try:
            while True:
                await asyncio.sleep(30)
                try:
                    await ws.send_json({"type": "ping"})
                except:
                    break
        except asyncio.CancelledError:
            pass

    async def _handle_index(self, request):
        index_path = HERE / "static" / "index.html"
        if index_path.exists():
            return web.Response(
                text=index_path.read_text(encoding="utf-8"),
                content_type="text/html"
            )
        return web.Response(
            text="<h1>Xens Assistant</h1><p>Web UI not found.</p>",
            content_type="text/html"
        )

    async def _handle_api_profile(self, request):
        profile.load()
        return web.json_response({
            "name": profile.name or "",
            "interactions": profile.interaction_count,
        })

    async def start(self):
        self._app = web.Application()
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/ws", self._handle_ws)
        self._app.router.add_get("/chat", self._handle_index)
        self._app.router.add_get("/api/profile", self._handle_api_profile)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", PORT)
        await site.start()
        logger.info(f"Web UI at http://127.0.0.1:{PORT}")

    async def stop(self):
        if self._runner:
            await self._runner.cleanup()
