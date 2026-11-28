# Edge Function `license`

Proxy de licencias + LLM estilo Codex para Xens. El cliente (llm/remote.py)
nunca ve las API keys de IA: solo recibe un token y el servidor llama al modelo.

## Endpoints (contrato de `llm/remote.py`)

| Endpoint  | Auth            | Body                          | Respuesta                          |
|-----------|-----------------|-------------------------------|------------------------------------|
| POST `/api/activate` | -     | `{"serial": "XENS-..."}`      | `{"token","tier","expires_at"}`    |
| GET `/api/me`       | Bearer token    | -                             | `{"tier","expires_at"}`            |
| POST `/api/chat`    | Bearer token    | `{"messages","tools"}` | `{"content","tool_calls","model"}` |
| POST `/api/deactivate` | Bearer license token | - | `{"status":"ok",...}` |
| POST `/api/credits-check` | Bearer account token | `{"need":1}` | authoritative server balance |
| POST `/api/credits-spend` | disabled | - | `410`; chats are billed server-side |

## Dispatch de modelos

- **free** → Mistral directo (`api.mistral.ai`, `mistral-small-2506`) con tope de
  `XENS_FREE_CHAT_CAP` chats/mes por licencia (tabla `usage`).
- **pro / premium** → OpenRouter (`mistralai/mistral-large-latest`), modelo
  sobreescribible por request con `{"model": "..."}`.

Credit checks and chat billing derive the account UID and active plan from
Supabase Auth and the `subscriptions` table. Never pass an account UID or usage
from the client as authority. The Edge reserves quota atomically before chat,
then tops it up using upstream provider usage where available.

## Deploy

```bash
# desde C:\xens assistant\ainslup_assistant

# 1. secrets (pedirlos en el panel o via CLI)
supabase secrets set XENS_TOKEN_SECRET=<random-largo> \
  XENS_MISTRAL_KEY=<key-mistral> \
  XENS_OPENROUTER_KEY=<sk-or-...> \
  XENS_POLLI_KEY=<key-pollinations> \
  XENS_FREE_CHAT_CAP=300 \
  --project-ref tzlbgoydgptlhspzdhfu

# 2. desplegar la funcion
supabase functions deploy license --project-ref tzlbgoydgptlhspzdhfu

# 3. configurar el cliente
#    en Xens: /server https://tzlbgoydgptlhspzdhfu.functions.supabase.co/license
#    luego:   /activate XENS-<serial>
```

La URL resultante queda `https://tzlbgoydgptlhspzdhfu.functions.supabase.co/license`.
`SUPABASE_URL` y `SUPABASE_SERVICE_ROLE_KEY` las inyecta la plataforma.

## Beta gratuita y pagos

- `XENS_BILLING_ENABLED` debe permanecer sin configurar o en cualquier valor
  distinto de `true` durante la beta gratuita. En ese estado, `POST /checkout`
  responde `403` y no crea una suscripción nueva en PayPal.
- No lo cambies a `true` hasta que la persona adulta responsable haya aprobado
  las condiciones, precios y pruebas del flujo de pago.
- Este bloqueo no cancela acuerdos recurrentes creados directamente en PayPal.
  La persona titular de la cuenta debe comprobarlos allí.
- El acceso gratuito todavía puede generar costes para las cuentas de IA y
  alojamiento del operador. Configura límites y alertas de gasto por separado.

## Migraciones SQL aplicadas

`../migrations/20260804_0*.sql`: tier CHECK ampliado, `activate_license` endurecida
(`SET search_path=''`, UTF-8), `deactivate_license`, índice machine_id,
tabla `usage` + `bump_usage`.
