import json, math, os, random
from pathlib import Path

from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QGridLayout, QScrollArea, QTextEdit, QCalendarWidget,
    QListWidget, QListWidgetItem, QSplitter, QTabWidget,
    QFileDialog, QSlider, QProgressBar,
)
from PySide6.QtCore import Qt, QRect, QPoint, Signal, QSize, QTimer, QUrl
from PySide6.QtGui import (
    QPainter, QColor, QLinearGradient, QBrush, QPen, QFont,
    QPixmap, QFontDatabase, QCursor,
)

logger = __import__("logging").getLogger("xens.ui.panels")

MEMORY_DIR = Path.home() / ".xens"
LAYOUT_FILE = MEMORY_DIR / "layout.json"
EVENTS_FILE = MEMORY_DIR / "events.json"
PLACES_FILE = MEMORY_DIR / "places.json"


# ─── FloatingPanel base ────────────────────────────────────

class FloatingPanel(QFrame):
    closed = Signal(str)

    def __init__(self, title, panel_id, min_size=(280, 300), parent=None):
        super().__init__(parent)
        self._panel_id = panel_id
        self._drag_pos = None
        self._min_w, self._min_h = min_size
        self._minimized = False
        self._original_geometry = None

        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(self._min_w, self._min_h)
        self._setup_ui(title)

    def _setup_ui(self, title):
        self._outer = QFrame(self)
        self._outer.setStyleSheet(f"""
            QFrame#panelOuter {{
                background: rgba(10, 10, 24, 0.75);
                border: 1px solid rgba(0, 212, 255, 0.08);
                border-radius: 10px;
            }}
            QFrame#panelTitle {{
                background: transparent;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
            }}
            QLabel {{ color: #e0e0e8; font-size: 12px; }}
            QPushButton {{
                background: transparent; border: none;
                color: #6b6b8a; font-size: 14px; padding: 2px 6px;
            }}
            QPushButton:hover {{ color: #e0e0e8; }}
        """)
        outer_layout = QVBoxLayout(self._outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # Title bar
        title_bar = QFrame()
        title_bar.setObjectName("panelTitle")
        title_bar.setFixedHeight(32)
        title_bar.setCursor(QCursor(Qt.OpenHandCursor))
        title_bar.mousePressEvent = self._on_drag_start
        title_bar.mouseMoveEvent = self._on_drag_move
        title_bar.mouseReleaseEvent = self._on_drag_end
        tl = QHBoxLayout(title_bar)
        tl.setContentsMargins(10, 0, 4, 0)

        icon_label = QLabel("⬡")
        icon_label.setStyleSheet("color: #00d4ff; font-size: 10px;")
        tl.addWidget(icon_label)

        name_label = QLabel(title)
        name_label.setStyleSheet("font-size: 11px; font-weight: 500; color: #e0e0e8;")
        tl.addWidget(name_label)
        tl.addStretch()

        self._btn_minimize = QPushButton("─")
        self._btn_minimize.setFixedSize(20, 20)
        self._btn_minimize.clicked.connect(self._on_minimize)
        tl.addWidget(self._btn_minimize)

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(20, 20)
        btn_close.clicked.connect(self._on_close)
        tl.addWidget(btn_close)

        outer_layout.addWidget(title_bar)

        # Content area
        self._content = QFrame()
        self._content.setObjectName("panelContent")
        self._content.setStyleSheet("background: transparent;")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(8, 4, 8, 8)
        outer_layout.addWidget(self._content, 1)

        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self._outer)

    def content_layout(self):
        return self._content_layout

    def _on_drag_start(self, event):
        self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        self.raise_()
        self._outer.setStyleSheet(self._outer.styleSheet() + """
            QFrame#panelOuter { border-color: rgba(0, 212, 255, 0.2); }
        """)

    def _on_drag_move(self, event):
        if self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def _on_drag_end(self, event):
        self._drag_pos = None
        self._outer.setStyleSheet(self._outer.styleSheet().replace(
            "border-color: rgba(0, 212, 255, 0.2);", ""
        ))
        self._save_layout()

    def _on_minimize(self):
        self._minimized = not self._minimized
        if self._minimized:
            self._original_geometry = self.geometry()
            self._content.hide()
            self._btn_minimize.setText("□")
            self.setFixedHeight(32)
        else:
            self._content.show()
            self._btn_minimize.setText("─")
            if self._original_geometry:
                self.setGeometry(self._original_geometry)
            self._save_layout()

    def _on_close(self):
        self._save_layout()
        self.closed.emit(self._panel_id)
        self.hide()

    def _save_layout(self):
        try:
            MEMORY_DIR.mkdir(parents=True, exist_ok=True)
            data = {}
            if LAYOUT_FILE.exists():
                data = json.loads(LAYOUT_FILE.read_text())
            geo = self.geometry()
            data[self._panel_id] = {
                "x": geo.x(), "y": geo.y(),
                "w": geo.width(), "h": geo.height(),
                "minimized": self._minimized,
                "visible": self.isVisible(),
            }
            LAYOUT_FILE.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.debug(f"Layout save error: {e}")

    def restore_geometry(self):
        try:
            data = json.loads(LAYOUT_FILE.read_text()) if LAYOUT_FILE.exists() else {}
            d = data.get(self._panel_id, {})
            if d:
                self.setGeometry(d.get("x", 100), d.get("y", 100),
                                 d.get("w", 300), d.get("h", 350))
                if d.get("minimized"):
                    self._on_minimize()
                self.setVisible(d.get("visible", True))
                return True
        except:
            pass
        return False


# ─── Calendar Panel ────────────────────────────────────────

class CalendarPanel(FloatingPanel):
    def __init__(self, parent=None):
        super().__init__("Calendar", "calendar", (320, 400), parent)
        self._events = self._load_events()
        self._build_ui()

    def _build_ui(self):
        cl = self.content_layout()

        self._calendar = QCalendarWidget()
        self._calendar.setGridVisible(True)
        self._calendar.clicked.connect(self._on_date_clicked)
        self._calendar.setStyleSheet("""
            QCalendarWidget { background: transparent; color: #e0e0e8; }
            QCalendarWidget QToolButton { color: #00d4ff; font-size: 12px; }
            QCalendarWidget QSpinBox { color: #e0e0e8; }
            QCalendarWidget QWidget#qt_calendar_navigationbar { background: rgba(0,0,0,0.2); }
            QTableView { selection-background-color: rgba(0,212,255,0.15); }
        """)
        cl.addWidget(self._calendar)

        self._event_list = QListWidget()
        self._event_list.setStyleSheet("""
            QListWidget { background: transparent; border: none; color: #e0e0e8; font-size: 11px; }
            QListWidget::item { padding: 4px 6px; }
            QListWidget::item:hover { background: rgba(0,212,255,0.05); border-radius: 4px; }
        """)
        cl.addWidget(self._event_list)

        add_row = QHBoxLayout()
        self._event_input = QTextEdit()
        self._event_input.setPlaceholderText("New event...")
        self._event_input.setFixedHeight(32)
        self._event_input.setStyleSheet("""
            QTextEdit { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06);
                        border-radius: 6px; color: #e0e0e8; font-size: 11px; padding: 4px 8px; }
        """)
        add_row.addWidget(self._event_input)

        btn = QPushButton("+")
        btn.setFixedSize(28, 28)
        btn.setStyleSheet("""
            QPushButton { background: rgba(0,212,255,0.1); border: none; border-radius: 14px;
                         color: #00d4ff; font-size: 16px; }
            QPushButton:hover { background: rgba(0,212,255,0.2); }
        """)
        btn.clicked.connect(self._add_event)
        add_row.addWidget(btn)
        cl.addLayout(add_row)

        self._update_events()

    def _on_date_clicked(self, date):
        self._update_events()

    def _add_event(self):
        text = self._event_input.toPlainText().strip()
        if not text:
            return
        date = self._calendar.selectedDate().toString("yyyy-MM-dd")
        self._events.append({"date": date, "text": text, "done": False})
        self._save_events()
        self._event_input.clear()
        self._update_events()

    def _update_events(self):
        self._event_list.clear()
        sel = self._calendar.selectedDate().toString("yyyy-MM-dd")
        for ev in self._events:
            if ev["date"] == sel:
                prefix = "✓" if ev.get("done") else "○"
                item = QListWidgetItem(f"{prefix} {ev['text']}")
                if ev.get("done"):
                    item.setForeground(QColor(100, 100, 140))
                self._event_list.addItem(item)

    def _load_events(self):
        try:
            if EVENTS_FILE.exists():
                return json.loads(EVENTS_FILE.read_text())
        except:
            pass
        return []

    def _save_events(self):
        try:
            MEMORY_DIR.mkdir(parents=True, exist_ok=True)
            EVENTS_FILE.write_text(json.dumps(self._events, indent=2))
        except:
            pass


# ─── Music Panel ───────────────────────────────────────────

class MusicPanel(FloatingPanel):
    def __init__(self, parent=None):
        super().__init__("Music", "music", (300, 380), parent)
        self._spotify_available = False
        self._player = None
        self._current_playlist = []
        self._build_ui()
        self._init_spotify()

    def _build_ui(self):
        cl = self.content_layout()

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane { background: transparent; border: none; }
            QTabBar::tab { background: rgba(255,255,255,0.03); color: #6b6b8a;
                          padding: 6px 14px; font-size: 11px; border: none; }
            QTabBar::tab:selected { color: #00d4ff; border-bottom: 2px solid #00d4ff; }
        """)
        cl.addWidget(self._tabs)

        # Spotify tab
        spotify_widget = QWidget()
        spotify_layout = QVBoxLayout(spotify_widget)
        spotify_layout.setContentsMargins(0, 8, 0, 0)

        search_row = QHBoxLayout()
        self._spotify_search = QTextEdit()
        self._spotify_search.setPlaceholderText("Search Spotify...")
        self._spotify_search.setFixedHeight(30)
        self._spotify_search.setStyleSheet("""
            QTextEdit { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06);
                        border-radius: 6px; color: #e0e0e8; font-size: 11px; padding: 2px 8px; }
        """)
        search_row.addWidget(self._spotify_search)

        search_btn = QPushButton("🔍")
        search_btn.setFixedSize(26, 26)
        search_btn.setStyleSheet("QPushButton { background: transparent; border: none; color: #00d4ff; }")
        search_btn.clicked.connect(self._search_spotify)
        search_row.addWidget(search_btn)
        spotify_layout.addLayout(search_row)

        self._spotify_list = QListWidget()
        self._spotify_list.setStyleSheet("""
            QListWidget { background: transparent; border: none; color: #e0e0e8; font-size: 11px; }
            QListWidget::item { padding: 6px; border-radius: 4px; }
            QListWidget::item:hover { background: rgba(0,212,255,0.05); }
        """)
        spotify_layout.addWidget(self._spotify_list)

        self._tabs.addTab(spotify_widget, "Spotify")

        # Local tab
        local_widget = QWidget()
        local_layout = QVBoxLayout(local_widget)
        local_layout.setContentsMargins(0, 8, 0, 0)

        browse_btn = QPushButton("📂 Browse music folder")
        browse_btn.setStyleSheet("""
            QPushButton { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06);
                         border-radius: 6px; color: #e0e0e8; font-size: 11px; padding: 6px; text-align: left; }
            QPushButton:hover { background: rgba(0,212,255,0.05); }
        """)
        browse_btn.clicked.connect(self._browse_local)
        local_layout.addWidget(browse_btn)

        self._local_list = QListWidget()
        self._local_list.setStyleSheet(self._spotify_list.styleSheet())
        self._local_list.itemDoubleClicked.connect(self._play_local)
        local_layout.addWidget(self._local_list)

        self._tabs.addTab(local_widget, "Local")

        # Controls
        controls = QFrame()
        controls.setStyleSheet("background: rgba(0,0,0,0.2); border-radius: 6px;")
        cl2 = QHBoxLayout(controls)
        cl2.setContentsMargins(8, 4, 8, 4)

        self._play_btn = QPushButton("▶")
        self._play_btn.setFixedSize(28, 28)
        self._play_btn.setStyleSheet("""
            QPushButton { background: rgba(0,212,255,0.1); border: none; border-radius: 14px; color: #00d4ff; }
            QPushButton:hover { background: rgba(0,212,255,0.2); }
        """)
        cl2.addWidget(self._play_btn)

        self._now_playing = QLabel("No track")
        self._now_playing.setStyleSheet("color: #6b6b8a; font-size: 10px;")
        cl2.addWidget(self._now_playing, 1)

        cl.addWidget(controls)

    def _init_spotify(self):
        try:
            import spotipy
            from spotipy.oauth2 import SpotifyOAuth
            TOKEN_FILE = MEMORY_DIR / "spotify_token.json"
            self._spotify = spotipy.Spotify(auth_manager=SpotifyOAuth(
                client_id="1e3a1b9d8c5e4f7a9b2c3d4e5f6a7b8c",
                client_secret="abc123def456ghi789jkl012mno345pq",
                redirect_uri="http://localhost:8888/callback",
                scope="user-library-read playlist-read-private user-modify-playback-state",
                cache_path=str(TOKEN_FILE),
                open_browser=False,
            ))
            user = self._spotify.current_user()
            if user:
                self._spotify_available = True
                self._now_playing.setText(f"✓ {user.get('display_name', 'Spotify')}")
        except Exception as e:
            self._spotify_available = False
            self._now_playing.setText("⚠ Login needed")

    def _search_spotify(self):
        if not self._spotify_available:
            self._now_playing.setText("⚠ Spotify not connected")
            return
        query = self._spotify_search.toPlainText().strip()
        if not query:
            return
        try:
            results = self._spotify.search(query, limit=10, type="track")
            self._spotify_list.clear()
            for track in results["tracks"]["items"]:
                name = track["name"]
                artist = track["artists"][0]["name"]
                item = QListWidgetItem(f"🎵 {name} - {artist}")
                item.setData(Qt.UserRole, track["uri"])
                self._spotify_list.addItem(item)
        except Exception as e:
            self._now_playing.setText(f"⚠ {e}")

    def _browse_local(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Music Folder")
        if not folder:
            return
        self._local_list.clear()
        self._current_playlist = []
        for f in Path(folder).rglob("*"):
            if f.suffix.lower() in (".mp3", ".wav", ".flac", ".ogg", ".m4a"):
                self._current_playlist.append(str(f))
                self._local_list.addItem(f"🎵 {f.stem}")

    def _play_local(self, item):
        idx = self._local_list.row(item)
        if idx < len(self._current_playlist):
            path = self._current_playlist[idx]
            if not self._player:
                from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
                self._player = QMediaPlayer()
                self._audio = QAudioOutput()
                self._player.setAudioOutput(self._audio)
            self._player.setSource(QUrl.fromLocalFile(path))
            self._player.play()
            self._now_playing.setText(f"▶ {Path(path).stem}")

    def play(self, query: str):
        """Called by Xens tool — search and play a track"""
        if self._spotify_available:
            self._spotify_search.setPlainText(query)
            self._search_spotify()
            if self._spotify_list.count() > 0:
                item = self._spotify_list.item(0)
                uri = item.data(Qt.UserRole)
                try:
                    devices = self._spotify.devices()
                    if devices["devices"]:
                        self._spotify.start_playback(uris=[uri])
                        self._now_playing.setText(f"▶ {item.text()}")
                        return True
                except:
                    pass
        # Fallback to browse
        self._now_playing.setText(f"🔍 Searching for: {query}")
        return False


# ─── Map Panel ─────────────────────────────────────────────

class MapPanel(FloatingPanel):
    def __init__(self, parent=None):
        super().__init__("World Map", "map", (400, 300), parent)
        self._places = self._load_places()
        self._build_ui()

    def _build_ui(self):
        cl = self.content_layout()

        # Check if WebEngine is available
        self._use_webengine = False
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            self._use_webengine = True
        except ImportError:
            pass

        if self._use_webengine:
            self._build_webengine_map(cl)
        else:
            self._build_qpainter_map(cl)

    def _build_webengine_map(self, cl):
        from PySide6.QtWebEngineWidgets import QWebEngineView
        self._web = QWebEngineView()
        html = self._leaflet_html()
        self._web.setHtml(html)
        cl.addWidget(self._web, 1)

        # Places list
        self._places_list = QListWidget()
        self._places_list.setStyleSheet("""
            QListWidget { background: transparent; border: none; color: #e0e0e8; font-size: 11px;
                         max-height: 80px; }
            QListWidget::item { padding: 2px 6px; }
        """)
        self._refresh_places_list()
        cl.addWidget(self._places_list)

    def _build_qpainter_map(self, cl):
        self._map_widget = _SimpleGlobe(self._places)
        cl.addWidget(self._map_widget, 1)

        self._places_list = QListWidget()
        self._places_list.setStyleSheet("""
            QListWidget { background: transparent; border: none; color: #e0e0e8; font-size: 11px;
                         max-height: 80px; }
            QListWidget::item { padding: 2px 6px; }
        """)
        self._refresh_places_list()
        cl.addWidget(self._places_list)

    def _leaflet_html(self):
        places_js = ""
        for p in self._places:
            places_js += f"""
                L.marker([{p['lat']}, {p['lng']}])
                  .addTo(map)
                  .bindPopup('{p.get("name", "Place")}');
            """
        return f"""
        <!DOCTYPE html>
        <html><head>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <style>body{{margin:0}} #m{{width:100vw;height:100vh}}</style>
        </head><body>
        <div id="m"></div>
        <script>
        var map = L.map('m').setView([20, 0], 2);
        L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            attribution: '&copy; OpenStreetMap',
            maxZoom: 18,
        }}).addTo(map);
        {places_js}
        map.on('click', function(e) {{
            qtw.call('map_click', JSON.stringify({{lat: e.latlng.lat, lng: e.latlng.lng}}));
        }});
        </script></body></html>
        """

    def add_place(self, name: str, lat: float, lng: float):
        self._places.append({"name": name, "lat": lat, "lng": lng})
        self._save_places()
        self._refresh_places_list()

    def _refresh_places_list(self):
        if hasattr(self, '_places_list'):
            self._places_list.clear()
            for p in self._places:
                self._places_list.addItem(f"📍 {p['name']} ({p['lat']:.2f}, {p['lng']:.2f})")

    def _load_places(self):
        try:
            if PLACES_FILE.exists():
                return json.loads(PLACES_FILE.read_text())
        except:
            pass
        return []

    def _save_places(self):
        try:
            MEMORY_DIR.mkdir(parents=True, exist_ok=True)
            PLACES_FILE.write_text(json.dumps(self._places, indent=2))
        except:
            pass


class _SimpleGlobe(QWidget):
    """Fallback map drawn with QPainter when WebEngine is unavailable"""
    def __init__(self, places=None):
        super().__init__()
        self._places = places or []
        self.setMinimumSize(200, 150)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) * 0.4

        # Globe background
        p.setPen(QPen(QColor(0, 212, 255, 40), 1))
        p.setBrush(QColor(10, 10, 30))
        p.drawEllipse(QPointF(cx, cy), r, r)

        # Grid lines (lat/lng)
        p.setPen(QPen(QColor(0, 212, 255, 15), 0.5))
        for i in range(0, 360, 30):
            a = math.radians(i)
            p.drawLine(
                QPointF(cx + math.cos(a) * r * 0.3, cy + math.sin(a) * r * 0.3),
                QPointF(cx + math.cos(a) * r, cy + math.sin(a) * r),
            )
        for i in range(0, 180, 30):
            y = cy + math.sin(math.radians(i)) * r
            wr = math.cos(math.radians(i)) * r
            p.drawEllipse(QPointF(cx, y), wr, 2)

        # Continents (simplified blobs)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 212, 255, 25))
        continents = [
            (cx - r * 0.15, cy - r * 0.4, r * 0.3, r * 0.4),
            (cx + r * 0.1, cy - r * 0.35, r * 0.25, r * 0.35),
            (cx + r * 0.3, cy + r * 0.15, r * 0.25, r * 0.3),
            (cx - r * 0.35, cy + r * 0.2, r * 0.2, r * 0.25),
            (cx + r * 0.5, cy - r * 0.15, r * 0.15, r * 0.15),
        ]
        for cx2, cy2, rw, rh in continents:
            p.drawEllipse(QPointF(cx2, cy2), rw, rh)

        # Places
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(124, 92, 252, 180))
        for place in self._places:
            # Simple projection
            px = cx + (place.get("lng", 0) / 180) * r
            py = cy - (place.get("lat", 0) / 90) * r
            p.drawEllipse(QPointF(px, py), 3, 3)

        p.end()
