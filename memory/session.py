import json, time, logging
from pathlib import Path

logger = logging.getLogger("xens.memory")

MEMORY_DIR = Path.home() / ".ainslup" / "sessions"
_SAVE_DEBOUNCE = 3.0

class Session:
    def __init__(self, session_id="default"):
        self.session_id = session_id
        self.messages = []
        self.summary = ""
        self.created = time.time()
        self.updated = time.time()
        self._dir = MEMORY_DIR
        self._path = self._dir / f"{session_id}.json"
        self._dirty = False
        self._last_save = 0.0
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                with open(self._path) as f:
                    data = json.load(f)
                    self.messages = data.get("messages", [])
                    self.summary = data.get("summary", "")
                    self.created = data.get("created", self.created)
                    self.updated = data.get("updated", self.updated)
            except:
                self.messages = []

    def save(self):
        if not self._dirty:
            return
        now = time.time()
        if now - self._last_save < _SAVE_DEBOUNCE:
            return
        self._flush()

    def _flush(self):
        self._dir.mkdir(parents=True, exist_ok=True)
        self.updated = time.time()
        try:
            with open(self._path, "w") as f:
                json.dump({
                    "session_id": self.session_id,
                    "messages": self.messages[-100:],
                    "summary": self.summary,
                    "created": self.created,
                    "updated": self.updated,
                }, f, indent=2)
            self._dirty = False
            self._last_save = time.time()
        except:
            logger.exception("Session save failed")

    def add(self, role, content):
        self.messages.append({"role": role, "content": content, "time": time.time()})
        self._dirty = True
        self.save()

    def pop_last(self, role):
        """Elimina el último mensaje con el rol dado (rehacer/editar)."""
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i]["role"] == role:
                self.messages.pop(i)
                self._dirty = True
                self.save()
                return True
        return False

    def get_context(self, limit=30):
        return self.messages[-limit:]

    def clear(self):
        self.messages = []
        self.summary = ""
        self._dirty = True
        self._flush()

    def flush(self):
        if self._dirty:
            self._flush()

    def list_sessions(self):
        if not self._dir.exists():
            return []
        sessions = []
        for f in sorted(self._dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            sessions.append(f.stem)
        return sessions

    @property
    def message_count(self):
        return len(self.messages)

    @property
    def user_interactions(self):
        return sum(1 for m in self.messages if m["role"] == "user")
