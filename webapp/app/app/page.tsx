"use client";
import { FormEvent, useEffect, useState } from "react";
import { supabase } from "../../lib/supabase";

const EDGE = "https://tzlbgoydgptlhspzdhfu.supabase.co/functions/v1/license";
type Message = { role: "user" | "assistant"; content: string };

export default function AppPage() {
  const [email, setEmail] = useState(""); const [tier, setTier] = useState("free");
  const [messages, setMessages] = useState<Message[]>([]); const [text, setText] = useState("");
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  useEffect(() => { supabase?.auth.getUser().then(async ({ data }) => { if (!data.user) { window.location.href = "/login"; return; } setEmail(data.user.email || ""); const token = (await supabase!.auth.getSession()).data.session?.access_token; if (token) { const r = await fetch(`${EDGE}/me`, { headers: { Authorization: `Bearer ${token}` } }); if (r.ok) { const d = await r.json(); setTier(d.tier || "free"); } } }); }, []);
  async function send(e: FormEvent) { e.preventDefault(); const value = text.trim(); if (!value || busy || !supabase) return; setText(""); setError(""); const next = [...messages, { role: "user" as const, content: value }]; setMessages(next); setBusy(true); try { const token = (await supabase!.auth.getSession()).data.session?.access_token; if (!token) throw new Error("Sesión expirada. Inicia sesión de nuevo."); const r = await fetch(`${EDGE}/chat`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ messages: next, xens_model: "auto", stream: false }) }); const data = await r.json(); if (!r.ok) throw new Error(data.error || "No se pudo generar la respuesta."); setMessages([...next, { role: "assistant", content: data.content || "No se recibió contenido." }]); } catch (err) { setError(err instanceof Error ? err.message : "Error de conexión"); } finally { setBusy(false); } }
  async function logout() { await supabase?.auth.signOut(); window.location.href = "/"; }
  return <main className="dashboard"><nav className="nav"><b>AINSLUP</b><div><span>{email}</span><span className="eyebrow">{tier.toUpperCase()}</span><button className="button ghost" onClick={logout}>Cerrar sesión</button></div></nav><section className="chat-card"><div className="chat-head"><h1>¿En qué trabajamos?</h1><p>Cuenta compartida con AINSLUP Desktop · modelo automático</p></div><div className="chat-messages">{messages.length===0&&<div className="empty-chat"><b>Tu asistente web está listo.</b><span>Prueba: “Resume este texto” o “Ayúdame a planificar mi semana”.</span></div>}{messages.map((m,i)=><div key={i} className={`chat-bubble ${m.role}`}>{m.content}</div>)}{busy&&<div className="chat-bubble assistant">Pensando…</div>}</div>{error&&<p className="chat-error">{error}</p>}<form className="chat-form" onSubmit={send}><textarea value={text} onChange={e=>setText(e.target.value)} placeholder="Escribe una tarea…" rows={2}/><button className="button" disabled={busy}>{busy?"Procesando…":"Enviar"}</button></form></section></main>;
}
