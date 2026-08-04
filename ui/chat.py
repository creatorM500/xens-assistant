"""
ChatGPT-style chat bubble widget.
Edit the constants at the top to customize the look.
"""

import base64

from PySide6.QtWidgets import (
    QScrollArea, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QColor, QFont

# ─── ChatGPT Dark Theme Colors ──────────────────────────────
# Change these to customize
BG_ASSISTANT = "rgba(0,0,0,0.2)"  # subtle bg on assistant rows
USER_BUBBLE  = "#2f2f2f"          # user message bubble bg
USER_TEXT    = "#ececec"          # user message text
ASSISTANT_TEXT = "#ececec"        # assistant text
AVATAR_USER  = "#5436da"          # user avatar circle
AVATAR_BOT   = "#19c37d"          # bot avatar circle (green)
ACCENT       = "#19c37d"          # accent color
DIM          = "#8e8ea0"          # dim text
MAX_WIDTH    = 800                # max content width


class ChatArea(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setStyleSheet("background: transparent;")

        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addStretch()
        self.setWidget(self._container)

        self._streaming = False
        self._last_label = None

    def add_user_message(self, text):
        w = self._make_bubble(text, True)
        self._layout.insertWidget(self._layout.count() - 1, w)

    def start_assistant_message(self, text=""):
        self._streaming = True
        w = self._make_bubble(text, False)
        self._layout.insertWidget(self._layout.count() - 1, w)
        self._last_label = w.findChild(QLabel, "chatText")
        self._scroll_down()

    def append_assistant_text(self, text):
        if self._last_label:
            self._last_label.setText(self._last_label.text() + text)
            self._scroll_down()

    def finish_assistant(self):
        self._streaming = False
        self._last_label = None

    def add_tool_call(self, name, args=""):
        frame = QFrame()
        frame.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(48, 2, 48, 2)
        layout.setSpacing(6)

        icon = QLabel("\u26a1")
        icon.setStyleSheet(f"color: {ACCENT}; font-size: 10px; background: transparent;")
        layout.addWidget(icon)

        nl = QLabel(name)
        nl.setStyleSheet(f"color: {ACCENT}; font-size: 11px; font-family: monospace; background: transparent;")
        layout.addWidget(nl)

        if args:
            al = QLabel(f"({args})")
            al.setStyleSheet(f"color: {DIM}; font-size: 11px; background: transparent;")
            layout.addWidget(al)

        self._status_label = QLabel("running...")
        self._status_label.setObjectName("toolStatus")
        self._status_label.setStyleSheet(f"color: {ACCENT}; font-size: 10px; background: transparent;")
        layout.addWidget(self._status_label)
        layout.addStretch()

        self._layout.insertWidget(self._layout.count() - 1, frame)
        self._scroll_down()

    def update_tool_status(self, ok=True):
        for i in range(self._layout.count()):
            item = self._layout.itemAt(i)
            if item and item.widget():
                st = item.widget().findChild(QLabel, "toolStatus")
                if st:
                    st.setText("done" if ok else "failed")
                    st.setStyleSheet(f"color: {'#22c55e' if ok else '#ef4444'}; font-size: 10px; background: transparent;")

    def add_screenshot(self, b64, w, h):
        pixmap = QPixmap()
        pixmap.loadFromData(base64.b64decode(b64))
        pixmap = pixmap.scaledToWidth(360, Qt.SmoothTransformation)

        frame = QFrame()
        frame.setStyleSheet("background: transparent;")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(48, 2, 48, 2)
        fl.setSpacing(2)

        img = QLabel()
        img.setPixmap(pixmap)
        img.setStyleSheet("border-radius: 8px; background: transparent;")
        fl.addWidget(img)

        meta = QLabel(f"screen \u00b7 {w}x{h}")
        meta.setStyleSheet(f"color: {DIM}; font-size: 9px; font-family: monospace; background: transparent;")
        fl.addWidget(meta)

        self._layout.insertWidget(self._layout.count() - 1, frame)
        self._scroll_down()

    def clear_all(self):
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._streaming = False
        self._last_label = None

    def _make_bubble(self, text, is_user):
        # Outer frame (full width row)
        frame = QFrame()
        frame.setStyleSheet(f"background: {'transparent' if is_user else BG_ASSISTANT};")
        frame.setMaximumWidth(16777215)

        # Center layout: max-width 800px, auto margins
        outer = QHBoxLayout(frame)
        outer.setContentsMargins(0, 8, 0, 8)
        outer.setSpacing(0)

        # Left spacer
        left = QWidget()
        left.setStyleSheet("background: transparent;")
        left.setFixedWidth(0)
        outer.addWidget(left)

        # Content column (centered, max 800px)
        content = QFrame()
        content.setStyleSheet("background: transparent;")
        content.setMaximumWidth(MAX_WIDTH)
        cl = QHBoxLayout(content)
        cl.setContentsMargins(20, 0, 20, 0)
        cl.setSpacing(16)

        if is_user:
            # User message — right-aligned bubble
            cl.addStretch()
            bubble = QLabel(text)
            bubble.setObjectName("chatText")
            bubble.setWordWrap(True)
            bubble.setMaximumWidth(640)
            bubble.setStyleSheet(f"""
                QLabel {{
                    background: {USER_BUBBLE};
                    border-radius: 14px 14px 4px 14px;
                    padding: 10px 16px;
                    font-size: 13px;
                    line-height: 1.5;
                    color: {USER_TEXT};
                }}
            """)
            cl.addWidget(bubble)
        else:
            # Assistant message — avatar + text
            avatar = QLabel("X")
            avatar.setFixedSize(32, 32)
            avatar.setAlignment(Qt.AlignCenter)
            avatar.setStyleSheet(f"""
                QLabel {{
                    background: {AVATAR_BOT};
                    border-radius: 16px;
                    color: white;
                    font-weight: 700;
                    font-size: 12px;
                }}
            """)
            cl.addWidget(avatar)

            text_label = QLabel(text)
            text_label.setObjectName("chatText")
            text_label.setWordWrap(True)
            text_label.setStyleSheet(f"""
                QLabel {{
                    background: transparent;
                    padding: 4px 0;
                    font-size: 13px;
                    line-height: 1.6;
                    color: {ASSISTANT_TEXT};
                }}
            """)
            cl.addWidget(text_label, 1)
            cl.addStretch()

        outer.addWidget(content, 1)

        # Right spacer
        right = QWidget()
        right.setStyleSheet("background: transparent;")
        right.setFixedWidth(0)
        outer.addWidget(right)

        return frame

    def _scroll_down(self):
        QTimer.singleShot(50, lambda: self.verticalScrollBar().setValue(
            self.verticalScrollBar().maximum()
        ))
