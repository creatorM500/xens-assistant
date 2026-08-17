import asyncio, json, logging
from pathlib import Path

import aiohttp
from aiohttp import web

from ..core.config import PORT
from ..core.llm import run_tool_loop, reset_provider
from ..core import dependencies as deps
from ..core import license as lic
from ..core.credits import credits
from ..core.firebase_auth import firebase_auth
from ..core.tier_config import tier_config
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

    def _build_messages(self, session=None):
        session = session or self._session
        profile.load()
        memory_ctx = profile.get_memory_context()
        system = build_system(memory_context=memory_ctx)
        messages = [{"role": "system", "content": system}]
        for m in session.get_context(25):
            messages.append({"role": m["role"], "content": m["content"]})
        return messages

    async def _handle_ws(self, request):
        ws = web.WebSocketResponse(max_msg_size=5 * 1024 * 1024)
        await ws.prepare(request)
        # Modo local: sesión por conexión (dos pestañas no se pisan).
        # Con cuenta autenticada: sesión por UID (aislada entre cuentas,
        # compartida entre pestañas de la misma cuenta).
        account = None
        session = Session("web")
        messages = self._build_messages(session)

        heartbeat_task = asyncio.ensure_future(self._heartbeat(ws))

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(data, dict):
                        continue

                    try:
                        if data.get("type") == "auth":
                            token = data.get("token")
                            claims = await firebase_auth.verify(token) if token else None
                            if claims:
                                account = claims
                                uid = str(claims.get("uid") or "")
                                session = Session(f"acct:{uid}")
                                messages = self._build_messages(session)
                                tier = account.get("tier") or "free"
                                try:
                                    registry.set_tier(tier)
                                except ValueError:
                                    registry.set_tier("free")
                                await ws.send_json({
                                    "type": "auth_ok",
                                    "account": {
                                        "uid": uid,
                                        "email": claims.get("email") or "",
                                        "name": claims.get("name") or "",
                                        "tier": tier,
                                    },
                                })
                            else:
                                await ws.send_json({"type": "auth_error"})
                            continue

                        if data.get("type") == "message":
                            text = data.get("text")
                            if not isinstance(text, str):
                                continue
                            text = text.strip()
                            if not text:
                                continue
                            # Rehacer/editar: la respuesta (y el mensaje) previos
                            # se reemplazan para no duplicar contexto ni historial.
                            if data.get("replaceLast"):
                                session.pop_last("assistant")
                                if data.get("replaceUser"):
                                    session.pop_last("user")
                                messages = self._build_messages(session)
                            if account:
                                uid = str(account.get("uid") or "")
                                tier = account.get("tier") or "free"
                                allowed, remaining, limit, reset_sec = credits.check(tier=tier, uid=uid)
                                if not allowed:
                                    await ws.send_json({
                                        "type": "error",
                                        "content": (
                                            f"Alcanzaste el límite de Xens Credits de tu plan "
                                            f"({limit} al mes). Se renuevan el 1º de cada mes. "
                                            f"Mejora tu plan para obtener más."
                                        ),
                                    })
                                    await ws.send_json({"type": "done"})
                                    continue
                            else:
                                gate = await asyncio.to_thread(lic.gate_status)
                                if not gate["allowed"]:
                                    await ws.send_json({"type": "license", "state": gate["state"]})
                                    await ws.send_json({"type": "done"})
                                    continue
                                if gate["reason"] == "trial":
                                    await asyncio.to_thread(lic.record_trial_use)
                                await asyncio.to_thread(profile.record_interaction)
                            session.add("user", text)
                            messages.append({"role": "user", "content": text})

                            full = ""
                            tier = account.get("tier") if account else registry.get_tier()
                            uid = str(account.get("uid") or "") if account else None
                            try:
                                async for chunk in run_tool_loop(messages, tier=tier, uid=uid):
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
                                session.add("assistant", full)

                            if account:
                                used, credit_limit = credits.get_usage(tier=tier, uid=uid)
                                await ws.send_json({
                                    "type": "credits",
                                    "credits": max(0, credit_limit - used),
                                    "creditsUsed": used,
                                    "creditsLimit": credit_limit,
                                })

                            msgs_count = len(session.messages)
                            if msgs_count > 0 and msgs_count % 8 == 0:
                                asyncio.ensure_future(summarize_conversation(messages))
                            asyncio.ensure_future(extract_user_info(messages))

                            await ws.send_json({"type": "done"})

                        elif data.get("type") == "clear":
                            session.clear()
                            messages = self._build_messages(session)
                            await ws.send_json({"type": "cleared"})

                        elif data.get("type") == "get_profile":
                            profile.load()
                            ctx = profile.get_memory_context()
                            await ws.send_json({"type": "profile", "content": ctx})

                        elif data.get("type") == "get_license":
                            await ws.send_json({"type": "license", "state": lic.get_state()})

                        elif data.get("type") == "activate":
                            key = str(data.get("key") or "").strip()
                            if not key:
                                await ws.send_json({"type": "license", "state": lic.get_state(), "result": {"success": False, "error": "No key provided"}})
                            else:
                                server_url = lic.get_server_url()
                                result = None
                                note = ""
                                if server_url:
                                    # activate_online hace I/O bloqueante (httpx sync):
                                    # fuera del event loop para no congelar las WS.
                                    result = await asyncio.to_thread(lic.activate_online, key, server_url)
                                    if not result["success"] and result.get("status") in ("no_server", "unreachable"):
                                        note = f" (online activation failed: {result['error']})"
                                        result = None
                                if result is None:
                                    result = lic.activate(key)
                                    if note:
                                        result["note"] = f"Fallback to offline activation{note}"
                                if result["success"]:
                                    registry.set_tier(result["tier"])
                                    reset_provider()
                                await ws.send_json({"type": "license", "state": lic.get_state(), "result": result})

                        elif data.get("type") == "deactivate":
                            lic.deactivate()
                            registry.set_tier("free")
                            reset_provider()
                            await ws.send_json({"type": "license", "state": lic.get_state(), "result": {"success": True, "status": "deactivated"}})

                    except Exception as e:
                        logger.exception("WS handler error")
                        try:
                            await ws.send_json({"type": "error", "content": f"Error interno: {e}"})
                        except Exception:
                            pass

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
        account = await firebase_auth.account_from_authorization(
            request.headers.get("Authorization")
        )
        if account:
            uid = str(account.get("uid") or "")
            tier = account.get("tier") or "free"
            used, credit_limit = credits.get_usage(tier=tier, uid=uid)
            lic_state = lic.get_state()
            return web.json_response({
                "account": True,
                "uid": uid,
                "name": account.get("name") or "",
                "email": account.get("email") or "",
                "interactions": used,
                "credits": max(0, credit_limit - used),
                "creditsUsed": used,
                "creditsLimit": credit_limit,
                "creditsResetAt": credits._seconds_until_reset(),
                "plan": tier,
                "license": lic_state,
            })
        profile.load()
        lic_state = lic.get_state()
        tier = lic_state.get("tier") or "free"
        # El tier FREE ES la prueba gratuita: un solo contador (trial),
        # no dos números distintos en pantalla.
        if tier == "free":
            message_limit = lic_state.get("trial_limit", 300)
            message_count = lic_state.get("trial_used", 0)
        else:
            message_limit = 999999
            message_count = profile.interaction_count
        return web.json_response({
            "account": False,
            "name": profile.name or "",
            "email": lic_state.get("name") or "",
            "interactions": profile.interaction_count,
            "messageCount": message_count,
            "messageLimit": message_limit,
            "credits": None,
            "plan": tier,
            "license": lic_state,
        })

    async def _handle_api_deps(self, request):
        return web.json_response(deps.status())

    async def _handle_api_deps_install(self, request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        ids = body.get("deps")
        if not isinstance(ids, list) or not ids:
            ids = [d["id"] for d in deps.DEPS]
        consent = bool(body.get("consent", True))
        return web.json_response(deps.request_install(ids, consent=consent))

    async def _handle_api_version(self, request):
        try:
            from ..core.updater import get_current_version
            version = get_current_version()
        except Exception:
            version = "0.0.0"
        return web.json_response({"version": version})

    async def start(self):
        self._app = web.Application()
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/ws", self._handle_ws)
        self._app.router.add_get("/chat", self._handle_index)
        self._app.router.add_get("/api/profile", self._handle_api_profile)
        self._app.router.add_get("/api/deps", self._handle_api_deps)
        self._app.router.add_post("/api/deps/install", self._handle_api_deps_install)
        self._app.router.add_get("/api/version", self._handle_api_version)
        self._app.router.add_static("/", HERE / "static", show_index=False)

        st = lic.get_state()
        if st["status"] in ("licensed", "unlocked"):
            try:
                registry.set_tier(st.get("tier") or "free")
            except ValueError:
                pass

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", PORT)
        await site.start()
        logger.info(f"Web UI at http://127.0.0.1:{PORT}")

    async def stop(self):
        if self._runner:
            await self._runner.cleanup()
