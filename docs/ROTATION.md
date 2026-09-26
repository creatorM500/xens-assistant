# Rotación de secrets (las keys quedaron expuestas en un chat)

## Ya rotado por API

- [x] DB password de **staging** (Management API, este doc no la contiene).

## Pendiente: 3 acciones en dashboard (owner)

1. **service_role de staging** (se filtró en un ZIP público, ya borrado):
   Dashboard del proyecto `ainslup-staging` → Project Settings → API →
   *Legacy API keys* → **Regenerate** (service_role). Avisame y actualizo
   `staging_keys.json` releyendo la API.
2. **service_role de prod** (`tzlbgoydgptlhspzdhfu`): mismos 3 clics.
   Avisame y actualizo `~/.ainslup/supabase.json` + verifico.
3. **Mistral key** (se pegó en el chat): console.mistral.ai → API Keys →
   Revoke la vieja + Create nueva. Pásame la nueva y yo hago
   `supabase secrets set` + redeploy + prueba live.

## No requiere rotación

- `anon` (pública por diseño, va en el front).
- OpenRouter (solo se vio truncada).
- `XENS_TOKEN_SECRET` (nunca expuesta; vive solo en Supabase).
