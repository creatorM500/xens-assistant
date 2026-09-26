# Staging — proyecto separado

**Prod:** `tzlbgoydgptlhspzdhfu` (us-east-2) · feed `xens-updates`
**Staging:** `mwqkfeyttegxhfvcsjcm` (us-east-2) · feed `xens-updates-staging`

Regla: a prod solo llega lo probado en staging. Nunca se publica a prod
directo desde una rama de trabajo.

## Probar contra staging (sin recompilar)

Backend (Python):
```cmd
set AINSLUP_ENV=staging
python -X utf8 cli_entry.py --headless
```
Esto cambia: edge de licencias, verificación de Auth y feed de updates
a staging. Las keys anon de staging pueden ir en `~/.ainslup/config.json`:
```json
{"supabase": {"staging_url": "https://mwqkfeyttegxhfvcsjcm.supabase.co",
              "staging_anon_key": "<anon de staging>"}}
```

Web UI: abrir con `?staging=1` (o `localStorage ainslup.env=staging`).
Usa `web/static/supabase-config.staging.js` (solo clave pública anon).

## Publicar feed de staging

```cmd
python scripts/build_update.py --version YYYYMMDD-staging.N --bucket xens-updates-staging
```
Requiere `staging_keys.json` local (service_role de staging, NO commitear).
El ZIP **nunca** incluye: `staging_keys.json`, `staging_dbpass.txt`,
`staging_*.py`, `supabase/.temp`, `server/data` (ver `EXCLUDE_*` en
`scripts/build_update.py`).

## Crear el proyecto desde cero (si se pierde)

```cmd
# 1. crear proyecto free vía dashboard o Management API
# 2. vincular y pushear migraciones (incluye 20260801000000_base_licenses.sql):
supabase link --project-ref <ref-staging>
supabase db push
supabase link --project-ref tzlbgoydgptlhspzdhfu   # volver a prod
# 3. secrets: XENS_TOKEN_SECRET (nuevo), XENS_MISTRAL_KEY, XENS_FREE_CHAT_CAP
supabase secrets set --project-ref <ref> XENS_TOKEN_SECRET=... XENS_MISTRAL_KEY=... XENS_FREE_CHAT_CAP=300
# 4. funciones:
supabase functions deploy license --project-ref <ref>
supabase functions deploy paypal-webhook --project-ref <ref>
# 5. bucket: lo crea solo build_update.py (--bucket ...)
```

## Rotación de emergencia (staging)

- DB password: `PATCH /v1/projects/<ref>/database/password` (Management API).
- service_role legacy: dashboard del proyecto staging → Project Settings →
  API → Legacy API keys → Regenerate; luego actualizar `staging_keys.json`
  (releer vía `GET /v1/projects/<ref>/api-keys`).
