import json, os, re, time, math
from typing import Optional
from .registry import register

DATA_DIR = os.path.join(os.path.expanduser("~"), ".xens")
INDEX_FILE = os.path.join(DATA_DIR, "rag_index.json")

def _load_index():
    try:
        if os.path.exists(INDEX_FILE):
            with open(INDEX_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {"documents": [], "vectors": []}

def _save_index(index):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(INDEX_FILE, "w") as f:
        json.dump(index, f, indent=2)

_index = _load_index()
_embeddings_model = None

def _get_embeddings(texts: list[str]) -> list[list[float]]:
    global _embeddings_model
    try:
        if _embeddings_model is None:
            from sentence_transformers import SentenceTransformer
            _embeddings_model = SentenceTransformer("all-MiniLM-L6-v2")
        return _embeddings_model.encode(texts).tolist()
    except ImportError:
        return _tfidf_fallback(texts)
    except Exception:
        return []

def _tfidf_fallback(texts: list[str]) -> list[list[float]]:
    words = set()
    for t in texts:
        words.update(re.findall(r"\w+", t.lower()))
    words = sorted(words)
    word_index = {w: i for i, w in enumerate(words)}
    vectors = []
    for t in texts:
        vec = [0.0] * len(words)
        tokens = re.findall(r"\w+", t.lower())
        for token in tokens:
            if token in word_index:
                vec[word_index[token]] += 1.0
        mag = math.sqrt(sum(v * v for v in vec))
        if mag > 0:
            vec = [v / mag for v in vec]
        vectors.append(vec)
    return vectors

def _cosine_similarity(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    ma = sum(x * x for x in a) ** 0.5
    mb = sum(y * y for y in b) ** 0.5
    if ma == 0 or mb == 0:
        return 0.0
    return dot / (ma * mb)

@register(name="rag_index", description="Indexar texto en el motor RAG para busqueda semantica", parameters={"type": "object", "properties": {"text": {"type": "string", "description": "Texto a indexar"}, "source": {"type": "string", "description": "Fuente del texto"}, "metadata": {"type": "object", "description": "Metadatos opcionales"}}, "required": ["text"]}, tier="premium")
def rag_index(text: str, source: str = "", metadata: dict = None) -> str:
    global _index
    segments = re.split(r"(?<=\n)(?=Usuario:|Asistente:)", text)
    segments = [s.strip() for s in segments if len(s.strip()) > 20]
    if not segments:
        return "Texto muy corto para indexar"
    vectors = _get_embeddings(segments)
    for i, seg in enumerate(segments):
        _index["documents"].append({"text": seg[:1000], "vector": vectors[i] if i < len(vectors) else [], "source": source, "metadata": metadata or {}, "ts": time.time()})
    _index["documents"] = _index["documents"][-500:]
    _save_index(_index)
    return f"Indexados {len(segments)} segmentos"

@register(name="rag_search", description="Busqueda semantica en el indice RAG", parameters={"type": "object", "properties": {"query": {"type": "string", "description": "Consulta"}, "limit": {"type": "integer", "description": "Maximo de resultados"}, "min_score": {"type": "number", "description": "Puntaje minimo (0-1)"}}, "required": ["query"]}, tier="premium")
def rag_search(query: str, limit: int = 5, min_score: float = 0.3) -> str:
    global _index
    if not _index["documents"]:
        return "No hay contenido indexado aun"
    query_vec = _get_embeddings([query])
    if not query_vec:
        return "Error generando embedding"
    query_vec = query_vec[0]
    scored = []
    for doc in _index["documents"]:
        if doc.get("vector"):
            score = _cosine_similarity(query_vec, doc["vector"])
            scored.append((score, doc["text"], doc.get("source", "")))
    scored.sort(key=lambda x: x[0], reverse=True)
    results = [s for s in scored if s[0] >= min_score][:limit]
    if not results:
        return f"Sin resultados para: {query}"
    lines = [f"Resultados ({len(results)}):"]
    for score, text, source in results:
        src = f" [{source}]" if source else ""
        lines.append(f"  [{score:.2f}]{src} {text[:200]}")
    return "\n".join(lines)

@register(name="rag_stats", description="Estadisticas del indice RAG", parameters={"type": "object", "properties": {}, "required": []}, tier="free")
def rag_stats() -> str:
    return f"Indice RAG: {len(_index['documents'])} documentos"

@register(name="semantic_index", description="Alias de rag_index para compatibilidad", parameters={"type": "object", "properties": {"text": {"type": "string", "description": "Texto a indexar"}, "metadata": {"type": "object", "description": "Metadatos opcionales"}}, "required": ["text"]}, tier="premium")
def semantic_index(text: str, metadata: dict = None) -> str:
    return rag_index(text, source="semantic", metadata=metadata)

@register(name="semantic_search", description="Alias de rag_search para compatibilidad", parameters={"type": "object", "properties": {"query": {"type": "string", "description": "Consulta"}, "limit": {"type": "integer", "description": "Maximo resultados"}}, "required": ["query"]}, tier="premium")
def semantic_search(query: str, limit: int = 5) -> str:
    return rag_search(query, limit=limit, min_score=0.3)

@register(name="semantic_stats", description="Estadisticas del indice semantico", parameters={"type": "object", "properties": {}, "required": []}, tier="free")
def semantic_stats() -> str:
    return rag_stats()
