/* ============================================================
   firebase-config.example.js — Plantilla para el modo cuenta
   ------------------------------------------------------------
   PASOS PARA ACTIVAR CUENTAS (modo SaaS):
   1. Crea un proyecto en https://console.firebase.google.com/
   2. Agrega una app Web (</>) y copia la config que Firebase te da.
   3. Activa Authentication -> Sign-in method: Email/Password,
      Google y GitHub.
   4. Renombra este archivo a  firebase-config.js  con tus datos.
   5. En el motor (core/config.py o ~/.xens/config.json) agrega:
         "firebase": { "project_id": "TU-PROJECT-ID" }
      para que el motor valide los tokens (mismo project id que
      el campo projectId de abajo).

   SIN ESTE ARCHIVO el cliente funciona en modo local (la máquina
   es el usuario); con él, login/registro real por cuenta.
   ============================================================ */

window.FIREBASE_CONFIG = {
  apiKey: "AIzaSyXXXXXXX",
  authDomain: "tu-proyecto.firebaseapp.com",
  projectId: "tu-proyecto",
  storageBucket: "tu-proyecto.appspot.com",
  messagingSenderId: "000000000000",
  appId: "1:000000000000:web:xxxxxxxxxxxx",
};