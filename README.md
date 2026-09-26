# Ainslup Assistant

Asistente de escritorio (JARVIS-class) con más de 120 herramientas que se ejecutan localmente, sin necesidad de internet para la mayoría de funciones.

## Estado actual

- **187 tools registradas**, 123 disponibles en el plan gratuito (64 internas)
- Consola CLI con comandos de prueba directa de herramientas: `/test <tool>`, `/tools`, `/tier`, `/limits`
- Sistema de planes por niveles (free / pro / premium) con límite diario de peticiones
- Enrutador multi-proveedor de LLM: Mistral, OpenAI y OpenRouter (Claude/Gemini/DeepSeek)
- Servidor web local integrado
- Empaquetado en `.exe` (PyInstaller) y probado con herramientas reales del sistema

## Comandos de consola

```
/help                      lista de comandos
/tools [filtro]            herramientas disponibles
/test <tool> [json]        ejecuta una herramienta sin usar IA
/tier [free|pro|premium]   ver o cambiar el plan
/limits                    consumo diario por plan
/providers                 modelos configurados
/config                    ruta del archivo de configuración
/profile                   perfil de usuario
/clear                     limpia pantalla
/quit                      salir
```

## Configuración del chat (opcional)

Crea `~/.ainslup/config.json`:

```json
{
  "llm": {
    "mistral": { "api_key": "TU_CLAVE" }
  }
}
```

O define `MISTRAL_API_KEY` como variable de entorno. Sin clave, el chat no responde pero todas las herramientas se pueden probar con `/test`.

## Desarrollo

```bash
python -m ainslup_assistant --check --no-web   # diagnóstico
python -m ainslup_assistant --no-web           # modo consola
python -m PyInstaller Ainslup.spec             # build del .exe
```

## Arquitectura

- `tools/` — 40+ módulos de herramientas (sistema, archivos, email, voz, visión, RAG, web, automatización, IA...)
- `core/` — chat CLI, configuración, límites, niveles, actualizador
- `llm/` — clientes Mistral/OpenAI/OpenRouter y enrutador por plan
- `memory/` — sesiones y perfil de usuario persistente
- `web/` — servidor web local
- `ui/` — interfaces de escritorio

Datos locales del usuario en `~/.ainslup/`.