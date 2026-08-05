"""
scripts/supabase_admin.py — Emisión y gestión de seriales Xens en Supabase.

Genera keys XENS-... (misma firma HMAC que core.license) y las inserta en la
tabla licenses del proyecto. La activacion online (Edge Function) valida la key
contra esa tabla, asi que T O D O serial vendido debe generarse con este script
(o con make_license.py + insert manual).

Credenciales: ~/.xens/supabase.json  ({"management_pat", "service_role", "project_ref"})
  o entorno:  XENS_SUPABASE_TOKEN  (management PAT)

Uso:
    python scripts/supabase_admin.py gen --tier PRO --days 365 --name MARIA
    python scripts/supabase_admin.py gen --tier FREE --days 0 --count 5
    python scripts/supabase_admin.py list
    python scripts/supabase_admin.py list --tier pro
    python scripts/supabase_admin.py check XENS-PRO-365-... 
    python scripts/supabase_admin.py revoke XENS-PRO-365-...
    python scripts/supabase_admin.py usage XENS-PRO-365-...
"""
import argparse, json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import license as lic

import httpx

TIER_DB = {"FREE": "free", "PRO": "pro", "PREMIUM": "premium"}
API = "https://api.supabase.com/v1"


def _creds() -> dict:
    env_pat = os.environ.get("XENS_SUPABASE_TOKEN")
    if env_pat:
        return {"management_pat": env_pat, "project_ref": os.environ.get("XENS_PROJECT_REF", "tzlbgoydgptlhspzdhfu")}
    try:
        data = json.loads((Path.home() / ".xens" / "supabase.json").read_text(encoding="utf-8"))
        if data.get("management_pat"):
            return data
    except Exception as e:
        print(f"! No credentials: {e}")
    sys.exit("Set XENS_SUPABASE_TOKEN or create ~/.xens/supabase.json")


def _headers(creds: dict) -> dict:
    return {"Authorization": f"Bearer {creds['management_pat']}", "Content-Type": "application/json"}


def _query(creds: dict, sql: str) -> list:
    r = httpx.post(
        f"{API}/projects/{creds['project_ref']}/database/query",
        headers=_headers(creds), json={"query": sql}, timeout=60,
    )
    if r.status_code >= 400:
        sys.exit(f"DB error {r.status_code}: {r.text[:500]}")
    return r.json()


def cmd_gen(creds: dict, args) -> None:
    tier = args.tier.upper()
    if tier not in TIER_DB:
        sys.exit(f"tier must be one of {list(TIER_DB)}")
    for _ in range(args.count):
        key = lic.issue_serial(tier=tier, days=args.days, hwid="00000000", name=args.name)
        key = key.upper()  # canonical: el cliente y la Edge Function normalizan a mayusculas
        expires = "NULL" if args.days == 0 else f"now() + interval '{int(args.days)} days'"
        sql = (
            "insert into public.licenses (key, tier, expires_at, max_activations) "
            f"values ('{key}', '{TIER_DB[tier]}', {expires}, {args.max_activations}) "
            "on conflict (key) do nothing returning key, tier, expires_at;"
        )
        rows = _query(creds, sql)
        print(f"OK {key}" if rows else f"!! duplicate/skip {key}")
    print("Tip: entrega este serial al comprador. Se ata al primer dispositivo que active.")


def cmd_list(creds: dict, args) -> None:
    where = f"where tier = '{args.tier.lower()}'" if args.tier else ""
    rows = _query(creds, (
        "select key, tier, expires_at, revoked, used_activations, max_activations, "
        "to_char(created_at, 'YYYY-MM-DD') as created "
        f"from public.licenses {where} order by created_at desc limit {args.limit};"
    ))
    if not rows:
        print("(no serials)")
        return
    for r in rows:
        exp = (r.get("expires_at") or "lifetime")
        if isinstance(exp, str):
            exp = exp[:10]
        print(f"{r['key']:<40} {r['tier']:<8} {exp:<12} "
              f"{'REVOKED' if r['revoked'] else 'ok':<7} "
              f"devices {r['used_activations']}/{r['max_activations']}")


def cmd_check(creds: dict, args) -> None:
    rows = _query(creds, (
        "select l.key, l.tier, l.revoked, l.expires_at, l.created_at, "
        "count(d.id)::int as devices "
        "from public.licenses l left join public.devices d on d.license_id = l.id "
        f"where l.key = '{args.key.upper()}' group by l.id;"
    ))
    if not rows:
        sys.exit(f"No license with key {args.key.upper()}")
    for r in rows:
        print(r)


def cmd_revoke(creds: dict, args) -> None:
    rows = _query(creds, (
        f"update public.licenses set revoked = true "
        f"where key = '{args.key.upper()}' returning key, revoked;"
    ))
    print("REVOKED" if rows else f"No license with key {args.key.upper()}")
    print("El proximo chat del cliente dara 401 al instante.")


def cmd_usage(creds: dict, args) -> None:
    lic = _query(creds, f"select id, key from public.licenses where key = '{args.key.upper()}';")
    if not lic:
        sys.exit(f"No license with key {args.key.upper()}")
    rows = _query(creds, (
        f"select period, chats, tokens_in, tokens_out, to_char(updated_at, 'YYYY-MM-DD HH24:MI') as up "
        f"from public.usage where license_id = '{lic[0]['id']}' order by period desc limit {args.limit};"
    ))
    if not rows:
        print("(no usage yet)")
        return
    for r in rows:
        print(f"{r['period']}  chats={r['chats']:<5} tokens_in={r['tokens_in']:<8} "
              f"tokens_out={r['tokens_out']:<8} updated={r['up']}")


def main():
    ap = argparse.ArgumentParser(description="Xens serial admin (Supabase)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("gen", help="generate + insert serials")
    p.add_argument("--tier", default="PRO", help="FREE|PRO|PREMIUM")
    p.add_argument("--days", type=int, default=365, help="0 = lifetime")
    p.add_argument("--name", default="", help="buyer name suffix")
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--max-activations", type=int, default=3)
    p.set_defaults(fn=cmd_gen)

    p = sub.add_parser("list")
    p.add_argument("--tier", default="", help="filter free|pro|premium")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("check")
    p.add_argument("key")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("revoke")
    p.add_argument("key")
    p.set_defaults(fn=cmd_revoke)

    p = sub.add_parser("usage")
    p.add_argument("key")
    p.add_argument("--limit", type=int, default=12)
    p.set_defaults(fn=cmd_usage)

    args = ap.parse_args()
    args.fn(_creds(), args)


if __name__ == "__main__":
    main()