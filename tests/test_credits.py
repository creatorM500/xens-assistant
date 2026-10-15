"""Unit tests: Ainslup Credits (ledger por uid, multiplicadores, lÃ­mites).

Uso: python tests/test_credits.py  (desde la raÃ­z del repo)
"""
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

from ainslup_assistant.core import credits as cred_mod
from ainslup_assistant.core.credits import CreditLedger
from ainslup_assistant.core.tier_config import tier_config


def main():
    tmp = Path(tempfile.mkdtemp(prefix="xens_credits_test_"))
    cred_mod.CREDITS_DIR = tmp
    cred_mod.CREDITS_FILE = tmp / "credits.json"

    c = CreditLedger()

    # multiplicadores por modelo
    assert cred_mod.model_multiplier("deepseek-chat") == 1.2
    assert cred_mod.model_multiplier("mistral-medium-latest") == 3.5
    assert cred_mod.model_multiplier("anthropic/claude-sonnet-4") == 20.0
    assert cred_mod.model_multiplier("") == cred_mod.DEFAULT_MULTIPLIER
    assert cred_mod.model_multiplier("openai/gpt-oss-20b") == 1.0
    assert cred_mod.model_multiplier("deepseek/deepseek-v4.1-flash") == 1.2
    assert cred_mod.model_multiplier("deepseek/deepseek-v4-pro") == 6.0
    assert cred_mod.model_multiplier("nvidia/nemotron-3-ultra") == 0.5

    # costo: base (prompt + 3.5*out)/1000 * mult, mÃ­nimo 1
    assert c.cost(1000, 0, "deepseek-chat") == 2
    assert c.cost(0, 1000, "deepseek-chat") == 5
    assert c.cost(100, 100, "deepseek-chat") == 1
    assert c.cost(1000, 0, "claude-sonnet-4") == 20
    assert c.cost(0, 0, "deepseek-chat") == 1  # mÃ­nimo 1

    # lÃ­mites por tier (no pueden faltar)
    for tier in ("free", "pro", "premium"):
        assert tier_config.get_credits(tier) > 0, tier

    # gasto por uid aislado
    r1 = c.spend("pro", "u-1", None, model="mistral-medium-latest", prompt_tokens=1000, completion_tokens=0)
    assert r1["used"] == 4, r1
    r2 = c.spend("pro", "u-2", None, model="deepseek-chat", prompt_tokens=1000, completion_tokens=0)
    assert r2["used"] == 2, r2
    used1, limit1 = c.get_usage("pro", "u-1")
    assert used1 == 4 and limit1 == tier_config.get_credits("pro")

    # con usage del provider
    r3 = c.spend("free", "u-1", {"prompt_tokens": 5000, "completion_tokens": 1000}, model="deepseek-chat")
    assert r3["spent_now"] == 11, r3  # (5000 + 3500)/1000*1.2

    # check respeta lÃ­mite
    allowed, remaining, limit, reset_sec = c.check("free", "u-1")
    assert remaining >= 0 and limit == tier_config.get_credits("free")
    assert reset_sec > 0, "reset mensual debe estar en el futuro"

    # persistencia: nuevo ledger lee lo gastado
    c2 = CreditLedger()
    used1b, _ = c2.get_usage("pro", "u-1")
    assert used1b == 4, used1b

    # reset limpia
    c.reset()
    c3 = CreditLedger()
    used1c, _ = c3.get_usage("pro", "u-1")
    assert used1c == 0, used1c

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    print("CREDITS_OK")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)


