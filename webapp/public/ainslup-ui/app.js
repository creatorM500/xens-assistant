(() => {
  'use strict';

  const STORAGE_KEY = 'ainslup_state_v1';
  const AUTH_STORAGE_KEY = 'ainslup_session_v1';
  const DAY = 24 * 60 * 60 * 1000;
  const backend = window.AINSLUP_BACKEND;

  const MODELS = [
    { id: 'auto', shortName: 'Automático', name: 'AINSLUP · Automático', badge: 'Recomendado', desc: 'El servidor elige el mejor modelo disponible para tu cuenta.', color: '#61d190' },
    { id: 'Flash', shortName: 'Flash', name: 'AINSLUP · Flash', badge: 'Rápido', desc: 'Respuestas ágiles para tareas cotidianas.', color: '#f6c453' },
    { id: 'Core', shortName: 'Core', name: 'AINSLUP · Core', badge: 'Equilibrado', desc: 'Equilibrio entre profundidad, calidad y velocidad.', color: '#8b78ff' },
    { id: 'Think', shortName: 'Think', name: 'AINSLUP · Think', badge: 'Razonamiento', desc: 'Más esfuerzo de razonamiento para problemas complejos.', color: '#54b6ff' },
    { id: 'Code', shortName: 'Code', name: 'AINSLUP · Code', badge: 'Código', desc: 'Especializado en programación y revisión de código.', color: '#61d190' },
    { id: 'Research', shortName: 'Research', name: 'AINSLUP · Research', badge: 'Investigación', desc: 'Para análisis e investigación con fuentes.', color: '#c084fc' },
    { id: 'Vision', shortName: 'Vision', name: 'AINSLUP · Vision', badge: 'Visual', desc: 'Modelo con capacidades de visión cuando el proveedor las admite.', color: '#fb7185' },
    { id: 'Ultra', shortName: 'Ultra', name: 'AINSLUP · Ultra', badge: 'Avanzado', desc: 'Modelo avanzado; puede tener disponibilidad o coste distintos.', color: '#f97316' }
  ];

  const DEFAULT_LIBRARY = [
    { id: 'lib1', tag: 'Productividad', title: 'Planificador Semanal Deep Work', prompt: 'Organiza mi semana laboral en bloques de trabajo profundo de 90 minutos, reuniones agrupadas por la tarde y tiempo de revisión el viernes:' },
    { id: 'lib2', tag: 'Desarrollo', title: 'Auditoría de Código y Arquitectura', prompt: 'Revisa el siguiente código buscando cuellos de botella, vulnerabilidades de seguridad, accesibilidad y propón una versión refactorizada:' },
    { id: 'lib3', tag: 'Producto', title: 'PRD de Nueva Funcionalidad', prompt: 'Redacta un Documento de Requisitos de Producto (PRD) con problema, métricas de éxito, historias de usuario y riesgos para:' },
    { id: 'lib4', tag: 'Comunicación', title: 'Correo Ejecutivo Conciso', prompt: 'Transforma estas notas en un correo ejecutivo de menos de 120 palabras con asunto claro y llamada a la acción:' }
  ];

  const DEFAULT_PREFS = {
    userName: '',
    userRole: '',
    tone: 'equilibrado',
    customInstructions: '',
    theme: 'obsidian',
    accent: '#6d5efc',
    density: 'comfortable',
    showSuggestions: true,
    memoryEnabled: true,
    memories: []
  };

  let state = loadState();
  let authSession = loadAuthSession();
  let pendingSendAfterAuth = false;
  let currentChatId = null;
  let isTemporaryChat = false;
  let pendingAttachments = [];
  let isGenerating = false;
  let isPreparingSend = false;
  let generationTimer = null;
  let generationController = null;
  let webSearchEnabled = false;
  let deepThinkEnabled = false;
  let activeArtifact = null;

  const el = {
    appShell: document.getElementById('appShell'),
    sidebarOverlay: document.getElementById('sidebarOverlay'),
    collapseSidebarBtn: document.getElementById('collapseSidebarBtn'),
    openSidebarBtn: document.getElementById('openSidebarBtn'),
    brandHomeBtn: document.getElementById('brandHomeBtn'),
    newChatBtn: document.getElementById('newChatBtn'),
    currentWorkspaceBtn: document.getElementById('currentWorkspaceBtn'),
    workspaceLabel: document.getElementById('workspaceLabel'),
    historyList: document.getElementById('historyList'),
    toggleHistoryBtn: document.getElementById('toggleHistoryBtn'),
    openSearchModalBtn: document.getElementById('openSearchModalBtn'),
    openPersonalizeBtn: document.getElementById('openPersonalizeBtn'),
    personalizeActiveDot: document.getElementById('personalizeActiveDot'),
    userProfileBtn: document.getElementById('userProfileBtn'),
    userPopover: document.getElementById('userPopover'),
    userAvatarInitial: document.getElementById('userAvatarInitial'),
    userNameDisplay: document.getElementById('userNameDisplay'),
    popoverUserEmail: document.getElementById('popoverUserEmail'),
    authStatus: document.getElementById('authStatus'),
    authPlanChip: document.getElementById('authPlanChip'),
    connectionBadge: document.getElementById('connectionBadge'),
    connectionStatusText: document.getElementById('connectionStatusText'),
    menuConnectBtn: document.getElementById('menuConnectBtn'),
    menuLogoutBtn: document.getElementById('menuLogoutBtn'),
    authModal: document.getElementById('authModal'),
    authForm: document.getElementById('authForm'),
    authEmail: document.getElementById('authEmail'),
    authPassword: document.getElementById('authPassword'),
    authError: document.getElementById('authError'),
    authSubmitBtn: document.getElementById('authSubmitBtn'),
    closeAuthModalBtn: document.getElementById('closeAuthModalBtn'),
    menuShortcutsBtn: document.getElementById('menuShortcutsBtn'),
    menuExportChatBtn: document.getElementById('menuExportChatBtn'),
    menuClearHistoryBtn: document.getElementById('menuClearHistoryBtn'),
    currentChatTitle: document.getElementById('currentChatTitle'),
    tempChatBtn: document.getElementById('tempChatBtn'),
    incognitoBadge: document.getElementById('incognitoBadge'),
    topModelName: document.getElementById('topModelName'),
    chatScroll: document.getElementById('chatScroll'),
    emptyState: document.getElementById('emptyState'),
    heroGreeting: document.getElementById('heroGreeting'),
    suggestionCards: document.getElementById('suggestionCards'),
    messagesList: document.getElementById('messagesList'),
    attachmentsPreview: document.getElementById('attachmentsPreview'),
    promptInput: document.getElementById('promptInput'),
    plusMenuBtn: document.getElementById('plusMenuBtn'),
    plusMenu: document.getElementById('plusMenu'),
    uploadFileBtn: document.getElementById('uploadFileBtn'),
    fileInput: document.getElementById('fileInput'),
    insertPromptFromLibBtn: document.getElementById('insertPromptFromLibBtn'),
    createCodeArtifactDemoBtn: document.getElementById('createCodeArtifactDemoBtn'),
    webSearchToggle: document.getElementById('webSearchToggle'),
    deepThinkToggle: document.getElementById('deepThinkToggle'),
    modelSelectorBtn: document.getElementById('modelSelectorBtn'),
    modelSelectorDropdown: document.getElementById('modelSelectorDropdown'),
    modelOptionsList: document.getElementById('modelOptionsList'),
    composerModelDot: document.getElementById('composerModelDot'),
    composerModelLabel: document.getElementById('composerModelLabel'),
    dropdownThinkingSwitch: document.getElementById('dropdownThinkingSwitch'),
    voiceBtn: document.getElementById('voiceBtn'),
    sendBtn: document.getElementById('sendBtn'),
    libraryGrid: document.getElementById('libraryGrid'),
    addCustomPromptBtn: document.getElementById('addCustomPromptBtn'),
    librarySearch: document.getElementById('librarySearch'),
    libraryCategory: document.getElementById('libraryCategory'),
    libraryEmpty: document.getElementById('libraryEmpty'),
    libraryEmptyTitle: document.getElementById('libraryEmptyTitle'),
    libraryEmptyText: document.getElementById('libraryEmptyText'),
    promptCount: document.getElementById('promptCount'),
    scheduledList: document.getElementById('scheduledList'),
    generateImageBtn: document.getElementById('generateImageBtn'),
    imagePromptInput: document.getElementById('imagePromptInput'),
    imageRatioSelect: document.getElementById('imageRatioSelect'),
    imageAttachBtn: document.getElementById('imageAttachBtn'),
    imageReferenceInput: document.getElementById('imageReferenceInput'),
    imageReferenceName: document.getElementById('imageReferenceName'),
    removeImageReferenceBtn: document.getElementById('removeImageReferenceBtn'),
    addScheduleBtn: document.getElementById('addScheduleBtn'),
    scheduleComposer: document.getElementById('scheduleComposer'),
    scheduleTaskInput: document.getElementById('scheduleTaskInput'),
    scheduleDateInput: document.getElementById('scheduleDateInput'),
    scheduleFrequency: document.getElementById('scheduleFrequency'),
    saveScheduleBtn: document.getElementById('saveScheduleBtn'),
    artifactPanel: document.getElementById('artifactPanel'),
    artifactTitle: document.getElementById('artifactTitle'),
    artifactLang: document.getElementById('artifactLang'),
    artifactTabPreview: document.getElementById('artifactTabPreview'),
    artifactTabCode: document.getElementById('artifactTabCode'),
    artifactPreviewFrame: document.getElementById('artifactPreviewFrame'),
    artifactCodeContent: document.getElementById('artifactCodeContent'),
    copyArtifactBtn: document.getElementById('copyArtifactBtn'),
    downloadArtifactBtn: document.getElementById('downloadArtifactBtn'),
    closeArtifactBtn: document.getElementById('closeArtifactBtn'),
    personalizeModal: document.getElementById('personalizeModal'),
    closePersonalizeBtn: document.getElementById('closePersonalizeBtn'),
    cancelPersonalizeBtn: document.getElementById('cancelPersonalizeBtn'),
    savePersonalizeBtn: document.getElementById('savePersonalizeBtn'),
    resetPersonalizeBtn: document.getElementById('resetPersonalizeBtn'),
    prefUserName: document.getElementById('prefUserName'),
    prefUserRole: document.getElementById('prefUserRole'),
    prefCustomInstructions: document.getElementById('prefCustomInstructions'),
    toneSelectorGrid: document.getElementById('toneSelectorGrid'),
    themeOptions: document.getElementById('themeOptions'),
    accentSwatches: document.getElementById('accentSwatches'),
    densityOptions: document.getElementById('densityOptions'),
    prefShowSuggestions: document.getElementById('prefShowSuggestions'),
    prefMemoryEnabled: document.getElementById('prefMemoryEnabled'),
    newMemoryInput: document.getElementById('newMemoryInput'),
    addMemoryBtn: document.getElementById('addMemoryBtn'),
    memoryList: document.getElementById('memoryList'),
    searchModal: document.getElementById('searchModal'),
    quickSearchInput: document.getElementById('quickSearchInput'),
    quickSearchResults: document.getElementById('quickSearchResults'),
    shortcutsModal: document.getElementById('shortcutsModal'),
    closeShortcutsBtn: document.getElementById('closeShortcutsBtn'),
    toastContainer: document.getElementById('toastContainer')
  };

  function loadState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        const prefs = { ...DEFAULT_PREFS, ...(parsed.prefs || {}) };
        if (prefs.userName === 'diegotejeda880') prefs.userName = '';
        // El prototipo anterior podía guardar claves API en texto claro.
        delete prefs.apiEndpoint;
        delete prefs.apiKey;
        delete prefs.apiModel;
        return {
          chats: Array.isArray(parsed.chats) ? parsed.chats.filter(chat => chat && Array.isArray(chat.messages) && !String(chat.id).startsWith('chat_seed_')) : [],
          selectedModelId: MODELS.some(model => model.id === parsed.selectedModelId) ? parsed.selectedModelId : 'auto',
          prefs,
          library: Array.isArray(parsed.library) ? parsed.library : DEFAULT_LIBRARY,
          images: Array.isArray(parsed.images) ? parsed.images : [],
          scheduled: Array.isArray(parsed.scheduled) ? parsed.scheduled : []
        };
      }
    } catch (error) {
      console.error('No se pudo guardar el estado local de AINSLUP', error);
      if (error?.name === 'QuotaExceededError') showToast('El almacenamiento está lleno. Exporta o elimina conversaciones antiguas.');
      else showToast('No se pudieron guardar los cambios en este navegador.');
    }
    return {
      chats: [],
      selectedModelId: 'auto',
      prefs: { ...DEFAULT_PREFS },
      library: [...DEFAULT_LIBRARY],
      images: [],
      scheduled: []
    };
  }

  function saveState() {
    try {
      const prefs = { ...state.prefs };
      delete prefs.apiEndpoint;
      delete prefs.apiKey;
      delete prefs.apiModel;
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...state, prefs, selectedModelId: state.selectedModelId, scheduled: state.scheduled, usageCount: undefined, _tempMessages: undefined }));
    } catch (error) {
      console.error('No se pudo guardar el estado local de AINSLUP', error);
      showToast(error?.name === 'QuotaExceededError' ? 'El almacenamiento está lleno; elimina datos antiguos para guardar.' : 'No se pudieron guardar los cambios.');
    }
  }

  function loadAuthSession() {
    try {
      const value = JSON.parse(sessionStorage.getItem(AUTH_STORAGE_KEY) || 'null');
      return value?.access_token && value?.refresh_token ? value : null;
    } catch (_) { return null; }
  }

  function saveAuthSession(value) {
    authSession = value;
    try {
      if (value) sessionStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(value));
      else sessionStorage.removeItem(AUTH_STORAGE_KEY);
    } catch (_) {}
    updateAuthUI();
  }

  function updateAuthUI() {
    const email = authSession?.user?.email || '';
    el.authStatus.textContent = email || 'Sin iniciar sesión';
    el.popoverUserEmail.textContent = email || 'Conecta tu cuenta AINSLUP';
    el.authPlanChip.textContent = email ? 'CLOUD' : 'LOCAL';
    el.connectionBadge.textContent = email ? 'Conectado' : 'Sin conectar';
    el.connectionStatusText.textContent = email ? `Chat conectado como ${email}` : 'Inicia sesión para conversar con AINSLUP';
    el.menuConnectBtn.hidden = Boolean(email);
    el.menuLogoutBtn.hidden = !email;
    if (email) {
      const name = email.split('@')[0] || 'Usuario';
      el.userNameDisplay.textContent = name;
      el.userAvatarInitial.textContent = name.charAt(0).toUpperCase();
    } else {
      el.userNameDisplay.textContent = 'Usuario';
      el.userAvatarInitial.textContent = 'U';
    }
  }

  function openAuthModal() {
    el.authError.hidden = true;
    el.authError.textContent = '';
    el.authModal.hidden = false;
    el.authEmail.focus();
  }

  function friendlyNetworkError(error, fallback) {
    if (error instanceof TypeError && /fetch/i.test(error.message)) {
      return 'No se pudo conectar con AINSLUP. Comprueba tu conexión y vuelve a intentarlo.';
    }
    return error instanceof Error ? error.message : fallback;
  }

  async function requestAuth(path, body) {
    if (!backend?.supabaseUrl || !backend?.publishableKey) throw new Error('Falta configurar el acceso público de Supabase.');
    const response = await fetch(`${backend.supabaseUrl}/auth/v1/${path}`, {
      method: 'POST',
      headers: { apikey: backend.publishableKey, 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.msg || data.message || data.error_description || data.error || 'No se pudo iniciar sesión.');
    return data;
  }

  async function getAccessToken() {
    if (!authSession) return null;
    if (Number(authSession.expires_at || 0) > Date.now() + 60_000) return authSession.access_token;
    try {
      const refreshed = await requestAuth('token?grant_type=refresh_token', { refresh_token: authSession.refresh_token });
      saveAuthSession({ ...refreshed, expires_at: Date.now() + Number(refreshed.expires_in || 3600) * 1000 });
      return refreshed.access_token;
    } catch (_) {
      saveAuthSession(null);
      return null;
    }
  }

  function init() {
    saveState();
    applyPreferencesToUI();
    renderModelSelector();
    renderHistory();
    renderLibrary();
    renderScheduled();
    updateAuthUI();
    bindEvents();
    startNewChat(false);
  }

  function applyPreferencesToUI() {
    const p = state.prefs;
    document.documentElement.setAttribute('data-theme', p.theme);
    document.documentElement.setAttribute('data-density', p.density);
    document.documentElement.style.setProperty('--accent', p.accent);
    document.documentElement.style.setProperty('--accent-light', lightenHex(p.accent, 18));
    document.documentElement.style.setProperty('--accent-soft', hexToRgba(p.accent, 0.14));
    document.documentElement.style.setProperty('--accent-glow', hexToRgba(p.accent, 0.28));

    const name = (p.userName || 'Usuario').trim();
    el.userNameDisplay.textContent = name;
    el.userAvatarInitial.textContent = name.charAt(0).toUpperCase();
    el.personalizeActiveDot.classList.toggle('visible', Boolean(p.customInstructions));
    el.suggestionCards.hidden = !p.showSuggestions;
  }

  function openPersonalizeModal() {
    const p = state.prefs;
    el.prefUserName.value = p.userName || '';
    el.prefUserRole.value = p.userRole || '';
    el.prefCustomInstructions.value = p.customInstructions || '';
    el.prefShowSuggestions.checked = p.showSuggestions !== false;
    el.prefMemoryEnabled.checked = p.memoryEnabled !== false;
    syncActiveButtons(el.toneSelectorGrid, 'data-tone', p.tone);
    syncActiveButtons(el.themeOptions, 'data-theme-val', p.theme);
    syncActiveButtons(el.accentSwatches, 'data-accent', p.accent);
    syncActiveButtons(el.densityOptions, 'data-density-val', p.density);
    renderMemoryList();
    el.personalizeModal.hidden = false;
  }

  function renderMemoryList() {
    el.memoryList.innerHTML = '';
    if (!state.prefs.memories.length) {
      el.memoryList.innerHTML = '<p style="font-size:0.82rem;color:var(--text-muted)">No hay recuerdos guardados aún.</p>';
      return;
    }
    state.prefs.memories.forEach((mem, idx) => {
      const div = document.createElement('div');
      div.className = 'memory-item';
      div.innerHTML = `<span>${escapeHtml(mem)}</span><button class="icon-btn tiny" data-del-mem="${idx}" title="Eliminar">✕</button>`;
      div.querySelector('button').addEventListener('click', () => {
        state.prefs.memories.splice(idx, 1);
        renderMemoryList();
      });
      el.memoryList.appendChild(div);
    });
  }

  function syncActiveButtons(container, attr, value) {
    container.querySelectorAll(`[${attr}]`).forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute(attr) === value);
    });
  }

  function getSelectedModel() {
    return MODELS.find(m => m.id === state.selectedModelId) || MODELS[0];
  }

  function renderModelSelector() {
    const selected = getSelectedModel();
    el.topModelName.textContent = selected.shortName;
    el.composerModelLabel.textContent = selected.name;
    el.composerModelDot.style.background = selected.color;

    el.modelOptionsList.innerHTML = '';
    MODELS.forEach(m => {
      const btn = document.createElement('button');
      btn.className = `model-option ${m.id === selected.id ? 'selected' : ''}`;
      btn.innerHTML = `
        <div>
          <div class="model-opt-name">
            <span class="model-dot" style="background:${m.color}"></span>
            <span>${m.name}</span>
            <span class="model-opt-badge">${m.badge}</span>
          </div>
          <div class="model-opt-desc">${m.desc}</div>
        </div>
        <span class="model-opt-check">${m.id === selected.id ? '✓' : ''}</span>
      `;
      btn.addEventListener('click', () => {
        state.selectedModelId = m.id;
        deepThinkEnabled = m.id === 'Think';
        el.deepThinkToggle.classList.toggle('active', deepThinkEnabled);
        el.deepThinkToggle.setAttribute('aria-pressed', String(deepThinkEnabled));
        el.dropdownThinkingSwitch.checked = deepThinkEnabled;
        saveState();
        renderModelSelector();
        el.modelSelectorDropdown.hidden = true;
        showToast(`Modelo cambiado a ${m.name}`);
      });
      el.modelOptionsList.appendChild(btn);
    });
  }

  function setDeepThink(enabled) {
    deepThinkEnabled = Boolean(enabled);
    state.selectedModelId = deepThinkEnabled ? 'Think' : (state.selectedModelId === 'Think' ? 'auto' : state.selectedModelId);
    saveState();
    el.deepThinkToggle.classList.toggle('active', deepThinkEnabled);
    el.deepThinkToggle.setAttribute('aria-pressed', String(deepThinkEnabled));
    el.dropdownThinkingSwitch.checked = deepThinkEnabled;
    renderModelSelector();
  }

  function switchView(viewName) {
    document.querySelectorAll('.view-section').forEach(sec => {
      sec.hidden = sec.id !== `view-${viewName}`;
    });
    document.querySelectorAll('.nav-item[data-view], .workspace-pill[data-view]').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.view === viewName);
    });
    closeMobileSidebar();
  }

  function startNewChat(focusInput = true) {
    currentChatId = null;
    if (isTemporaryChat) state._tempMessages = [];
    switchView('chat');
    el.currentChatTitle.textContent = isTemporaryChat ? 'Chat temporal' : 'Nueva conversación';
    el.workspaceLabel.textContent = isTemporaryChat ? 'Sesión temporal' : 'Conversación actual';
    el.messagesList.innerHTML = '';
    el.messagesList.hidden = true;
    el.emptyState.hidden = false;
    renderHistory();
    if (focusInput) el.promptInput.focus();
  }

  function loadChat(chatId) {
    const chat = state.chats.find(c => c.id === chatId);
    if (!chat) return;
    currentChatId = chat.id;
    isTemporaryChat = false;
    el.incognitoBadge.hidden = true;
    el.tempChatBtn.classList.remove('active');
    switchView('chat');
    el.currentChatTitle.textContent = chat.title;
    el.workspaceLabel.textContent = chat.title;
    if (chat.modelId) {
      state.selectedModelId = chat.modelId;
      deepThinkEnabled = chat.modelId === 'Think';
      el.deepThinkToggle.classList.toggle('active', deepThinkEnabled);
      el.deepThinkToggle.setAttribute('aria-pressed', String(deepThinkEnabled));
      el.dropdownThinkingSwitch.checked = deepThinkEnabled;
      renderModelSelector();
    }
    renderMessages(chat.messages);
    renderHistory();
  }

  function renderHistory() {
    el.historyList.innerHTML = '';
    const sorted = [...state.chats].sort((a, b) => b.updatedAt - a.updatedAt);
    if (!sorted.length) {
      el.historyList.innerHTML = '<div style="padding:12px 10px;font-size:0.8rem;color:var(--text-muted)">Sin conversaciones guardadas.</div>';
      return;
    }
    const groups = { 'HOY': [], 'AYER': [], 'ÚLTIMOS 7 DÍAS': [], 'ANTERIORES': [] };
    const todayStart = new Date().setHours(0, 0, 0, 0);
    sorted.forEach(c => {
      if (c.updatedAt >= todayStart) groups['HOY'].push(c);
      else if (c.updatedAt >= todayStart - DAY) groups['AYER'].push(c);
      else if (c.updatedAt >= todayStart - 7 * DAY) groups['ÚLTIMOS 7 DÍAS'].push(c);
      else groups['ANTERIORES'].push(c);
    });
    Object.entries(groups).forEach(([label, items]) => {
      if (!items.length) return;
      const gTitle = document.createElement('div');
      gTitle.className = 'history-group-title';
      gTitle.textContent = label;
      el.historyList.appendChild(gTitle);
      items.forEach(chat => {
        const row = document.createElement('div');
        row.className = `history-item ${chat.id === currentChatId ? 'active' : ''}`;
        row.innerHTML = `<span class="history-item-title">${escapeHtml(chat.title)}</span><button class="history-item-delete" title="Eliminar conversación">✕</button>`;
        row.addEventListener('click', (e) => {
          if (e.target.closest('.history-item-delete')) {
            e.stopPropagation();
            state.chats = state.chats.filter(x => x.id !== chat.id);
            saveState();
            if (currentChatId === chat.id) startNewChat(false);
            else renderHistory();
            return;
          }
          loadChat(chat.id);
        });
        el.historyList.appendChild(row);
      });
    });
  }

  function renderMessages(messages) {
    el.messagesList.innerHTML = '';
    if (!messages.length) {
      el.emptyState.hidden = false;
      el.messagesList.hidden = true;
      return;
    }
    el.emptyState.hidden = true;
    el.messagesList.hidden = false;
    messages.forEach((msg, idx) => appendMessageElement(msg, idx));
    scrollToBottom();
  }

  function appendMessageElement(msg, idx) {
    const turn = document.createElement('div');
    turn.className = `message-turn ${msg.role}`;
    if (msg.role === 'user') {
      const attHtml = msg.attachments?.length
        ? `<div class="user-attachments-tags">${msg.attachments.map(a => `<span class="att-tag">📎 ${escapeHtml(a.name)}</span>`).join('')}</div>`
        : '';
      turn.innerHTML = `<div class="user-bubble">${attHtml}${escapeHtml(msg.text)}</div>`;
    } else {
      const thinkingHtml = msg.thinking
        ? `<div class="thinking-block"><button class="thinking-toggle" type="button"><span>💭 Proceso de razonamiento</span><span style="margin-left:auto;font-size:0.72rem;opacity:0.7">Ver / ocultar</span></button><div class="thinking-body">${escapeHtml(msg.thinking)}</div></div>`
        : '';
      turn.innerHTML = `
        <div class="assistant-row">
          <div class="assistant-avatar" aria-hidden="true">
            <svg viewBox="0 0 28 28" fill="none"><path d="M14 4L16.5 11.5L24 14L16.5 16.5L14 24L11.5 16.5L4 14L11.5 11.5L14 4Z" fill="currentColor"/></svg>
          </div>
          <div class="assistant-content">
            <div class="assistant-meta-line"><strong>AINSLUP</strong><span>· ${escapeHtml(msg.model || getSelectedModel().name)}</span></div>
            ${thinkingHtml}
            <div class="assistant-prose">${formatMarkdown(msg.text)}</div>
            <div class="msg-actions">
              <button class="msg-action-btn copy-msg-btn" title="Copiar respuesta">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                <span>Copiar</span>
              </button>
              <button class="msg-action-btn regen-msg-btn" title="Regenerar respuesta">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
                <span>Regenerar</span>
              </button>
            </div>
          </div>
        </div>
      `;
      const thinkBtn = turn.querySelector('.thinking-toggle');
      if (thinkBtn) thinkBtn.addEventListener('click', () => thinkBtn.closest('.thinking-block').classList.toggle('collapsed'));
      turn.querySelector('.copy-msg-btn').addEventListener('click', () => {
        void copyText(msg.text, 'Respuesta copiada al portapapeles');
      });
      turn.querySelector('.regen-msg-btn').addEventListener('click', () => regenerateFromIndex(idx));
      turn.querySelectorAll('.code-copy-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          void copyText(decodeURIComponent(btn.dataset.code), 'Código copiado');
        });
      });
      turn.querySelectorAll('.code-artifact-btn').forEach(btn => {
        btn.addEventListener('click', () => openArtifact('Artifact generado', btn.dataset.lang || 'html', decodeURIComponent(btn.dataset.code)));
      });
    }
    el.messagesList.appendChild(turn);
  }

  async function sendMessage(overrideText = null) {
    if (isGenerating) { stopGeneration(); return; }
    const rawText = overrideText !== null ? overrideText : el.promptInput.value.trim();
    if (!rawText && !pendingAttachments.length) return;
    if (isPreparingSend) return;
    if (pendingAttachments.length) {
      showToast('Los adjuntos todavía no están conectados al chat. Quita los archivos para enviar texto.');
      return;
    }
    isPreparingSend = true;
    let accessToken;
    try {
      accessToken = await getAccessToken();
    } catch (error) {
      isPreparingSend = false;
      showToast(friendlyNetworkError(error, 'No se pudo conectar con AINSLUP.'));
      return;
    }
    isPreparingSend = false;
    if (!accessToken) {
      pendingSendAfterAuth = true;
      openAuthModal();
      return;
    }
    const text = rawText || 'Analiza los archivos adjuntos.';
    const attachments = [...pendingAttachments];
    el.promptInput.value = '';
    el.promptInput.style.height = 'auto';
    pendingAttachments = [];
    renderAttachments();
    updateSendButtonState();

    let chat;
    if (isTemporaryChat) {
      if (!currentChatId) currentChatId = 'temp_' + Date.now();
      chat = { id: currentChatId, title: 'Chat temporal', messages: state._tempMessages || [], modelId: state.selectedModelId, updatedAt: Date.now() };
      state._tempMessages = chat.messages;
    } else {
      chat = state.chats.find(c => c.id === currentChatId);
      if (!chat) {
        chat = { id: 'chat_' + Date.now(), title: text.slice(0, 42) + (text.length > 42 ? '...' : ''), updatedAt: Date.now(), modelId: state.selectedModelId, messages: [] };
        state.chats.unshift(chat);
        currentChatId = chat.id;
      }
      chat.updatedAt = Date.now();
      chat.modelId = state.selectedModelId;
      el.currentChatTitle.textContent = chat.title;
      el.workspaceLabel.textContent = chat.title;
    }

    const userMsg = { role: 'user', text, attachments, time: Date.now() };
    chat.messages.push(userMsg);
    el.emptyState.hidden = true;
    el.messagesList.hidden = false;
    appendMessageElement(userMsg, chat.messages.length - 1);
    scrollToBottom();

    if (!isTemporaryChat) {
      saveState();
      renderHistory();
    }
    await generateAssistantReply(chat, text, attachments, accessToken, userMsg);
  }

  async function generateAssistantReply(chat, userText, attachments, accessToken, retryUserMessage = null) {
    const targetChatId = currentChatId;
    setGeneratingState(true);
    const model = getSelectedModel();
    const controller = new AbortController();
    let requestTimedOut = false;
    const requestTimeout = window.setTimeout(() => {
      requestTimedOut = true;
      controller.abort();
    }, 90000);
    generationController = controller;
    const loader = document.createElement('div');
    loader.className = 'message-turn assistant';
    loader.id = 'activeLoaderTurn';
    loader.innerHTML = `
      <div class="assistant-row">
        <div class="assistant-avatar"><svg viewBox="0 0 28 28" fill="none"><path d="M14 4L16.5 11.5L24 14L16.5 16.5L14 24L11.5 16.5L4 14L11.5 11.5L14 4Z" fill="currentColor"/></svg></div>
        <div class="assistant-content">
          <div class="assistant-meta-line"><strong>AINSLUP</strong><span>· ${model.name}</span></div>
          <div class="typing-dots"><span></span><span></span><span></span></div>
        </div>
      </div>
    `;
    el.messagesList.appendChild(loader);
    scrollToBottom();

    try {
      const preferences = state.prefs;
      const systemParts = [
        'Eres AINSLUP, un asistente de IA útil. Responde en español salvo que el usuario prefiera otro idioma.',
        `Usa un tono ${preferences.tone || 'equilibrado'}.`,
        preferences.userRole ? `Contexto del usuario: ${preferences.userRole}.` : '',
        preferences.customInstructions || '',
        preferences.memoryEnabled && preferences.memories.length ? `Preferencias recordadas: ${preferences.memories.join('; ')}` : ''
      ].filter(Boolean);
      const historyWindow = chat.messages.slice(-40);
      const messages = [
        { role: 'system', content: systemParts.join('\n') },
        ...historyWindow.map(message => ({ role: message.role, content: message.text }))
      ];
      const needsWebTools = webSearchEnabled || /\b(busca(?:r)?|búsqueda|internet|web|investiga(?:r|me)?|consulta|noticias?|precio|clima|fuentes?)\b/i.test(userText);
      const streamReply = !needsWebTools;
      const response = await fetch(backend.chatEndpoint, {
        method: 'POST',
        // Supabase Edge Functions currently allow Authorization and
        // Content-Type in CORS, but not the Auth REST `apikey` header.
        headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json', Accept: streamReply ? 'text/event-stream' : 'application/json' },
        body: JSON.stringify({
          messages,
          xens_model: deepThinkEnabled ? 'Think' : state.selectedModelId,
          tool_mode: needsWebTools,
          web_search: needsWebTools,
          client_now: new Date().toISOString(),
          client_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'America/New_York',
          stream: streamReply,
          xens_stream: streamReply
        }),
        signal: controller.signal
      });
      let data = {};
      let replyText = '';
      if (response.ok && response.headers.get('content-type')?.includes('text/event-stream') && response.body) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let prose = null;
        const renderDelta = (delta) => {
          if (!delta) return;
          replyText += delta;
          if (currentChatId !== targetChatId) return;
          if (!prose) {
            loader.querySelector('.typing-dots')?.remove();
            prose = document.createElement('div');
            prose.className = 'assistant-prose';
            loader.querySelector('.assistant-content')?.appendChild(prose);
          }
          prose.innerHTML = formatMarkdown(replyText);
          scrollToBottom();
        };
        const consumeSseLine = (line) => {
          const raw = line.trim();
          if (!raw.startsWith('data:')) return;
          const payload = raw.slice(5).trim();
          if (!payload || payload === '[DONE]') return;
          let event;
          try { event = JSON.parse(payload); } catch { return; }
          if (event.error) throw new Error(String(event.error.message || event.error));
          const delta = event.choices?.[0]?.delta?.content ?? event.choices?.[0]?.message?.content ?? '';
          if (typeof delta === 'string') renderDelta(delta);
          else if (Array.isArray(delta)) renderDelta(delta.filter(part => part?.type === 'text').map(part => part.text || '').join(''));
        };
        const consumeSseChunk = (chunk, final = false) => {
          buffer += chunk;
          const lines = buffer.split(/\r?\n/);
          buffer = final ? '' : lines.pop() || '';
          if (final && lines.length === 1 && lines[0]) consumeSseLine(lines[0]);
          else lines.forEach(consumeSseLine);
        };
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          consumeSseChunk(decoder.decode(value, { stream: true }));
        }
        consumeSseChunk(decoder.decode(), true);
      } else {
        data = await response.json().catch(() => ({}));
        replyText = String(data.content || '').trim();
      }
      if (response.status === 401) {
        saveAuthSession(null);
        pendingSendAfterAuth = true;
        openAuthModal();
      }
      if (!response.ok) throw new Error(data.detail ? `${data.error || 'Error del modelo'}: ${data.detail}` : data.error || 'No se pudo obtener una respuesta de AINSLUP.');
      replyText = replyText.trim();
      if (!replyText) throw new Error('AINSLUP devolvió una respuesta vacía. Inténtalo de nuevo.');
      if (/^(web_search|calculator|get_current_time|generate_image)$/i.test(replyText)) {
        throw new Error('AINSLUP no terminó la herramienta solicitada. Regenera la respuesta para intentarlo otra vez.');
      }
      const assistantMsg = { role: 'assistant', model: data.model || model.name, text: replyText, time: Date.now() };
      chat.messages.push(assistantMsg);
      if (isTemporaryChat) state._tempMessages = chat.messages;
      if (!isTemporaryChat) saveState();
      if (currentChatId !== targetChatId) return;
      loader.remove();
      appendMessageElement(assistantMsg, chat.messages.length - 1);
      scrollToBottom();
    } catch (error) {
      if (error?.name !== 'AbortError' || requestTimedOut) {
        if (retryUserMessage && chat.messages.at(-1) === retryUserMessage) {
          chat.messages.pop();
          if (isTemporaryChat) state._tempMessages = chat.messages;
          else {
            saveState();
            renderHistory();
          }
          renderMessages(chat.messages);
          el.promptInput.value = userText;
          autoResizeTextarea();
          updateSendButtonState();
        }
        showToast(requestTimedOut
          ? 'AINSLUP tardó demasiado en responder. El mensaje se restauró; inténtalo de nuevo.'
          : friendlyNetworkError(error, 'No se pudo completar la solicitud.'));
      }
    } finally {
      window.clearTimeout(requestTimeout);
      loader.remove();
      if (generationController === controller) generationController = null;
      setGeneratingState(false);
    }
  }

  async function regenerateFromIndex(msgIdx) {
    if (isGenerating) return;
    const chat = isTemporaryChat
      ? { id: currentChatId, messages: state._tempMessages || [] }
      : state.chats.find(c => c.id === currentChatId);
    if (!chat) return;
    const prevUser = [...chat.messages].slice(0, msgIdx).reverse().find(m => m.role === 'user');
    if (!prevUser) return;
    let accessToken;
    try { accessToken = await getAccessToken(); }
    catch (error) { showToast(friendlyNetworkError(error, 'No se pudo renovar la sesión.')); return; }
    if (!accessToken) {
      openAuthModal();
      return;
    }
    const originalMessages = [...chat.messages];
    chat.messages = chat.messages.slice(0, msgIdx);
    if (isTemporaryChat) state._tempMessages = chat.messages;
    else saveState();
    renderMessages(chat.messages);
    await generateAssistantReply(chat, prevUser.text, [], accessToken);
    if (!chat.messages.some(message => message.role === 'assistant' && message.time >= Date.now() - 1000)) {
      chat.messages = originalMessages;
      if (isTemporaryChat) state._tempMessages = chat.messages;
      else saveState();
      renderMessages(chat.messages);
    }
  }

  function setGeneratingState(active) {
    isGenerating = active;
    el.sendBtn.disabled = false;
    el.sendBtn.querySelector('.icon-send').hidden = active;
    el.sendBtn.querySelector('.icon-stop').hidden = !active;
    if (!active) updateSendButtonState();
  }

  function stopGeneration() {
    generationController?.abort();
    generationController = null;
    document.getElementById('activeLoaderTurn')?.remove();
    setGeneratingState(false);
    showToast('Generación detenida');
  }

  function openArtifact(title, lang, code) {
    activeArtifact = { title, lang, code };
    el.artifactTitle.textContent = title;
    el.artifactLang.textContent = lang.toUpperCase();
    el.artifactCodeContent.textContent = code;
    el.artifactPreviewFrame.srcdoc = lang.toLowerCase() === 'html'
      ? code
      : `<html><body style="background:#0b0b12;color:#e4e2f5;font-family:monospace;padding:18px;"><pre>${escapeHtml(code)}</pre></body></html>`;
    el.artifactPanel.hidden = false;
    setArtifactTab('preview');
  }

  function setArtifactTab(tab) {
    const isPrev = tab === 'preview';
    el.artifactTabPreview.classList.toggle('active', isPrev);
    el.artifactTabCode.classList.toggle('active', !isPrev);
    el.artifactPreviewFrame.hidden = !isPrev;
    el.artifactCodeContent.hidden = isPrev;
  }

  function renderLibrary() {
    el.libraryGrid.innerHTML = '';
    const query = (el.librarySearch?.value || '').trim().toLocaleLowerCase();
    const category = el.libraryCategory?.value || 'all';
    const categories = [...new Set(state.library.map(item => item.tag || 'General').filter(Boolean))].sort();
    if (el.libraryCategory) {
      const selected = el.libraryCategory.value || 'all';
      el.libraryCategory.innerHTML = '<option value="all">Todas las categorías</option>' +
        categories.map(tag => `<option value="${escapeHtml(tag)}">${escapeHtml(tag)}</option>`).join('');
      el.libraryCategory.value = categories.includes(selected) ? selected : 'all';
    }
    const items = state.library.filter(item =>
      (category === 'all' || (item.tag || 'General') === category) &&
      (!query || `${item.title} ${item.tag} ${item.prompt}`.toLocaleLowerCase().includes(query))
    );
    if (el.promptCount) el.promptCount.textContent = String(state.library.length);
    if (el.libraryEmpty) {
      el.libraryEmpty.hidden = items.length > 0;
      el.libraryEmptyTitle.textContent = query ? 'No encontramos resultados' : 'Todavía no hay prompts guardados';
      el.libraryEmptyText.textContent = query ? 'Prueba con otra búsqueda o categoría.' : 'Crea un prompt y reutilízalo cuando quieras.';
    }
    items.forEach(item => {
      const card = document.createElement('div');
      card.className = 'lib-card';
      card.innerHTML = `<div><span class="lib-tag">${escapeHtml(item.tag || 'General')}</span><h4 style="margin-top:10px;">${escapeHtml(item.title)}</h4><p>${escapeHtml(item.prompt)}</p></div><div class="lib-card-actions"><button class="ghost-btn use-prompt">Usar en chat</button><button class="ghost-btn delete-prompt" aria-label="Eliminar ${escapeHtml(item.title)}" title="Eliminar prompt">Eliminar</button></div>`;
      card.querySelector('.use-prompt').addEventListener('click', () => {
        switchView('chat');
        el.promptInput.value = item.prompt + ' ';
        autoResizeTextarea();
        updateSendButtonState();
        el.promptInput.focus();
      });
      card.querySelector('.delete-prompt').addEventListener('click', () => {
        if (!confirm(`¿Eliminar “${item.title}” de tu biblioteca?`)) return;
        state.library = state.library.filter(prompt => prompt.id !== item.id);
        saveState();
        renderLibrary();
        showToast('Prompt eliminado');
      });
      el.libraryGrid.appendChild(card);
    });
  }

  function renderScheduled() {
    const filter = document.querySelector('[data-schedule-filter].active')?.dataset.scheduleFilter || 'all';
    const items = state.scheduled.filter(item => filter === 'all' || (filter === 'done' ? item.done : !item.done));
    el.scheduledList.classList.toggle('feature-notice', !items.length);
    el.scheduledList.innerHTML = '';
    if (!items.length) { el.scheduledList.textContent = 'No hay tareas en esta vista.'; return; }
    items.forEach(item => {
      const row = document.createElement('article'); row.className = 'schedule-row';
      const parsedDate = item.date ? new Date(item.date) : null;
      const date = parsedDate && !Number.isNaN(parsedDate.getTime()) ? parsedDate.toLocaleString() : 'Sin fecha';
      row.innerHTML = `<div><h4>${escapeHtml(item.text)}</h4><p>${escapeHtml(date)} · ${escapeHtml(item.frequency)} · Borrador local</p></div><div class="lib-card-actions"><button class="ghost-btn toggle-schedule">${item.done ? 'Reabrir' : 'Completar'}</button><button class="ghost-btn delete-schedule">Eliminar</button></div>`;
      row.querySelector('.toggle-schedule').addEventListener('click', () => { item.done = !item.done; saveState(); renderScheduled(); });
      row.querySelector('.delete-schedule').addEventListener('click', () => { state.scheduled = state.scheduled.filter(task => task.id !== item.id); saveState(); renderScheduled(); });
      el.scheduledList.appendChild(row);
    });
  }

  function bindEvents() {
    el.collapseSidebarBtn.addEventListener('click', () => {
      if (window.innerWidth <= 920) closeMobileSidebar();
      else el.appShell.classList.toggle('sidebar-collapsed');
    });
    el.openSidebarBtn.addEventListener('click', () => {
      if (window.innerWidth <= 920) el.appShell.classList.add('mobile-sidebar-open');
      else el.appShell.classList.remove('sidebar-collapsed');
    });
    el.sidebarOverlay.addEventListener('click', closeMobileSidebar);
    el.newChatBtn.addEventListener('click', () => startNewChat(true));
    el.brandHomeBtn.addEventListener('click', (e) => { e.preventDefault(); startNewChat(true); });
    document.querySelectorAll('.nav-item[data-view], .workspace-pill[data-view]').forEach(btn => {
      btn.addEventListener('click', () => switchView(btn.dataset.view));
    });
    el.toggleHistoryBtn.addEventListener('click', () => {
      const historyScroll = el.historyList.closest('.history-scroll');
      if (!historyScroll) return;
      historyScroll.classList.toggle('collapsed');
      el.toggleHistoryBtn.setAttribute('aria-expanded', String(!historyScroll.classList.contains('collapsed')));
    });
    el.suggestionCards.querySelectorAll('.suggestion-card').forEach(card => {
      card.addEventListener('click', () => {
        el.promptInput.value = card.dataset.prompt;
        autoResizeTextarea();
        updateSendButtonState();
        el.promptInput.focus();
      });
    });
    el.promptInput.addEventListener('input', () => { autoResizeTextarea(); updateSendButtonState(); });
    el.promptInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        if (!isGenerating && !el.sendBtn.disabled) sendMessage();
      }
    });
    el.sendBtn.addEventListener('click', () => sendMessage());
    el.webSearchToggle.addEventListener('click', () => {
      webSearchEnabled = !webSearchEnabled;
      el.webSearchToggle.classList.toggle('active', webSearchEnabled);
      el.webSearchToggle.setAttribute('aria-pressed', String(webSearchEnabled));
    });
    el.deepThinkToggle.addEventListener('click', () => setDeepThink(!deepThinkEnabled));
    el.dropdownThinkingSwitch.addEventListener('change', (e) => setDeepThink(e.target.checked));

    el.modelSelectorBtn.addEventListener('click', (e) => { e.stopPropagation(); togglePopover(el.modelSelectorDropdown); });
    el.plusMenuBtn.addEventListener('click', (e) => { e.stopPropagation(); togglePopover(el.plusMenu); });
    el.userProfileBtn.addEventListener('click', (e) => { e.stopPropagation(); togglePopover(el.userPopover); });
    el.menuConnectBtn.addEventListener('click', () => { el.userPopover.hidden = true; openAuthModal(); });
    el.menuLogoutBtn.addEventListener('click', async () => {
      el.userPopover.hidden = true;
      if (authSession?.access_token && backend?.supabaseUrl && backend?.publishableKey) {
        try {
          await fetch(`${backend.supabaseUrl}/auth/v1/logout`, {
            method: 'POST',
            headers: { apikey: backend.publishableKey, Authorization: `Bearer ${authSession.access_token}` }
          });
        } catch (_) {}
      }
      saveAuthSession(null);
      showToast('Sesión cerrada en este navegador');
    });
    el.closeAuthModalBtn.addEventListener('click', () => {
      el.authModal.hidden = true;
      pendingSendAfterAuth = false;
    });
    el.authModal.addEventListener('click', event => {
      if (event.target === el.authModal) {
        el.authModal.hidden = true;
        pendingSendAfterAuth = false;
      }
    });
    el.authForm.addEventListener('submit', async event => {
      event.preventDefault();
      el.authError.hidden = true;
      el.authSubmitBtn.disabled = true;
      el.authSubmitBtn.textContent = 'Conectando…';
      try {
        const session = await requestAuth('token?grant_type=password', {
          email: el.authEmail.value.trim(),
          password: el.authPassword.value
        });
        if (!session.access_token) throw new Error('La cuenta requiere confirmación por correo antes de iniciar sesión.');
        const expiry = Number(session.expires_at || 0);
        saveAuthSession({
          ...session,
          expires_at: expiry > 0 ? expiry * 1000 : Date.now() + Number(session.expires_in || 3600) * 1000
        });
        el.authPassword.value = '';
        el.authModal.hidden = true;
        showToast('Cuenta AINSLUP conectada');
        if (pendingSendAfterAuth) {
          pendingSendAfterAuth = false;
          void sendMessage();
        }
      } catch (error) {
        el.authError.textContent = friendlyNetworkError(error, 'No se pudo iniciar sesión.');
        el.authError.hidden = false;
      } finally {
        el.authSubmitBtn.disabled = false;
        el.authSubmitBtn.textContent = 'Iniciar sesión';
      }
    });

    document.addEventListener('click', (e) => {
      [el.modelSelectorDropdown, el.plusMenu, el.userPopover].forEach(pop => {
        if (!pop.hidden && !pop.contains(e.target)) pop.hidden = true;
      });
    });

    el.uploadFileBtn.addEventListener('click', () => {
      el.plusMenu.hidden = true;
      showToast('El envío de archivos todavía no está conectado. No se adjuntó ningún archivo.');
    });
    el.insertPromptFromLibBtn.addEventListener('click', () => { el.plusMenu.hidden = true; switchView('library'); });
    el.createCodeArtifactDemoBtn.addEventListener('click', () => {
      el.plusMenu.hidden = true;
      sendMessage('Genera un Artifact interactivo con una tarjeta UI moderna en HTML y CSS');
    });
    el.voiceBtn.addEventListener('click', handleVoiceDictation);

    el.tempChatBtn.addEventListener('click', () => {
      isTemporaryChat = !isTemporaryChat;
      el.tempChatBtn.classList.toggle('active', isTemporaryChat);
      el.incognitoBadge.hidden = !isTemporaryChat;
      state._tempMessages = [];
      startNewChat(true);
      showToast(isTemporaryChat ? 'Modo temporal activo: no se guardará en tu historial' : 'Historial estándar restaurado');
    });

    el.openPersonalizeBtn.addEventListener('click', openPersonalizeModal);
    el.closePersonalizeBtn.addEventListener('click', () => el.personalizeModal.hidden = true);
    el.cancelPersonalizeBtn.addEventListener('click', () => el.personalizeModal.hidden = true);

    document.querySelectorAll('.modal-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        document.querySelectorAll('.modal-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-pane').forEach(p => p.hidden = true);
        tab.classList.add('active');
        document.getElementById(`tab-${tab.dataset.tab}`).hidden = false;
      });
    });

    el.toneSelectorGrid.addEventListener('click', (e) => { const b = e.target.closest('[data-tone]'); if (b) syncActiveButtons(el.toneSelectorGrid, 'data-tone', b.dataset.tone); });
    el.themeOptions.addEventListener('click', (e) => { const b = e.target.closest('[data-theme-val]'); if (b) syncActiveButtons(el.themeOptions, 'data-theme-val', b.dataset.themeVal); });
    el.accentSwatches.addEventListener('click', (e) => { const b = e.target.closest('[data-accent]'); if (b) syncActiveButtons(el.accentSwatches, 'data-accent', b.dataset.accent); });
    el.densityOptions.addEventListener('click', (e) => { const b = e.target.closest('[data-density-val]'); if (b) syncActiveButtons(el.densityOptions, 'data-density-val', b.dataset.densityVal); });

    el.addMemoryBtn.addEventListener('click', () => {
      const val = el.newMemoryInput.value.trim();
      if (!val) return;
      state.prefs.memories.unshift(val);
      el.newMemoryInput.value = '';
      renderMemoryList();
    });

    el.savePersonalizeBtn.addEventListener('click', () => {
      state.prefs.userName = el.prefUserName.value.trim();
      state.prefs.userRole = el.prefUserRole.value.trim();
      state.prefs.customInstructions = el.prefCustomInstructions.value.trim();
      state.prefs.tone = el.toneSelectorGrid.querySelector('.active')?.dataset.tone || 'equilibrado';
      state.prefs.theme = el.themeOptions.querySelector('.active')?.dataset.themeVal || 'obsidian';
      state.prefs.accent = el.accentSwatches.querySelector('.active')?.dataset.accent || '#6d5efc';
      state.prefs.density = el.densityOptions.querySelector('.active')?.dataset.densityVal || 'comfortable';
      state.prefs.showSuggestions = el.prefShowSuggestions.checked;
      state.prefs.memoryEnabled = el.prefMemoryEnabled.checked;
      saveState();
      applyPreferencesToUI();
      el.personalizeModal.hidden = true;
      showToast('Personalización guardada y aplicada');
    });

    el.resetPersonalizeBtn.addEventListener('click', () => {
      state.prefs = { ...DEFAULT_PREFS };
      saveState();
      applyPreferencesToUI();
      openPersonalizeModal();
      showToast('Valores restaurados');
    });

    el.addCustomPromptBtn.addEventListener('click', () => {
      const title = window.prompt('Nombre para este prompt:');
      const body = title ? window.prompt('¿Qué quieres que haga el asistente?') : null;
      if (title?.trim() && body?.trim()) {
        state.library.unshift({ id: 'lib_' + Date.now(), tag: 'Personalizado', title: title.trim(), prompt: body.trim() });
        saveState();
        if (el.librarySearch) el.librarySearch.value = '';
        if (el.libraryCategory) el.libraryCategory.value = 'all';
        renderLibrary();
        showToast('Prompt guardado en Biblioteca');
      }
    });
    el.librarySearch?.addEventListener('input', renderLibrary);
    el.libraryCategory?.addEventListener('change', renderLibrary);
    document.querySelectorAll('[data-library-tab]').forEach(tab => tab.addEventListener('click', () => {
      document.querySelectorAll('[data-library-tab]').forEach(item => {
        const active = item === tab;
        item.classList.toggle('active', active);
        item.setAttribute('aria-selected', String(active));
      });
      const section = tab.dataset.libraryTab;
      const prompts = section === 'prompts';
      el.libraryGrid.hidden = !prompts;
      el.librarySearch.closest('.library-toolbar').hidden = !prompts;
      el.libraryCategory.hidden = !prompts;
      el.libraryEmpty.hidden = prompts && state.library.length > 0;
      el.libraryEmptyTitle.textContent = section === 'documents' ? 'Tus documentos aparecerán aquí' : section === 'media' ? 'Tu contenido multimedia aparecerá aquí' : 'Todavía no hay prompts guardados';
      el.libraryEmptyText.textContent = section === 'documents' ? 'Los archivos y documentos que guardes estarán disponibles en este espacio.' : section === 'media' ? 'Aquí encontrarás las imágenes y otros contenidos que crees con AINSLUP.' : 'Crea un prompt y reutilízalo cuando quieras.';
      el.addCustomPromptBtn.hidden = !prompts;
    }));
    el.generateImageBtn?.addEventListener('click', () => {
      const promptText = el.imagePromptInput.value.trim();
      if (!promptText) return showToast('Describe primero la imagen que tienes en mente');
      switchView('chat');
      el.promptInput.value = `Crea una imagen${el.imageRatioSelect.value !== 'auto' ? ` con relación ${el.imageRatioSelect.value}` : ''}: ${promptText}`;
      autoResizeTextarea(); updateSendButtonState(); el.promptInput.focus();
      showToast('Prompt preparado en el chat. La generación requiere conectar el motor visual.');
    });
    el.imageAttachBtn?.addEventListener('click', () => el.imageReferenceInput?.click());
    el.imageReferenceInput?.addEventListener('change', () => {
      const file = el.imageReferenceInput.files?.[0];
      if (!file) return;
      el.imageReferenceName.hidden = false;
      el.imageReferenceName.querySelector('.reference-file-text').textContent = file.name;
    });
    el.removeImageReferenceBtn?.addEventListener('click', () => {
      el.imageReferenceInput.value = '';
      el.imageReferenceName.hidden = true;
    });
    el.addScheduleBtn?.addEventListener('click', () => {
      el.scheduleComposer.hidden = !el.scheduleComposer.hidden;
      if (!el.scheduleComposer.hidden) el.scheduleTaskInput.focus();
    });
    el.saveScheduleBtn?.addEventListener('click', () => {
      const text = el.scheduleTaskInput.value.trim();
      if (!text) return showToast('Escribe qué tarea quieres recordar');
      if (!el.scheduleDateInput.value || Number.isNaN(new Date(el.scheduleDateInput.value).getTime())) return showToast('Elige una fecha y hora válidas');
      state.scheduled.unshift({ id: 'task_' + crypto.randomUUID(), text, date: el.scheduleDateInput.value, frequency: el.scheduleFrequency.value, done: false, createdAt: new Date().toISOString() });
      saveState(); el.scheduleTaskInput.value = ''; el.scheduleDateInput.value = ''; el.scheduleComposer.hidden = true; renderScheduled();
      showToast('Borrador guardado en este navegador; no se ejecutará automáticamente.');
    });
    document.querySelectorAll('[data-schedule-filter]').forEach(button => button.addEventListener('click', () => {
      document.querySelectorAll('[data-schedule-filter]').forEach(filter => filter.classList.toggle('active', filter === button));
      renderScheduled();
    }));

    el.artifactTabPreview.addEventListener('click', () => setArtifactTab('preview'));
    el.artifactTabCode.addEventListener('click', () => setArtifactTab('code'));
    el.closeArtifactBtn.addEventListener('click', () => el.artifactPanel.hidden = true);
    el.copyArtifactBtn.addEventListener('click', () => { if (activeArtifact) void copyText(activeArtifact.code, 'Código del Artifact copiado'); });
    el.downloadArtifactBtn.addEventListener('click', () => {
      if (!activeArtifact) return;
      downloadFile(`ainslup-artifact.${activeArtifact.lang.toLowerCase() === 'html' ? 'html' : 'txt'}`, activeArtifact.code);
    });

    el.menuShortcutsBtn.addEventListener('click', () => { el.userPopover.hidden = true; el.shortcutsModal.hidden = false; });
    el.closeShortcutsBtn.addEventListener('click', () => el.shortcutsModal.hidden = true);
    el.menuExportChatBtn.addEventListener('click', () => {
      el.userPopover.hidden = true;
      const chat = state.chats.find(c => c.id === currentChatId);
      if (!chat || !chat.messages.length) return showToast('No hay mensajes para exportar');
      const md = `# ${chat.title}\n\n` + chat.messages.map(m => `**${m.role === 'user' ? 'Tú' : 'AINSLUP'}:**\n${m.text}\n`).join('\n---\n\n');
      downloadFile(`${chat.title.slice(0, 24).replace(/\W+/g, '_')}.md`, md);
    });

    el.menuClearHistoryBtn.addEventListener('click', () => {
      el.userPopover.hidden = true;
      if (confirm('¿Seguro que deseas borrar todo el historial local?')) {
        state.chats = [];
        saveState();
        startNewChat(false);
        showToast('Historial borrado');
      }
    });

    el.openSearchModalBtn.addEventListener('click', openSearchModal);
    el.quickSearchInput.addEventListener('input', renderSearchResults);

    document.addEventListener('keydown', (e) => {
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === 'k') { e.preventDefault(); openSearchModal(); }
      else if (mod && e.key.toLowerCase() === 'b') { e.preventDefault(); el.appShell.classList.toggle('sidebar-collapsed'); }
      else if (mod && e.shiftKey && e.key.toLowerCase() === 'o') { e.preventDefault(); startNewChat(true); }
      else if (e.key === 'Escape') {
        el.personalizeModal.hidden = true;
        el.searchModal.hidden = true;
        el.shortcutsModal.hidden = true;
        if (!el.authModal.hidden) {
          el.authModal.hidden = true;
          pendingSendAfterAuth = false;
        }
      }
    });
  }

  function openSearchModal() {
    el.searchModal.hidden = false;
    el.quickSearchInput.value = '';
    renderSearchResults();
    el.quickSearchInput.focus();
  }

  function renderSearchResults() {
    const q = el.quickSearchInput.value.trim().toLowerCase();
    const matches = state.chats.filter(c => String(c.title || '').toLowerCase().includes(q) || (Array.isArray(c.messages) && c.messages.some(m => String(m.text || '').toLowerCase().includes(q))));
    el.quickSearchResults.innerHTML = '';
    if (!matches.length) {
      el.quickSearchResults.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted);font-size:0.84rem">Sin coincidencias</div>';
      return;
    }
    matches.forEach(c => {
      const btn = document.createElement('button');
      btn.className = 'search-result-item';
      btn.innerHTML = `<span>${escapeHtml(c.title)}</span><span style="color:var(--text-muted);font-size:0.76rem">${c.messages.length} msgs</span>`;
      btn.addEventListener('click', () => { el.searchModal.hidden = true; loadChat(c.id); });
      el.quickSearchResults.appendChild(btn);
    });
  }

  function handleVoiceDictation() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return showToast('Tu navegador no soporta dictado por voz');
    const rec = new SR();
    rec.lang = 'es-ES';
    el.voiceBtn.classList.add('recording');
    rec.onresult = (e) => {
      el.promptInput.value += (el.promptInput.value ? ' ' : '') + e.results[0][0].transcript;
      autoResizeTextarea();
      updateSendButtonState();
    };
    rec.onend = () => el.voiceBtn.classList.remove('recording');
    rec.onerror = () => el.voiceBtn.classList.remove('recording');
    try {
      rec.start();
    } catch (_) {
      el.voiceBtn.classList.remove('recording');
      showToast('No se pudo iniciar el dictado. Comprueba los permisos del micrófono.');
    }
  }

  function renderAttachments() {
    el.attachmentsPreview.innerHTML = '';
    el.attachmentsPreview.hidden = pendingAttachments.length === 0;
    pendingAttachments.forEach((file, i) => {
      const chip = document.createElement('div');
      chip.className = 'attachment-chip';
      chip.innerHTML = `<span>📄 ${escapeHtml(file.name)}</span><button title="Quitar">✕</button>`;
      chip.querySelector('button').addEventListener('click', () => {
        pendingAttachments.splice(i, 1);
        renderAttachments();
        updateSendButtonState();
      });
      el.attachmentsPreview.appendChild(chip);
    });
  }

  function autoResizeTextarea() {
    el.promptInput.style.height = 'auto';
    el.promptInput.style.height = Math.min(el.promptInput.scrollHeight, 190) + 'px';
  }

  function updateSendButtonState() {
    if (isGenerating) return;
    el.sendBtn.disabled = !el.promptInput.value.trim() && pendingAttachments.length === 0;
  }

  function togglePopover(target) {
    const willOpen = target.hidden;
    [el.modelSelectorDropdown, el.plusMenu, el.userPopover].forEach(p => p.hidden = true);
    target.hidden = !willOpen;
  }

  function closeMobileSidebar() { el.appShell.classList.remove('mobile-sidebar-open'); }
  function scrollToBottom() { el.chatScroll.scrollTop = el.chatScroll.scrollHeight; }

  function showToast(msg) {
    const t = document.createElement('div');
    t.className = 'toast';
    t.textContent = msg;
    el.toastContainer.appendChild(t);
    setTimeout(() => t.remove(), 3000);
  }

  async function copyText(text, successMessage) {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard API no disponible');
      await navigator.clipboard.writeText(String(text));
      showToast(successMessage);
    } catch (_) {
      showToast('El navegador no permitió copiar al portapapeles.');
    }
  }

  function downloadFile(filename, content) {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    window.setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  function formatMarkdown(text) {
    const codeBlocks = [];
    const links = [];
    const decoded = String(text).replace(/&(#x[0-9a-f]+|#\d+|nbsp|amp|lt|gt|quot|apos);/gi, (entity, code) => {
      const named = { nbsp: ' ', amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" };
      if (code[0] !== '#') return named[code.toLowerCase()] ?? entity;
      const number = code[1].toLowerCase() === 'x' ? parseInt(code.slice(2), 16) : parseInt(code.slice(1), 10);
      try { return Number.isFinite(number) ? String.fromCodePoint(number) : entity; } catch { return entity; }
    });
    let safe = decoded.replace(/```(\w+)?\n([\s\S]*?)```/g, (_, lang = 'code', code) => {
      const idx = codeBlocks.length;
      const cleanCode = code.trimEnd();
      const encoded = encodeURIComponent(cleanCode);
      codeBlocks.push(`
        <div class="code-card">
          <div class="code-card-head">
            <span>${escapeHtml(lang)}</span>
            <div class="code-card-actions">
              <button class="code-mini-btn code-artifact-btn" data-lang="${escapeHtml(lang)}" data-code="${encoded}">Abrir Artifact</button>
              <button class="code-mini-btn code-copy-btn" data-code="${encoded}">Copiar</button>
            </div>
          </div>
          <pre><code>${escapeHtml(cleanCode)}</code></pre>
        </div>
      `);
      return `@@CODEBLOCK_${idx}@@`;
    });

    safe = safe.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (match, label, rawUrl) => {
      try {
        const url = new URL(rawUrl);
        if (url.protocol !== 'http:' && url.protocol !== 'https:') return match;
        const idx = links.length;
        links.push(`<a href="${escapeHtml(url.href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`);
        return `@@MARKDOWNLINK_${idx}@@`;
      } catch {
        return match;
      }
    });

    safe = escapeHtml(safe)
      .replace(/^### (.*)$/gm, '<h3>$1</h3>')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/^\- (.*)$/gm, '<li>$1</li>')
      .replace(/(<li>.*<\/li>\n?)+/g, m => `<ul>${m}</ul>`)
      .replace(/\n\n/g, '</p><p>')
      .replace(/\n/g, '<br>');

    safe = `<p>${safe}</p>`.replace(/<p><\/p>/g, '');
    codeBlocks.forEach((html, i) => { safe = safe.replace(`@@CODEBLOCK_${i}@@`, html); });
    links.forEach((html, i) => { safe = safe.replace(`@@MARKDOWNLINK_${i}@@`, html); });
    return safe;
  }

  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, s => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[s]));
  }

  function lightenHex(hex, pct) {
    const num = parseInt(hex.replace('#', ''), 16);
    const r = Math.min(255, (num >> 16) + pct);
    const g = Math.min(255, ((num >> 8) & 0x00FF) + pct);
    const b = Math.min(255, (num & 0x0000FF) + pct);
    return `#${(1 << 24 | r << 16 | g << 8 | b).toString(16).slice(1)}`;
  }

  function hexToRgba(hex, alpha) {
    const num = parseInt(hex.replace('#', ''), 16);
    return `rgba(${num >> 16}, ${(num >> 8) & 255}, ${num & 255}, ${alpha})`;
  }

  init();
})();
