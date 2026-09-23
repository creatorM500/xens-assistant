/* ============================================================
   supabase-config.example.js — Plantilla Supabase Auth
   ------------------------------------------------------------
   1. En Supabase dashboard -> Authentication -> Providers activa
      Email/Password, Google y GitHub.
   2. Copia Project URL y anon key en:
      Project Settings -> API -> Project URL / anon public key
   3. Renombra este archivo a supabase-config.js con tus datos.
   4. En el motor agrega en ~/.xens/config.json o env:
        env SUPABASE_JWT_SECRET = <JWT Secret de Project Settings -> API>
      o config.json: { "supabase": { "jwt_secret": "..." } }

   SIN ESTE ARCHIVO el cliente funciona en modo local
   (local-auth.js). Con él, login real vía Supabase Auth.
   ============================================================ */

window.SUPABASE_CONFIG = {
  url: "https://tzlbgoydgptlhspzdhfu.supabase.co",
  anonKey: "TU_ANON_KEY_AQUI",
};
