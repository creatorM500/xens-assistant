/**
 * Xens license edge function — Codex-style licensing + LLM proxy.
 *
 * Contract implemented by the client (llm/remote.py -> RemoteProvider):
 *   POST /api/activate   {"serial"}                                -> 200 {"token","tier","expires_at"}
 *   GET  /api/me         Authorization: Bearer <token>             -> 200 {"tier","expires_at"}
 *   POST /api/chat       Authorization: Bearer <token>
 *                        {"messages","tools","tier"}               -> 200 {"content","tool_calls","model"}
 *   POST /api/deactivate {"serial","device_id?"}                   -> 200 {"status":"ok",...}
 *
 * AI dispatch:
 *   free                -> Mistral directo (api.mistral.ai, mistral-small-2506)
 *   pro / premium       -> OpenRouter (openrouter.ai, mistralai/mistral-large-latest)
 *
 * Secrets (supabase secrets set --env XENS):
 *   XENS_TOKEN_SECRET     firma de los tokens de sesion (JWT HS256)
 *   XENS_MISTRAL_KEY      clave directa de Mistral (tier free)
 *   XENS_OPENROUTER_KEY   clave de OpenRouter (tiers pro/premium)
 *   XENS_FREE_CHAT_CAP    tope de chats/mes en tier free (default 300)
 * (SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY las inyecta la plataforma)
 */

const enc = new TextEncoder();

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_ROLE = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const TOKEN_SECRET = Deno.env.get("XENS_TOKEN_SECRET") ?? "xens-edge-token-secret";
const MISTRAL_KEY = Deno.env.get("XENS_MISTRAL_KEY") ?? "";
const OPENROUTER_KEY = Deno.env.get("XENS_OPENROUTER_KEY") ?? "";
const FREE_CHAT_CAP = parseInt(Deno.env.get("XENS_FREE_CHAT_CAP") ?? "300", 10) || 300;

const DEFAULT_MODELS = {
  free: "mistral-small-2506",
  pro: "mistralai/mistral-large",
  premium: "anthropic/claude-sonnet-5",
};

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "authorization, content-type",
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...CORS },
  });
}

// ---- JWT HS256 con WebCrypto (sin dependencias) ---------------------------
function b64u(b: Uint8Array): string {
  return btoa(String.fromCharCode(...b)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function b64uDecode(s: string): Uint8Array {
  let t = s.replace(/-/g, "+").replace(/_/g, "/");
  while (t.length % 4) t += "=";
  const bin = atob(t);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
async function hmacSign(data: string): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey(
    "raw", enc.encode(TOKEN_SECRET), { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  return new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(data)));
}
async function makeToken(payload: Record<string, unknown>): Promise<string> {
  const h = b64u(enc.encode(JSON.stringify({ alg: "HS256", typ: "JWT" })));
  const p = b64u(enc.encode(JSON.stringify(payload)));
  const sig = b64u(await hmacSign(`${h}.${p}`));
  return `${h}.${p}.${sig}`;
}
async function verifyToken(token: string): Promise<Record<string, unknown> | null> {
  try {
    const [h, p, s] = token.split(".");
    if (!h || !p || !s) return null;
    if (b64u(await hmacSign(`${h}.${p}`)) !== s) return null;
    const payload = JSON.parse(new TextDecoder().decode(b64uDecode(p)));
    if (typeof payload.exp === "number" && payload.exp * 1000 < Date.now()) return null;
    return payload;
  } catch {
    return null;
  }
}

// ---- Supabase helpers (service_role bypassa RLS) ---------------------------
function sbHeaders(): Record<string, string> {
  return { apikey: SERVICE_ROLE, authorization: `Bearer ${SERVICE_ROLE}`, "content-type": "application/json" };
}

async function rpc(name: string, args: Record<string, unknown>): Promise<{ status: number; data: any }> {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/rpc/${name}`, {
    method: "POST",
    headers: { ...sbHeaders(), prefer: "return=representation" },
    body: JSON.stringify(args),
  });
  return { status: r.status, data: await r.json().catch(() => null) };
}

async function fetchLicense(serial: string): Promise<any> {
  const r = await fetch(
    `${SUPABASE_URL}/rest/v1/licenses?select=id,tier,revoked,expires_at&key=eq.${encodeURIComponent(serial)}&limit=1`,
    { headers: sbHeaders() },
  );
  const rows = await r.json().catch(() => null);
  return Array.isArray(rows) ? (rows[0] ?? null) : null;
}

async function fetchUsage(licenseId: string, period: string): Promise<any> {
  const r = await fetch(
    `${SUPABASE_URL}/rest/v1/usage?select=chats&license_id=eq.${licenseId}&period=eq.${period}&limit=1`,
    { headers: sbHeaders() },
  );
  const rows = await r.json().catch(() => null);
  return Array.isArray(rows) ? (rows[0] ?? null) : null;
}

// ---- handlers --------------------------------------------------------------
async function handleActivate(req: Request, body: any): Promise<Response> {
  const serial = String(body?.serial ?? "").trim().toUpperCase();
  if (!serial) return json(400, { error: "serial required" });
  const device = await deviceFingerprint(req);
  const { status, data } = await rpc("activate_license", {
    p_key: serial,
    p_device_id: device,
    p_machine_id: device,
  });
  if (status !== 200 || !data || data.error) {
    return json(401, { error: data?.error ?? "Activation rejected" });
  }
  const tier = String(data.tier ?? "free").toLowerCase();
  const exp = Number(data.expires_at ?? 0);
  const token = await makeToken({
    sub: serial,
    tier,
    exp: exp || Math.floor(Date.now() / 1000) + 365 * 86400,
    iss: "xens",
    iat: Math.floor(Date.now() / 1000),
  });
  return json(200, { token, tier, expires_at: exp || undefined });
}

async function handleMe(auth: string): Promise<Response> {
  const payload = await requireAuth(auth);
  if (payload instanceof Response) return payload;
  return json(200, {
    tier: String(payload.tier ?? "free").toLowerCase(),
    expires_at: Number(payload.exp ?? 0),
    online: true,
  });
}

async function handleChat(req: Request, auth: string, body: any): Promise<Response> {
  const payload = await requireAuth(auth);
  if (payload instanceof Response) return payload;
  const serial = String(payload.sub ?? "");
  const tier = String(payload.tier ?? "free").toLowerCase();
  const messages = body?.messages;
  if (!Array.isArray(messages) || messages.length === 0) {
    return json(400, { error: "messages required" });
  }

  const lic = await fetchLicense(serial);
  if (!lic) return json(401, { error: "License not found" });
  if (lic.revoked) return json(401, { error: "License revoked by seller" });
  if (lic.expires_at && Date.parse(lic.expires_at) < Date.now()) {
    return json(401, { error: "License expired" });
  }

  const now = new Date();
  const period = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  if (tier === "free") {
    const usage = await fetchUsage(lic.id, period);
    const chats = Number(usage?.chats ?? 0);
    if (chats >= FREE_CHAT_CAP) {
      return json(402, { error: `Free tier limit reached (${FREE_CHAT_CAP} chats/month)` });
    }
  }

  const direct = tier === "free" || tier === "trial";
  let upstream: string;
  let apiKey: string;
  let model: string;
  if (direct) {
    upstream = "https://api.mistral.ai/v1/chat/completions";
    apiKey = MISTRAL_KEY;
    model = String(body?.model ?? DEFAULT_MODELS.free);
  } else {
    upstream = "https://openrouter.ai/api/v1/chat/completions";
    apiKey = OPENROUTER_KEY;
    model = String(body?.model ?? DEFAULT_MODELS.pro);
  }
  if (!apiKey) {
    return json(500, { error: "Server has no API key configured for this tier" });
  }

  const llmPayload: Record<string, unknown> = { model, messages, temperature: 0.3, max_tokens: 2000 };
  const tools = body?.tools;
  if (Array.isArray(tools) && tools.length > 0) llmPayload.tools = tools;

  let r: Response;
  try {
    r = await fetch(upstream, {
      method: "POST",
      headers: { authorization: `Bearer ${apiKey}`, "content-type": "application/json" },
      body: JSON.stringify(llmPayload),
    });
  } catch {
    return json(502, { error: "Upstream LLM unreachable" });
  }
  const up = await r.json().catch(() => null);
  if (r.status >= 400) {
    return json(502, { error: `Model error ${r.status}`, detail: String(up?.error?.message ?? "") });
  }

  const msg = up?.choices?.[0]?.message ?? {};
  await rpc("bump_usage", {
    p_license_id: lic.id,
    p_period: period,
    p_tokens_in: Number(up?.usage?.prompt_tokens ?? 0),
    p_tokens_out: Number(up?.usage?.completion_tokens ?? 0),
  });

  return json(200, {
    content: msg.content ?? "",
    tool_calls: msg.tool_calls ?? [],
    model: up?.model ?? model,
    usage: up?.usage ?? null,
    tier,
  });
}

async function handleDeactivate(body: any): Promise<Response> {
  const serial = String(body?.serial ?? "").trim().toUpperCase();
  if (!serial) return json(400, { error: "serial required" });
  const device = String(body?.device_id ?? "");
  const { status, data } = await rpc("deactivate_license", {
    p_key: serial,
    p_device_id: device,
    p_machine_id: device,
  });
  if (status !== 200 || !data || data.error) {
    return json(400, { error: data?.error ?? "Deactivation failed" });
  }
  return json(200, data);
}

// ---- shared -----------------------------------------------------------------
async function deviceFingerprint(req: Request): Promise<string> {
  const ip = req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "unknown";
  const ua = req.headers.get("user-agent") ?? "";
  const buf = await crypto.subtle.digest("SHA-256", enc.encode(`${ip}|${ua}`));
  return Array.from(new Uint8Array(buf))
    .slice(0, 8)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function requireAuth(auth: string): Promise<Record<string, unknown> | Response> {
  if (!auth?.toLowerCase().startsWith("bearer ")) {
    return json(401, { error: "Missing Bearer token" });
  }
  const payload = await verifyToken(auth.slice(7).trim());
  if (!payload) {
    return json(401, { error: "License token invalid, expired or revoked (401). Run /activate again." });
  }
  return payload;
}

// ---- router ------------------------------------------------------------------
Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
  const url = new URL(req.url);
  const path = url.pathname.split("/").filter(Boolean).pop() ?? "";
  try {
    if (req.method === "POST" && path === "activate") {
      return await handleActivate(req, await req.json().catch(() => ({})));
    }
    if (req.method === "GET" && path === "me") {
      return await handleMe(req.headers.get("authorization") ?? "");
    }
    if (req.method === "POST" && path === "chat") {
      return await handleChat(req, req.headers.get("authorization") ?? "", await req.json().catch(() => ({})));
    }
    if (req.method === "POST" && path === "deactivate") {
      return await handleDeactivate(await req.json().catch(() => ({})));
    }
    if (req.method === "GET" && path === "health") {
      return json(200, { ok: true });
    }
    return json(404, { error: "Not found" });
  } catch (e) {
    return json(500, { error: String(e) });
  }
});