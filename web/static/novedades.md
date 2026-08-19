# Novedades — Xens Assistant

## v20260819 — Cuentas aisladas y ahorro de contexto

- **Memoria por cuenta**: cada usuario (login con Google) tiene su propio perfil, hechos y aprendizaje — la cuenta A no ve lo de la cuenta B, ni el modo local. Mismo uid en cualquier dispositivo → mismo perfil y créditos.
- **Ahorro de tokens**: Xens ya no acumula schemas de herramientas sin límite. El descubrimiento ahora es LRU (las menos usadas se liberan solas) y hay una herramienta **run_any_tool** que ejecuta CUALQUIER tool por nombre sin esperar un turno de descubrimiento. Los resultados de herramientas se truncan al entrar al contexto.
- **Capturas de pantalla en el chat**: cuando Xens toma una screenshot (pantalla o browser), la imagen se muestra directamente en la conversación.
- **Robustez de conexión**: una conexión WebSocket muerta ya no puede congelar el servidor (lock de envío por conexión + timeout de guardia).
- **Suite de tests** en `tests/`: perfil por cuenta, descubrimiento LRU, run_any_tool, tareas, disparadores y créditos.

## v20260818 — Disparadores proactivos

- **Disparadores automáticos** (plan Pro/Premium): pedile "cada 30 minutos revisá mi bandeja" o "todas las mañanas a las 9 resumí mis notas" y Xens lo hace solo, sin que se lo recuerdes. También puede actuar cuando termina una tarea: "cuando termine de compilar, avisame".
- **Control de costos**: cada disparo presupuesta Xens Credits; podés limitar los disparos por día y elegir que solo actúe mientras estás conectado. Los eventos llegan como notas de sistema.
- Administralos con "¿qué disparadores tengo?" (list_triggers) y "eliminá el disparador X" (delete_trigger).

## v20260817 — Tareas en segundo plano

- **La conversación ya no se bloquea con la ejecución**: mientras Xens procesa una tarea larga (código, web, archivos), podés seguir escribiéndole; cada respuesta corre en su propia burbuja y todo llega ordenado.
- **Tareas en segundo plano** (plan Pro/Premium): pedile "lanza una tarea: …" y Xens sigue trabajando autónomamente mientras vos chateás. Consultá el avance con "¿cómo va la tarea?" (task_status), mandale más instrucciones o cancelala.
- Los eventos de tarea aparecen como notas de sistema y los resultados se resumen al completarse.

## v20260811 (b721122)

Esta versión trae:

- **Suite de video y audio**: Xens ahora corta, une, convierte, cambia velocidad, extrae audio, genera GIFs y miniaturas de tus videos. FFmpeg se instala automáticamente la primera vez (con tu permiso).
- **Descargas de video** con yt-dlp desde YouTube y otras plataformas.
- **Menú de conversaciones** (botón de tres puntos): compartir como .txt, fijar, cambiar nombre y eliminar con papelera de 30 días (recuperable).
- **Búsqueda de conversaciones** y atajo **Ctrl+K** para iniciar chat.
- **UI renovada**: respuestas con markdown (tablas, código, listas), adjuntos dentro del cuadro de texto y sugerencias de inicio rápido.
- **Prueba gratuita de 300 chats** en un solo contador, sin confusión de límites.