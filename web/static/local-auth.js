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
    logout() {
      window.location.reload();
    },
  };

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
