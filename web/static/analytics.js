/* ============================================================
   analytics.js — Carga PostHog y expone window.XensAnalytics
   ------------------------------------------------------------
   Requiere que posthog-config.js se cargue ANTES que este archivo.
   Incluir este script en TODAS las páginas (landing, pricing,
   login, terms, privacy, index) para medir el recorrido completo.
   ============================================================ */

(() => {
  "use strict";

  const cfg = window.XENS_POSTHOG_CONFIG;
  const notConfigured =
    !cfg || !cfg.apiKey || cfg.apiKey === "TU_PROJECT_API_KEY";

  if (notConfigured) {
    console.warn("PostHog no está configurado todavía (posthog-config.js). Analítica desactivada.");
    window.XensAnalytics = {
      track() {},
      identify() {},
    };
    return;
  }

  /* ---- snippet oficial de PostHog (JS Web) ---- */
  !function (t, e) {
    var o, n, p, r;
    e.__SV || (window.posthog && window.posthog.__loaded) ||
      (window.posthog = e, e._i = [], e.init = function (i, s, a) {
        function g(t, e) {
          var o = e.split(".");
          2 == o.length && (t = t[o[0]], e = o[1]);
          t[e] = function () { t.push([e].concat(Array.prototype.slice.call(arguments, 0))); };
        }
        (p = t.createElement("script")).type = "text/javascript";
        p.crossOrigin = "anonymous"; p.async = !0;
        p.src = s.api_host.replace(".i.posthog.com", "-assets.i.posthog.com") + "/static/array.js";
        (r = t.getElementsByTagName("script")[0]).parentNode.insertBefore(p, r);
        var u = e;
        for (void 0 !== a ? u = e[a] = [] : a = "posthog", u.people = u.people || [],
          u.toString = function (t) {
            var e = "posthog";
            return "posthog" !== a && (e += "." + a), t || (e += " (stub)"), e;
          },
          u.people.toString = function () { return u.toString(1) + ".people (stub)"; },
          o = "init capture register register_once register_for_session unregister unregister_for_session getFeatureFlag getFeatureFlagPayload isFeatureEnabled reloadFeatureFlags updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures on onFeatureFlags onSessionId getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey identify setPersonProperties group resetGroups setPersonPropertiesForFlags resetPersonPropertiesForFlags setGroupPropertiesForFlags resetGroupPropertiesForFlags reset get_distinct_id getGroups get_session_id get_session_replay_url alias set_config startSessionRecording stopSessionRecording sessionRecordingStarted captureException loadToolbar get_property getSessionProperty createPersonProfile opt_in_capturing opt_out_capturing has_opted_in_capturing has_opted_out_capturing clear_opt_in_out_capturing debug".split(" "),
          n = 0; n < o.length; n++) g(u, o[n]);
        e._i.push([i, s, a]);
      }, e.__SV = 1);
  }(document, window.posthog || []);

  posthog.init(cfg.apiKey, {
    api_host: cfg.apiHost,
    defaults: "2026-01-30",
  });

  window.XensAnalytics = {
    /** Evento con propiedades opcionales, ej: track('message_sent', {plan:'free'}) */
    track(eventName, properties) {
      try {
        posthog.capture(eventName, properties || {});
      } catch (err) {
        console.error("Error enviando evento a PostHog:", err);
      }
    },

    /** Asocia el usuario autenticado (llamar después del login) */
    identify(user) {
      if (!user) return;
      try {
        posthog.identify(user.uid, {
          email: user.email,
          name: user.displayName,
        });
      } catch (err) {
        console.error("Error identificando usuario en PostHog:", err);
      }
    },
  };
})();
