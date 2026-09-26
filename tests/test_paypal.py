"""Tests: planes PayPal, custom_id y helpers puros (sin red)."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

from ainslup_assistant.core import paypal as pp


def test_plans_cover_paid_tiers():
    for tier in ("lite", "pro", "premium"):
        assert tier in pp.PLANS, tier
        assert float(pp.plan_price(tier)) > 0
    assert pp.plan_price("free") is None
    assert pp.plan_price("nope") is None


def test_custom_id_roundtrip():
    cid = pp.custom_id_for("uid-123", "pro")
    assert cid == "uid-123:pro"
    uid, plan = pp.parse_custom_id(cid)
    assert (uid, plan) == ("uid-123", "pro")


def test_parse_custom_id_rejects_garbage():
    assert pp.parse_custom_id("") == (None, None)
    assert pp.parse_custom_id("nouid") == (None, None)
    assert pp.parse_custom_id("uid:unknownplan") == ("uid", None)


def test_approve_url_from_links():
    data = {"links": [
        {"rel": "self", "href": "https://x"},
        {"rel": "approve", "href": "https://paypal/approve/1"},
    ]}
    assert pp.approve_url_from(data) == "https://paypal/approve/1"
    assert pp.approve_url_from({"links": []}) is None
    assert pp.approve_url_from({}) is None


def test_not_configured_without_creds(monkeypatch):
    monkeypatch.setattr(pp, "_cfg", lambda: {})
    for var in ("AINSLUP_PAYPAL_CLIENT_ID", "AINSLUP_PAYPAL_CLIENT_SECRET"):
        monkeypatch.delenv(var, raising=False)
    assert pp.is_configured() is False
    assert pp.plan_id_for("pro") == ""
    assert pp.is_plan_configured("pro") is False
