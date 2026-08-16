"""paypal.py — Checkout de PayPal (Orders API v2) para el plan de la cuenta.

Config-driven (config["paypal"]):
    {"mode": "sandbox"|"live", "client_id": "...", "client_secret": "...",
     "return_url": "http://127.0.0.1:18000/paypal/return",
     "cancel_url": "http://127.0.0.1:18000/paypal/cancel"}

Planes (precio en USD):
    pro      -> 10.00/mes
    premium  -> 30.00/mes

Flujo:
    1. create_order(plan, uid) -> {approve_url, order_id}
    2. el usuario aprueba en PayPal y vuelve con ?token=<order_id>
    3. capture_order(order_id) -> {status: "COMPLETED", plan, uid}
    4. la suscripción se registra en la nube (Edge Function paypal-webhook
       también la confirma por webhook para el caso "sin retorno").

El pago en sí queda registrado en Supabase (tabla subscriptions) por la
Edge Function; este módulo solo crea y captura la orden.
"""
import asyncio, json, logging
from typing import Optional

import httpx

logger = logging.getLogger("xens.paypal")

PLANS = {
    "pro": {"amount": "10.00", "description": "XENS Plan Pro (mensual)"},
    "premium": {"amount": "30.00", "description": "XENS Plan Premium (mensual)"},
}


def _cfg() -> dict:
    try:
        from .config import config
        return (config.get("paypal", {}) or {})
    except Exception:
        return {}


def is_configured() -> bool:
    c = _cfg()
    return bool(c.get("client_id") and c.get("client_secret"))


def _api_url() -> str:
    mode = _cfg().get("mode", "sandbox")
    return "https://api-m.sandbox.paypal.com" if mode != "live" else "https://api-m.paypal.com"


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


async def create_order(plan: str, uid: str = "", email: str = "") -> Optional[dict]:
    """Crea una orden de pago. Devuelve {approve_url, order_id} o None."""
    if plan not in PLANS:
        return None
    c = _cfg()
    token = await _token()
    if not token:
        return None
    spec = PLANS[plan]
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": f"{plan}:{uid}" if uid else plan,
            "description": spec["description"],
            "amount": {"currency_code": "USD", "value": spec["amount"]},
        }],
        "application_context": {
            "brand_name": "XENS",
            "user_action": "PAY_NOW",
            "return_url": c.get("return_url") or "http://127.0.0.1:18000/paypal/return",
            "cancel_url": c.get("cancel_url") or "http://127.0.0.1:18000/paypal/cancel",
        },
    }
    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.post(
            f"{_api_url()}/v2/checkout/orders",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        if r.status_code not in (200, 201):
            logger.warning("PayPal create_order falló: %s %s", r.status_code, r.text[:300])
            return None
        data = r.json()
        approve = next(
            (l.get("href") for l in data.get("links", []) if l.get("rel") == "approve"),
            None,
        )
        return {"order_id": data.get("id"), "approve_url": approve}


async def capture_order(order_id: str) -> Optional[dict]:
    """Captura una orden aprobada. Devuelve {status, plan, uid} o None."""
    token = await _token()
    if not token:
        return None
    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.post(
            f"{_api_url()}/v2/checkout/orders/{order_id}/capture",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        if r.status_code not in (200, 201):
            logger.warning("PayPal capture falló: %s %s", r.status_code, r.text[:300])
            return None
        data = r.json()
        status = data.get("status")
        plan, uid = None, None
        for pu in data.get("purchase_units", []):
            ref = (pu.get("reference_id") or "")
            if ":" in ref:
                plan, _, uid = ref.partition(":")
        return {"status": status, "plan": plan, "uid": uid, "raw": data}


def plan_price(plan: str) -> Optional[str]:
    spec = PLANS.get(plan)
    return spec["amount"] if spec else None