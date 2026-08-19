"""Unit tests: aislamiento del perfil por cuenta (SaaS).

Uso: python tests/test_profile_uid.py  (desde la raÃ­z del repo)
"""
import os
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

from xens_assistant.memory import profile as pm


def main():
    tmp = Path(tempfile.mkdtemp(prefix="xens_profile_test_"))
    pm.PROFILE_DIR = tmp
    pm.PROFILE_FILE = tmp / "profile.json"

    p = pm.UserProfile()
    p.load()
    p.name = "Local"
    p.learn_fact("Facto local")
    # sin uid: archivo clÃ¡sico
    assert (tmp / "profile.json").exists(), "debe escribir profile.json en local"

    p2 = pm.UserProfile()
    p2.load("u-123")
    # uid distinto: estado limpio, archivo aparte
    assert p2.name == "", "el perfil de una cuenta no puede heredar el local"
    assert p2.facts == [], "los hechos no se mezclan entre perfiles"
    p2.name = "Cuenta A"
    p2.learn_fact("Facto de la cuenta A")
    p2.add_project("Proyecto Alpha", "desc")
    p2.track_topic("python")
    fa = tmp / "profile-u-123.json"
    assert fa.exists(), "debe escribir profile-u-123.json"

    # mismo uid: carga el archivo propio
    p3 = pm.UserProfile()
    p3.load("u-123")
    assert p3.name == "Cuenta A", p3.name
    assert "Facto de la cuenta A" in p3.facts, p3.facts
    assert any(x["name"] == "Proyecto Alpha" for x in p3.projects), p3.projects
    assert p3.common_topics.get("python") == 1, p3.common_topics

    # local otra vez: sigue intacto y separado
    p4 = pm.UserProfile()
    p4.load()
    assert p4.name == "Local", p4.name

    # otro uid: no ve nada del uid anterior
    p5 = pm.UserProfile()
    p5.load("u-999")
    assert p5.name == "" and p5.facts == [], "cuentas distintas no comparten memoria"

    # el singleton del mÃ³dulo tambiÃ©n respeta el uid
    pm.profile.load("u-123")
    assert pm.profile.name == "Cuenta A"
    pm.profile.load()
    assert pm.profile.name == "Local"

    # limpieza
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    print("PROFILE_UID_OK")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)


