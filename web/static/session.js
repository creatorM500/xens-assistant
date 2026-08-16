/* ============================================================
   session.js — Protege index.html (la app de chat)
   Requiere que auth.js (window.XensAuth) ya esté cargado.
   Se ejecuta ANTES que app.js.
   ============================================================ */

(() => {
  "use strict";

  if (!window.XensAuth) {
    console.error(
      "XensAuth no está definido: revisa que firebase-config.js tenga tus claves reales " +
      "y que los <script> de Firebase estén antes de session.js."
    );
    return;
  }

  const userNameEl = document.getElementById("userName");
  const userAvatarEl = document.getElementById("userAvatar");
  const logoutBtn = document.getElementById("logoutBtn");
  const settingsNameEl = document.getElementById("settingsName");
  const settingsEmailEl = document.getElementById("settingsEmail");

  window.XensAuth.onChange((user) => {
    if (!user) {
      window.location.href = "login.html";
      return;
    }

    const label = user.displayName || (user.email ? user.email.split("@")[0] : "Usuario");
    if (userNameEl) userNameEl.textContent = label;
    if (userAvatarEl) {
      userAvatarEl.textContent = label.charAt(0).toUpperCase();
      if (user.photoURL) {
        userAvatarEl.style.backgroundImage = `url(${user.photoURL})`;
        userAvatarEl.textContent = "";
      }
    }
    // El correo ya no se muestra en el sidebar; vive en el modal de Configuración
    if (settingsNameEl) settingsNameEl.textContent = label;
    if (settingsEmailEl) settingsEmailEl.textContent = user.email || "—";

    if (window.XensAnalytics) window.XensAnalytics.identify(user);
  });

  if (logoutBtn) {
    logoutBtn.addEventListener("click", () => window.XensAuth.logout());
  }
})();
