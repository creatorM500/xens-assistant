/**
 * Ainslup paypal-webhook — Registra suscripciones/planes de cuenta.
 *
 * Recibe eventos de PayPal (Subscriptions API v1) y:
 *   1. hace upsert en la tabla `subscriptions` (uid -> plan, auditoría), y
 *   2. escribe el tier en `app_metadata` del usuario vía Auth Admin API,
 *      para que su JWT lo traiga y el edge/motor le den ese plan sin serial.
 *
 * Eventos soportados:
 *   BILLING.SUBSCRIPTION.ACTIVATED/APPROVED -> activa el plan
 *   PAYMENT.SALE.COMPLETED                  -> confirma el cobro
 *   BILLING.SUBSCRIPTION.CANCELLED/SUSPENDED -> baja a free
 *
 * Secrets (supabase secrets set):
 *   XENS_PAYPAL_CLIENT_ID / XENS_PAYPAL_CLIENT_SECRET (modo sandbox por defecto)
 *   XENS_PAYPAL_MODE           "live" para producción
 *   XENS_PAYPAL_PLAN_LITE_ID / XENS_PAYPAL_PLAN_PRO_ID / XENS_PAYPAL_PLAN_PREMIUM_ID
 *   XENS_PAYPAL_WEBHOOK_ID     (verificación de firma)
 *
 * La verificación del webhook se hace con la API de PayPal
 * /v1/notifications/verify-webhook-signature.
 */

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_ROLE = Deno.env.get("SUPABASE_SECRET_KEY") ?? Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const CLIENT_ID = Deno.env.get("XENS_PAYPAL_CLIENT_ID") ?? "";
const CLIENT_SECRET = Deno.env.get("XENS_PAYPAL_CLIENT_SECRET") ?? "";
const MODE = Deno.env.get("XENS_PAYPAL_MODE") === "live" ? "live" : "sandbox";
const API = MODE === "live" ? "https://api-m.paypal.com" : "https://api-m.sandbox.paypal.com";
const PLAN_LITE = Deno.env.get("XENS_PAYPAL_PLAN_LITE_ID") ?? "";
const PLAN_PRO = Deno.env.get("XENS_PAYPAL_PLAN_PRO_ID") ?? "";
const PLAN_PREMIUM = Deno.env.get("XENS_PAYPAL_PLAN_PREMIUM_ID") ?? "";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

async function paypalToken(): Promise<string | null> {
  const r = await fetch(`${API}/v1/oauth2/token`, {
    method: "POST",
    headers: {
      authorization: `Basic ${btoa(`${CLIENT_ID}:${CLIENT_SECRET}`)}`,
      "content-type": "application/x-www-form-urlencoded",
    },
    body: "grant_type=client_credentials",
  });
  if (!r.ok) return null;
  const data = await r.json().catch(() => ({}));
  return data.access_token ?? null;
}

/** Verifica la firma del webhook contra la API de PayPal. */
async function verifyWebhook(req: Request, body: string): Promise<boolean> {
  if (!CLIENT_ID || !CLIENT_SECRET) return false;
  const token = await paypalToken();
  if (!token) return false;
  const url = new URL(req.url);
  const webhookId = Deno.env.get("XENS_PAYPAL_WEBHOOK_ID") ?? "";
  if (!webhookId) return true; // sin webhook id configurado: confiar (solo para staging)
  const r = await fetch(`${API}/v1/notifications/verify-webhook-signature`, {
    method: "POST",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: JSON.stringify({
      auth_algo: req.headers.get("paypal-auth-algo"),
      cert_url: req.headers.get("paypal-cert-url"),
      transmission_id: req.headers.get("paypal-transmission-id"),
      transmission_sig: req.headers.get("paypal-transmission-sig"),
      transmission_time: req.headers.get("paypal-transmission-time"),
      webhook_id: webhookId,
      webhook_event: JSON.parse(body),
    }),
  });
  const data = await r.json().catch(() => ({}));
  return data.verification_status === "SUCCESS";
}

async function sbFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${SUPABASE_URL}${path}`, {
    ...init,
    headers: {
      apikey: SERVICE_ROLE,
      authorization: `Bearer ${SERVICE_ROLE}`,
      "content-type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
}

async function upsertSubscription(uid: string, plan: string, status: string, periodEnd: string | null): Promise<boolean> {
  if (!uid) return false;
  const r = await sbFetch("/rest/v1/subscriptions", {
    method: "POST",
    headers: { prefer: "resolution=merge-duplicates" },
    body: JSON.stringify({
      uid,
      plan,
      status,
      current_period_end: periodEnd,
      updated_at: new Date().toISOString(),
    }),
  });
  if (r.status >= 400) {
    console.error("upsert subscriptions falló:", r.status, await r.text().catch(() => ""));
    return false;
  }
  return true;
}

function planFromId(planId: string): string {
  if (planId && planId === PLAN_PREMIUM) return "premium";
  if (planId && planId === PLAN_PRO) return "pro";
  if (planId && planId === PLAN_LITE) return "lite";
  return "free";
}

/** Escribe el tier en app_metadata del usuario (el JWT lo trae después). */
async function setUserTier(uid: string, tier: string): Promise<boolean> {
  if (!uid) return false;
  try {
    const g = await fetch(`${SUPABASE_URL}/auth/v1/admin/users/${uid}`, {
      headers: { apikey: SERVICE_ROLE, authorization: `Bearer ${SERVICE_ROLE}` },
    });
    if (g.status !== 200) {
      console.error("admin get user falló:", g.status);
      return false;
    }
    const user = await g.json().catch(() => ({}));
    const meta = { ...(user?.app_metadata ?? {}), tier };
    const p = await fetch(`${SUPABASE_URL}/auth/v1/admin/users/${uid}`, {
      method: "PUT",
      headers: { apikey: SERVICE_ROLE, authorization: `Bearer ${SERVICE_ROLE}`, "content-type": "application/json" },
      body: JSON.stringify({ app_metadata: meta }),
    });
    if (p.status >= 400) {
      console.error("admin set tier falló:", p.status, await p.text().catch(() => ""));
      return false;
    }
    return true;
  } catch (e) {
    console.error("setUserTier falló:", e);
    return false;
  }
}

function handleEvent(event: any): Promise<boolean> {
  const type: string = String(event?.event_type ?? "");
  const res: any = event?.resource ?? {};

  // Billing agreement v1: custom = "uid" (o "uid:plan")
  const agreementId = res.billing_agreement_id ?? "";
  const customRaw = String(res.custom_id ?? res.custom ?? "");

  // Subscripciones v1 (custom_id = "uid:plan" puesto al crearla)
  if (type.startsWith("BILLING.SUBSCRIPTION.")) {
    const uid = String(customRaw ?? "").split(":")[0];
    const hinted = String(customRaw ?? "").includes(":") ? String(customRaw).split(":")[1] : "";
    const plan = planFromId(String(res.plan_id ?? "")) !== "free"
      ? planFromId(String(res.plan_id ?? ""))
      : (["lite", "pro", "premium"].includes(hinted) ? hinted : "free");
    const periodEnd = res.billing_info?.next_billing_time ?? null;
    if (type === "BILLING.SUBSCRIPTION.ACTIVATED" || type === "BILLING.SUBSCRIPTION.APPROVED") {
      const ok = await upsertSubscription(uid, plan, "active", periodEnd);
      await setUserTier(uid, plan);
      return ok;
    }
    if (type === "BILLING.SUBSCRIPTION.CANCELLED" || type === "BILLING.SUBSCRIPTION.SUSPENDED") {
      const ok = await upsertSubscription(uid, plan || "free", "cancelled", null);
      await setUserTier(uid, "free");
      return ok;
    }
    return Promise.resolve(true); // otros eventos: ignorar
  }

  if (type === "PAYMENT.SALE.COMPLETED") {
    const uid = String(customRaw ?? "").split(":")[0];
    const hinted = String(customRaw ?? "").includes(":") ? String(customRaw).split(":")[1] : "";
    const plan = ["lite", "pro", "premium"].includes(hinted) ? hinted : "free";
    const ok = await upsertSubscription(uid, plan, "active", null);
    await setUserTier(uid, plan);
    return ok;
  }

  return Promise.resolve(true); // eventos no relevantes: 200 para no reintentar
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return json(405, { error: "Method not allowed" });
  const body = await req.text();
  const ok = await verifyWebhook(req, body);
  if (!ok) return json(401, { error: "Invalid webhook signature" });
  try {
    const event = JSON.parse(body);
    await handleEvent(event);
    return json(200, { received: true });
  } catch (e) {
    console.error("handleEvent falló:", e);
    return json(500, { error: String(e) });
  }
});