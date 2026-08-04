import math, random

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QPointF
from PySide6.QtGui import QPainter, QColor, QRadialGradient, QPen, QBrush


class NanobotCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

        self._particles = []
        self._mouse = QPointF(-9999, -9999)
        self._time = 0.0
        self._count = 200
        self._connection_dist = 110
        self._mouse_radius = 140

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(16)

        self.setMouseTracking(True)

    def showEvent(self, event):
        super().showEvent(event)
        self._init_particles()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._init_particles()

    def mouseMoveEvent(self, event):
        self._mouse = QPointF(event.position().x(), event.position().y())

    def leaveEvent(self, event):
        self._mouse = QPointF(-9999, -9999)

    def _init_particles(self):
        w, h = self.width(), self.height()
        if w < 10 or h < 10:
            return
        count = self._count
        self._particles = []
        for i in range(count):
            p = {
                "x": random.random() * w,
                "y": random.random() * h,
                "vx": (random.random() - 0.5) * 0.8,
                "vy": (random.random() - 0.5) * 0.8,
                "size": 2 + random.random() * 3,
                "phase": random.random() * math.pi * 2,
                "hex": self._gen_hex(2 + random.random() * 3),
            }
            # Some cluster near center
            if i < count * 0.4:
                p["tx"] = w / 2 + (random.random() - 0.5) * 120
                p["ty"] = h / 2 + (random.random() - 0.5) * 80
            else:
                p["tx"] = w / 2 + (random.random() - 0.5) * w * 0.6
                p["ty"] = h / 2 + (random.random() - 0.5) * h * 0.4
            self._particles.append(p)

    def _gen_hex(self, s):
        pts = []
        for i in range(6):
            a = (math.pi / 3) * i - math.pi / 6
            pts.append((math.cos(a) * s * 0.8, math.sin(a) * s * 0.8))
        return pts

    def _animate(self):
        self._time += 0.003
        w, h = self.width(), self.height()
        if w < 10 or h < 10:
            return
        w_f, h_f = float(w), float(h)
        mouse = self._mouse
        mdist = 0.0

        for p in self._particles:
            # Attraction to target
            dx = p["tx"] - p["x"]
            dy = p["ty"] - p["y"]
            d = math.hypot(dx, dy)
            if d > 10:
                p["vx"] += (dx / d) * 0.003
                p["vy"] += (dy / d) * 0.003

            # Mouse repel
            mdx = p["x"] - mouse.x()
            mdy = p["y"] - mouse.y()
            mdist = math.hypot(mdx, mdy)
            if mdist < self._mouse_radius and mdist > 1:
                force = (self._mouse_radius - mdist) / self._mouse_radius
                p["vx"] += (mdx / mdist) * force * 0.4
                p["vy"] += (mdy / mdist) * force * 0.4

            # Damping
            p["vx"] *= 0.96
            p["vy"] *= 0.96

            # Speed cap
            spd = math.hypot(p["vx"], p["vy"])
            if spd > 2:
                p["vx"] = (p["vx"] / spd) * 2
                p["vy"] = (p["vy"] / spd) * 2

            p["x"] += p["vx"]
            p["y"] += p["vy"]

            # Edge wrap
            margin = 60
            if p["x"] < -margin:
                p["x"] = w_f + margin
            elif p["x"] > w_f + margin:
                p["x"] = -margin
            if p["y"] < -margin:
                p["y"] = h_f + margin
            elif p["y"] > h_f + margin:
                p["y"] = -margin

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        t = self._time

        # Draw connections
        particles = self._particles
        for i in range(len(particles)):
            a = particles[i]
            for j in range(i + 1, len(particles)):
                b = particles[j]
                dx = a["x"] - b["x"]
                dy = a["y"] - b["y"]
                dist = math.hypot(dx, dy)
                if dist < self._connection_dist:
                    alpha = (1 - dist / self._connection_dist) * 0.12
                    painter.setPen(QPen(QColor(0, 212, 255, int(alpha * 255)), 0.3))
                    painter.drawLine(QPointF(a["x"], a["y"]), QPointF(b["x"], b["y"]))

        # Draw particles
        for p in particles:
            pulse = 0.85 + 0.15 * math.sin(t * 2 + p["phase"])
            cx, cy = p["x"], p["y"]

            # Outer glow
            grad = QRadialGradient(QPointF(cx, cy), p["size"] * 3 * pulse)
            grad.setColorAt(0, QColor(0, 212, 255, int(40 * pulse)))
            grad.setColorAt(1, QColor(0, 212, 255, 0))
            painter.setBrush(QBrush(grad))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(cx, cy), p["size"] * 3 * pulse, p["size"] * 3 * pulse)

            # Hex shape
            painter.save()
            painter.translate(QPointF(cx, cy))
            painter.rotate(t * 30 + p["phase"] * 57.3)
            path = p["hex"]
            poly = []
            for px, py in path:
                poly.append(QPointF(px * pulse, py * pulse))
            painter.setPen(QPen(QColor(0, 212, 255, int(70 * pulse)), 0.6))
            painter.setBrush(QColor(0, 212, 255, int(8 * pulse)))
            painter.drawPolygon(poly)
            painter.restore()

            # Core dot
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 212, 255, int(160 * pulse)))
            painter.drawEllipse(QPointF(cx, cy), 1.2 * pulse, 1.2 * pulse)

        # Center ambient glow
        grad = QRadialGradient(QPointF(w / 2, h / 2), 200)
        grad.setColorAt(0, QColor(0, 212, 255, 8))
        grad.setColorAt(0.5, QColor(124, 92, 252, 4))
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.NoPen)
        painter.drawRect(0, 0, w, h)

        painter.end()
