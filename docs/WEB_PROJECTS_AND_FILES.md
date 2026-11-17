# AINSLUP Web: proyectos y análisis de archivos

## Funciones incluidas en esta entrega

- Extrae texto de PDF seleccionables en el navegador; no sube el PDF al servidor durante la extracción.
- Analiza PDFs de hasta 20 MB y 100 páginas. Los PDFs escaneados requieren OCR, que aún no está incluido.
- Calcula un resumen local de CSV: hasta 5.000 filas y 40 columnas, con vacíos, estadísticas numéricas, valores frecuentes y una pequeña muestra.
- Permite crear proyectos privados y guardar hasta 20 documentos por proyecto (PDF, TXT, Markdown, CSV, JSON o LOG; 20 MB y 300.000 caracteres por archivo).
- Busca fragmentos relevantes con PostgreSQL Full Text Search y los adjunta al turno actual; el modelo recibe solo los extractos recuperados, no el documento completo.
- Las tablas usan RLS por `auth.uid()`; la función de búsqueda es `SECURITY INVOKER`, limita la búsqueda al propietario y devuelve extractos acotados.
- Los archivos y fragmentos recuperados se tratan como contenido no confiable, no como instrucciones.

## Activar en Supabase

Antes de desplegar la nueva web, aplicar una vez:

`supabase/migrations/20261116000000_projects_knowledge.sql`

La migración crea las tablas `ainslup_projects` y `ainslup_project_documents`, sus políticas RLS, límite de documentos e índice/función de búsqueda. No cambia tablas existentes.

## Límites conocidos

- El análisis numérico de CSV se ejecuta en el navegador; el modelo recibe el resumen y una muestra, no un entorno arbitrario de ejecución de código.
- La extracción de PDF no hace OCR.
- La recuperación de proyectos usa búsqueda de texto, no embeddings semánticos.
- Un usuario debe seleccionar explícitamente el proyecto activo; al cambiar de cuenta o recargar, no se mantiene selección activa.
- Los documentos de proyecto se guardan como texto extraído en Supabase y se envían fragmentos al proveedor LLM al consultar el proyecto. No adjuntar información que no se quiera procesar en esos servicios.
