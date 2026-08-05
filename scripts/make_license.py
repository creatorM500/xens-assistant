#!/usr/bin/env python3
"""make_license.py — generate serial keys for Xens Assistant (seller/admin side).

Usage:
    python make_license.py --tier pro --days 365                     # unbound key (binds on activation)
    python make_license.py --tier premium --days 120 --name Maria    # named key
    python make_license.py --tier free --days 0 --count 5            # 5 lifetime keys
    python make_license.py --hwid f3a29c1b --tier pro --days 30      # machine-bound key

Notes:
    - The default secret is the shipped placeholder: it matches keys generated
      without --secret. Publish your own secret in config.json ->
      "license": {"secret": "..."} for production so issued keys differ.
    - DAYS 0 = lifetime.
    - HWID 00000000 = unbound (binds to the first machine that activates).
"""
import argparse, os, sys
from pathlib import Path

p = argparse.ArgumentParser(description="Generate Xens Assistant serial keys")
p.add_argument("--tier", default="PRO", help="free | pro | premium (default PRO)")
p.add_argument("--days", type=int, default=365, help="Validity in days; 0 = lifetime")
p.add_argument("--hwid", default="", help="8-hex machine id to bind (default 00000000 = any machine)")
p.add_argument("--name", default="", help="Customer name embedded in the key")
p.add_argument("--count", type=int, default=1, help="How many keys to generate")
p.add_argument("--secret", default="", help="Secret signing key (must match Xens config)")
p.add_argument("--show-hwid", action="store_true", help="Print this machine's 8-hex HWID")
args = p.parse_args()

if args.secret:
    os.environ["XENS_LICENSE_SECRET"] = args.secret

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.license import issue_serial, get_hwid


def _main():
    if args.show_hwid:
        print(f"This machine HWID: {get_hwid()}")
        return

    keys = []
    for _ in range(max(1, args.count)):
        keys.append(issue_serial(tier=args.tier, days=args.days, hwid=args.hwid or "00000000", name=args.name))
    print("\n".join(keys))
    print(f"\n# {len(keys)} key(s) issued. In the Xens terminal, the buyer types: /activate <key>")


if __name__ == "__main__":
    _main()