"""setup_shares.py — One-time setup for the "Compartir" feature (like Gemini's share link).

Creates the public bucket `xens-shares`, allows anonymous uploads (anon insert policy)
and prints the anon key to embed in the frontend.

Run:  python scripts/setup_shares.py
"""
import json, sys
from pathlib import Path

import httpx

API = "https://api.supabase.com/v1"
PROJECT_REF = "tzlbgoydgptlhspzdhfu"
BUCKET = "xens-shares"


def creds() -> dict:
    data = json.loads((Path.home() / ".xens" / "supabase.json").read_text(encoding="utf-8"))
    if not data.get("management_pat"):
        sys.exit("supabase.json needs management_pat")
    return data


def main():
    c = creds()
    h = {"Authorization": f"Bearer {c['management_pat']}", "Content-Type": "application/json"}

    # 1. bucket public (idempotente) — los buckets viven en storage.buckets
    sql = f"""
    insert into storage.buckets (id, name, public, file_size_limit)
    values ('{BUCKET}', '{BUCKET}', true, 5242880)
    on conflict (id) do nothing
    returning id;
    """
    r = httpx.post(f"{API}/projects/{PROJECT_REF}/database/query",
                   headers=h, json={"query": sql}, timeout=60)
    if r.status_code >= 400:
        print(f"bucket: {r.status_code} {r.text[:300]}")
    else:
        print(f"bucket {BUCKET} OK (public)")

    # 2. policy anon insert (permite a cualquier cliente subir archivos con la anon key)
    sql = f"""
    create policy "anon share insert" on storage.objects
    for insert to anon with check (bucket_id = '{BUCKET}');
    """
    r = httpx.post(f"{API}/projects/{PROJECT_REF}/database/query",
                   headers=h, json={"query": sql}, timeout=60)
    if r.status_code >= 400 and "already exists" not in r.text:
        print(f"policy: {r.status_code} {r.text[:300]}")
    else:
        print("policy anon insert OK")

    # 3. anon key (publishable, segura para el frontend)
    r = httpx.get(f"{API}/projects/{PROJECT_REF}/api-keys", headers=h, timeout=30)
    r.raise_for_status()
    anon = next((k["api_key"] for k in r.json() if k.get("name") == "anon"), None)
    if not anon:
        sys.exit("anon key not found")
    print(f"\nANON_KEY={anon}")
    print(f"PUBLIC_URL_PREFIX=https://{PROJECT_REF}.supabase.co/storage/v1/object/public/{BUCKET}/")


if __name__ == "__main__":
    main()
