/* ============================================================
   XENS ASSISTANT — app.js
   Lógica de chat + integración WebSocket con el motor local (Xens.exe)

   Protocolo del backend (ws://127.0.0.1:18000/ws):
     Envío  -> { type: "message", text: "...", uid: "<firebase_uid>",
                 attachments: [{ name, type, size, data(base64) }] }
     Chunk  <- { type: "content", content: "..." }
     Fin    <- { type: "done" }
     Limpiar -> { type: "clear" }
     Perfil (REST) -> GET http://127.0.0.1:18000/api/profile

   NOTA sobre modelos de IA: el frontend NUNCA elige el modelo.
   El backend (llm/tiered.py) identifica el plan del usuario por su
   "uid" y enruta automáticamente a mistral-small/large o
   claude-sonnet-3.5, con fallback si el proveedor cae. Por eso el
   payload de arriba incluye "uid" en cada mensaje.

   NOTA DE SEGURIDAD (para producción): hoy el "uid" viaja tal cual
   lo manda el navegador, sin verificar. Antes de lanzar de verdad,
   el backend debe validar un ID Token de Firebase en vez de confiar
   en este campo, para que nadie pueda enviar el uid de otra persona.
   ============================================================ */

(() => {
  "use strict";

  /* ----------------------------------------------------------
     0. CONFIGURACIÓN — aquí se centraliza todo lo que cambiará
        cuando migremos de localhost a producción en la nube.
  ---------------------------------------------------------- */
  const CONFIG = {
    // En producción esto se reemplaza por la URL del servidor
    // cloud/serverless (ej: wss://api.xens.app/ws), idealmente
    // inyectada por variable de entorno / build step, no hardcodeada.
    WS_URL: "ws://127.0.0.1:18000/ws",
    PROFILE_URL: "http://127.0.0.1:18000/api/profile",

    // Xens Credits por plan (MENSUALES; se renuevan el 1º). El backend
    // (/api/profile) es la fuente autoritativa; esto solo es el fallback
    // si el perfil no llega. La prueba gratuita local (trial) usa además
    // un contador total único (300), informado por el estado de licencia.
    PLAN_LIMITS: {
      free: 10000,
      pro: 50000,
      premium: 250000,
    },
    PLAN_META: {
      free: { label: "Plan Gratuito", badge: "FREE" },
      pro: { label: "Plan Pro", badge: "PRO" },
      premium: { label: "Plan Premium", badge: "PREMIUM" },
    },

    // Reintentos de conexión si el .exe local no está corriendo
    RECONNECT_DELAY_MS: 3000,
    MAX_RECONNECT_ATTEMPTS: 5,

    // Límite de tamaño por archivo adjunto (5 MB) para no saturar
    // el WebSocket mientras no exista subida real a almacenamiento.
    MAX_ATTACHMENT_BYTES: 5 * 1024 * 1024,
  };

  /* ----------------------------------------------------------
     1. REFERENCIAS AL DOM
  ---------------------------------------------------------- */
  const el = {
    chatArea: document.getElementById("chatArea"),
    welcomeScreen: document.getElementById("welcomeScreen"),
    welcomeGreeting: document.getElementById("welcomeGreeting"),
    messages: document.getElementById("messages"),
    suggestions: document.getElementById("suggestions"),

    composerInput: document.getElementById("composerInput"),
    composerInner: document.querySelector(".composer-inner"),
    sendBtn: document.getElementById("sendBtn"),
    disclaimer: document.getElementById("disclaimer"),

    newChatBtn: document.getElementById("newChatBtn"),
    recentList: document.getElementById("recentList"),
    trashList: document.getElementById("trashList"),
    trashSection: document.getElementById("trashSection"),
    recentMenu: document.getElementById("recentMenu"),
    pinMenuLabel: document.getElementById("pinMenuLabel"),
    searchInput: document.getElementById("searchInput"),

    topbarTitle: document.getElementById("topbarTitle"),
    statusDot: document.getElementById("statusDot"),
    statusText: document.getElementById("statusText"),

    userPlanTag: document.getElementById("userPlanTag"),
    planName: document.getElementById("planName"),
    planBadge: document.getElementById("planBadge"),
    upgradeBtn: document.getElementById("upgradeBtn"),

    // Modal de configuración
    settingsBtn: document.getElementById("settingsBtn"),
    settingsOverlay: document.getElementById("settingsOverlay"),
    closeSettingsBtn: document.getElementById("closeSettingsBtn"),
    settingsPlanBadge: document.getElementById("settingsPlanBadge"),
    settingsUsageCount: document.getElementById("settingsUsageCount"),
    settingsUsageFill: document.getElementById("settingsUsageFill"),

    // Licencia (activación de serial)
    licenseStatusText: document.getElementById("licenseStatusText"),
    licenseKey: document.getElementById("licenseKey"),
    activateLicenseBtn: document.getElementById("activateLicenseBtn"),
    licenseMsg: document.getElementById("licenseMsg"),

    // Modal de licencia agotada / expirada
    licenseLockOverlay: document.getElementById("licenseLockOverlay"),
    closeLicenseLockBtn: document.getElementById("closeLicenseLockBtn"),
    lockTitle: document.getElementById("lockTitle"),
    lockText: document.getElementById("lockText"),
    lockLicenseKey: document.getElementById("lockLicenseKey"),
    lockActivateBtn: document.getElementById("lockActivateBtn"),
    lockMsg: document.getElementById("lockMsg"),

    // Modal de herramientas usadas
    toolsOverlay: document.getElementById("toolsOverlay"),
    closeToolsBtn: document.getElementById("closeToolsBtn"),
    toolsLog: document.getElementById("toolsLog"),

    // Adjuntar archivos
    attachBtn: document.getElementById("attachBtn"),
    fileInput: document.getElementById("fileInput"),
    attachmentsRow: document.getElementById("attachmentsRow"),

    // Dictado por voz
    micBtn: document.getElementById("micBtn"),

    // Wizard de bienvenida / tutorial / novedades / dependencias
    wizardOverlay: document.getElementById("wizardOverlay"),
    wizardBar: document.getElementById("wizardBar"),
    wizardStepLabel: document.getElementById("wizardStepLabel"),
    wizardTitle: document.getElementById("wizardTitle"),
    wizardVersion: document.getElementById("wizardVersion"),
    wizardChangelog: document.getElementById("wizardChangelog"),
    wizardDeps: document.getElementById("wizardDeps"),
    wizardInstallBtn: document.getElementById("wizardInstallBtn"),
    wizardSkipBtn: document.getElementById("wizardSkipBtn"),
    wizardDepsMsg: document.getElementById("wizardDepsMsg"),
    wizardPrevBtn: document.getElementById("wizardPrevBtn"),
    wizardNextBtn: document.getElementById("wizardNextBtn"),
    settingsDepsStatus: document.getElementById("settingsDepsStatus"),
    settingsDepsBtn: document.getElementById("settingsDepsBtn"),
  };

  /* ----------------------------------------------------------
     2. ESTADO DE LA APLICACIÓN
  ---------------------------------------------------------- */
  const state = {
    socket: null,
    reconnectAttempts: 0,
    isConnected: false,

    // contador de generación: se incrementa al resetear/limpiar para
    // invalidar chunks/tool_calls que lleguen tarde de respuestas previas
    generation: 0,
    activeGeneration: 0,

    messageCount: 0,
    conversationStarted: false,

    // límite de mensajes actual (viene de /api/profile; fallback en CONFIG)
    messageLimit: null,

    // Xens Credits (modo cuenta; null = modo local con contador de trial)
    credits: null,
    creditsLimit: null,
    creditsResetSec: null,

    // todas las conversaciones cargadas (para filtrar con el buscador)
    allConversations: [],
    allTrash: [],

    // conversación seleccionada en el menú de tres puntos
    menuConvId: null,
    menuConv: null,

    // usuario autenticado (Firebase), su plan, y conversación activa (Supabase)
    user: null,
    plan: "free",
    account: null,
    currentConversationId: null,

    // archivos seleccionados pendientes de enviar con el próximo mensaje
    pendingAttachments: [],

    // dictado por voz
    recognition: null,
    isRecording: false,

    // burbuja de IA que se está llenando actualmente con chunks
    currentAssistantBubble: null,

    // respuestas concurrentes (canal conversacional separado de la
    // ejecución): burbujas por requestId para no pisarse entre sí
    activeBubbles: {},          // requestId -> {bubble, text}
    activeReqIds: new Set(),
    currentAssistantText: "",

    // último texto enviado por el usuario (para "rehacer respuesta")
    lastUserText: "",

    // herramientas usadas en esta conversación (para el modal de tools)
    toolLog: [],

    // wizard de bienvenida / dependencias
    wizardStep: 1,
    wizardDeps: null,       // último GET /api/deps
    wizardSelected: new Set(),
    wizardInstalling: false,
  };

  /* ----------------------------------------------------------
     2b. LICENCIA (activación de serial y estado)
  ---------------------------------------------------------- */
  const LICENSE_STATUS_TEXT = {
    licensed: "Licenciado",
    trial: "Prueba gratuita",
    locked: "Prueba agotada",
    expired: "Expirada",
    unlicensed: "Sin licencia",
    unlocked: "Desbloqueada",
  };

  function renderLicenseStatus(license) {
    if (!el.licenseStatusText || !license) return;
    const status = license.status || "unlicensed";
    let text = LICENSE_STATUS_TEXT[status] || status;
    if (license.tier) text += " · " + String(license.tier).toUpperCase();
    if (status === "trial") text += ` (${license.trial_used}/${license.trial_limit})`;
    else if (license.days_left != null) text += ` · ${license.days_left}d restantes`;
    el.licenseStatusText.textContent = text;
  }

  function setLicenseMsg(text, isError) {
    if (!el.licenseMsg) return;
    el.licenseMsg.textContent = text;
    el.licenseMsg.style.color = isError ? "var(--red, #ef4444)" : "var(--green, #22c55e)";
  }

  function activateLicense() {
    const key = el.licenseKey.value.trim();
    if (!key) {
      setLicenseMsg("Escribe un serial, ej. XENS-PRO-365-...", true);
      return;
    }
    setLicenseMsg("Activando...", false);
    sendToServer({ type: "activate", key });
  }

  if (el.activateLicenseBtn) {
    el.activateLicenseBtn.addEventListener("click", activateLicense);
  }
  if (el.licenseKey) {
    el.licenseKey.addEventListener("keydown", (e) => {
      if (e.key === "Enter") activateLicense();
    });
  }

  /* ----------------------------------------------------------
     2c. MODAL DE LICENCIA AGOTADA / EXPIRADA
  ---------------------------------------------------------- */
  function showLicenseLock(license) {
    if (!el.licenseLockOverlay || !license) return;
    const status = license.status || "";

    if (status === "locked") {
      el.lockTitle.textContent = "Prueba gratuita agotada";
      el.lockText.textContent =
        `Usaste tus ${license.trial_used || 0}/${license.trial_limit || 0} chats de prueba. ` +
        "Activa un serial para seguir usando XENS.";
    } else if (status === "expired") {
      el.lockTitle.textContent = "Licencia expirada";
      el.lockText.textContent =
        "Tu licencia venció. Activa un serial nuevo para seguir usando XENS.";
    } else {
      return;
    }
    el.licenseLockOverlay.classList.add("open");
  }

  function closeLicenseLock() {
    el.licenseLockOverlay.classList.remove("open");
    if (el.lockMsg) el.lockMsg.textContent = "";
  }

  function setLockMsg(text, isError) {
    if (!el.lockMsg) return;
    el.lockMsg.textContent = text;
    el.lockMsg.style.color = isError ? "var(--red, #ef4444)" : "var(--green, #22c55e)";
  }

  function activateFromLock() {
    const key = el.lockLicenseKey.value.trim();
    if (!key) {
      setLockMsg("Escribe un serial, ej. XENS-PRO-365-...", true);
      return;
    }
    setLockMsg("Activando...", false);
    sendToServer({ type: "activate", key });
  }

  if (el.closeLicenseLockBtn) el.closeLicenseLockBtn.addEventListener("click", closeLicenseLock);
  if (el.lockActivateBtn) el.lockActivateBtn.addEventListener("click", activateFromLock);
  if (el.lockLicenseKey) {
    el.lockLicenseKey.addEventListener("keydown", (e) => {
      if (e.key === "Enter") activateFromLock();
    });
  }

  /* ----------------------------------------------------------
     2d. MARKDOWN (renderizado de respuestas, sin librerías externas)
  ---------------------------------------------------------- */
  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderMarkdown(md) {
    const placeholders = [];
    let html = escapeHtml(md);

    // 1. bloques de código cercados -> placeholder (protegidos del resto)
    html = html.replace(/```(\w*)\n?([\s\S]*?)(?:\n?```|$)/g, (m, lang, code) => {
      const idx = placeholders.length;
      placeholders.push(
        `<pre><code class="lang-${lang}">${code.replace(/\n$/, "")}</code></pre>`
      );
      return `\u0000${idx}\u0000`;
    });

    // 2. tablas (líneas "| a | b |" con separador "|--|")
    html = html.replace(/^(?:(^\|.*\|[^\n]*\n?)+)(?=\n|$)/gm, (block) => {
      const lines = block.trim().split("\n");
      const cells = (l) =>
        l
          .replace(/^\|/, "")
          .replace(/\|$/, "")
          .split("|")
          .map((c) => c.trim() || "&nbsp;");
      const isSeparator = (l) => /^\|[\s:|-]+\|$/.test(l) && /-{2,}/.test(l);
      if (lines.length < 2 || !isSeparator(lines[1])) return block;

      const head = cells(lines[0]).map((c) => `<th>${c}</th>`).join("");
      const rows = lines.slice(2).map(
        (l) => `<tr>${cells(l).map((c) => `<td>${c}</td>`).join("")}</tr>`
      );
      return `<table><thead><tr>${head}</tr></thead><tbody>${rows.join("")}</tbody></table>`;
    });

    // 3. bloques por líneas: encabezados, citas y listas
    const lines = html.split("\n");
    const blocks = [];
    let list = null; // { tag: "ul"|"ol", items: [] }

    function flushList() {
      if (list && list.items.length) {
        blocks.push(`<${list.tag}>${list.items.map((i) => `<li>${i}</li>`).join("")}</${list.tag}>`);
        list = null;
      }
    }

    lines.forEach((line) => {
      const header = line.match(/^(#{1,3})\s+(.+)$/);
      const quote = line.match(/^&gt;\s?(.*)$/);
      const ulItem = line.match(/^[-*]\s+(.+)$/);
      const olItem = line.match(/^\d+\.\s+(.+)$/);

      if (header) {
        flushList();
        blocks.push(`<h${header[1].length}>${header[2]}</h${header[1].length}>`);
      } else if (quote) {
        flushList();
        blocks.push(`<blockquote>${quote[1] || "&nbsp;"}</blockquote>`);
      } else if (ulItem || olItem) {
        const tag = ulItem ? "ul" : "ol";
        const content = ulItem ? ulItem[1] : olItem[1];
        if (!list || list.tag !== tag) {
          flushList();
          list = { tag, items: [] };
        }
        list.items.push(content);
      } else {
        flushList();
        blocks.push(line);
      }
    });
    flushList();

    // 4. inline: links, código, negritas, itálicas
    html = blocks.join("\n");
    html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, (m, t, u) =>
      `<a href="${u}" target="_blank" rel="noopener">${t}</a>`
    );
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");

    // 5. párrafos y saltos de línea
    html = html.replace(/\n{3,}/g, "\n\n");
    html = html.split(/\n{2,}/)
      .map((chunk) => {
        const trimmed = chunk.trim();
        if (!trimmed) return "";
        if (/^\u0000\d+\u0000$/.test(trimmed)) return trimmed;
        if (/^<(pre|table|blockquote|h[1-4]|ul|ol)[\s>]/.test(trimmed)) return trimmed;
        return `<p>${trimmed.replace(/\n/g, "<br>")}</p>`;
      })
      .join("");

    // 6. restaurar bloques de código
    placeholders.forEach((blockHtml, idx) => {
      html = html.split(`\u0000${idx}\u0000`).join(blockHtml);
    });

    return html;
  }

  /* ----------------------------------------------------------
     3. UTILIDADES DE UI
  ---------------------------------------------------------- */
  const ACTION_ICONS = {
    copy: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>',
    edit: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>',
    refresh: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>',
    tool: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
    check: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
  };

  function copyText(text) {
    if (!text) return;
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).catch(() => {});
    } else {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
      } catch (err) {}
      ta.remove();
    }
  }

  function makeActionBtn(icon, title, onClick, label) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "msg-action-btn";
    btn.title = title;
    btn.innerHTML = icon + (label ? `<span>${label}</span>` : "");
    btn.addEventListener("click", () => {
      onClick(btn);
    });
    return btn;
  }

  function flashCopied(btn) {
    const was = btn.innerHTML;
    btn.innerHTML = ACTION_ICONS.check + (btn.querySelector("span") ? "<span>✓</span>" : "");
    btn.classList.add("copied");
    setTimeout(() => {
      btn.innerHTML = was;
      btn.classList.remove("copied");
    }, 1200);
  }

  function scrollToBottom() {
    el.chatArea.scrollTop = el.chatArea.scrollHeight;
  }

  function showChatView() {
    if (state.conversationStarted) return;
    state.conversationStarted = true;
    el.welcomeScreen.style.display = "none";
    el.messages.classList.add("visible");
    el.chatArea.classList.add("has-messages");
    el.topbarTitle.textContent = "Conversación";
  }

  function resetToWelcome() {
    state.generation += 1;
    state.conversationStarted = false;
    el.messages.innerHTML = "";
    el.welcomeScreen.style.display = "";
    el.messages.classList.remove("visible");
    el.chatArea.classList.remove("has-messages");
    el.topbarTitle.textContent = "Conversación nueva";
    state.currentAssistantBubble = null;
    state.currentAssistantText = "";
    state.activeBubbles = {};
    state.activeReqIds = new Set();
    state.toolLog = [];
  }

  function attachMessageActions(bubble, opts) {
    const actions = document.createElement("div");
    actions.className = "msg-actions";

    if (opts.role === "user") {
      actions.appendChild(makeActionBtn(ACTION_ICONS.copy, "Copiar mensaje", (btn) => {
        const textEl = bubble.querySelector(".msg-text");
        copyText(textEl ? textEl.textContent : "");
        flashCopied(btn);
      }));
      actions.appendChild(makeActionBtn(ACTION_ICONS.edit, "Editar y reenviar", () => {
        const textEl = bubble.querySelector(".msg-text");
        if (textEl) startEditUserBubble(bubble, textEl, actions);
      }));
    } else {
      actions.appendChild(makeActionBtn(ACTION_ICONS.copy, "Copiar respuesta", (btn) => {
        const content = bubble.querySelector(".msg-content");
        copyText(content ? content.textContent : "");
        flashCopied(btn);
      }));
      if (opts.withRegenerate) {
        actions.appendChild(makeActionBtn(ACTION_ICONS.refresh, "Rehacer respuesta", () => {
          regenerateLastResponse();
        }, "Rehacer"));
        actions.appendChild(makeActionBtn(ACTION_ICONS.tool, "Ver herramientas usadas", () => {
          openToolsModal();
        }, "Tools"));
      }
    }

    bubble.appendChild(actions);
    return actions;
  }

  function buildUserBubble(text) {
    const bubble = document.createElement("div");
    bubble.className = "msg user";

    const box = document.createElement("div");
    box.className = "user-bubble";

    const textEl = document.createElement("div");
    textEl.className = "msg-text";
    textEl.textContent = text;
    box.appendChild(textEl);

    bubble.appendChild(box);
    attachMessageActions(bubble, { role: "user" });
    return bubble;
  }

  function addUserBubble(text) {
    const bubble = buildUserBubble(text);
    el.messages.appendChild(bubble);
    scrollToBottom();
    return bubble;
  }

  function startEditUserBubble(bubble, textEl, actions) {
    actions.style.display = "none";
    textEl.style.display = "none";

    const wrap = document.createElement("div");
    wrap.className = "msg-edit-wrap";

    const ta = document.createElement("textarea");
    ta.className = "msg-edit-input";
    ta.rows = 3;
    ta.value = textEl.textContent;

    const btnRow = document.createElement("div");
    btnRow.className = "msg-edit-btns";

    const cancelBtn = makeActionBtn("", "Cancelar", () => {
      wrap.remove();
      textEl.style.display = "";
      actions.style.display = "";
    }, "Cancelar");
    cancelBtn.classList.add("ghost");

    const sendBtn = makeActionBtn("", "Enviar", () => {
      const newText = ta.value.trim();
      if (!newText) return;
      wrap.remove();
      textEl.textContent = newText;
      textEl.style.display = "";
      actions.style.display = "";
      resendEditedUserMessage(bubble, newText);
    }, "Enviar");
    sendBtn.classList.add("primary");

    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendBtn.click();
      }
    });

    btnRow.appendChild(cancelBtn);
    btnRow.appendChild(sendBtn);
    wrap.appendChild(ta);
    wrap.appendChild(btnRow);
    const box = bubble.querySelector(".user-bubble");
    (box || bubble).appendChild(wrap);
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
  }

  function resendEditedUserMessage(bubble, newText) {
    // elimina la respuesta anterior (si es de IA) que sigue a este mensaje
    let isLastUser = true;
    if (bubble) {
      const next = bubble.nextElementSibling;
      if (next && next.classList.contains("assistant")) next.remove();
      const users = el.messages.querySelectorAll(".msg.user");
      isLastUser = users.length > 0 && users[users.length - 1] === bubble;
    }

    // Persistencia: la respuesta rehecha REEMPLAZA a la anterior para que
    // no queden duplicados al volver a entrar a la conversación.
    if (isLastUser && window.XensDB && state.currentConversationId) {
      window.XensDB.deleteLastMessage(state.currentConversationId, "assistant");
      window.XensDB.updateLastMessage(state.currentConversationId, "user", newText);
    }

    state.lastUserText = newText;
    const requestId = Date.now() + "-" + Math.random().toString(36).slice(2, 8);
    state.activeReqIds.add(requestId);
    startAssistantBubble(requestId);
    const ok = sendToServer({
      type: "message",
      text: newText,
      requestId,
      uid: state.user ? state.user.uid : null,
      attachments: [],
      replaceLast: isLastUser,
      replaceUser: isLastUser,
    });
    if (!ok) {
      finishAssistantBubble(requestId);
      state.activeReqIds.delete(requestId);
    }
    if (window.XensAnalytics) window.XensAnalytics.track("message_edited");
  }

  function addSystemNote(text) {
    const note = document.createElement("div");
    note.className = "msg system";
    note.textContent = text;
    el.messages.appendChild(note);
    scrollToBottom();
  }

  function bubbleEntry(reqId) {
    if (!reqId) return null; // ruta clásica de burbuja única
    let entry = state.activeBubbles[reqId];
    if (!entry) {
      if (!state.activeReqIds.has(reqId)) return null; // respuesta de una conversación ya cerrada
      const bubble = document.createElement("div");
      bubble.className = "msg assistant typing";
      el.messages.appendChild(bubble);
      entry = { bubble, text: "" };
      state.activeBubbles[reqId] = entry;
      scrollToBottom();
    }
    return entry;
  }

  function startAssistantBubble(reqId) {
    if (reqId) {
      bubbleEntry(reqId);
      return;
    }
    state.activeGeneration = state.generation;
    const bubble = document.createElement("div");
    bubble.className = "msg assistant typing";
    el.messages.appendChild(bubble);
    state.currentAssistantBubble = bubble;
    state.currentAssistantText = "";
    scrollToBottom();
    return bubble;
  }

  function appendAssistantChunk(chunk, reqId) {
    if (reqId) {
      const entry = bubbleEntry(reqId);
      if (!entry) return;
      entry.text += chunk;
      let content = entry.bubble.querySelector(".msg-content");
      if (!content) {
        content = document.createElement("div");
        content.className = "msg-content";
        entry.bubble.appendChild(content);
      }
      content.innerHTML = renderMarkdown(entry.text);
      scrollToBottom();
      return;
    }
    if (state.activeGeneration !== state.generation) return; // respuesta vieja tras reset
    if (!state.currentAssistantBubble) startAssistantBubble();
    state.currentAssistantText += chunk;
    let content = state.currentAssistantBubble.querySelector(".msg-content");
    if (!content) {
      content = document.createElement("div");
      content.className = "msg-content";
      state.currentAssistantBubble.appendChild(content);
    }
    content.innerHTML = renderMarkdown(state.currentAssistantText);
    scrollToBottom();
  }

  function showToolCall(name, args, reqId) {
    const target = reqId ? (bubbleEntry(reqId) || {}).bubble : null;
    if (reqId && !target) return;
    if (state.activeGeneration !== state.generation && !reqId) return;
    if (!target) {
      if (!state.currentAssistantBubble) startAssistantBubble();
      target = state.currentAssistantBubble;
    }
    let chips = target.querySelector(".tool-chips");
    if (!chips) {
      chips = document.createElement("div");
      chips.className = "tool-chips";
      target.appendChild(chips);
    }
    const chip = document.createElement("span");
    chip.className = "tool-chip running";
    chip.dataset.tool = name;

    const summary = [];
    if (args && typeof args === "object") {
      for (const [k, v] of Object.entries(args)) {
        if (v === undefined || v === null || v === "") continue;
        let s = String(v);
        if (s.length > 40) s = s.slice(0, 40) + "…";
        summary.push(`${k}=${s}`);
      }
    }
    const summaryText = summary.join(" · ");

    chip.innerHTML =
      `<span class="tool-chip-ico">${ACTION_ICONS.tool}</span>` +
      `<span class="tool-chip-name">${escapeHtml(name)}</span>` +
      (summaryText ? `<span class="tool-chip-args">${escapeHtml(summaryText)}</span>` : "") +
      `<span class="tool-chip-status">…</span>`;
    chips.appendChild(chip);
    scrollToBottom();

    state.toolLog.push({
      name,
      args: args || {},
      summary: summaryText,
      success: null,
      time: Date.now(),
    });
    if (state.toolLog.length > 200) state.toolLog.shift();
    if (el.toolsOverlay && el.toolsOverlay.classList.contains("open")) renderToolsLog();
  }

  function finishToolCall(name, success, reqId) {
    const target = reqId ? (bubbleEntry(reqId) || {}).bubble : state.currentAssistantBubble;
    if (!target) return;
    const chips = target.querySelector(".tool-chips");
    if (!chips) return;
    const matches = Array.from(chips.querySelectorAll(`.tool-chip[data-tool="${CSS.escape(String(name))}"]`));
    const chip = matches.length ? matches[matches.length - 1] : chips.lastElementChild;
    if (chip) {
      chip.classList.remove("running");
      chip.classList.add(success ? "ok" : "err");
      const status = chip.querySelector(".tool-chip-status");
      if (status) status.textContent = success ? "✓" : "✗";
      // el chip aparece y se quita solo tras 2 segundos
      setTimeout(() => {
        if (!chip.isConnected) return;
        chip.classList.add("fading");
        setTimeout(() => chip.remove(), 300);
      }, 2000);
    }

    const entry = state.toolLog.filter((e) => e.name === name && e.success === null).pop();
    if (entry) entry.success = !!success;
    if (el.toolsOverlay && el.toolsOverlay.classList.contains("open")) renderToolsLog();
  }

  function finishAssistantBubble(reqId) {
    if (reqId) {
      const entry = state.activeBubbles[reqId];
      if (!entry) return;
      const bubble = entry.bubble;
      bubble.classList.remove("typing");
      const text = entry.text;
      const hasToolCards = bubble.querySelector(".tool-call");
      if (!text && !hasToolCards) {
        bubble.remove();
      } else if (text) {
        attachMessageActions(bubble, { role: "assistant", withRegenerate: true });
      }
      if (window.XensDB && state.currentConversationId && text) {
        window.XensDB.saveMessage(state.currentConversationId, "assistant", text);
      }
      delete state.activeBubbles[reqId];
      state.activeReqIds.delete(reqId);
      return;
    }
    if (state.activeGeneration !== state.generation) {
      // respuesta vieja que llegó tarde: descartar sin persistir
      state.currentAssistantBubble = null;
      state.currentAssistantText = "";
      return;
    }
    if (state.currentAssistantBubble) {
      const bubble = state.currentAssistantBubble;
      bubble.classList.remove("typing");

      const text = state.currentAssistantText;
      const hasToolCards = bubble.querySelector(".tool-call");
      if (!text && !hasToolCards) {
        // respuesta vacía (error sin contenido): no dejar burbuja fantasma
        bubble.remove();
      } else if (text) {
        attachMessageActions(bubble, { role: "assistant", withRegenerate: true });
      }
    }

    // Persistir la respuesta de la IA en Supabase (si está configurado)
    if (window.XensDB && state.currentConversationId && state.currentAssistantText) {
      window.XensDB.saveMessage(
        state.currentConversationId,
        "assistant",
        state.currentAssistantText
      );
    }

    state.currentAssistantBubble = null;
    state.currentAssistantText = "";
  }

  function regenerateLastResponse() {
    if (state.currentAssistantBubble) return; // ya hay una respuesta generándose
    const text = state.lastUserText;
    if (!text) return;
    const assistants = el.messages.querySelectorAll(".msg.assistant");
    const last = assistants.length ? assistants[assistants.length - 1] : null;
    if (last) last.remove();
    if (window.XensAnalytics) window.XensAnalytics.track("regenerate_response");
    resendEditedUserMessage(null, text);
  }

  /* ----------------------------------------------------------
     3b. HISTORIAL DE CONVERSACIONES ("Recientes" en el sidebar)
  ---------------------------------------------------------- */
  const THREE_DOTS_SVG =
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/></svg>';

  function renderRecentList(conversations) {
    el.recentList.innerHTML = "";

    const newItem = document.createElement("div");
    newItem.className = "recent-item" + (!state.currentConversationId ? " active" : "");
    newItem.textContent = "Nueva conversación";
    newItem.dataset.id = "";
    newItem.addEventListener("click", clearConversation);
    el.recentList.appendChild(newItem);

    conversations.forEach((conv) => {
      const row = document.createElement("div");
      row.className =
        "recent-item-row" +
        (conv.id === state.currentConversationId ? " active" : "") +
        (conv.pinned ? " pinned" : "");

      const item = document.createElement("div");
      item.className = "recent-item";
      item.textContent = conv.title || "Conversación";
      item.dataset.id = conv.id;
      item.title = conv.title || "Conversación";
      item.addEventListener("click", () => loadConversation(conv));
      row.appendChild(item);

      const menuBtn = document.createElement("button");
      menuBtn.className = "recent-menu-btn";
      menuBtn.innerHTML = THREE_DOTS_SVG;
      menuBtn.setAttribute("aria-label", "Opciones de conversación");
      menuBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        openRecentMenu(menuBtn, conv);
      });
      row.appendChild(menuBtn);

      el.recentList.appendChild(row);
    });
  }

  function renderTrashList(trash) {
    el.trashList.innerHTML = "";
    el.trashSection.style.display = trash.length ? "" : "none";

    trash.forEach((conv) => {
      const row = document.createElement("div");
      row.className = "trash-item-row";

      const title = document.createElement("span");
      title.className = "trash-item-title";
      title.textContent = conv.title || "Conversación";
      title.title = conv.title || "Conversación";
      row.appendChild(title);

      const actions = document.createElement("div");
      actions.className = "trash-actions";

      const restore = document.createElement("button");
      restore.className = "trash-action";
      restore.textContent = "Restaurar";
      restore.addEventListener("click", async () => {
        await window.XensDB.restoreConversation(conv.id);
        loadRecentConversations();
      });
      actions.appendChild(restore);

      const del = document.createElement("button");
      del.className = "trash-action danger";
      del.textContent = "Borrar";
      del.title = "Eliminar definitivamente";
      del.addEventListener("click", async () => {
        if (!confirm("¿Eliminar esta conversación para siempre? No se puede deshacer.")) return;
        await window.XensDB.deleteForever(conv.id);
        loadRecentConversations();
      });
      actions.appendChild(del);

      row.appendChild(actions);
      el.trashList.appendChild(row);
    });
  }

  /* ---- menú de tres puntos ---- */
  function openRecentMenu(btn, conv) {
    if (el.recentMenu) {
      const rect = btn.getBoundingClientRect();
      el.recentMenu.style.display = "block";
      el.recentMenu.style.left = Math.max(8, rect.right - 190) + "px";
      el.recentMenu.style.top = rect.bottom + 4 + "px";
      el.pinMenuLabel.textContent = conv.pinned ? "Desfijar" : "Fijar";
    }
    state.menuConvId = conv.id;
    state.menuConv = conv;
  }

  function closeRecentMenu() {
    if (el.recentMenu) el.recentMenu.style.display = "none";
    state.menuConvId = null;
    state.menuConv = null;
  }

  function buildShareText(conv, msgs) {
    const lines = [
      "XENS — Conversación compartida",
      "Título: " + (conv.title || "Conversación"),
      "Fecha: " + new Date().toLocaleString("es-ES"),
      "",
    ];
    msgs.forEach((m) => {
      lines.push((m.role === "user" ? "Tú: " : "Xens: ") + m.content, "");
    });
    return lines.join("\n");
  }

  async function shareConversation(conv) {
    const msgs = (await window.XensDB.listMessages(conv.id)) || [];
    const text = buildShareText(conv, msgs);
    const safeName = (conv.title || "conversacion").replace(/[\\/:*?"<>|]/g, "_").slice(0, 60);
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = safeName + ".txt";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    if (window.XensAnalytics) window.XensAnalytics.track("conversation_shared", { msgs: msgs.length });
  }

  function handleRecentMenuAction(action) {
    const conv = state.menuConv;
    if (!conv) return;

    if (action === "share") {
      shareConversation(conv);
    } else if (action === "pin") {
      window.XensDB.togglePin(conv.id).then(loadRecentConversations);
    } else if (action === "rename") {
      const name = prompt("Nuevo nombre de la conversación:", conv.title || "");
      if (name === null || name.trim() === "") {
        closeRecentMenu();
        return;
      }
      window.XensDB.renameConversation(conv.id, name.trim()).then((updated) => {
        loadRecentConversations();
        if (updated && state.currentConversationId === conv.id) {
          el.topbarTitle.textContent = updated.title || "Conversación";
        }
      });
    } else if (action === "trash") {
      window.XensDB.trashConversation(conv.id).then((trashed) => {
        closeRecentMenu();
        loadRecentConversations();
        if (trashed && trashed.id === state.currentConversationId) {
          clearConversation();
        }
      });
      return;
    }
    closeRecentMenu();
  }

  function applyRecentFilter() {
    const q = (el.searchInput && el.searchInput.value || "").trim().toLowerCase();
    const list = state.allConversations.filter((conv) => {
      if (!q) return true;
      return String(conv.title || "").toLowerCase().includes(q);
    });
    renderRecentList(list);
  }

  function highlightActiveRecent() {
    const rows = el.recentList.querySelectorAll(".recent-item-row");
    rows.forEach((row) => {
      const item = row.querySelector(".recent-item");
      row.classList.toggle("active", item.dataset.id === (state.currentConversationId || ""));
    });
    const plain = el.recentList.querySelectorAll(":scope > .recent-item");
    plain.forEach((item) => {
      item.classList.toggle("active", item.dataset.id === (state.currentConversationId || ""));
    });
  }

  async function loadRecentConversations() {
    if (!window.XensDB || !state.user) return;
    const userId = state.user.uid;
    const [conversations, trash] = await Promise.all([
      window.XensDB.listConversations(userId),
      window.XensDB.listTrash(),
    ]);
    state.allConversations = conversations || [];
    state.allTrash = trash || [];
    applyRecentFilter();
    renderTrashList(state.allTrash);
  }

  async function loadConversation(conv) {
    if (!window.XensDB) return;

    state.generation += 1;
    state.currentAssistantBubble = null;
    state.currentAssistantText = "";
    state.activeBubbles = {};
    state.activeReqIds = new Set();
    state.currentConversationId = conv.id;
    showChatView();
    el.messages.innerHTML = "";

    const msgs = await window.XensDB.listMessages(conv.id);
    msgs.forEach((m, idx) => {
      if (m.role === "user") {
        const bubble = buildUserBubble(m.content);
        state.lastUserText = m.content;
        el.messages.appendChild(bubble);
      } else {
        const bubble = document.createElement("div");
        bubble.className = "msg assistant";

        const content = document.createElement("div");
        content.className = "msg-content";
        content.innerHTML = renderMarkdown(m.content);
        bubble.appendChild(content);
        attachMessageActions(bubble, {
          role: "assistant",
          withRegenerate: idx === msgs.length - 1,
        });
        el.messages.appendChild(bubble);
      }
    });

    scrollToBottom();
    highlightActiveRecent();
    el.topbarTitle.textContent = conv.title || "Conversación";
  }

  /* ----------------------------------------------------------
     4. ESTADO DE CONEXIÓN (indicador visual arriba a la derecha)
  ---------------------------------------------------------- */
  function setConnectionUI(status) {
    // status: "connected" | "connecting" | "disconnected"
    el.statusDot.classList.remove("connecting", "disconnected");

    if (status === "connected") {
      el.statusText.textContent = "XENS — activo";
    } else if (status === "connecting") {
      el.statusDot.classList.add("connecting");
      el.statusText.textContent = "XENS — conectando...";
    } else {
      el.statusDot.classList.add("disconnected");
      el.statusText.textContent = "XENS — desconectado";
    }
  }

  /* ----------------------------------------------------------
     5. LÍMITE POR PLAN — créditos (cuenta) o chats de trial (local)
        visible solo en Configuración
  ---------------------------------------------------------- */
  function currentLimit() {
    if (typeof state.creditsLimit === "number" && state.creditsLimit > 0) return state.creditsLimit;
    const l = state.messageLimit;
    if (typeof l === "number" && l > 0) return l;
    return CONFIG.PLAN_LIMITS[state.plan] || CONFIG.PLAN_LIMITS.free;
  }

  function creditsMode() {
    return typeof state.credits === "number" && typeof state.creditsLimit === "number";
  }

  function formatCredits(n) {
    if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, "") + "k";
    return String(n);
  }

  function updateUsageUI() {
    const meta = CONFIG.PLAN_META[state.plan] || CONFIG.PLAN_META.free;

    // Sidebar: solo el nombre del plan, sin números de uso a la vista
    if (el.planName) el.planName.textContent = meta.label;
    if (el.planBadge) el.planBadge.textContent = meta.badge;
    if (el.userPlanTag) el.userPlanTag.textContent = meta.badge;

    // Modal de Configuración: aquí sí se ve el detalle de uso
    if (el.settingsPlanBadge) el.settingsPlanBadge.textContent = meta.badge;
    if (el.settingsUsageLabel) {
      el.settingsUsageLabel.textContent = creditsMode() ? "Xens Credits (mensual)" : "Chats usados";
    }
    if (el.settingsUsageCount) {
      if (creditsMode()) {
        const used = state.creditsLimit - state.credits;
        el.settingsUsageCount.textContent =
          `${formatCredits(state.credits)} / ${formatCredits(state.creditsLimit)} Xens Credits`;
      } else {
        el.settingsUsageCount.textContent = `${state.messageCount} / ${currentLimit()}`;
      }
    }
    if (el.settingsUsageFill) {
      const used = creditsMode() ? state.creditsLimit - state.credits : state.messageCount;
      const limit = currentLimit();
      el.settingsUsageFill.style.width = `${Math.min(100, (used / limit) * 100)}%`;
    }
  }

  function limitReached() {
    if (creditsMode()) return state.credits <= 0;
    return state.messageCount >= currentLimit();
  }

  function lockComposer() {
    el.composerInput.disabled = true;
    el.sendBtn.disabled = true;
    el.composerInner.classList.add("locked");
    if (creditsMode()) {
      el.composerInput.placeholder = "Sin créditos";
      el.disclaimer.textContent =
        "Agotaste tus Xens Credits del mes. Se renuevan el 1º. Mejora tu plan para obtener más.";
    } else {
      el.composerInput.placeholder = "Límite de chats alcanzado";
      el.disclaimer.textContent =
        "Alcanzaste el límite de chats de tu plan. Mejora tu plan para seguir chateando.";
    }
  }

  function unlockComposer() {
    el.composerInput.disabled = false;
    el.sendBtn.disabled = false;
    el.composerInner.classList.remove("locked");
    el.composerInput.placeholder = "Escribe un mensaje...";
    el.disclaimer.textContent =
      "XENS puede cometer errores. Verifica la información importante.";
  }

  /* ----------------------------------------------------------
     5b. MODAL DE CONFIGURACIÓN
  ---------------------------------------------------------- */
  function openSettings() {
    updateUsageUI();
    el.settingsOverlay.classList.add("open");
    if (window.XensAnalytics) window.XensAnalytics.track("settings_opened");
  }

  function closeSettings() {
    el.settingsOverlay.classList.remove("open");
  }

  if (el.settingsBtn) el.settingsBtn.addEventListener("click", openSettings);
  if (el.closeSettingsBtn) el.closeSettingsBtn.addEventListener("click", closeSettings);
  if (el.settingsOverlay) {
    el.settingsOverlay.addEventListener("click", (e) => {
      if (e.target === el.settingsOverlay) closeSettings();
    });
  }

  /* ----------------------------------------------------------
     5b2. MODAL DE HERRAMIENTAS USADAS
  ---------------------------------------------------------- */
  function renderToolsLog() {
    if (!el.toolsLog) return;
    el.toolsLog.innerHTML = "";

    if (state.toolLog.length === 0) {
      const empty = document.createElement("div");
      empty.className = "tools-log-empty";
      empty.textContent = "Aún no se han usado herramientas en esta conversación.";
      el.toolsLog.appendChild(empty);
      return;
    }

    state.toolLog.forEach((entry) => {
      const row = document.createElement("div");
      row.className = "tools-log-item";

      const badge = document.createElement("span");
      badge.className = "tools-log-status " + (entry.success === null ? "running" : entry.success ? "ok" : "err");
      badge.textContent = entry.success === null ? "…" : entry.success ? "✓" : "✗";

      const name = document.createElement("span");
      name.className = "tools-log-name";
      name.textContent = entry.name;
      name.title = entry.name;

      const meta = document.createElement("span");
      meta.className = "tools-log-meta";
      const parts = [];
      if (entry.summary) parts.push(entry.summary);
      parts.push(new Date(entry.time).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
      meta.textContent = parts.join(" · ");

      row.appendChild(badge);
      row.appendChild(name);
      row.appendChild(meta);
      el.toolsLog.appendChild(row);
    });
  }

  function openToolsModal() {
    if (!el.toolsOverlay) return;
    renderToolsLog();
    el.toolsOverlay.classList.add("open");
  }

  function closeToolsModal() {
    if (el.toolsOverlay) el.toolsOverlay.classList.remove("open");
  }

  if (el.closeToolsBtn) el.closeToolsBtn.addEventListener("click", closeToolsModal);
  if (el.toolsOverlay) {
    el.toolsOverlay.addEventListener("click", (e) => {
      if (e.target === el.toolsOverlay) closeToolsModal();
    });
  }

  /* ----------------------------------------------------------
     5c. ADJUNTAR ARCHIVOS
  ---------------------------------------------------------- */
  function renderAttachments() {
    el.attachmentsRow.innerHTML = "";
    if (state.pendingAttachments.length === 0) {
      el.attachmentsRow.classList.remove("visible");
      return;
    }
    el.attachmentsRow.classList.add("visible");

    state.pendingAttachments.forEach((file, index) => {
      const chip = document.createElement("div");
      chip.className = "attachment-chip";
      chip.innerHTML = `
        <span class="attachment-name">${escapeHtml(String(file.name))}</span>
        <button type="button" class="attachment-remove" aria-label="Quitar archivo">×</button>
      `;
      chip.querySelector(".attachment-remove").addEventListener("click", () => {
        state.pendingAttachments.splice(index, 1);
        renderAttachments();
      });
      el.attachmentsRow.appendChild(chip);
    });
  }

  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.split(",")[1] || "");
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }

  if (el.attachBtn && el.fileInput) {
    el.attachBtn.addEventListener("click", () => el.fileInput.click());

    el.fileInput.addEventListener("change", () => {
      const files = Array.from(el.fileInput.files || []);
      files.forEach((file) => {
        if (file.size > CONFIG.MAX_ATTACHMENT_BYTES) {
          addSystemNote(`"${file.name}" supera el límite de 5 MB y no se adjuntó.`);
          return;
        }
        state.pendingAttachments.push(file);
      });
      el.fileInput.value = "";
      renderAttachments();
      if (window.XensAnalytics) window.XensAnalytics.track("file_attached", { count: files.length });
    });
  }

  /* ----------------------------------------------------------
     5d. DICTADO POR VOZ (no es llamada, solo transcribe al input)
  ---------------------------------------------------------- */
  function setupMic() {
    if (!el.micBtn) return;
    const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SpeechRecognitionAPI) {
      el.micBtn.disabled = true;
      el.micBtn.title = "Dictado no soportado en este navegador";
      return;
    }

    state.recognition = new SpeechRecognitionAPI();
    state.recognition.lang = "es-ES";
    state.recognition.continuous = false;
    state.recognition.interimResults = false;

    state.recognition.addEventListener("result", (e) => {
      const transcript = Array.from(e.results)
        .map((r) => r[0].transcript)
        .join(" ");
      const prefix = el.composerInput.value ? el.composerInput.value + " " : "";
      el.composerInput.value = prefix + transcript;
      el.composerInput.focus();
    });

    state.recognition.addEventListener("end", () => {
      state.isRecording = false;
      el.micBtn.classList.remove("recording");
    });

    state.recognition.addEventListener("error", () => {
      state.isRecording = false;
      el.micBtn.classList.remove("recording");
    });

    el.micBtn.addEventListener("click", () => {
      if (state.isRecording) {
        state.recognition.stop();
        return;
      }
      state.isRecording = true;
      el.micBtn.classList.add("recording");
      if (window.XensAnalytics) window.XensAnalytics.track("mic_dictation_started");
      state.recognition.start();
    });
  }

  /* ----------------------------------------------------------
     6. WEBSOCKET
  ---------------------------------------------------------- */
  function connectSocket() {
    setConnectionUI("connecting");

    try {
      state.socket = new WebSocket(CONFIG.WS_URL);
    } catch (err) {
      handleSocketUnavailable();
      return;
    }

    state.socket.addEventListener("open", () => {
      state.isConnected = true;
      state.reconnectAttempts = 0;
      setConnectionUI("connected");
      sendAuthToken();
    });

    state.socket.addEventListener("message", (event) => {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (err) {
        console.error("Mensaje no-JSON recibido del servidor:", event.data);
        return;
      }
      handleServerMessage(data);
    });

    state.socket.addEventListener("close", () => {
      state.isConnected = false;
      setConnectionUI("disconnected");
      attemptReconnect();
    });

    state.socket.addEventListener("error", () => {
      // 'close' se dispara también tras 'error', el reintento se
      // maneja ahí para no duplicar lógica.
      state.isConnected = false;
    });
  }

  function attemptReconnect() {
    if (state.reconnectAttempts >= CONFIG.MAX_RECONNECT_ATTEMPTS) {
      setConnectionUI("disconnected");
      addSystemNote(
        "No se pudo conectar con el motor de XENS. Verifica que la aplicación local esté abierta."
      );
      return;
    }
    state.reconnectAttempts += 1;
    setTimeout(connectSocket, CONFIG.RECONNECT_DELAY_MS);
  }

  function handleSocketUnavailable() {
    setConnectionUI("disconnected");
    attemptReconnect();
  }

  function handleTriggerEvent(trigger) {
    if (!trigger) return;
    const name = String(trigger.name || "disparador");
    if (trigger.status === "fired") {
      addSystemNote(`Disparador «${name}» activado — tarea en segundo plano lanzada.`);
    } else if (trigger.status === "error") {
      addSystemNote(`El disparador «${name}» falló: ${trigger.reason || "error desconocido"}`);
    }
  }

  function handleTaskEvent(task) {
    if (!task) return;
    const name = String(task.name || "tarea");
    if (task.status === "done") {
      addSystemNote(`Tarea «${name}» completada. Pregúntame "¿cómo va la tarea?" para ver el resultado.`);
    } else if (task.status === "error") {
      addSystemNote(`La tarea «${name}» falló: ${task.error || "error desconocido"}`);
    } else if (task.status === "cancelled") {
      addSystemNote(`La tarea «${name}» fue cancelada.`);
    }
  }

  async function sendAuthToken() {
    let token = null;
    try {
      if (window.XensAuth && typeof window.XensAuth.getToken === "function") {
        token = await window.XensAuth.getToken();
      }
    } catch (err) {
      token = null;
    }
    if (token && state.socket && state.socket.readyState === WebSocket.OPEN) {
      state.socket.send(JSON.stringify({ type: "auth", token }));
    }
  }

  function handleServerMessage(data) {
    const reqId = data.requestId || null;
    switch (data.type) {
      case "content":
        appendAssistantChunk(data.content ?? "", reqId);
        break;

      case "done":
        finishAssistantBubble(reqId);
        break;

      case "tool_call":
        showToolCall(data.name || "herramienta", data.args, reqId);
        break;

      case "tool_result":
        finishToolCall(data.name || "", !!data.success, reqId);
        break;

      case "error":
        finishAssistantBubble(reqId);
        addSystemNote(data.message || data.content || "Ocurrió un error procesando tu mensaje.");
        break;

      case "task_event":
        handleTaskEvent(data.task);
        break;

      case "trigger_event":
        handleTriggerEvent(data.trigger);
        break;

      case "auth_ok":
        if (data.account) {
          state.account = data.account;
          state.plan = data.account.tier || "free";
          updateUsageUI();
          if (data.account.name && el.welcomeGreeting) {
            const firstName = String(data.account.name).split(" ")[0];
            el.welcomeGreeting.textContent = `Hola, ${firstName}`;
          }
        }
        loadProfile();
        break;

      case "auth_error":
        addSystemNote("No se pudo autenticar tu cuenta con el motor local.");
        break;

      case "credits":
        if (typeof data.credits === "number" && typeof data.creditsLimit === "number") {
          state.credits = data.credits;
          state.creditsLimit = data.creditsLimit;
          updateUsageUI();
          if (limitReached()) lockComposer();
        }
        break;

      case "ping":
        if (state.socket && state.socket.readyState === WebSocket.OPEN) {
          state.socket.send(JSON.stringify({ type: "pong" }));
        }
        break;

      case "cleared":
        state.currentConversationId = null;
        loadRecentConversations();
        break;

      case "profile":
        if (data.content && typeof data.content === "object") {
          state.serverProfile = data.content;
        }
        break;

      case "license":
        if (data.result) {
          if (data.result.success) {
            setLicenseMsg(`Licencia activada: ${String(data.result.tier || "").toUpperCase()}`);
            closeLicenseLock();
            loadProfile();
          } else {
            setLicenseMsg(data.result.error || "No se pudo activar la licencia.", true);
            setLockMsg(data.result.error || "No se pudo activar la licencia.", true);
          }
        }
        if (data.state) {
          renderLicenseStatus(data.state);
          showLicenseLock(data.state);
        }
        break;

      default:
        console.warn("Tipo de mensaje desconocido:", data.type, data);
    }
  }

  function sendToServer(payload) {
    if (state.socket && state.socket.readyState === WebSocket.OPEN) {
      state.socket.send(JSON.stringify(payload));
      return true;
    }
    addSystemNote("Sin conexión con XENS. Intentando reconectar...");
    return false;
  }

  /* ----------------------------------------------------------
     7. ENVÍO DE MENSAJES DEL USUARIO
  ---------------------------------------------------------- */
  async function sendMessage(text) {
    const trimmed = text.trim();
    if (!trimmed && state.pendingAttachments.length === 0) return;
    if (limitReached()) return;

    state.lastUserText = trimmed || "(archivo adjunto)";
    showChatView();
    addUserBubble(trimmed || "(archivo adjunto)");
    const requestId = Date.now() + "-" + Math.random().toString(36).slice(2, 8);
    state.activeReqIds.add(requestId);
    startAssistantBubble(requestId);

    // Persistencia ANTES de enviar: la conversación y el mensaje del
    // usuario deben existir antes de que el motor pueda responder,
    // o la respuesta ("done") no tendría conversación donde guardarse.
    await persistUserMessage(trimmed || "(archivo adjunto)");

    // Serializamos adjuntos a base64 antes de enviar por el WebSocket.
    // NOTA para el backend: esto es un envío directo por WS, adecuado
    // para archivos pequeños de prueba. En producción lo ideal es subir
    // el archivo a un storage (ej. Supabase Storage) y enviar solo la URL.
    const attachments = await Promise.all(
      state.pendingAttachments.map(async (file) => ({
        name: file.name,
        type: file.type,
        size: file.size,
        data: await fileToBase64(file),
      }))
    );

    const ok = sendToServer({
      type: "message",
      text: trimmed,
      requestId,
      uid: state.user ? state.user.uid : null,
      attachments,
    });

    if (!ok) {
      // revertimos la burbuja "escribiendo" si no hay conexión
      finishAssistantBubble(requestId);
      state.activeReqIds.delete(requestId);
    } else {
      if (!state.account) {
        state.messageCount += 1;
        updateUsageUI();
        if (limitReached()) lockComposer();
      }
    }

    if (window.XensAnalytics) {
      window.XensAnalytics.track("message_sent", {
        message_count: state.messageCount,
        with_attachments: attachments.length > 0,
      });
    }

    el.composerInput.value = "";
    state.pendingAttachments = [];
    renderAttachments();
  }

  async function persistUserMessage(text) {
    if (!window.XensDB) return;

    // Si el perfil aún no cargó, usamos el uid local por defecto:
    // así el primer mensaje nunca se pierde.
    const uid = state.user ? state.user.uid : "local-trial";

    if (!state.currentConversationId) {
      const conv = await window.XensDB.createConversation(uid, text);
      if (conv) {
        state.currentConversationId = conv.id;
        loadRecentConversations();
      }
    }

    if (state.currentConversationId) {
      // Solo persistimos si el envío al motor va a ocurrir de verdad;
      // la validación de conexión ocurre en sendToServer justo después.
      window.XensDB.saveMessage(state.currentConversationId, "user", text);
    }

    window.XensDB.incrementMessageCount(uid, state.messageCount);
  }

  function clearConversation() {
    sendToServer({ type: "clear" });
    resetToWelcome();
    state.currentConversationId = null;
    if (window.XensAnalytics) window.XensAnalytics.track("new_conversation");
    loadRecentConversations();
  }

  /* ----------------------------------------------------------
     8. EVENTOS DEL DOM
  ---------------------------------------------------------- */
  el.sendBtn.addEventListener("click", () => {
    sendMessage(el.composerInput.value);
  });

  el.composerInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(el.composerInput.value);
    }
  });

  el.composerInput.addEventListener("input", () => {
    el.composerInput.style.height = "auto";
    el.composerInput.style.height = Math.min(200, el.composerInput.scrollHeight) + "px";
  });

  el.suggestions.addEventListener("click", (e) => {
    const card = e.target.closest(".suggestion-card");
    if (!card) return;
    sendMessage(card.dataset.prompt || card.textContent);
  });

  if (el.searchInput) {
    el.searchInput.addEventListener("input", applyRecentFilter);
  }

  if (el.recentMenu) {
    el.recentMenu.querySelectorAll(".recent-menu-item").forEach((btn) => {
      btn.addEventListener("click", () => handleRecentMenuAction(btn.dataset.action));
    });
    document.addEventListener("click", (e) => {
      if (!el.recentMenu.contains(e.target) && e.target.closest(".recent-menu-btn") === null) {
        closeRecentMenu();
      }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        closeRecentMenu();
        closeSettings();
        closeToolsModal();
        if (el.licenseOverlay && el.licenseOverlay.classList.contains("open")) {
          el.licenseOverlay.classList.remove("open");
        }
        if (el.lockOverlay && el.lockOverlay.classList.contains("open")) {
          el.lockOverlay.classList.remove("open");
        }
      }
    });
    window.addEventListener("scroll", closeRecentMenu, true);
  }

  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      clearConversation();
      if (el.composerInput) el.composerInput.focus();
    }
  });

  el.newChatBtn.addEventListener("click", clearConversation);

  el.upgradeBtn.addEventListener("click", () => {
    if (window.XensAnalytics) window.XensAnalytics.track("upgrade_click", { from: "sidebar" });
    if (state.account) {
      // Cuenta: el upgrade es una suscripción (pricing → PayPal).
      window.location.href = "pricing.html";
      return;
    }
    // Cliente local sin cuenta: "mejorar plan" = activar un serial.
    openSettings();
    if (el.licenseKey) el.licenseKey.focus();
  });

  /* ----------------------------------------------------------
     9. PERFIL DE USUARIO (REST, opcional al cargar)
  ---------------------------------------------------------- */
  async function loadProfile() {
    const headers = {};
    try {
      if (window.XensAuth && typeof window.XensAuth.getToken === "function") {
        const token = await window.XensAuth.getToken();
        if (token) headers.Authorization = "Bearer " + token;
      }
    } catch (err) {
      /* sin token: modo local */
    }
    try {
      const res = await fetch(CONFIG.PROFILE_URL, { headers, cache: "no-store" });
      if (!res.ok) return;
      const profile = await res.json();

      if (typeof profile.messageCount === "number") {
        state.messageCount = profile.messageCount;
        updateUsageUI();
        if (limitReached()) lockComposer();
      }
      if (typeof profile.messageLimit === "number") {
        state.messageLimit = profile.messageLimit;
        updateUsageUI();
        if (limitReached()) lockComposer();
      }
      if (typeof profile.credits === "number" && typeof profile.creditsLimit === "number") {
        state.credits = profile.credits;
        state.creditsLimit = profile.creditsLimit;
        state.creditsResetSec = typeof profile.creditsResetAt === "number" ? profile.creditsResetAt : null;
        updateUsageUI();
        if (limitReached()) lockComposer();
      }
      if (profile.plan) {
        state.plan = profile.plan;
        updateUsageUI();
        if (limitReached()) lockComposer();
      }
      if (profile.license) {
        renderLicenseStatus(profile.license);
        showLicenseLock(profile.license);
      }
    } catch (err) {
      // el motor local puede no exponer aún este endpoint; fallamos
      // en silencio y seguimos con el contador local en 0.
    }
  }

  /* ----------------------------------------------------------
     2e. BIENVENIDA / TUTORIAL / NOVEDADES / DEPENDENCIAS
  ---------------------------------------------------------- */
  const INTRO_KEY = "xens.seen_intro";
  const DEPS_URL = "http://127.0.0.1:18000/api/deps";

  const WIZARD_STEPS = 4;

  function setWizardStep(n) {
    state.wizardStep = n;
    document.querySelectorAll(".wizard-step").forEach((step) => {
      step.style.display = step.dataset.step == n ? "" : "none";
    });
    el.wizardBar.style.width = `${(n / WIZARD_STEPS) * 100}%`;
    el.wizardStepLabel.textContent = `${n} / ${WIZARD_STEPS}`;
    el.wizardPrevBtn.classList.toggle("visible", n > 1);
    if (el.wizardNextBtn) {
      el.wizardNextBtn.textContent = n === WIZARD_STEPS ? "Empezar" : "Continuar";
    }
  }

  function openWizard(step) {
    if (!el.wizardOverlay) return;
    setWizardStep(step || 1);
    el.wizardOverlay.classList.add("open");
  }

  function closeWizard() {
    if (!el.wizardOverlay) return;
    el.wizardOverlay.classList.remove("open");
    localStorage.setItem(INTRO_KEY, "1");
  }

  async function fetchDeps() {
    try {
      const res = await fetch(DEPS_URL);
      if (!res.ok) return null;
      return await res.json();
    } catch (err) {
      return null;
    }
  }

  function depsPendingCount(data) {
    if (!data || !Array.isArray(data.deps)) return 0;
    return data.deps.filter((d) => !d.installed).length;
  }

  function updateSettingsDeps(data) {
    if (!el.settingsDepsStatus) return;
    if (!data) {
      el.settingsDepsStatus.textContent = "No disponible";
      return;
    }
    const pending = depsPendingCount(data);
    if (pending === 0) {
      el.settingsDepsStatus.textContent = "Todas instaladas";
    } else {
      el.settingsDepsStatus.textContent = `${pending} pendiente(s)`;
    }
  }

  function renderWizardDeps(data) {
    if (!el.wizardDeps) return;
    state.wizardDeps = data;
    el.wizardDeps.innerHTML = "";
    if (!data || !Array.isArray(data.deps)) {
      el.wizardDeps.innerHTML =
        '<p class="wizard-text">No se pudo consultar el estado de dependencias.</p>';
      return;
    }
    data.deps.forEach((dep) => {
      const row = document.createElement("label");
      row.className = "wizard-dep";
      if (dep.installed) row.classList.add("disabled");

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = dep.installed;
      checkbox.disabled = dep.installed || state.wizardInstalling;
      if (!dep.installed && !state.wizardInstalling) {
        state.wizardSelected.add(dep.id);
        checkbox.checked = true;
      }
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) state.wizardSelected.add(dep.id);
        else state.wizardSelected.delete(dep.id);
      });

      const meta = document.createElement("span");
      meta.className = "wizard-dep-meta";
      meta.textContent = `${dep.kind} · ${dep.size}`;

      const status = document.createElement("span");
      status.className = "dep-status " + (dep.installed ? "ok" : "pending");
      status.textContent = dep.installed ? "✓ instalada" : "pendiente";

      const body = document.createElement("div");
      body.style.flex = "1";
      const name = document.createElement("b");
      name.textContent = dep.name;
      const desc = document.createElement("span");
      desc.className = "wizard-dep-desc";
      desc.textContent = dep.desc;
      const metaLine = document.createElement("div");
      metaLine.style.marginTop = "5px";
      metaLine.appendChild(meta);
      body.appendChild(name);
      body.appendChild(desc);

      row.appendChild(checkbox);
      row.appendChild(body);
      row.appendChild(status);
      el.wizardDeps.appendChild(row);
    });

    if (el.wizardInstallBtn) {
      const pending = depsPendingCount(data);
      el.wizardInstallBtn.disabled = pending === 0 || state.wizardInstalling;
      el.wizardInstallBtn.textContent =
        state.wizardInstalling
          ? "Instalando..."
          : pending === 0
            ? "Todo instalado"
            : "Instalar seleccionadas";
      el.wizardInstallBtn.title =
        pending === 0 ? "No hay dependencias pendientes" : "";
    }
  }

  async function installSelectedDeps() {
    if (!state.wizardDeps || state.wizardInstalling) return;
    const pending = state.wizardDeps.deps.filter(
      (d) => !d.installed && state.wizardSelected.has(d.id)
    );
    if (pending.length === 0) return;

    state.wizardInstalling = true;
    renderWizardDeps(state.wizardDeps);
    if (el.wizardDepsMsg) {
      el.wizardDepsMsg.textContent = "Descargando componentes... esto puede tardar unos minutos.";
      el.wizardDepsMsg.style.color = "var(--text-muted, #8e8ea0)";
    }
    try {
      await fetch(DEPS_URL.replace("/deps", "/deps/install"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ deps: pending.map((d) => d.id), consent: true }),
      });
    } catch (err) {
      // sin backend: seguimos sondeando igual, no hay instalación real
    }

    await waitForInstalls();
    state.wizardInstalling = false;

    const data = await fetchDeps();
    state.wizardDeps = data;
    renderWizardDeps(data);
    updateSettingsDeps(data);
    updateUsageUI();

    if (el.wizardDepsMsg) {
      const missing = depsPendingCount(data);
      el.wizardDepsMsg.textContent =
        missing === 0
          ? "¡Listo! Todas las dependencias están instaladas."
          : "Algunas dependencias no se pudieron instalar. Revisá tu conexión y reintentá.";
      el.wizardDepsMsg.style.color =
        missing === 0 ? "var(--green, #22c55e)" : "var(--red, #ef4444)";
    }
  }

  async function waitForInstalls() {
    for (let i = 0; i < 240; i++) {
      const data = await fetchDeps();
      if (data && (!data.installing || data.installing.length === 0)) return;
      await new Promise((r) => setTimeout(r, 1500));
    }
  }

  async function initWizard() {
    const data = await fetchDeps();
    state.wizardDeps = data;
    updateSettingsDeps(data);

    if (el.wizardChangelog) {
      try {
        const res = await fetch("novedades.md");
        if (res.ok) {
          const md = await res.text();
          el.wizardChangelog.innerHTML = renderMarkdown(md);
        } else {
          el.wizardChangelog.innerHTML =
            '<p class="wizard-text">No hay registro de novedades.</p>';
        }
      } catch (err) {
        el.wizardChangelog.innerHTML =
          '<p class="wizard-text">No hay registro de novedades.</p>';
      }
    }

    if (el.wizardVersion) {
      try {
        const res = await fetch("http://127.0.0.1:18000/api/version");
        if (res.ok) {
          const v = await res.json();
          el.wizardVersion.textContent = "Versión " + (v.version || "—");
        }
      } catch (err) {
        el.wizardVersion.textContent = "Versión —";
      }
    }

    if (!localStorage.getItem(INTRO_KEY)) {
      renderWizardDeps(data);
      openWizard(1);
    }
  }

  if (el.wizardPrevBtn) {
    el.wizardPrevBtn.addEventListener("click", () => {
      if (state.wizardStep > 1) setWizardStep(state.wizardStep - 1);
    });
  }
  if (el.wizardNextBtn) {
    el.wizardNextBtn.addEventListener("click", () => {
      if (state.wizardStep < WIZARD_STEPS) {
        setWizardStep(state.wizardStep + 1);
      } else {
        closeWizard();
      }
    });
  }
  if (el.wizardInstallBtn) {
    el.wizardInstallBtn.addEventListener("click", installSelectedDeps);
  }
  if (el.wizardSkipBtn) {
    el.wizardSkipBtn.addEventListener("click", () => {
      if (el.wizardDepsMsg) {
        el.wizardDepsMsg.textContent =
          "Sin problema: podés instalar las dependencias más tarde desde Configuración.";
        el.wizardDepsMsg.style.color = "var(--text-muted, #8e8ea0)";
      }
      closeWizard();
      const btn = el.wizardSkipBtn;
      btn.style.display = "none";
    });
  }
  if (el.settingsDepsBtn) {
    el.settingsDepsBtn.addEventListener("click", async () => {
      closeSettings();
      const data = await fetchDeps();
      state.wizardDeps = data;
      renderWizardDeps(data);
      openWizard(4);
    });
  }

  /* ----------------------------------------------------------
     10. INICIALIZACIÓN
  ---------------------------------------------------------- */
  async function setupUserData(user) {
    state.user = user;

    const firstName = String((user && user.displayName) || "").split(" ")[0];
    if (el.welcomeGreeting) {
      el.welcomeGreeting.textContent = firstName ? `Hola, ${firstName}` : "Hola";
    }

    if (!window.XensDB) {
      // Supabase no configurado todavía: seguimos solo con el
      // contador local (se resetea al recargar la página).
      updateUsageUI();
      return;
    }

    const profile = await window.XensDB.ensureProfile(user);
    if (profile) {
      state.messageCount = profile.message_count || 0;
      state.plan = profile.plan || "free";
    }

    updateUsageUI();
    if (limitReached()) lockComposer();

    await loadRecentConversations();
    renderLicenseStatus(profile);
  }

  function init() {
    updateUsageUI();
    connectSocket();
    loadProfile();
    setupMic();
    initWizard();

    if (window.XensAuth) {
      window.XensAuth.onChange((user) => {
        if (!user || state.user) return; // session.js redirige si no hay user
        setupUserData(user);
      });
    }
  }

  init();
})();
