# AINSLUP Web — estado y continuidad

Última actualización: 7 de noviembre de 2026.
Repositorio: `creatorM500/xens-assistant` (rama `main`).
Proyecto local visto en esta sesión: `C:\ainslup\ainslup_assistant`.
Web app: `webapp/` (Render, URL configurada: `https://ainslup-web.onrender.com`).
Backend cloud: Supabase Edge Function `license`, proyecto `tzlbgoydgptlhspzdhfu`.

> No guardar aquí API keys, tokens, service-role keys ni otros secretos. Los secretos viven en Supabase Edge Function Secrets.

## Objetivo del producto

AINSLUP Web debe ser un asistente cloud confiable, con chat, herramientas ejecutadas dentro del mismo turno, búsqueda web con fuentes comprobables, memoria conversacional pertinente y fecha/hora actual correctas. El frontend está en Render y la orquestación/proveedores/tools en la Edge Function de Supabase. La búsqueda web no debe aparentar que se hizo si no se ejecutó ni convertir resultados débiles en hechos.

## Arquitectura y rutas importantes

- `supabase/functions/license/index.ts`: chat, licencia/créditos, proveedores, tool calling, web search, fecha actual y fallbacks.
- `webapp/app/app/page.tsx`: UI de chat, peticiones a Edge Function, reloj/zona horaria del cliente, memoria de conversación y estado de generación.
- La app solicita `tool_mode:true` sin streaming para el flujo de herramientas; el otro flujo puede usar `chat-stream`.
- Supabase Edge Function se despliega con `supabase functions deploy license --project-ref tzlbgoydgptlhspzdhfu`.
- Render despliega el frontend desde `main` (confirmar el servicio/configuración si hay cambios; no asumir que un push ya terminó el deploy).

## Estado entregado recientemente

Commits recientes en `main` (cronología):

- `1903946 filter_irrelevant_search_results_and_date_grounding`: filtra resultados poco pertinentes, divide consultas alternativas, lee páginas y evita sugerencias de búsquedas externas.
- `a4ff7c1 improve_tool_turn_progress_and_followups`: progresos visibles por turno, reconocimiento inicial de seguimientos y error recuperable ante salida vacía.
- `afa3d35 enforce_current_clock_and_evidence_limits`: envía reloj/zona del navegador, fecha temporal prioritaria y respuesta acotada cuando no hay evidencia.
- `6d2766c add_nemotron_super_vl_free_test_fallback`: añade `nvidia/nemotron-3.5-super-vl:free` al array de fallbacks de OpenRouter.
- `510656b continue_fallback_after_provider_balance_error`: hace que errores de proveedor (incluido 402) continúen a los siguientes candidatos, en lugar de cortar la cadena.
- `0821845 fix_mistral_fallback_for_streamed_free_chat`: añade Mistral al final de la cadena del plan Free en streaming, usando `mistral-small-2506` cuando el modelo base no es Mistral.

Todos los commits anteriores se desplegaron a Supabase y se empujaron a `main`. Build Next.js pasó durante una iteración anterior. No se hizo prueba E2E autenticada contra proveedores después de cada cambio.

## Proveedores y modelos configurados (no confundir configuración con disponibilidad)

En `index.ts` aparecen estas claves de proveedor:

- `XENS_OPENROUTER_KEY` — proveedor principal/unificado.
- `XENS_POLLI_KEY` — Pollinations; `POLLI_MODEL` está fijado a `nvidia/nemotron-3-ultra`.
- `XENS_MISTRAL_KEY` — respaldo directo Mistral.

La configuración incluye MiMo Flash como default de Free/Lite, DeepSeek Flash para Pro y MiniMax Flash para Premium. Fallbacks gratuitos de OpenRouter configurados incluyen `nvidia/nemotron-3.5-super-vl:free`, GLM, Nemotron Ultra, Gemma y Nemotron Nano. **No se debe asegurar que un modelo sea gratuito o que un secreto esté configurado sin una comprobación actual de proveedor/Supabase.** OpenRouter mostró ficha del modelo base Nemotron 3.5 Super VL con precios pagados; no se confirmó que la variante `:free` exista. MiMo default tampoco equivale a tarifa $0.

## Problema de herramientas: SIGUE PENDIENTE

El usuario informa que el problema de tools sigue ocurriendo. Los cambios previos no bastan para darlo por resuelto. Investigar y reproducir primero antes de modificar:

1. En `handleWebToolChat` comprobar la secuencia real de llamadas, `tool_choice`, respuesta tool-call y continuación del modelo. El ejecutor directo debe invocar la herramienta, registrar el evento y alimentar el resultado al siguiente turno del modelo.
2. Revisar los nombres y schemas ofrecidos (`WEB_TOOL_SCHEMAS`) frente a los handlers efectivos y el router del frontend. Asegurar que la respuesta final se muestra en el mismo mensaje y que jamás se imprime JSON de tool-call.
3. Comprobar qué endpoint usa realmente cada modo (`/chat` vs `/chat-stream`), en especial búsqueda/visión/adjuntos. Streaming y no-streaming tenían cadenas de fallback distintas; un cambio en una no corrige automáticamente la otra.
4. Seguimientos como “dale”, “verifica” o “hazlo” pueden perder la intención/herramienta previa. Evitar clasificar cualquier palabra “actual/modelo” como search intent y evitar ejecutar búsqueda cuando el usuario solo conversa.
5. Asegurar progreso real, no cosmético: conexión, proveedor, herramienta concreta, ejecución, retorno al modelo y finalización en el mismo turno. No dejar el indicador fijo ni declarar completado antes de la respuesta final.
6. Añadir logs de diagnóstico sin secretos: endpoint, candidato/provider, estado HTTP, nombre de tool, tool-call id, duración y tamaño de salida. Usarlos para localizar dónde se interrumpe la cadena.
7. Preparar pruebas de regresión para tool-call simple, search con fuentes, multi-tool, fallo de proveedor, tool-call JSON textual, respuesta vacía, cambio/cancelación de conversación y seguimiento afirmativo.

## Fallos observados / límites conocidos

- El usuario compartió error literal de Pollinations: cuenta detrás de la API key sin créditos, y enlaces a top-up/quests. Esto indica problema de saldo de la cuenta Pollinations, no de OpenRouter. Se desplegó continuación de fallback en errores 402, pero falta verificar con una petición real que sigue a OpenRouter/Mistral y devuelve respuesta útil.
- Se encontró bug en la ruta de streaming: Mistral no se probaba para Free si el modelo pedido era MiMo. Se corrigió y desplegó `0821845`, pero falta test real que pruebe el fallback.
- La websearch del entorno de desarrollo falló varias veces con HTTP 402. Eso no prueba que la búsqueda del backend AINSLUP esté caída; separar ambos sistemas al diagnosticar.
- Se detectaron respuestas con fecha 2025 y afirmaciones fuertes sobre modelos sin fuentes. El cliente envía `client_now` e `client_timezone`; validar que cada ruta (incluida streaming y herramientas) realmente los transmite y respeta.
- Resultados web irrelevantes (p. ej. páginas que solo contienen “busca”) deben ser descartados. No afirmar inexistencia de modelos por ausencia de resultados.
- El usuario pidió que el flujo de tools ocurra dentro del mismo mensaje y que se muestre lo que AINSLUP hace. Esto sigue siendo criterio de aceptación, no un problema marcado como cerrado.

## Próximos pasos recomendados para retomar AINSLUP Web

1. Reproducir el bug actual de tools con una petición pequeña y guardar request/response/status/logs (secretos redactados).
2. Verificar cuáles secrets están definidos en Supabase sin imprimir sus valores; probar salud/autorización de OpenRouter, Pollinations y Mistral por separado.
3. Corregir la cadena completa tool-call → ejecución → retorno del resultado → respuesta final, tanto streaming como no streaming.
4. Probar fallbacks con HTTP 402/401/429/5xx y confirmar el proveedor/modelo que respondió sin exponer keys.
5. Agregar pruebas unitarias/integración, correr build, desplegar Edge Function/Render según aplique, hacer smoke test y registrar commit/deploy.

## Nueva aplicación principal Desktop (separada de este repo)

El proyecto de escritorio activo está en `C:\mistralv8` (repo `creatorM500/mistral-ai-desktop`), no en este repositorio. La app actual usa `mistral_AI_APP/index.html`, `mistral_AI_APP/app.js`, config `mistral_AI_APP/core/config.js`, servicios `services/mistral.api.js` y `services/websocket.js`, y backend local Flask por defecto en `http://127.0.0.1:5000`. Vite toma `mistral_AI_APP/index.html` como entrada. **Aún no está conectada a AINSLUP Web.**

El repo desktop tiene muchos cambios locales preexistentes sin commitear; no limpiar ni reemplazar archivos existentes. El siguiente trabajo debe diseñar una nueva página principal desktop e integrar AINSLUP Web sin romper la UI/servicios locales: definir primero si será reemplazo de la pantalla actual o una página/modo separado; acordar autenticación segura (no incrustar secretos), contrato API, persistencia de sesión, estado online/offline, permisos desktop y fallback local.

## Criterio para declarar terminado

No dar por arregladas tools o fallbacks solo porque el código compile. Confirmar mediante tests reproducibles qué proveedor se invocó, qué herramienta se ejecutó, que la respuesta final apareció en el mismo turno, y que un error upstream no se filtró crudo al usuario cuando otro proveedor podía responder.
