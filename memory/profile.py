import json, time, logging, re
from pathlib import Path

logger = logging.getLogger("xens.memory")

PROFILE_DIR = Path.home() / ".xens"
PROFILE_FILE = PROFILE_DIR / "profile.json"
_SAVE_DEBOUNCE = 3.0

def _normalize(text):
    return re.sub(r"\s+", " ", text.strip().lower())

def _is_duplicate(new_fact, existing):
    n = _normalize(new_fact)
    for e in existing:
        en = _normalize(e)
        if n == en or n in en or en in n:
            return True
    return False

class UserProfile:
    def __init__(self):
        self.name = ""
        self.first_seen = time.time()
        self.interaction_count = 0
        self.preferences = {}
        self.projects = []
        self.facts = []
        self.common_topics = {}
        self.last_summary = ""
        self.bio = ""
        self._dirty = False
        self._last_save = 0.0
        self._uid = None
        self._file = PROFILE_FILE

    def _profile_file(self, uid):
        # Perfil aislado por cuenta (SaaS): ~/.xens/profile-{uid}.json.
        # Sin uid (modo local): ~/.xens/profile.json como siempre.
        if uid:
            return PROFILE_DIR / f"profile-{uid}.json"
        return PROFILE_FILE

    def load(self, uid=None):
        if uid is not None:
            uid = str(uid)
        if uid != self._uid:
            self._reset_state()
            self._uid = uid
            self._file = self._profile_file(uid)
        if self._file.exists():
            try:
                with open(self._file) as f:
                    data = json.load(f)
                    self.name = data.get("name", "")
                    self.first_seen = data.get("first_seen", time.time())
                    self.interaction_count = data.get("interaction_count", 0)
                    self.preferences = data.get("preferences", {})
                    self.projects = data.get("projects", [])
                    self.facts = data.get("facts", [])
                    self.common_topics = data.get("common_topics", {})
                    self.last_summary = data.get("last_summary", "")
                    self.bio = data.get("bio", "")
            except:
                pass

    def _reset_state(self):
        self.name = ""
        self.first_seen = time.time()
        self.interaction_count = 0
        self.preferences = {}
        self.projects = []
        self.facts = []
        self.common_topics = {}
        self.last_summary = ""
        self.bio = ""
        self._dirty = False
        self._last_save = 0.0

    def save(self):
        if not self._dirty:
            return
        now = time.time()
        if now - self._last_save < _SAVE_DEBOUNCE:
            return
        self._flush()

    def _flush(self):
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._file, "w") as f:
                json.dump({
                    "name": self.name,
                    "first_seen": self.first_seen,
                    "interaction_count": self.interaction_count,
                    "preferences": self.preferences,
                    "projects": self.projects,
                    "facts": self.facts,
                    "common_topics": dict(sorted(self.common_topics.items(), key=lambda x: -x[1])[:20]),
                    "last_summary": self.last_summary,
                    "bio": self.bio,
                }, f, indent=2)
            self._dirty = False
            self._last_save = time.time()
        except:
            logger.exception("Profile save failed")

    def learn_fact(self, fact):
        fact = fact.strip()
        if not fact:
            return
        if _is_duplicate(fact, self.facts):
            return
        self.facts.append(fact)
        self.facts = self.facts[-50:]
        self._dirty = True
        self._flush()

    def add_project(self, name, description=""):
        for p in self.projects:
            if p["name"].lower() == name.lower():
                p["last_active"] = time.time()
                if description:
                    p["description"] = description
                self._dirty = True
                self._flush()
                return
        self.projects.append({"name": name, "description": description, "created": time.time(), "last_active": time.time()})
        self.projects = self.projects[-20:]
        self._dirty = True
        self._flush()

    def track_topic(self, topic):
        if topic:
            self.common_topics[topic] = self.common_topics.get(topic, 0) + 1
            self._dirty = True
            self._flush()

    def get_memory_context(self):
        parts = []
        if self.name:
            parts.append(f"User's name is {self.name}.")
        if self.bio:
            parts.append(f"About them: {self.bio}")
        if self.facts:
            parts.append(f"Things I know about them: {'; '.join(self.facts[-5:])}")
        if self.projects:
            active = sorted(self.projects, key=lambda p: -p.get("last_active", 0))[:3]
            parts.append(f"Their active projects: {', '.join(p['name'] for p in active)}")
        if self.last_summary:
            parts.append(f"Summary of our last conversation: {self.last_summary}")
        if self.preferences:
            pref_str = "; ".join(f"{k}: {v}" for k, v in list(self.preferences.items())[:5])
            parts.append(f"Preferences I've noticed: {pref_str}")
        parts.append(f"We've had {self.interaction_count} interactions since {time.strftime('%Y-%m-%d', time.localtime(self.first_seen))}.")
        return "\n".join(parts)

    def record_interaction(self):
        self.interaction_count += 1
        self._dirty = True
        if self.interaction_count % 5 == 0:
            self.save()

    def flush(self):
        if self._dirty:
            self._flush()


profile = UserProfile()
profile.load()
