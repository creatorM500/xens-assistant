"""Tests: contrato del Edge (handlers, rutas y RPCs sin red).

Garantiza que el edge expone lo que el cliente usa y que cada RPC
llamado tiene su migración. Si alguien borra un handler, esto falla.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

REPO = Path(__file__).resolve().parent.parent
EDGE = REPO / "supabase" / "functions" / "license" / "index.ts"
WEBHOOK = REPO / "supabase" / "functions" / "paypal-webhook" / "index.ts"
MIGR = REPO / "supabase" / "migrations"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_license_handlers_exist():
    src = _read(EDGE)
    for fn in ("handleActivate", "handleMe", "handleChat", "handleChatStream",
               "handleCreditsCheck", "handleCreditsSpend", "handleDeactivate",
               "handleProvisionFree", "resolveAuth", "supabaseUser"):
        assert f"function {fn}" in src or f"async function {fn}" in src, fn


def test_license_routes_exist():
    src = _read(EDGE)
    for route in ('path==="activate"', 'path==="me"', 'path==="chat"',
                  'path==="chat-stream"', 'path==="credits-check"',
                  'path==="credits-spend"', 'path==="deactivate"',
                  'path==="provision-free"', 'path==="health"'):
        assert route in src, route


def test_license_tiers_and_models():
    src = _read(EDGE)
    for tier, credits in (("free", "5000"), ("lite", "15000"),
                          ("pro", "35000"), ("premium", "125000")):
        assert tier in src
        assert credits in src
    for model in ("mistralai/mistral-nemo", "deepseek/deepseek-chat",
                  "anthropic/claude-sonnet-4"):
        assert model in src, model


def test_every_rpc_has_migration():
    src = _read(EDGE)
    rpcs = set(re.findall(r'rpc\("([a-z_]+)"', src))
    rpcs |= set(re.findall(r"/rpc/([a-z_]+)", src))
    assert rpcs, "no se detectaron RPCs"
    mig_text = "\n".join(p.read_text(encoding="utf-8") for p in MIGR.glob("*.sql"))
    for rpc in rpcs:
        assert rpc in mig_text, f"RPC {rpc} sin migración"


def test_webhook_supports_all_paid_plans_and_tier_sync():
    src = _read(WEBHOOK)
    assert "PLAN_LITE" in src
    assert "PLAN_PRO" in src
    assert "PLAN_PREMIUM" in src
    assert "BILLING.SUBSCRIPTION.ACTIVATED" in src
    assert "BILLING.SUBSCRIPTION.CANCELLED" in src
    assert "app_metadata" in src
    assert "/auth/v1/admin/users" in src
