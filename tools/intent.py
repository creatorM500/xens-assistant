from .registry import register
"""
intent.py — Intent detection + message classification.
Recognizes user intents and classifies messages into chat/assistant/full_capacity modes.
"""
from . import modes
from .modes import _classify_message
import json, logging, re
from typing import Optional

logger = logging.getLogger("xens.tools.intent")

_INTENT_PATTERNS: list[tuple[str, re.Pattern, float]] = []
_PLUGIN_INTENTS: dict[str, list[str]] = {}
_FASTPATH_MAP: dict[str, str] = {}


def register_intent(name: str, phrases: list[str]):
    _PLUGIN_INTENTS.setdefault(name, []).extend(phrases)


_INTENTS_RAW = {
    "google": ["busca en google", "googlea", "busca información sobre", "quiero saber sobre", "busca noticias de"],
    "youtube": ["pon música", "ponme música", "busca en youtube", "quiero ver un video de", "ponme algo de"],
    "reddit": ["busca en reddit", "qué dicen en reddit sobre", "opiniones sobre"],
    "research": ["investiga", "busca información detallada sobre", "quiero aprender sobre", "explícame cómo", "explicame como", "guía para", "guia para"],
    "open": ["abre", "abre la página de", "entra a", "navega a", "ejecuta", "lanza"],
    "system_status": ["qué hora es", "cómo está el sistema", "cuánta ram tengo", "dime la hora", "hora actual"],
    "translate": ["traduce al", "traducir al", "cómo se dice", "cómo se escribe en"],
    "weather": ["qué tiempo hace", "cómo está el clima", "clima en", "tiempo en", "temperatura en"],
    "calculate": ["calcula", "cuánto es", "cuanto es", "resuelve"],
    "reminder": ["recuerda que", "recuerda hacer", "pon un recordatorio", "avísame que", "crea un recordatorio"],
    "note": ["guarda esto", "escribe una nota", "anota", "recuerda esto", "nota:"],
    "learn": ["recuerda que", "mi nombre es", "me llamo", "me gusta"],
    "chat": ["cuéntame", "háblame de", "qué opinas", "cómo estás", "dame un consejo", "qué es", "cómo funciona"],
    "list_windows": ["lista las ventanas", "muestra las ventanas", "qué ventanas hay abiertas"],
    "screenshot": ["captura la pantalla", "toma una captura de pantalla", "screenshot", "pantallazo"],
    "read_screen": ["lee la pantalla", "qué hay en la pantalla", "qué texto hay", "qué dice la pantalla"],
    "describe_desktop": ["describe el escritorio", "cómo está el escritorio", "qué está pasando en el escritorio", "qué hay abierto"],
}

_FASTPATH_MAP = {
    "system_status": "get_env_info",
    "weather": "get_weather",
    "calculate": "calculate",
    "translate": "translate",
    "screenshot": "screenshot",
}


def _build_patterns():
    _INTENT_PATTERNS.clear()
    for intent, phrases in _INTENTS_RAW.items():
        for phrase in phrases:
            _INTENT_PATTERNS.append((intent, re.compile(re.escape(phrase), re.IGNORECASE), 0.85))
    for intent, phrases in _PLUGIN_INTENTS.items():
        for phrase in phrases:
            _INTENT_PATTERNS.append((intent, re.compile(re.escape(phrase), re.IGNORECASE), 0.80))


_build_patterns()

# ── TF-IDF fallback (optional) ──────────────────────────────────

_tfidf = None
_tfidf_matrix = None
_tfidf_labels = None


def _init_tfidf():
    global _tfidf, _tfidf_matrix, _tfidf_labels
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        import numpy as np
        all_texts, all_labels = [], []
        for intent, phrases in _INTENTS_RAW.items():
            for p in phrases:
                all_texts.append(p)
                all_labels.append(intent)
        for intent, phrases in _PLUGIN_INTENTS.items():
            for p in phrases:
                all_texts.append(p)
                all_labels.append(intent)
        if not all_texts:
            return
        _tfidf = TfidfVectorizer(stop_words=["el", "la", "de", "en", "un", "y", "a", "que", "es"])
        _tfidf_matrix = _tfidf.fit_transform(all_texts)
        _tfidf_labels = all_labels
    except Exception:
        pass


_init_tfidf()

# ── Keyword fallback ────────────────────────────────────────────

_FILE_KEYWORDS = {"archivo", "carpeta", "documento", "contenido", ".py", ".js", ".json", ".md", ".txt"}
_FILE_ACTIONS = {"lee", "lista", "muestra", "busca", "encuentra", "localiza"}


def _fallback_keyword(text: str) -> tuple[Optional[str], float]:
    t = text.lower().strip()
    if _FILE_KEYWORDS & set(t.split()) and any(a in t for a in _FILE_ACTIONS):
        return "file_management", 0.9
    if any(p in t for p in ["ponme", "pon musica", "busca en youtube"]):
        return "youtube", 0.9
    if "busca" in t or "googlea" in t:
        return "google", 0.9
    if t.startswith("abre") or t.startswith("ábre"):
        return "open", 0.95
    if "investiga" in t:
        return "research", 0.9
    if any(p in t for p in ["qué hora", "dime la hora", "hora actual", "batería", "cpu", "ram"]):
        return "system_status", 0.9
    if "clima" in t or "tiempo" in t:
        return "weather", 0.85
    if "recuerda" in t or "recordatorio" in t:
        return "reminder", 0.85
    if "nota" in t or "anota" in t:
        return "note", 0.85
    for intent, phrases in _PLUGIN_INTENTS.items():
        if any(p in t for p in phrases):
            return intent, 0.9
    return None, 0.0


_GREETINGS = frozenset({"hola", "holaa", "buenas", "hey", "hello", "hi", "qué tal", "qué onda", "cómo estás"})


@register(name="detect_intent", description="Detect user intent from a message.", tier="free", internal=True)
def detect_intent(text: str, threshold: float = 0.75) -> tuple[str, float]:
    t = text.lower().strip()
    if t in _GREETINGS or t.rstrip("!?.") in _GREETINGS:
        return "chat", 1.0
    if len(t.split()) <= 2 and not any(p in t for p in ["abre", "busca", "pon", "investiga", "lee", "lista"]):
        return "chat", 0.6

    best_intent, best_conf = None, 0.0
    for intent, pattern, conf in _INTENT_PATTERNS:
        if pattern.search(t) and conf > best_conf:
            best_intent, best_conf = intent, conf
    if best_intent and best_conf >= threshold:
        return best_intent, best_conf

    if _tfidf is not None and _tfidf_matrix is not None:
        try:
            vec = _tfidf.transform([t])
            from sklearn.metrics.pairwise import cosine_similarity
            import numpy as np
            sims = cosine_similarity(vec, _tfidf_matrix)[0]
            idx = int(np.argmax(sims))
            conf = float(sims[idx])
            if conf >= threshold:
                return _tfidf_labels[idx], round(conf, 4)
        except Exception:
            pass

    intent, conf = _fallback_keyword(text)
    if intent and conf >= threshold:
        return intent, conf

    return "chat", 0.5


@register(name="extract_argument", description="Extract the argument/parameter from a message for a given intent.", tier="free", internal=True)
def extract_argument(text: str, intent: str) -> str:
    t = text.strip()
    patterns = {
        "google": [r"busca en google\s+(.+)", r"googlea\s+(.+)", r"busca información sobre\s+(.+)"],
        "youtube": [r"pon música\s+(.+)", r"ponme\s+(.+)", r"busca en youtube\s+(.+)"],
        "research": [r"investiga\s+(.+)", r"explícame\s+(.+)", r"explicame\s+(.+)", r"dame información sobre\s+(.+)"],
        "open": [r"abre\s+(.+)", r"entra a\s+(.+)", r"navega a\s+(.+)", r"lanza\s+(.+)"],
        "weather": [r"clima en\s+(.+)", r"tiempo en\s+(.+)", r"cómo está el clima en\s+(.+)"],
        "calculate": [r"calcula\s+(.+)", r"cuánto es\s+(.+)", r"cuanto es\s+(.+)"],
        "translate": [r"traduce al\s+(.+)", r"cómo se dice\s+(.+)", r"cómo se escribe en\s+(.+)"],
        "reminder": [r"recuerda\s+(.+)", r"avísame\s+(.+)", r"crea un recordatorio\s+(.+)"],
        "note": [r"guarda esto\s+(.+)", r"anota\s+(.+)", r"nota:\s*(.+)"],
    }
    for pat in patterns.get(intent, []):
        m = re.search(pat, t, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return t


@register(name="try_fastpath", description="Try to resolve a message via fast-path (no LLM, returns tool name or null).", tier="free", internal=True)
def try_fastpath(text: str) -> Optional[str]:
    intent, conf = detect_intent(text, threshold=0.9)
    if conf < 0.9:
        return None
    return _FASTPATH_MAP.get(intent)


def register_fastpath(intent_name: str, tool_name: str):
    _FASTPATH_MAP[intent_name] = tool_name


@register(name="list_fastpath_intents", description="List all registered fast-path intent→tool mappings.", tier="free", internal=True)
def list_fastpath_intents() -> str:
    return json.dumps({"success": True, "fastpaths": _FASTPATH_MAP})

@register(name="classify", description="Classify a message into the appropriate mode (chat/assistant/full_capacity).", tier="free", internal=True)
def classify(text: str) -> str:
    mode = modes._current_mode
    if mode == "auto":
        return _classify_message(text)
    return mode
