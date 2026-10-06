import asyncio, copy, json, logging
from pathlib import Path

import aiohttp
from aiohttp import web

from ..core.config import PORT
from ..core.llm import run_tool_loop, reset_provider
from ..core import dependencies as deps
from ..core import license as lic
from ..core.credits import credits
from ..core.supabase_auth import supabase_auth as firebase_auth  # compat alias; real es supabase_auth
from ..core.tasks import task_manager
from ..core.triggers import trigger_manager
from ..core.tier_config import tier_config
from ..memory.session import Session
from ..memory.profile import profile
from ..memory.summarizer import summarize_conversation, extract_user_info
from ..personality import build_system
from ..tools.registry import registry

logger = logging.getLogger("xens.web")
HERE = Path(__file__).parent



def _static_dir() -> Path:
    """Carpeta web/static en fuente y en exe congelado.

    En el bundle PyInstaller el código corre como
    ``_MEIPASS/ainslup_assistant/web/server.py`` mientras que los datas
    pueden haber quedado en ``_MEIPASS/web/static`` o en
    ``_MEIPASS/ainslup_assistant/web/static`` según el spec usado.
    Se prueban todas antes de rendirse (sin static no hay UI).
    """
    candidates = [HERE / "static"]
    try:
        import sys
        base = getattr(sys, "_MEIPASS", None)
        if base:
            base = Path(base)
            candidates += [
                base / "ainslup_assistant" / "web" / "static",
                base / "web" / "static",
            ]
    except Exception:
        pass
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


class WebServer:
    def __init__(self, session=None):
        self._session = session or Session("web")
        # Canal conversacional separado de la ejecución:
        # cada mensaje corre su propio task (run_tool_loop) con un snapshot
        # aislado del contexto, de modo que una tarea larga (tools, LLM) no
        # bloquea la conversación y viceversa.
        self._session_lock = asyncio.Lock()
        self._session_epoch = 0
        # UIDs con conexión WS activa: los disparadores online_only solo
        # disparan si su dueño está conectado (control de costos).
        self._connected_uids: set = set()
        trigger_manager.set_online_check(lambda uid: uid in self._connected_uids)

    def _build_messages(self, session=None, uid=None):
        session = session or self._session
        profile.load(uid)
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
        acct_state: dict = {"account": None}
        session = Session("web")
        # Lock de envío POR CONEXIÓN: un cliente muerto no puede bloquear
        # los envíos de las demás conexiones (un send atascado en un socket
        # zombie no debe tumbar el servidor entero).
        send_lock = asyncio.Lock()

        async def send(data: dict):
            # Timeout de guardia: si el socket está muerto, raise en vez de
            # colgarse para siempre; el handler hace teardown de la conexión.
            async with send_lock:
                await asyncio.wait_for(ws.send_json(data), timeout=15)

        async def on_task(rec: dict):
            # Eventos de tareas: solo al dueño (uid de la cuenta) de la tarea.
            try:
                owner = (rec.get("meta") or {}).get("uid")
                account = acct_state.get("account")
                if owner:
                    if not account or str(account.get("uid") or "") != owner:
                        return
                elif account:
                    return  # tarea local: solo a conexiones locales
                await send({
                    "type": "task_event",
                    "task": {
                        "id": rec["id"],
                        "name": rec["name"],
                        "status": rec["status"],
                        "error": rec.get("error"),
                    },
                })
            except Exception:
                pass

        async def on_trigger(evt: dict):
            # Eventos de disparadores: solo al dueño (o a conexiones locales).
            try:
                t = trigger_manager.get(evt.get("id") or "")
                owner = (t.get("owner") if t else None) or evt.get("owner")
                account = acct_state.get("account")
                if owner:
                    if not account or str(account.get("uid") or "") != owner:
                        return
                elif account:
                    return
                await send({"type": "trigger_event", "trigger": {
                    "id": evt.get("id"),
                    "name": evt.get("name"),
                    "status": evt.get("status"),
                    "task_id": evt.get("task_id"),
                    "reason": evt.get("reason"),
                }})
            except Exception:
                pass

        listener_id = task_manager.subscribe(on_task)
        trigger_listener_id = trigger_manager.subscribe(on_trigger)
        heartbeat_task = asyncio.ensure_future(self._heartbeat(ws, send))

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
                            claims = await firebase_auth.verify(token) if token else None  # supabase JWT HS256
                            if claims:
                                # Se guarda el token Supabase: con cuenta, el LLM va
                                # por el edge (sin serial ni keys locales).
                                claims["_token"] = token
                                acct_state["account"] = claims
                                uid = str(claims.get("uid") or "")
                                self._connected_uids.add(uid)
                                session = Session(f"acct:{uid}")
                                tier = claims.get("tier") or "free"
                                try:
                                    registry.set_tier(tier)
                                except ValueError:
                                    registry.set_tier("free")
                                await send({
                                    "type": "auth_ok",
                                    "account": {
                                        "uid": uid,
                                        "email": claims.get("email") or "",
                                        "name": claims.get("name") or "",
                                        "tier": tier,
                                    },
                                })
                            else:
                                await send({"type": "auth_error"})
                            continue

                        if data.get("type") == "message":
                            text = data.get("text")
                            if not isinstance(text, str):
                                continue
                            text = text.strip()
                            if not text:
                                continue
                            request_id = str(data.get("requestId") or "")
                            account = acct_state.get("account")

                            # Gate de créditos (cuenta) o licencia (local):
                            # se valida ANTES de despachar el task.
                            # Beta: el plan elegido en Configuración manda.
                            if account:
                                uid = str(account.get("uid") or "")
                                tier = tier_config.effective_tier(account.get("tier") or "free")
                                allowed, remaining, limit, reset_sec = credits.check(tier=tier, uid=uid)
                                if not allowed:
                                    await send({
                                        "type": "error",
                                        "requestId": request_id or None,
                                        "content": (
                                            f"Alcanzaste el límite de Ainslup Credits de tu plan "
                                            f"({limit} al mes). Se renuevan el 1º de cada mes. "
                                            f"Mejora tu plan para obtener más."
                                        ),
                                    })
                                    await send({"type": "done", "requestId": request_id or None})
                                    continue
                            else:
                                beta = tier_config.get_beta_plan()
                                if beta:
                                    # Beta interna: créditos del plan elegido (ledger local),
                                    # modelos siempre Free. Sin trial de licencia.
                                    allowed, remaining, limit, reset_sec = await asyncio.to_thread(
                                        credits.check, beta, None, 1)
                                    if not allowed:
                                        await send({
                                            "type": "error",
                                            "requestId": request_id or None,
                                            "content": (
                                                f"Agotaste los Ainslup Credits beta de tu plan "
                                                f"({limit} al mes). Se renuevan el 1º de cada mes."
                                            ),
                                        })
                                        await send({"type": "done", "requestId": request_id or None})
                                        continue
                                    await asyncio.to_thread(profile.record_interaction)
                                else:
                                    gate = await asyncio.to_thread(lic.gate_status)
                                    if not gate["allowed"]:
                                        await send({"type": "license", "state": gate["state"]})
                                        await send({"type": "done", "requestId": request_id or None})
                                        continue
                                    if gate["reason"] == "trial":
                                        await asyncio.to_thread(lic.record_trial_use)
                                    await asyncio.to_thread(profile.record_interaction)

                            # Rehacer/editar: se aplica sobre la sesión bajo lock
                            # antes de tomar el snapshot.
                            async with self._session_lock:
                                if data.get("replaceLast"):
                                    session.pop_last("assistant")
                                    if data.get("replaceUser"):
                                        session.pop_last("user")
                                session.add("user", text)

                            # La respuesta corre en su propio task: la
                            # conversación no se bloquea con la ejecución.
                            xens_model = data.get("xens_model") or data.get("model") or "auto"
                            asyncio.ensure_future(self._run_response(
                                ws, send, session, acct_state, text, request_id, xens_model,
                            ))
                            continue

                        elif data.get("type") == "clear":
                            async with self._session_lock:
                                self._session_epoch += 1
                                session.clear()
                            await send({"type": "cleared"})

                        elif data.get("type") == "get_profile":
                            account = acct_state.get("account")
                            uid = str(account.get("uid") or "") if account else None
                            profile.load(uid)
                            ctx = profile.get_memory_context()
                            await send({"type": "profile", "content": ctx})

                        elif data.get("type") == "get_license":
                            await send({"type": "license", "state": lic.get_state()})

                        elif data.get("type") == "activate":
                            key = str(data.get("key") or "").strip()
                            if not key:
                                await send({"type": "license", "state": lic.get_state(), "result": {"success": False, "error": "No key provided"}})
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
                                await send({"type": "license", "state": lic.get_state(), "result": result})

                        elif data.get("type") == "deactivate":
                            lic.deactivate()
                            registry.set_tier("free")
                            reset_provider()
                            await send({"type": "license", "state": lic.get_state(), "result": {"success": True, "status": "deactivated"}})

                        elif data.get("type") == "set_beta_plan":
                            # Beta interna: cualquiera elige plan en Configuración.
                            # Créditos/tools del plan, modelos siempre Free.
                            plan = str(data.get("plan") or "").strip().lower()
                            try:
                                beta = await asyncio.to_thread(tier_config.set_beta_plan, plan)
                                base = lic.get_state().get("tier") or "free"
                                registry.set_tier(beta or base)
                                reset_provider()
                                await send({"type": "beta_plan", "beta_plan": beta,
                                            "plan": tier_config.effective_tier(base),
                                            "models": tier_config.aliases_for_tier("free")})
                            except ValueError as e:
                                await send({"type": "beta_plan", "error": str(e),
                                            "beta_plan": tier_config.get_beta_plan()})

                        elif data.get("type") == "get_beta_plan":
                            await send({"type": "beta_plan", "beta_plan": tier_config.get_beta_plan(),
                                        "models": tier_config.aliases_for_tier("free")})

                        elif data.get("type") == "check_exe_update":
                            from ..core.updater import check_exe_update
                            info = await check_exe_update()
                            info["type"] = "exe_update"
                            await send(info)

                        elif data.get("type") == "download_exe_update":
                            from ..core.updater import download_exe_update
                            res = await download_exe_update()
                            await send({"type": "exe_update", "downloaded": bool(res.get("ok")),
                                        "error": res.get("error", ""), "bytes": res.get("bytes", 0)})

                        elif data.get("type") == "restart_for_exe_update":
                            from ..core.updater import stage_exe_swap_and_exit
                            await send({"type": "exe_update", "restarting": True})
                            await asyncio.sleep(0.5)
                            await asyncio.to_thread(stage_exe_swap_and_exit)

                    except Exception as e:
                        logger.exception("WS handler error")
                        try:
                            await send({"type": "error", "content": f"Error interno: {e}"})
                        except Exception:
                            pass

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WS error: {ws.exception()}")

        finally:
            task_manager.unsubscribe(listener_id)
            trigger_manager.unsubscribe(trigger_listener_id)
            heartbeat_task.cancel()
            acc = acct_state.get("account")
            if acc:
                self._connected_uids.discard(str(acc.get("uid") or ""))

        return ws

    async def _run_response(self, ws, send, session, acct_state, text, request_id, xens_model="auto", origin_conv_id=None):
        """Task de respuesta para UN mensaje: snapshot aislado del contexto,
        ejecución concurrente, y escritura ordenada en la sesión."""
        try:
            account = acct_state.get("account")
            tier = tier_config.effective_tier(account.get("tier") if account else registry.get_tier())
            uid = str(account.get("uid") or "") if account else None
            account_token = (account.get("_token") or "") if account else ""

            async with self._session_lock:
                epoch = self._session_epoch
                messages = copy.deepcopy(self._build_messages(session, uid))

            full = ""
            async for chunk in run_tool_loop(messages, tier=tier, uid=uid, xens_model=xens_model, account_token=account_token):
                if isinstance(chunk, dict):
                    chunk["requestId"] = request_id or None
                    await send(chunk)
                    if chunk["type"] == "content":
                        full += chunk.get("content") or ""
                elif isinstance(chunk, str):
                    full += chunk
                    await send({"type": "content", "requestId": request_id or None, "content": chunk})

            if full and self._session_epoch == epoch:
                async with self._session_lock:
                    session.add("assistant", full)

            if account:
                used, credit_limit = credits.get_usage(tier=tier, uid=uid)
                await send({
                    "type": "credits",
                    "requestId": request_id or None,
                    "credits": max(0, credit_limit - used),
                    "creditsUsed": used,
                    "creditsLimit": credit_limit,
                })

            msgs_count = len(session.messages)
            if msgs_count > 0 and msgs_count % 8 == 0:
                asyncio.ensure_future(summarize_conversation(messages, uid=uid))
            asyncio.ensure_future(extract_user_info(messages, uid=uid))

            await send({"type": "done", "requestId": request_id or None})
        except Exception as e:
            logger.exception("Response task error")
            try:
                await send({"type": "error", "requestId": request_id or None,
                            "content": "Failed to generate response"})
            except Exception:
                pass

    async def _heartbeat(self, ws, send):
        try:
            while True:
                await asyncio.sleep(30)
                try:
                    await send({"type": "ping"})
                except:
                    break
        except asyncio.CancelledError:
            pass

    async def _handle_index(self, request):
        index_path = _static_dir() / "index.html"
        if index_path.exists():
            return web.Response(
                text=index_path.read_text(encoding="utf-8"),
                content_type="text/html"
            )
        return web.Response(
                text="<h1>Ainslup Assistant</h1><p>Web UI not found.</p>",
            content_type="text/html"
        )

    async def _handle_api_profile(self, request):
        account = await firebase_auth.account_from_authorization(
            request.headers.get("Authorization")
        )
        beta = tier_config.get_beta_plan()
        if account:
            uid = str(account.get("uid") or "")
            tier = tier_config.effective_tier(account.get("tier") or "free")
            used, credit_limit = credits.get_usage(tier=tier, uid=uid)
            lic_state = lic.get_state()
            try:
                from ..core import paypal as paypal_mod
                paypal_info = {"configured": paypal_mod.is_configured(),
                               "plans": [p for p in ("lite", "pro", "premium")
                                         if paypal_mod.is_plan_configured(p)]}
            except Exception:
                paypal_info = {"configured": False, "plans": []}
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
                "beta": bool(beta),
                "beta_plan": beta,
                "beta_models": tier_config.aliases_for_tier("free") if beta else [],
                "paypal": paypal_info,
                "license": lic_state,
            })
        profile.load()
        lic_state = lic.get_state()
        tier = tier_config.effective_tier(lic_state.get("tier") or "free")
        # El tier FREE ES la prueba gratuita: un solo contador (trial),
        # no dos números distintos en pantalla.
        if tier == "free":
            message_limit = lic_state.get("trial_limit", 300)
            message_count = lic_state.get("trial_used", 0)
        else:
            message_limit = 999999
            message_count = profile.interaction_count
        if beta:
            used_b, limit_b = credits.get_usage(tier=tier, uid=None)
        return web.json_response({
            "account": False,
            "name": profile.name or "",
            "email": lic_state.get("name") or "",
            "interactions": profile.interaction_count,
            "messageCount": message_count,
            "messageLimit": message_limit,
            "credits": (max(0, limit_b - used_b) if beta else None),
            "creditsUsed": (used_b if beta else None),
            "creditsLimit": (limit_b if beta else None),
            "plan": tier,
            "beta": bool(beta),
            "beta_plan": beta,
            "beta_models": tier_config.aliases_for_tier("free") if beta else [],
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

    async def _handle_api_paypal_subscribe(self, request):
        """Crea una suscripción PayPal para la cuenta logueada. -> {approve_url}."""
        account = await firebase_auth.account_from_authorization(
            request.headers.get("Authorization")
        )
        if not account:
            return web.json_response({"error": "login required"}, status=401)
        try:
            body = await request.json()
        except Exception:
            body = {}
        plan = str(body.get("plan") or "").strip().lower()
        try:
            from ..core import paypal as paypal_mod
        except Exception:
            return web.json_response({"error": "paypal unavailable"}, status=500)
        if plan not in paypal_mod.PLANS:
            return web.json_response({"error": "unknown plan"}, status=400)
        if not paypal_mod.is_plan_configured(plan):
            return web.json_response({"error": "plan not configured"}, status=501)
        sub = await paypal_mod.create_subscription(plan, uid=str(account.get("uid") or ""))
        if not sub or not sub.get("approve_url"):
            return web.json_response({"error": "paypal failed"}, status=502)
        return web.json_response({"approve_url": sub["approve_url"],
                                  "subscription_id": sub.get("subscription_id"),
                                  "plan": plan})

    def _paypal_page(self, title: str, text: str, ok: bool) -> web.Response:
        color = "#3ddc84" if ok else "#e5484d"
        return web.Response(
            text=f"<!DOCTYPE html><html lang='es'><head><meta charset='UTF-8'>"
                 f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
                 f"<title>{title} — AINSLUP</title>"
                 f"<link rel='stylesheet' href='/site.css'></head><body>"
                 f"<div class='auth-shell'><div class='auth-card'>"
                 f"<div class='auth-brand'>AINSLUP</div>"
                 f"<p class='auth-subtitle' style='color:{color}'>{title}</p>"
                 f"<p class='modal-text'>{text}</p>"
                 f"<a href='/index.html' class='btn btn-primary btn-block'>Volver al chat</a>"
                 f"</div></div></body></html>",
            content_type="text/html",
        )

    async def _handle_paypal_return(self, request):
        sub_id = (request.query.get("subscription_id") or "").strip()
        if not sub_id:
            return self._paypal_page("Pago sin confirmar",
                                     "PayPal no devolvió suscripción. Revisa tu plan en Configuración en unos minutos.",
                                     False)
        try:
            from ..core import paypal as paypal_mod
            sub = await paypal_mod.get_subscription(sub_id)
        except Exception:
            sub = None
        if sub and sub.get("status") in ("ACTIVE", "APPROVAL_PENDING", "APPROVED"):
            plan = (sub.get("plan") or "tu plan").upper()
            return self._paypal_page("¡Plan activado!",
                                     f"Tu suscripción {plan} está en proceso. El plan se refleja en tu cuenta en cuanto PayPal confirme (normalmente segundos).",
                                     True)
        return self._paypal_page("Pago sin confirmar",
                                 "No pudimos verificar la suscripción todavía. Si el cobro aparece en PayPal, el plan se activará solo vía webhook.",
                                 False)

    async def _handle_paypal_cancel(self, request):
        return self._paypal_page("Pago cancelado",
                                 "No se realizó ningún cobro. Puedes intentarlo de nuevo cuando quieras.",
                                 False)

    async def start(self):
        self._app = web.Application()
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/ws", self._handle_ws)
        self._app.router.add_get("/chat", self._handle_index)
        self._app.router.add_get("/api/profile", self._handle_api_profile)
        self._app.router.add_get("/api/deps", self._handle_api_deps)
        self._app.router.add_post("/api/deps/install", self._handle_api_deps_install)
        self._app.router.add_get("/api/version", self._handle_api_version)
        self._app.router.add_post("/api/paypal/subscribe", self._handle_api_paypal_subscribe)
        self._app.router.add_get("/paypal/return", self._handle_paypal_return)
        self._app.router.add_get("/paypal/cancel", self._handle_paypal_cancel)
        static_dir = _static_dir()
        if not static_dir.is_dir():
            logger.warning("Web static dir missing (%s); UI servida sin estáticos", static_dir)
        else:
            self._app.router.add_static("/", static_dir, show_index=False)

        st = lic.get_state()
        beta = tier_config.get_beta_plan()
        if beta:
            try:
                registry.set_tier(beta)
            except ValueError:
                pass
        elif st["status"] in ("licensed", "unlocked"):
            try:
                registry.set_tier(st.get("tier") or "free")
            except ValueError:
                pass

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", PORT)
        await site.start()
        trigger_manager.start()
        logger.info(f"Web UI at http://127.0.0.1:{PORT}")

    async def stop(self):
        trigger_manager.stop()
        if self._runner:
            await self._runner.cleanup()