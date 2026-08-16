/* ============================================================
   auth.js — Capa de autenticación con Firebase (modo nube)
   ------------------------------------------------------------
   Se carga SOLO cuando firebase-config.js existe y el SDK de
   Firebase llegó a cargar (ver login.html). En modo local (sin
   firebase-config.js) esta capa no hace nada: local-auth.js
   ya expone window.XensAuth con la misma API.

   Configuración: firebase-config.js debe definir
     window.FIREBASE_CONFIG = { apiKey, authDomain, projectId, ... }

   Expone window.XensAuth (sobrescribe la versión local):
     onChange(cb) -> cb(user | null)
     loginWithEmail(email, password)
     registerWithEmail(email, password, name)
     loginWithGoogle()  /  loginWithGithub()
     resetPassword(email)
     logout()
     refresh()
   ============================================================ */

(() => {
  "use strict";

  if (typeof window.FIREBASE_CONFIG === "undefined" || !window.FIREBASE_CONFIG) {
    return; // Sin configuración: se queda el modo local (local-auth.js)
  }

  function init() {
    if (!window.firebase || !window.firebase.auth) {
      return false; // El SDK todavía no está; login.js reintentará
    }
    try {
      const app = window.firebase.initializeApp(window.FIREBASE_CONFIG);
      const auth = app.auth();

      const makeUser = (fbUser) => {
        if (!fbUser) return null;
        return {
          uid: fbUser.uid,
          displayName: fbUser.displayName || fbUser.email || "Usuario",
          email: fbUser.email || null,
          photoURL: fbUser.photoURL || null,
        };
      };

      const handleError = (err) => {
        const e = new Error(err && err.message ? err.message : "Error de autenticación");
        e.code = err && err.code ? err.code : "auth/unknown";
        throw e;
      };

      window.XensAuth = {
        onChange(cb) {
          auth.onAuthStateChanged((fbUser) => cb(makeUser(fbUser)));
        },
        async refresh() {
          return makeUser(auth.currentUser);
        },
        async getToken() {
          const u = auth.currentUser;
          if (!u) return null;
          try {
            return await u.getIdToken(true);
          } catch (err) {
            console.warn("No se pudo obtener el token:", err);
            return null;
          }
        },
        async loginWithEmail(email, password) {
          try {
            await auth.signInWithEmailAndPassword(email, password);
          } catch (err) {
            handleError(err);
          }
        },
        async registerWithEmail(email, password, name) {
          try {
            const cred = await auth.createUserWithEmailAndPassword(email, password);
            if (name && cred.user) {
              try {
                await cred.user.updateProfile({ displayName: name });
              } catch (err) {
                console.warn("No se pudo guardar el nombre:", err);
              }
            }
          } catch (err) {
            handleError(err);
          }
        },
        async loginWithGoogle() {
          try {
            const provider = new window.firebase.auth.GoogleAuthProvider();
            await auth.signInWithPopup(provider);
          } catch (err) {
            handleError(err);
          }
        },
        async loginWithGithub() {
          try {
            const provider = new window.firebase.auth.GithubAuthProvider();
            await auth.signInWithPopup(provider);
          } catch (err) {
            handleError(err);
          }
        },
        async resetPassword(email) {
          try {
            await auth.sendPasswordResetEmail(email);
          } catch (err) {
            handleError(err);
          }
        },
        async logout() {
          try {
            await auth.signOut();
          } catch (err) {
            handleError(err);
          }
        },
      };
      return true;
    } catch (err) {
      console.error("No se pudo inicializar Firebase Auth:", err);
      return false;
    }
  }

  init();
})();