/* ============================================================
   local-db.js — Historial local de conversaciones (localStorage)
   ------------------------------------------------------------
   Sustituye a la capa de Supabase en el cliente local: guarda
   conversaciones y mensajes en el navegador para que los
   "Recientes" sobrevivan al reinicio.

   Expone la misma API que app.js espera de window.XensDB:
     listConversations, createConversation, saveMessage,
     listMessages, ensureProfile, incrementMessageCount

   NOTA: el plan y el contador NO vienen de aquí (local: true);
   el motor (/api/profile + licencia) es la fuente autoritativa.
   ============================================================ */

(() => {
  "use strict";

  const PREFIX = "xens.local";
  const MAX_CONVERSATIONS = 50;
  const MAX_MESSAGES = 300;
  const MAX_TRASH = 30;
  const TRASH_DAYS = 30;

  function read(key, fallback) {
    try {
      const raw = localStorage.getItem(PREFIX + "." + key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (err) {
      return fallback;
    }
  }

  function write(key, value) {
    try {
      localStorage.setItem(PREFIX + "." + key, JSON.stringify(value));
    } catch (err) {
      console.error("localStorage lleno:", err);
    }
  }

  function newId() {
    return "c-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  }

  function getConversations() {
    return read("conversations", []);
  }

  function saveConversations(list) {
    write("conversations", list.slice(-MAX_CONVERSATIONS));
  }

  function getTrash() {
    return read("trash", []);
  }

  function saveTrash(list) {
    write("trash", list.slice(-MAX_TRASH));
  }

  function getMessages(conversationId) {
    return read("messages." + conversationId, []);
  }

  function saveMessages(conversationId, msgs) {
    write("messages." + conversationId, msgs.slice(-MAX_MESSAGES));
  }

  function purgeExpiredTrash() {
    const now = Date.now();
    const cutoff = now - TRASH_DAYS * 86400000;
    const trash = getTrash();
    const kept = [];
    let purged = 0;
    trash.forEach((conv) => {
      const deletedAt = new Date(conv.deleted_at || 0).getTime();
      if (deletedAt && deletedAt < cutoff) {
        purged += 1;
        localStorage.removeItem(PREFIX + ".messages." + conv.id);
      } else {
        kept.push(conv);
      }
    });
    if (purged > 0) saveTrash(kept);
    return purged;
  }

  window.XensDB = {
    local: true,

    /** El perfil/plan vienen del motor; aquí no se sobreescribe nada */
    async ensureProfile() {
      return null;
    },

    async listConversations(_uid, limit = 20) {
      purgeExpiredTrash();
      return getConversations()
        .filter((c) => !c.deleted_at)
        .sort((a, b) => {
          if (!!a.pinned !== !!b.pinned) return a.pinned ? -1 : 1;
          return String(b.updated_at).localeCompare(String(a.updated_at));
        })
        .slice(0, limit);
    },

    async listTrash() {
      purgeExpiredTrash();
      return getTrash().sort((a, b) =>
        String(b.deleted_at).localeCompare(String(a.deleted_at))
      );
    },

    async togglePin(conversationId) {
      const list = getConversations();
      const conv = list.find((c) => c.id === conversationId);
      if (conv) {
        conv.pinned = !conv.pinned;
        saveConversations(list);
      }
      return conv ? conv.pinned : false;
    },

    async renameConversation(conversationId, title) {
      const list = getConversations();
      const conv = list.find((c) => c.id === conversationId);
      if (conv) {
        conv.title = (title || "Conversación").slice(0, 60);
        conv.updated_at = new Date().toISOString();
        saveConversations(list);
      }
      return conv || null;
    },

    async trashConversation(conversationId) {
      const list = getConversations();
      const idx = list.findIndex((c) => c.id === conversationId);
      if (idx === -1) return null;
      const [conv] = list.splice(idx, 1);
      conv.deleted_at = new Date().toISOString();
      conv.pinned = false;
      saveConversations(list);
      const trash = getTrash();
      trash.push(conv);
      saveTrash(trash);
      return conv;
    },

    async restoreConversation(conversationId) {
      const trash = getTrash();
      const idx = trash.findIndex((c) => c.id === conversationId);
      if (idx === -1) return null;
      const [conv] = trash.splice(idx, 1);
      delete conv.deleted_at;
      saveTrash(trash);
      const list = getConversations();
      list.push(conv);
      saveConversations(list);
      return conv;
    },

    async deleteForever(conversationId) {
      const trash = getTrash();
      const kept = trash.filter((c) => c.id !== conversationId);
      saveTrash(kept);
      localStorage.removeItem(PREFIX + ".messages." + conversationId);
      return true;
    },

    async createConversation(_uid, title) {
      const conv = {
        id: newId(),
        firebase_uid: _uid,
        title: (title || "Nueva conversación").slice(0, 60),
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      const list = getConversations();
      list.push(conv);
      saveConversations(list);
      return conv;
    },

    async saveMessage(conversationId, role, content) {
      const list = getConversations();
      const conv = list.find((c) => c.id === conversationId);
      if (conv) {
        conv.updated_at = new Date().toISOString();
        saveConversations(list);
      }
      const msgs = getMessages(conversationId);
      msgs.push({
        id: newId(),
        conversation_id: conversationId,
        role,
        content,
        created_at: new Date().toISOString(),
      });
      saveMessages(conversationId, msgs);
    },

    async listMessages(conversationId) {
      return getMessages(conversationId);
    },

    /** Elimina el último mensaje de un rol (para rehacer/editar respuestas) */
    async deleteLastMessage(conversationId, role) {
      const msgs = getMessages(conversationId);
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].role === role) {
          msgs.splice(i, 1);
          saveMessages(conversationId, msgs);
          return true;
        }
      }
      return false;
    },

    /** Reemplaza el contenido del último mensaje de un rol (mensaje editado) */
    async updateLastMessage(conversationId, role, content) {
      const msgs = getMessages(conversationId);
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].role === role) {
          msgs[i].content = content;
          saveMessages(conversationId, msgs);
          return true;
        }
      }
      return false;
    },

    /** El contador lo lleva el motor; no-op aquí */
    async incrementMessageCount() {
      return null;
    },
  };
})();
