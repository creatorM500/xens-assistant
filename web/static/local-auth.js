/* ============================================================
   local-auth.js — Capa de "usuario" local de XENS
   ------------------------------------------------------------
   Sustituye a Firebase Auth en la versión local del cliente:
   el usuario es la MÁQUINA, y su identidad/plan vienen de la
   licencia del motor (endpoint /api/profile).

   Expone la misma API que esperan session.js y app.js:
     window.XensAuth.onChange(callback)  -> cb(user)
     window.XensAuth.logout()
     window.XensAuth.refresh()

   user = { uid, displayName, email, license: {...} }
   ============================================================ */

(() => {
  "use strict";

  const PROFILE_URL = "http://127.0.0.1:18000/api/profile";
  const listeners = [];
  let user = null;

  function makeUser(profile) {
    return {
      uid: "local-" + (profile.serial || "trial"),
      displayName: profile.name || "Usuario local",
      email: profile.email || null,
      license: profile || {},
    };
  }

  function notify() {
    listeners.forEach((cb) => {
      try {
        cb(user);
      } catch (err) {
        console.error("Error en listener de XensAuth:", err);
      }
    });
  }

  async function refresh() {
    try {
      const r = await fetch(PROFILE_URL, { cache: "no-store" });
      if (!r.ok) return;
      const profile = await r.json();
      user = makeUser(profile);
      notify();
      return user;
    } catch (err) {
      // El motor local no responde: mantenemos el usuario optimista.
      return user;
    }
  }

  window.XensAuth = {
    onChange(cb) {
      listeners.push(cb);
      if (user) cb(user);
    },
    async refresh() {
      return refresh();
    },
    /* Modo local: no hay cuenta Firebase, nunca hay token. */
    async getToken() {
      return null;
    },
    logout() {
      window.location.reload();
    },
    /* ---- Modo local: sin Firebase, los formularios de login/registro
       guardan el correo en localStorage y entran directo. El usuario
       real de la máquina es la licencia del motor (/api/profile). ---- */
    async loginWithEmail(email, password) {
      return localLogin(email);
    },
    async registerWithEmail(email, password, name) {
      return localLogin(email, name);
    },
    async loginWithGoogle() {
      return localLogin(null, "Usuario (Google)");
    },
    async loginWithGithub() {
      return localLogin(null, "Usuario (GitHub)");
    },
    async resetPassword(email) {
      return { ok: true };
    },
  };

  function localLogin(email, name) {
    try {
      if (email) localStorage.setItem("xens.local.email", email);
    } catch (err) {
      /* localStorage puede no estar disponible; no es crítico */
    }
    const base = email ? email.split("@")[0] : "Usuario";
    user = Object.assign({}, user, {
      email: email || user.email,
      displayName: name || base || "Usuario local",
    });
    notify();
    return user;
  }

  // Usuario optimista inmediato: evita que session.js redirija al
  // login antes de que el motor responda el perfil.
  user = {
    uid: "local-trial",
    displayName: "XENS",
    email: null,
    license: {},
  };
  refresh();
  setInterval(refresh, 30000);
})();
