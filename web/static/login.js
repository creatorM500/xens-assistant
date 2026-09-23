/* ============================================================
   login.js — Interacción de la página login.html
   Requiere que auth.js (window.XensAuth) ya esté cargado.
   ============================================================ */

(function () {
  "use strict";

  function init() {
    const tabLogin = document.getElementById("tabLogin");
    const tabRegister = document.getElementById("tabRegister");
    const formLogin = document.getElementById("formLogin");
    const formRegister = document.getElementById("formRegister");
    const errorBox = document.getElementById("authError");

  /* ---- alternar entre pestañas login / registro ---- */
  function showTab(tab) {
    const isLogin = tab === "login";
    tabLogin.classList.toggle("active", isLogin);
    tabRegister.classList.toggle("active", !isLogin);
    formLogin.style.display = isLogin ? "flex" : "none";
    formRegister.style.display = isLogin ? "none" : "flex";
    clearError();
  }

  tabLogin.addEventListener("click", () => showTab("login"));
  tabRegister.addEventListener("click", () => showTab("register"));

  // Si venimos de landing/pricing con ?mode=register, abrir esa pestaña
  const params = new URLSearchParams(window.location.search);
  if (params.get("mode") === "register") showTab("register");

  /* ---- manejo de errores legibles ---- */
  const ERROR_MESSAGES = {
    "auth/invalid-email": "El correo no es válido.",
    "auth/user-not-found": "No existe una cuenta con ese correo.",
    "auth/wrong-password": "Contraseña incorrecta.",
    "auth/email-already-in-use": "Ya existe una cuenta con ese correo.",
    "auth/weak-password": "La contraseña debe tener al menos 6 caracteres.",
    "auth/popup-closed-by-user": "Se cerró la ventana antes de completar el inicio de sesión.",
    "auth/network-request-failed": "Error de red. Revisa tu conexión.",
  };

  function showError(err) {
    const code = err && err.code;
    const msg = err && err.message ? String(err.message) : "";
    errorBox.style.color = "var(--red)";
    if (msg && !ERROR_MESSAGES[code]) errorBox.textContent = msg;
    else errorBox.textContent = ERROR_MESSAGES[code] || msg || "Ocurrió un error. Inténtalo de nuevo.";
    console.error("Auth error:", err);
  }

  function clearError() {
    errorBox.textContent = "";
  }

  function requireAuth() {
    if (!window.XensAuth) {
      showError({ code: "auth/network-request-failed" });
      console.error(
        "XensAuth no está definido: revisa que firebase-config.js tenga tus claves reales."
      );
      return false;
    }
    return true;
  }

  /* ---- formulario de login ---- */
  formLogin.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!requireAuth()) return;
    clearError();

    const email = document.getElementById("loginEmail").value.trim();
    const password = document.getElementById("loginPassword").value;

    try {
      await window.XensAuth.loginWithEmail(email, password);
      if (window.XensAnalytics) window.XensAnalytics.track("login", { method: "email" });
      window.location.href = "index.html";
    } catch (err) {
      showError(err);
    }
  });

  /* ---- formulario de registro ---- */
  formRegister.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!requireAuth()) return;
    clearError();

    const name = document.getElementById("registerName").value.trim();
    const email = document.getElementById("registerEmail").value.trim();
    const password = document.getElementById("registerPassword").value;

    try {
      await window.XensAuth.registerWithEmail(email, password, name);
      if (window.XensAnalytics) window.XensAnalytics.track("sign_up", { method: "email" });
      window.location.href = "index.html";
    } catch (err) {
      showError(err);
    }
  });

  /* ---- OAuth ---- */
  document.getElementById("googleBtn").addEventListener("click", async () => {
    if (!requireAuth()) return;
    clearError();
    try {
      await window.XensAuth.loginWithGoogle();
      if (window.XensAnalytics) window.XensAnalytics.track("login", { method: "google" });
      window.location.href = "index.html";
    } catch (err) {
      showError(err);
    }
  });

  document.getElementById("githubBtn").addEventListener("click", async () => {
    if (!requireAuth()) return;
    clearError();
    try {
      await window.XensAuth.loginWithGithub();
      if (window.XensAnalytics) window.XensAnalytics.track("login", { method: "github" });
      window.location.href = "index.html";
    } catch (err) {
      showError(err);
    }
  });

  /* ---- recuperar contraseña ---- */
  document.getElementById("forgotPassword").addEventListener("click", async (e) => {
    e.preventDefault();
    if (!requireAuth()) return;

    const email = document.getElementById("loginEmail").value.trim();
    if (!email) {
      showError({ code: "auth/invalid-email" });
      return;
    }
    try {
      await window.XensAuth.resetPassword(email);
      errorBox.style.color = "var(--green)";
      errorBox.textContent = "Te enviamos un correo para restablecer tu contraseña.";
    } catch (err) {
      showError(err);
    }
  });

  /* ---- si ya hay sesión real (Supabase), saltar al chat; en modo local no redirigir ---- */
  if (window.XensAuth) {
    window.XensAuth.onChange((user) => {
      if (!user) return;
      const isLocal = String(user.uid||"").startsWith("local-");
      const hasSupabase = !!window.SUPABASE_CONFIG;
      if (!isLocal || !hasSupabase) {
        // solo auto-redirect si es usuario real o si no hay Supabase (modo local ya está en chat)
        // pero en login.html con Supabase configurado, no redirigir local-trial para permitir login real
        if (!isLocal) window.location.href = "index.html";
      }
    });
  }
  }

  /* auth.js (modo Firebase) se carga de forma asíncrona: esperar a que
     window.XensAuth exista antes de conectar la página. */
  function boot() {
    if (window.XensAuth) {
      init();
    } else {
      setTimeout(boot, 100);
    }
  }
  boot();
})();
