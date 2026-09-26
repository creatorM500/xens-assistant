"""paypal.py — Suscripciones PayPal (Subscriptions API v1) para la cuenta.

Config-driven (config["paypal"] o env AINSLUP_PAYPAL_*):
    {"mode": "sandbox"|"live", "client_id": "...", "client_secret": "...",
     "plan_ids": {"lite": "P-...", "pro": "P-...", "premium": "P-..."},
     "return_url": "http://127.0.0.1:18000/paypal/return",
     "cancel_url": "http://127.0.0.1:18000/paypal/cancel"}

Los precios viven en los planes creados en el dashboard de PayPal
(los plan_id); aquí solo se muestran para la UI.

Planes (USD/mes):
    lite     -> 5.00
    pro      -> 10.00
    premium  -> 30.00

Flujo:
    1. POST /api/paypal/subscribe {plan} (con cuenta) -> {approve_url}
    2. el usuario aprueba en PayPal y vuelve a /paypal/return?subscription_id=...
    3. el webhook (Edge paypal-webhook) activa el plan en app_metadata
       al recibir BILLING.SUBSCRIPTION.ACTIVATED (fuente autoritativa).
    4. /paypal/return verifica el estado vía API y lo muestra.
"""
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("ainslup.paypal")

PLANS = {
    "lite": {"amount": "5.00", "description": "AINSLUP Plan Lite (mensual)"},
    "pro": {"amount": "10.00", "description": "AINSLUP Plan Pro (mensual)"},
    "premium": {"amount": "30.00", "description": "AINSLUP Plan Premium (mensual)"},
}


def _cfg() -> dict:
    try:
        from .config import config
        base = (config.get("paypal", {}) or {})
    except Exception:
        base = {}
    cfg = dict(base)
    if os.environ.get("AINSLUP_PAYPAL_MODE"):
        cfg["mode"] = os.environ["AINSLUP_PAYPAL_MODE"]
    if os.environ.get("AINSLUP_PAYPAL_CLIENT_ID"):
        cfg["client_id"] = os.environ["AINSLUP_PAYPAL_CLIENT_ID"]
    if os.environ.get("AINSLUP_PAYPAL_CLIENT_SECRET"):
        cfg["client_secret"] = os.environ["AINSLUP_PAYPAL_CLIENT_SECRET"]
    return cfg


def is_configured() -> bool:
    c = _cfg()
    return bool(c.get("client_id") and c.get("client_secret"))


def plan_id_for(plan: str) -> str:
    """ID del plan en PayPal (creado en el dashboard). Vacío = sin configurar."""
    c = _cfg()
    ids = c.get("plan_ids") or {}
    if isinstance(ids, dict) and ids.get(plan):
        return str(ids[plan])
    env = os.environ.get(f"AINSLUP_PAYPAL_PLAN_{plan.upper()}_ID", "")
    if env:
        return env
    return ""


def is_plan_configured(plan: str) -> bool:
    return plan in PLANS and bool(plan_id_for(plan))


def _api_url() -> str:
    mode = _cfg().get("mode", "sandbox")
    return "https://api-m.sandbox.paypal.com" if mode != "live" else "https://api-m.paypal.com"


def custom_id_for(uid: str, plan: str) -> str:
    """Une uid:plan para que el webhook sepa a quién activar."""
    return f"{uid}:{plan}"


def parse_custom_id(custom: str) -> tuple[Optional[str], Optional[str]]:
    if not custom or ":" not in custom:
        return None, None
    uid, _, plan = custom.partition(":")
    if not uid or plan not in PLANS:
        return uid or None, None
    return uid, plan


def approve_url_from(data: dict) -> Optional[str]:
    for link in data.get("links", []) or []:
        if link.get("rel") == "approve":
            return link.get("href")
    return None


async def _token() -> Optional[str]:
    c = _cfg()
    if not is_configured():
        return None
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            f"{_api_url()}/v1/oauth2/token",
            auth=(c["client_id"], c["client_secret"]),
            data={"grant_type": "client_credentials"},
        )
        if r.status_code != 200:
            logger.warning("PayPal token falló: %s", r.status_code)
            return None
        return r.json().get("access_token")


def _redirect_urls() -> tuple[str, str]:
    c = _cfg()
    return (
        c.get("return_url") or "http://127.0.0.1:18000/paypal/return",
        c.get("cancel_url") or "http://127.0.0.1:18000/paypal/cancel",
    )


async def create_subscription(plan: str, uid: str = "") -> Optional[dict]:
    """Crea una suscripción. Devuelve {subscription_id, approve_url, plan} o None."""
    if plan not in PLANS:
        return None
    pid = plan_id_for(plan)
    if not pid:
        logger.warning("PayPal sin plan_id para '%s' (config paypal.plan_ids)", plan)
        return None
    token = await _token()
    if not token:
        return None
    return_url, cancel_url = _redirect_urls()
    payload = {
        "plan_id": pid,
        "custom_id": custom_id_for(uid, plan) if uid else plan,
        "application_context": {
            "brand_name": "AINSLUP",
            "user_action": "SUBSCRIBE_NOW",
            "return_url": return_url,
            "cancel_url": cancel_url,
        },
    }
    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.post(
            f"{_api_url()}/v1/billing/subscriptions",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        if r.status_code not in (200, 201):
            logger.warning("PayPal create_subscription falló: %s %s", r.status_code, r.text[:300])
            return None
        data = r.json()
        return {
            "subscription_id": data.get("id"),
            "approve_url": approve_url_from(data),
            "plan": plan,
            "status": data.get("status"),
        }


async def get_subscription(subscription_id: str) -> Optional[dict]:
    """Estado actual de una suscripción. Devuelve {status, plan, uid} o None."""
    if not subscription_id:
        return None
    token = await _token()
    if not token:
        return None
    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.get(
            f"{_api_url()}/v1/billing/subscriptions/{subscription_id}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        if r.status_code != 200:
            logger.warning("PayPal get_subscription falló: %s %s", r.status_code, r.text[:300])
            return None
        data = r.json()
        uid, plan = parse_custom_id(str(data.get("custom_id") or ""))
        return {"status": data.get("status"), "plan": plan, "uid": uid, "raw": data}


def plan_price(plan: str) -> Optional[str]:
    spec = PLANS.get(plan)
    return spec["amount"] if spec else None
