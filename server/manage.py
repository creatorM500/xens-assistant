"""server/manage.py — admin CLI for the reference license server.

Usage:
    python -m server.manage gen --tier pro --days 365 --name Maria [--count 5]
    python -m server.manage list
    python -m server.manage revoke XENS-XXXX-...
    python -m server.manage nuke        (wipe all serials/users)
"""
import argparse, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import store  # noqa: E402


def cmd_gen(args):
    codes = store.new_serial(args.tier, args.days, args.name, args.count)
    for c in codes:
        print(c)
    print(f"\n# {len(codes)} serial(s) created. Buyer activates with: /activate <serial>")


def cmd_list(_args):
    serials = store.load_serials()
    if not serials:
        print("(no serials)")
        return
    for code, e in sorted(serials.items()):
        status = "ACTIVE " if e.get("active") else "REVOKED"
        used = f"used by {e['used_by']} @ {e['used_at']}" if e.get("used_by") else "unused"
        print(f"  {code}  {status} {e['tier']:<8} {e['days']}d  {e.get('name',''):<12} {used}")


def cmd_revoke(args):
    if store.revoke_serial(args.serial):
        print(f"Revoked: {args.serial.upper()} — its token now returns 401.")
    else:
        print(f"Not found: {args.serial}")


def cmd_nuke(_args):
    store.save_serials({})
    store.save_users({})
    print("All serials and users wiped.")


def main():
    ap = argparse.ArgumentParser(prog="manage", description="Admin CLI for Xens reference license server")
    sub = ap.add_subparsers(dest="cmd")

    g = sub.add_parser("gen", help="Create serial key(s)")
    g.add_argument("--tier", default="PRO", help="free | pro | premium (default PRO)")
    g.add_argument("--days", type=int, default=365, help="0 = lifetime token window (server TTL default)")
    g.add_argument("--name", default="")
    g.add_argument("--count", type=int, default=1)
    g.set_defaults(fn=cmd_gen)

    sub.add_parser("list", help="List serials").set_defaults(fn=cmd_list)
    sub.add_parser("nuke", help="Wipe all data").set_defaults(fn=cmd_nuke)

    r = sub.add_parser("revoke", help="Revoke a serial (kills its token immediately)")
    r.add_argument("serial")
    r.set_defaults(fn=cmd_revoke)

    args = ap.parse_args()
    if not getattr(args, "fn", None):
        ap.print_help()
        sys.exit(1)
    args.fn(args)


if __name__ == "__main__":
    main()