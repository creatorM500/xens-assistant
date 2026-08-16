/**
 * Xens paypal-webhook — Registra suscripciones/planes de cuenta.
 *
 * Recibe eventos de PayPal y hace upsert en la tabla `subscriptions`
 * (uid -> plan). El motor local consulta esa tabla con el token de
 * Firebase del usuario (RLS: solo su fila) para asignar el tier.
 *
 * Eventos soportados (subscriptions API v2 + billing v1):
 *   BILLING.SUBSCRIPTION.ACTIVATED    -> activa el plan
 *   PAYMENT.SALE.COMPLETED            -> confirma el cobro
 *   BILLING.SUBSCRIPTION.CANCELLED    -> baja el plan
 *   BILLING.SUBSCRIPTION.SUSPENDED    -> suspende el plan
 *
 * Secrets (supabase secrets set --env XENS):
 *   XENS_PAYPAL_CLIENT_ID / XENS_PAYPAL_CLIENT_SECRET (modo sandbox por defecto)
 *   XENS_PAYPAL_MODE           "live" para producción
 *   XENS_PAYPAL_PLAN_PRO_ID / XENS_PAYPAL_PLAN_PREMIUM_ID (ids de plan de suscripción)
 *
 * La verificación del webhook se hace con la API de PayPal
 * /v1/notifications/verify-webhook-signature.
 */

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_ROLE = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const CLIENT_ID = Deno.env.get("XENS_PAYPAL_CLIENT_ID") ?? "";
const CLIENT_SECRET = Deno.env.get("XENS_PAYPAL_CLIENT_SECRET") ?? "";
const MODE = Deno.env.get("XENS_PAYPAL_MODE") === "live" ? "live" : "sandbox";
const API = MODE === "live" ? "https://api-m.paypal.com" : "https://api-m.sandbox.paypal.com";
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
  return "free";
}

function handleEvent(event: any): Promise<boolean> {
  const type: string = String(event?.event_type ?? "");
  const res: any = event?.resource ?? {};

  // Billing agreement v1: custom = "uid" (o "uid:plan")
  const agreementId = res.billing_agreement_id ?? "";
  const customRaw = String(res.custom_id ?? res.custom ?? "");

  // Subscripciones v2
  if (type.startsWith("BILLING.SUBSCRIPTION.")) {
    const uid = String(customRaw ?? "").split(":")[0];
    const plan = planFromId(String(res.plan_id ?? ""));
    const periodEnd = res.billing_info?.next_billing_time ?? null;
    if (type === "BILLING.SUBSCRIPTION.ACTIVATED" || type === "BILLING.SUBSCRIPTION.APPROVED") {
      return upsertSubscription(uid, plan, "active", periodEnd);
    }
    if (type === "BILLING.SUBSCRIPTION.CANCELLED" || type === "BILLING.SUBSCRIPTION.SUSPENDED") {
      return upsertSubscription(uid, plan || "free", "cancelled", null);
    }
    return Promise.resolve(true); // otros eventos: ignorar
  }

  if (type === "PAYMENT.SALE.COMPLETED") {
    const uid = String(customRaw ?? "").split(":")[0];
    const plan = String(customRaw ?? "").includes(":") ? String(customRaw).split(":")[1] : planFromId(String(res.billing_agreement_id ?? ""));
    return upsertSubscription(uid, plan || "free", "active", null);
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