from .registry import register
"""
knowledge.py — Entity-relation knowledge graph in SQLite.
Persistent structured memory for learned facts, app profiles, and inferred context.
Ported from Omni knowledge_graph.py with cleanup and JSON returns.
"""
import json, logging, os, sqlite3
from collections import deque
from pathlib import Path
from typing import Optional

logger = logging.getLogger("xens.tools.knowledge")

_DB_PATH = Path.home() / ".ainslup" / "knowledge" / "knowledge.db"


class KnowledgeGraph:
    def __init__(self):
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(_DB_PATH)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                type TEXT,
                attributes TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS relations (
                id TEXT PRIMARY KEY,
                from_id TEXT,
                to_id TEXT,
                type TEXT,
                confidence REAL DEFAULT 1.0,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY(from_id) REFERENCES entities(id),
                FOREIGN KEY(to_id) REFERENCES entities(id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_type ON entities(type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_relation_type ON relations(type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_relation_from ON relations(from_id)")
        conn.commit()
        conn.close()

    def add_entity(self, entity_id: str, entity_type: str, attributes: dict):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO entities (id, type, attributes) VALUES (?, ?, ?)",
            (entity_id, entity_type, json.dumps(attributes, default=str)),
        )
        conn.commit()
        conn.close()

    def get_entity(self, entity_id: str) -> Optional[dict]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute("SELECT id, type, attributes FROM entities WHERE id = ?", (entity_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return {"id": row[0], "type": row[1], "attributes": json.loads(row[2])}

    def find_entities(self, entity_type: str, name: str = "") -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        if name:
            cur = conn.execute(
                "SELECT id, type, attributes FROM entities WHERE type = ? AND id LIKE ?",
                (entity_type, f"%{name}%"),
            )
        else:
            cur = conn.execute("SELECT id, type, attributes FROM entities WHERE type = ?", (entity_type,))
        rows = cur.fetchall()
        conn.close()
        return [{"id": r[0], "type": r[1], "attributes": json.loads(r[2])} for r in rows]

    def delete_entity(self, entity_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM relations WHERE from_id = ? OR to_id = ?", (entity_id, entity_id))
        conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
        conn.commit()
        conn.close()

    def add_relation(self, from_id: str, to_id: str, relation_type: str, confidence: float = 1.0):
        rid = f"{from_id}__{relation_type}__{to_id}"
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO relations (id, from_id, to_id, type, confidence) VALUES (?, ?, ?, ?, ?)",
            (rid, from_id, to_id, relation_type, confidence),
        )
        conn.commit()
        conn.close()

    def get_relations(self, from_id: str, relation_type: str = "") -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        if relation_type:
            cur = conn.execute("SELECT to_id, type, confidence FROM relations WHERE from_id = ? AND type = ?", (from_id, relation_type))
        else:
            cur = conn.execute("SELECT to_id, type, confidence FROM relations WHERE from_id = ?", (from_id,))
        rows = cur.fetchall()
        conn.close()
        return [{"to_id": r[0], "type": r[1], "confidence": r[2]} for r in rows]

    def find_path(self, start_id: str, end_id: str, max_depth: int = 4) -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        visited = {start_id}
        queue = deque([(start_id, [])])
        while queue:
            current, path = queue.popleft()
            if current == end_id:
                conn.close()
                return path + [{"entity": current, "relation": "__target__"}]
            if len(path) >= max_depth:
                continue
            cur = conn.execute("SELECT to_id, type FROM relations WHERE from_id = ?", (current,))
            for row in cur.fetchall():
                nid = row[0]
                if nid not in visited:
                    visited.add(nid)
                    queue.append((nid, path + [{"entity": nid, "relation": row[1]}]))
        conn.close()
        return []

    def get_stats(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        ec = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        rc = conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
        conn.close()
        return {"entities": ec, "relations": rc}


_graph: Optional[KnowledgeGraph] = None


def get_graph() -> KnowledgeGraph:
    global _graph
    if _graph is None:
        _graph = KnowledgeGraph()
    return _graph


# ── Tool-callable wrapper functions ─────────────────────────────

@register(name="knowledge_add", description="Store an entity in the knowledge graph.", tier="free")
def knowledge_add(entity_id: str, entity_type: str, attributes: dict) -> str:
    g = get_graph()
    g.add_entity(entity_id, entity_type, attributes)
    return json.dumps({"success": True, "entity_id": entity_id, "type": entity_type})


@register(name="knowledge_get", description="Retrieve an entity from the knowledge graph.", tier="free")
def knowledge_get(entity_id: str) -> str:
    g = get_graph()
    entity = g.get_entity(entity_id)
    if not entity:
        return json.dumps({"error": f"Entity not found: {entity_id}", "success": False})
    return json.dumps({"success": True, "entity": entity})


@register(name="knowledge_find", description="Find entities by type and optional name.", tier="free")
def knowledge_find(entity_type: str, name: str = "") -> str:
    g = get_graph()
    results = g.find_entities(entity_type, name)
    return json.dumps({"success": True, "count": len(results), "results": results})


@register(name="knowledge_relate", description="Create a relation between two entities.", tier="free")
def knowledge_relate(from_id: str, to_id: str, relation_type: str, confidence: float = 1.0) -> str:
    g = get_graph()
    g.add_relation(from_id, to_id, relation_type, confidence)
    return json.dumps({"success": True, "from": from_id, "to": to_id, "type": relation_type})


@register(name="knowledge_query", description="Get relations from an entity.", tier="free")
def knowledge_query(entity_id: str, relation_type: str = "") -> str:
    g = get_graph()
    relations = g.get_relations(entity_id, relation_type)
    return json.dumps({"success": True, "entity_id": entity_id, "count": len(relations), "relations": relations})


@register(name="knowledge_path", description="Find path between two entities in the graph.", tier="free")
def knowledge_path(start: str, end: str, max_depth: int = 4) -> str:
    g = get_graph()
    path = g.find_path(start, end, max_depth)
    return json.dumps({"success": True, "found": len(path) > 0, "path": path})


@register(name="knowledge_stats", description="Get knowledge graph statistics.", tier="free")
def knowledge_stats() -> str:
    g = get_graph()
    stats = g.get_stats()
    return json.dumps({"success": True, **stats})
