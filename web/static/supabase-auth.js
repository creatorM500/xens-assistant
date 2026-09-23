/* ============================================================
   supabase-auth.js — Capa Supabase Auth (reemplaza auth.js)
   Se carga SOLO cuando supabase-config.js existe.
   Usa @supabase/supabase-js via CDN.
   Expone window.XensAuth igual que local-auth.js/auth.js
   ============================================================ */
(() => {
  "use strict";
  if (typeof window.SUPABASE_CONFIG === "undefined" || !window.SUPABASE_CONFIG || !window.SUPABASE_CONFIG.url) return;

  const cfg = window.SUPABASE_CONFIG;
  if (!window.supabase || !window.supabase.createClient) {
    console.warn("supabase-js no cargado");
    return;
  }
  const client = window.supabase.createClient(cfg.url, cfg.anonKey);

  function makeUser(sbUser) {
    if (!sbUser) return null;
    const meta = sbUser.user_metadata || {};
    return {
      uid: sbUser.id,
      displayName: meta.name || meta.full_name || sbUser.email || "Usuario",
      email: sbUser.email || null,
      photoURL: meta.avatar_url || null,
    };
  }

  window.XensAuth = {
    onChange(cb) {
      client.auth.onAuthStateChange((_event, session) => {
        const u = session && session.user ? makeUser(session.user) : null;
        cb(u);
      });
      // initial
      client.auth.getSession().then(({ data }) => {
        const u = data.session && data.session.user ? makeUser(data.session.user) : null;
        cb(u);
      });
    },
    async refresh() {
      const { data } = await client.auth.getSession();
      return data.session && data.session.user ? makeUser(data.session.user) : null;
    },
    async getToken() {
      const { data } = await client.auth.getSession();
      return data.session ? data.session.access_token : null;
    },
    async loginWithEmail(email, password) {
      const { error } = await client.auth.signInWithPassword({ email, password });
      if (error) throw new Error(error.message);
    },
    async registerWithEmail(email, password, name) {
      const { error } = await client.auth.signUp({ email, password, options: { data: { name } } });
      if (error) throw new Error(error.message);
    },
    async loginWithGoogle() {
      const { error } = await client.auth.signInWithOAuth({ provider: "google", options: { redirectTo: window.location.origin } });
      if (error) throw new Error(error.message);
    },
    async loginWithGithub() {
      const { error } = await client.auth.signInWithOAuth({ provider: "github", options: { redirectTo: window.location.origin } });
      if (error) throw new Error(error.message);
    },
    async resetPassword(email) {
      const { error } = await client.auth.resetPasswordForEmail(email);
      if (error) throw new Error(error.message);
    },
    async logout() {
      await client.auth.signOut();
    },
  };
})();
