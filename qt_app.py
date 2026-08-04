import asyncio, json, logging, os, sys, base64

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QScrollArea, QLabel, QFrame,
)
from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QFont, QPixmap, QColor, QCursor

logger = logging.getLogger("xens.qt")

import qasync
from .ui.chat import ChatArea

_main_window = None

# ─── Theme colors ────────────────────────────────────────────
# Change these to customize the look
BG      = "#212121"   # main background
BG2     = "#171717"   # sidebar / darker areas
INPUT   = "#2f2f2f"   # input area background
TEXT    = "#ececec"   # primary text
DIM     = "#8e8ea0"   # secondary text
ACCENT  = "#10a37f"   # green accent (ChatGPT)
BORDER  = "#3f3f3f"   # subtle borders


# ─── Main Window ────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        global _main_window
        _main_window = self

        self.setWindowTitle("Xens")
        self.setMinimumSize(600, 500)
        self.resize(900, 700)
        self.setStyleSheet(f"QMainWindow, QWidget {{ background: {BG}; color: {TEXT}; }}")

        self._messages = []
        self._running = False

        # ── Central layout ──
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top bar ──
        bar = QFrame()
        bar.setFixedHeight(44)
        bar.setStyleSheet(f"background: {BG}; border-bottom: 1px solid {BORDER};")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 0, 16, 0)

        title = QLabel("Xens")
        title.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {TEXT}; background: transparent;")
        bl.addWidget(title)

        bl.addStretch()

        self._status = QLabel("ready")
        self._status.setStyleSheet(f"color: {DIM}; font-size: 10px; background: transparent;")
        bl.addWidget(self._status)

        status_dot = QLabel("\u25cf")
        status_dot.setStyleSheet(f"color: {ACCENT}; font-size: 8px; background: transparent;")
        bl.addWidget(status_dot)
        root.addWidget(bar)

        # ── Chat area (centered) ──
        chat_wrap = QFrame()
        chat_wrap.setStyleSheet(f"background: {BG};")
        cwl = QHBoxLayout(chat_wrap)
        cwl.setContentsMargins(0, 0, 0, 0)

        cwl.addStretch()
        chat_col = QFrame()
        chat_col.setStyleSheet("background: transparent;")
        chat_col.setMaximumWidth(800)
        ccl = QVBoxLayout(chat_col)
        ccl.setContentsMargins(0, 0, 0, 0)
        self._chat = ChatArea()
        ccl.addWidget(self._chat, 1)
        cwl.addWidget(chat_col, 1)
        cwl.addStretch()
        root.addWidget(chat_wrap, 1)

        # ── Input area (centered) ──
        input_wrap = QFrame()
        input_wrap.setStyleSheet(f"background: {BG};")
        input_wrap.setFixedHeight(140)
        iwl = QVBoxLayout(input_wrap)
        iwl.setContentsMargins(0, 0, 0, 0)
        iwl.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        spacer_top = QWidget()
        spacer_top.setFixedHeight(8)
        spacer_top.setStyleSheet("background: transparent;")
        iwl.addWidget(spacer_top)

        input_col = QFrame()
        input_col.setStyleSheet("background: transparent;")
        input_col.setMaximumWidth(800)
        icol = QVBoxLayout(input_col)
        icol.setContentsMargins(24, 0, 24, 24)
        icol.setSpacing(0)

        # Input row (rounded container)
        input_row = QFrame()
        input_row.setObjectName("chatInput")
        input_row.setStyleSheet(f"""
            QFrame#chatInput {{
                background: {INPUT}; border: 1px solid {BORDER}; border-radius: 12px;
            }}
        """)
        irl = QHBoxLayout(input_row)
        irl.setContentsMargins(12, 4, 4, 4)
        irl.setSpacing(6)

        self._input = QTextEdit()
        self._input.setPlaceholderText("Message Xens...")
        self._input.setFixedHeight(40)
        self._input.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._input.setStyleSheet(f"""
            QTextEdit {{
                background: transparent; color: {TEXT}; border: none;
                font-size: 13px; padding: 4px 0; selection-background-color: {ACCENT};
            }}
        """)
        self._input.setMinimumWidth(200)
        self._input.textChanged.connect(self._auto_resize)
        self._input.installEventFilter(self)
        irl.addWidget(self._input)

        self._send_btn = QPushButton("\u2192")
        self._send_btn.setFixedSize(32, 32)
        self._send_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._send_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT}; color: white; border: none; border-radius: 8px;
                font-size: 16px; font-weight: 600;
            }}
            QPushButton:hover {{ background: #0d8c6f; }}
            QPushButton:disabled {{ background: {BORDER}; color: {DIM}; }}
        """)
        self._send_btn.clicked.connect(self._send_message)
        irl.addWidget(self._send_btn)

        icol.addWidget(input_row)

        # Bottom text
        note = QLabel("Xens may produce inaccurate information.")
        note.setStyleSheet(f"color: {DIM}; font-size: 10px; background: transparent;")
        note.setAlignment(Qt.AlignCenter)
        note.setFixedHeight(20)
        icol.addWidget(note)

        iwl.addWidget(input_col)

        root.addWidget(input_wrap)

        self._input.setFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F11:
            self.toggle_fullscreen()
        super().keyPressEvent(event)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    async def _process_message(self, text):
        self._messages.append({"role": "user", "content": text})
        from .core.llm import run_tool_loop
        try:
            async for chunk in run_tool_loop(self._messages):
                if isinstance(chunk, dict):
                    t = chunk["type"]
                    if t == "content":
                        if not self._chat._streaming:
                            self._chat.start_assistant_message(chunk["content"])
                        else:
                            self._chat.append_assistant_text(chunk["content"])
                    elif t == "tool_call":
                        args = chunk.get("args", {})
                        arg_str = ", ".join(f"{k}={v}" for k, v in args.items() if v is not None)
                        self._chat.add_tool_call(chunk["name"], arg_str)
                    elif t == "tool_result":
                        self._chat.update_tool_status(chunk.get("success", False))
                    elif t == "screenshot":
                        self._chat.add_screenshot(chunk["base64"], chunk["width"], chunk["height"])
                    elif t == "error":
                        self._chat.start_assistant_message(f"Error: {chunk['content']}")
                elif isinstance(chunk, str):
                    if not self._chat._streaming:
                        self._chat.start_assistant_message(chunk)
                    else:
                        self._chat.append_assistant_text(chunk)
        except Exception as e:
            logger.error(f"Tool loop error: {e}")
            self._chat.start_assistant_message(f"Error: {e}")

        self._chat.finish_assistant()
        self._running = False
        self._send_btn.setEnabled(True)
        self._input.setEnabled(True)
        self._input.setFocus()
        self._status.setText("ready")

    def _send_message(self):
        text = self._input.toPlainText().strip()
        if not text or self._running:
            return
        self._chat.add_user_message(text)
        self._input.clear()
        self._running = True
        self._send_btn.setEnabled(False)
        self._input.setEnabled(False)
        self._status.setText("thinking")
        asyncio.ensure_future(self._process_message(text))

    def _clear_chat(self):
        self._chat.clear_all()
        self._messages = []

    def _auto_resize(self):
        doc = self._input.document()
        doc.setTextWidth(self._input.viewport().width())
        h = int(doc.size().height()) + 10
        self._input.setFixedHeight(max(40, min(h, 120)))

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj == self._input and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Return and not event.modifiers() & Qt.ShiftModifier:
                self._send_message()
                return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        from .core.utils import shutdown_all
        asyncio.ensure_future(shutdown_all())
        event.accept()


# ─── UI Tools ───────────────────────────────────────────────

def _get_window():
    global _main_window
    return _main_window

def open_view_ui(view="chat", mode="fullscreen"):
    return json.dumps({"success": True, "view": view, "mode": mode})

def play_music_ui(query=""):
    return json.dumps({"success": True, "query": query})

def minimize_view_ui(view=""):
    return json.dumps({"success": True, "view": view})

def close_view_ui(view=""):
    return json.dumps({"success": True, "view": view})

def set_nanobot_state_ui(state="idle"):
    return json.dumps({"success": True, "state": state})

def form_figure_ui(name="", url=""):
    return json.dumps({"success": True, "figure": name})

def reset_figure_ui():
    return json.dumps({"success": True})


# ─── Run ───────────────────────────────────────────────────

def run_qt_app():
    logging.basicConfig(level=logging.INFO)

    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("xens.assistant.v6")
    except:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("Xens")

    font = QFont("Segoe UI", 10)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)

    # Dark palette
    palette = app.palette()
    palette.setColor(palette.ColorRole.Window, QColor(BG))
    palette.setColor(palette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(palette.ColorRole.Base, QColor(INPUT))
    palette.setColor(palette.ColorRole.Text, QColor(TEXT))
    palette.setColor(palette.ColorRole.Button, QColor(INPUT))
    palette.setColor(palette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(palette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(palette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    window.show()

    from .tools.registry import registry
    registry.register(
        "open_view", open_view_ui,
        "Show a view: chat, map, music, calendar.",
        {
            "type": "object",
            "properties": {
                "view": {"type": "string", "enum": ["chat", "map", "music", "calendar"]},
                "mode": {"type": "string", "enum": ["fullscreen", "panel"]},
            },
            "required": ["view"],
        }
    )
    registry.register(
        "play_music", play_music_ui,
        "Play music via Spotify or local files.",
        {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Song or artist"}},
            "required": ["query"],
        }
    )
    registry.register(
        "form_figure", form_figure_ui,
        "Make nanobots form a shape from an image URL.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "url": {"type": "string"},
            },
            "required": ["name"],
        }
    )
    registry.register(
        "reset_figure", reset_figure_ui,
        "Release nanobots to free floating.",
        {"type": "object", "properties": {}}
    )
    registry.register(
        "minimize_view", minimize_view_ui,
        "Minimize a panel.",
        {
            "type": "object",
            "properties": {"view": {"type": "string"}},
            "required": ["view"],
        }
    )
    registry.register(
        "close_view", close_view_ui,
        "Close a view.",
        {
            "type": "object",
            "properties": {"view": {"type": "string"}},
            "required": ["view"],
        }
    )
    registry.register(
        "set_nanobot_state", set_nanobot_state_ui,
        "Change nanobot behavior.",
        {
            "type": "object",
            "properties": {
                "state": {"type": "string", "enum": ["idle", "swarm", "pulse", "construct"]}
            },
            "required": ["state"],
        }
    )

    logger.info(f"Qt UI started with {registry.count} tools")

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    run_qt_app()
