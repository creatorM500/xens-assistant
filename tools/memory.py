import json, time, math, logging
from pathlib import Path
from .registry import register

logger = logging.getLogger("xens.tools.memory")
STORE = Path.home() / ".xens" / "memory.json"

def _load():
    if STORE.exists():
        try: return json.loads(STORE.read_text(encoding="utf-8"))
        except: return []
    return []

def _save(data):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def _cos(a,b):
    dot=sum(x*y for x,y in zip(a,b))
    na=math.sqrt(sum(x*x for x in a)); nb=math.sqrt(sum(x*x for x in b))
    return dot/(na*nb) if na and nb else 0

@register(name="remember", description="Remember a fact for later recall.", parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}, tier="free")
def remember(text: str) -> str:
    if not text or not text.strip():
        return json.dumps({"error": "text required", "success": False})
    data=_load()
    # embedding opcional
    emb=None
    try:
        from ..llm.factory import create_provider
        from ..core.config import config
        import asyncio
        prov=create_provider(config)
        try:
            emb=asyncio.run(prov.get_embedding(text))
        except RuntimeError:
            emb=asyncio.new_event_loop().run_until_complete(prov.get_embedding(text))
    except Exception as e:
        logger.debug("embedding failed: %s", e)
    data.append({"text": text.strip(), "time": time.time(), "embedding": emb})
    # cap 500
    if len(data)>500: data=data[-500:]
    _save(data)
    return json.dumps({"success": True, "remembered": text[:100]})

@register(name="recall", description="Recall memories relevant to a query.", parameters={"type": "object", "properties": {"query": {"type": "string"}, "k": {"type": "integer"}}, "required": ["query"]}, tier="free")
def recall(query: str, k: int = 5) -> str:
    data=_load()
    if not data:
        return json.dumps({"success": True, "results": [], "message": "No memories yet."})
    # si no hay embeddings, fallback a substring
    q_emb=None
    try:
        from ..llm.factory import create_provider
        from ..core.config import config
        import asyncio
        prov=create_provider(config)
        try:
            q_emb=asyncio.run(prov.get_embedding(query))
        except RuntimeError:
            q_emb=asyncio.new_event_loop().run_until_complete(prov.get_embedding(query))
    except: pass
    scored=[]
    for item in data:
        if q_emb and item.get("embedding"):
            try: score=_cos(q_emb, item["embedding"])
            except: score=0
        else:
            score=1 if query.lower() in item["text"].lower() else 0
        scored.append((score, item))
    scored.sort(key=lambda x: -x[0])
    top=[s[1]["text"] for s in scored[:max(1,min(k,10))] if s[0]>0]
    if not top:
        top=[s[1]["text"] for s in scored[:3]]
    return json.dumps({"success": True, "results": top})
