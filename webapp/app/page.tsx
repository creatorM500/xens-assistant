const cards = [
  ["Trabaja con tus archivos", "Analiza documentos y proyectos que tú eliges compartir."],
  ["Modelos optimizados", "AINSLUP elige modelos según la tarea, coste y disponibilidad."],
  ["Control transparente", "Mira qué se procesa, cuánto consume y qué acción se propone."],
];
const structuredData = { "@context": "https://schema.org", "@type": "SoftwareApplication", name: "AINSLUP", applicationCategory: "BusinessApplication", operatingSystem: "Web", description: "Asistente de inteligencia artificial para conversar, analizar, investigar y terminar tareas.", offers: { "@type": "Offer", price: "0", priceCurrency: "USD" }, brand: { "@type": "Brand", name: "AINSLUP" } };

export default function Home() {
  return <main><script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }} />
    <nav className="nav"><b>AINSLUP</b><div><a href="#features">Funciones</a><a href="#privacy">Privacidad</a><a className="button ghost" href="/login">Iniciar sesión</a></div></nav>
    <section className="hero"><span className="eyebrow">IA para pensar y terminar tareas</span><h1>Un asistente que trabaja contigo, no solo responde.</h1><p>Conversa, analiza archivos, investiga y convierte instrucciones en resultados. Tú mantienes el control.</p><div className="actions"><a className="button" href="/login?mode=register">Empezar gratis</a><a className="button ghost" href="#demo">Ver cómo funciona</a></div><div id="demo" className="demo"><div className="bar">AINSLUP Web <span>● conectado</span></div><div className="bubble user">Revisa este proyecto y dime qué debo corregir.</div><div className="bubble assistant"><b>He encontrado 3 puntos para revisar.</b><br/>Puedo analizar los archivos que selecciones y preparar los cambios antes de pedirte confirmación.</div><div className="input">Escribe una tarea… <b>➤</b></div></div></section>
    <section id="features" className="section"><h2>Útil desde la primera conversación</h2><div className="grid">{cards.map(([title, text]) => <article key={title}><i>✦</i><h3>{title}</h3><p>{text}</p></article>)}</div></section>
    <section id="privacy" className="privacy"><div><span className="eyebrow">Privacidad primero</span><h2>Tus datos no son una caja negra.</h2><p>Te informamos qué proveedor procesa cada tarea. El acceso a herramientas sensibles requiere permisos y confirmación.</p></div><div className="checks"><p>✓ Historial y eliminación de datos</p><p>✓ Créditos y consumo visibles</p><p>✓ Modo seguro y permisos</p></div></section>
    <footer><b>AINSLUP</b><span>© 2026 SvY Teck · <a href="/privacy">Privacidad</a> · <a href="/terms">Términos</a></span></footer>
  </main>;
}
