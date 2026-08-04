import math, random, struct, json, time, base64, io
from pathlib import Path

import numpy as np
from PIL import Image

from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtCore import Qt, QTimer, QPointF, Signal, QRect
from PySide6.QtGui import (
    QSurfaceFormat, QColor, QMouseEvent, QPainter, QFont,
)

logger = __import__("logging").getLogger("xens.ui.engine")

MEMORY_DIR = Path.home() / ".xens"
FIGURES_DIR = MEMORY_DIR / "figures"

VERTEX_SHADER = """
#version 120
attribute vec2 aPos;
attribute float aSize;
attribute float aAlpha;
attribute float aPhase;
varying float vAlpha;
varying float vPhase;
void main() {
    gl_Position = vec4(aPos, 0.0, 1.0);
    gl_PointSize = aSize;
    vAlpha = aAlpha;
    vPhase = aPhase;
}
"""

FRAGMENT_SHADER = """
#version 120
varying float vAlpha;
varying float vPhase;
uniform float uTime;
void main() {
    vec2 c = gl_PointCoord - vec2(0.5);
    float d = length(c);
    // Hex shape
    float a = atan(c.y, c.x);
    float h = cos(floor(a * 1.90986 + 0.5) * 0.5236 - a) * 0.5;
    float hex = 1.0 - smoothstep(0.32, 0.5, d / h);
    // Glow
    float glow = exp(-d * 6.0) * 0.3;
    float pulse = 0.8 + 0.2 * sin(uTime * 2.0 + vPhase);
    float alpha = (hex + glow) * vAlpha * pulse;
    gl_FragColor = vec4(0.0, 0.83, 1.0, alpha);
}
"""

LINE_VERTEX = """
#version 120
attribute vec2 aPos;
uniform mat4 uProj;
void main() {
    gl_Position = uProj * vec4(aPos, 0.0, 1.0);
}
"""

LINE_FRAGMENT = """
#version 120
uniform float uAlpha;
void main() {
    gl_FragColor = vec4(0.0, 0.83, 1.0, uAlpha * 0.12);
}
"""


class NanobotEngine(QOpenGLWidget):
    forming_complete = Signal(str)  # panel_id
    figure_ready = Signal(str)  # figure_name

    PARTICLE_COUNT = 1200
    CONNECTION_DIST = 120.0
    MOUSE_RADIUS = 150.0

    STATE_IDLE = 0
    STATE_ORBITING = 1
    STATE_FORMING = 2
    STATE_FIGURING = 3

    def __init__(self, parent=None):
        fmt = QSurfaceFormat()
        fmt.setSamples(4)
        fmt.setAlphaBufferSize(8)
        fmt.setSwapInterval(1)
        QSurfaceFormat.setDefaultFormat(fmt)

        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

        self._time = 0.0
        self._mouse = QPointF(-9999, -9999)
        self._animating = True

        # Particle data
        self._pos = None  # (N, 2) float32
        self._vel = None  # (N, 2) float32
        self._sizes = None
        self._phases = None
        self._states = None  # int array of states
        self._targets = None  # (N, 2) target positions
        self._orbit_angles = None
        self._alphas = None

        # Rendering
        self._program = None
        self._vbo_pos = None
        self._vbo_size = None
        self._vbo_alpha = None
        self._vao = None
        self._line_program = None
        self._line_vbo = None
        self._line_vao = None

        # Spatial grid
        self._grid_size = 80
        self._grid = {}

        # Figures / borders
        self._borders = {}  # panel_id -> [(x1,y1,x2,y2), ...]
        self._active_figure = None  # {"indices": [...], "name": "..."}

        # Nucleus (orbiting)
        self._nucleus_indices = []

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update)
        self._timer.start(16)  # ~60fps

        self.setMouseTracking(True)

    def initializeGL(self):
        import OpenGL.GL as gl
        gl.glClearColor(0.01, 0.01, 0.03, 0.0)
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        err = gl.glGetError()
        if err:
            logger.warning(f"GL error early: {err}")

        self._init_particles()
        self._init_shaders(gl)
        self._init_buffers(gl)
        self._init_nucleus()

        err = gl.glGetError()
        if err:
            logger.error(f"GL error in init: {err}")

    def resizeGL(self, w, h):
        import OpenGL.GL as gl
        gl.glViewport(0, 0, w, h)
        self._update_targets()

    def paintGL(self):
        import OpenGL.GL as gl
        if self._vbo_pos is None:
            return  # not initialized yet
        try:
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)
            w, h = self.width(), self.height()
            if w < 10 or h < 10:
                return

            # Update particle data
            self._update_particles(float(w), float(h))

            # Upload VBOs
            flat = self._pos.flatten().astype(np.float32)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo_pos)
            gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, flat.nbytes, flat)

            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo_size)
            gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, self._sizes.nbytes, self._sizes)

            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo_alpha)
            gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, self._alphas.nbytes, self._alphas)

            # Draw connections (line batch)
            self._draw_connections(gl, w, h)

            # Draw particles (no VAO — compatible with GLES2)
            gl.glUseProgram(self._program)
            gl.glUniform1f(gl.glGetUniformLocation(self._program, "uTime"), self._time)

            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo_pos)
            gl.glVertexAttribPointer(0, 2, gl.GL_FLOAT, False, 0, None)
            gl.glEnableVertexAttribArray(0)

            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo_size)
            gl.glVertexAttribPointer(1, 1, gl.GL_FLOAT, False, 0, None)
            gl.glEnableVertexAttribArray(1)

            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo_alpha)
            gl.glVertexAttribPointer(2, 1, gl.GL_FLOAT, False, 0, None)
            gl.glEnableVertexAttribArray(2)

            gl.glDrawArrays(gl.GL_POINTS, 0, self.PARTICLE_COUNT)

            gl.glDisableVertexAttribArray(0)
            gl.glDisableVertexAttribArray(1)
            gl.glDisableVertexAttribArray(2)
            gl.glUseProgram(0)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        except Exception as e:
            logger.error(f"paintGL error: {e}")

    def _init_particles(self):
        n = self.PARTICLE_COUNT
        w, h = 1920, 1080  # initial, will be adjusted
        self._pos = np.zeros((n, 2), dtype=np.float32)
        self._vel = np.zeros((n, 2), dtype=np.float32)
        self._sizes = np.zeros(n, dtype=np.float32)
        self._phases = np.zeros(n, dtype=np.float32)
        self._states = np.zeros(n, dtype=np.int32)
        self._targets = np.zeros((n, 2), dtype=np.float32)
        self._alphas = np.ones(n, dtype=np.float32)
        self._orbit_angles = np.zeros(n, dtype=np.float32)

        for i in range(n):
            self._pos[i] = [random.random() * w, random.random() * h]
            self._vel[i] = [(random.random() - 0.5) * 0.8, (random.random() - 0.5) * 0.8]
            self._sizes[i] = 6 + random.random() * 8
            self._phases[i] = random.random() * math.pi * 2
            self._states[i] = self.STATE_IDLE

        self._update_targets()

    def _update_targets(self):
        n = self.PARTICLE_COUNT
        w, h = self.width(), self.height()
        if w < 10:
            w, h = 1920, 1080
        for i in range(n):
            if i < n * 0.4:
                self._targets[i] = [w / 2 + (random.random() - 0.5) * 140,
                                    h / 2 + (random.random() - 0.5) * 100]
            else:
                self._targets[i] = [w / 2 + (random.random() - 0.5) * w * 0.6,
                                    h / 2 + (random.random() - 0.5) * h * 0.4]

    def _init_nucleus(self):
        """Select ~60 particles for the central nucleus orbit"""
        n = self.PARTICLE_COUNT
        self._nucleus_indices = random.sample(range(n), min(60, n))

    def _init_shaders(self, gl):
        def compile(src, stype):
            shader = gl.glCreateShader(stype)
            gl.glShaderSource(shader, src)
            gl.glCompileShader(shader)
            if not gl.glGetShaderiv(shader, gl.GL_COMPILE_STATUS):
                err = gl.glGetShaderInfoLog(shader)
                raise RuntimeError(f"Shader compile error: {err}")
            return shader

        # Particle shader
        vs = compile(VERTEX_SHADER, gl.GL_VERTEX_SHADER)
        fs = compile(FRAGMENT_SHADER, gl.GL_FRAGMENT_SHADER)
        self._program = gl.glCreateProgram()
        gl.glAttachShader(self._program, vs)
        gl.glAttachShader(self._program, fs)
        gl.glBindAttribLocation(self._program, 0, "aPos")
        gl.glBindAttribLocation(self._program, 1, "aSize")
        gl.glBindAttribLocation(self._program, 2, "aAlpha")
        gl.glLinkProgram(self._program)
        if not gl.glGetProgramiv(self._program, gl.GL_LINK_STATUS):
            raise RuntimeError(f"Program link error: {gl.glGetProgramInfoLog(self._program)}")
        gl.glDeleteShader(vs)
        gl.glDeleteShader(fs)

        # Line shader
        lvs = compile(LINE_VERTEX, gl.GL_VERTEX_SHADER)
        lfs = compile(LINE_FRAGMENT, gl.GL_FRAGMENT_SHADER)
        self._line_program = gl.glCreateProgram()
        gl.glAttachShader(self._line_program, lvs)
        gl.glAttachShader(self._line_program, lfs)
        gl.glBindAttribLocation(self._line_program, 0, "aPos")
        gl.glLinkProgram(self._line_program)
        gl.glDeleteShader(lvs)
        gl.glDeleteShader(lfs)

    def _init_buffers(self, gl):
        n = self.PARTICLE_COUNT

        # Position VBO (vec2)
        self._vbo_pos = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo_pos)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, n * 8, self._pos.flatten().astype(np.float32), gl.GL_DYNAMIC_DRAW)

        # Size VBO
        self._vbo_size = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo_size)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, n * 4, self._sizes.astype(np.float32), gl.GL_DYNAMIC_DRAW)

        # Alpha VBO
        self._vbo_alpha = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo_alpha)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, n * 4, self._alphas.astype(np.float32), gl.GL_DYNAMIC_DRAW)

        # Line VBO
        self._line_vbo = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._line_vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, 0, None, gl.GL_DYNAMIC_DRAW)

        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)

    def _update(self):
        self._time += 1.0 / 60.0
        if self._animating:
            self.update()

    def _update_particles(self, w, h):
        t = self._time
        mouse = self._mouse
        pos = self._pos
        vel = self._vel
        targets = self._targets
        states = self._states
        alphas = self._alphas
        sizes = self._sizes
        phases = self._phases
        n = self.PARTICLE_COUNT

        for i in range(n):
            state = states[i]
            mx, my = pos[i, 0], pos[i, 1]
            vx, vy = vel[i, 0], vel[i, 1]
            tx, ty = targets[i, 0], targets[i, 1]

            if state == self.STATE_IDLE:
                # Flocking: attract to target
                dx = tx - mx
                dy = ty - my
                d = math.hypot(dx, dy)
                if d > 10:
                    vx += (dx / d) * 0.003
                    vy += (dy / d) * 0.003

                # Nucleus attraction for selected particles
                if i in self._nucleus_indices:
                    cx, cy = w / 2, h / 2
                    dx = cx - mx
                    dy = cy - my
                    d = math.hypot(dx, dy)
                    if d > 5:
                        speed = 0.002 + 0.001 * math.sin(t + phases[i])
                        vx += (dx / d) * speed
                        vy += (dy / d) * speed

            elif state == self.STATE_ORBITING:
                # Orbit around center
                cx, cy = w / 2, h / 2
                dx = mx - cx
                dy = my - cy
                d = math.hypot(dx, dy)
                if d < 5:
                    d = 5
                radius = 30 + (phases[i] * 20 % 70)
                target_r = radius
                # Adjust radius
                dr = target_r - d
                vx += (dx / d) * dr * 0.02
                vy += (dy / d) * dr * 0.02
                # Tangential force
                angle = math.atan2(dy, dx)
                speed = 0.5 + 0.3 * math.sin(t * 0.5 + phases[i])
                vx += -math.sin(angle) * speed * 0.02
                vy += math.cos(angle) * speed * 0.02
                alphas[i] = 0.6 + 0.4 * math.sin(t * 3 + phases[i])

            elif state == self.STATE_FORMING:
                # Strong attraction to target
                dx = tx - mx
                dy = ty - my
                d = math.hypot(dx, dy)
                if d > 1:
                    vx += (dx / d) * 0.03 + dx * 0.001
                    vy += (dy / d) * 0.03 + dy * 0.001
                sizes[i] = max(3, sizes[i] - 0.1)
                alphas[i] = min(1.0, alphas[i] + 0.02)

                if d < 2:
                    alphas[i] = 1.0
                    if random.random() < 0.01:
                        states[i] = self.STATE_IDLE
                        targets[i] = [random.random() * w, random.random() * h]

            elif state == self.STATE_FIGURING:
                dx = tx - mx
                dy = ty - my
                d = math.hypot(dx, dy)
                if d > 0.5:
                    vx += (dx / d) * 0.02 + dx * 0.005
                    vy += (dy / d) * 0.02 + dy * 0.005
                sizes[i] = 4 + 3 * math.sin(t * 2 + phases[i])
                alphas[i] = 0.6 + 0.4 * math.sin(t + phases[i])

            # Mouse repel
            mdx = mx - mouse.x()
            mdy = my - mouse.y()
            mdist = math.hypot(mdx, mdy)
            if mdist < self.MOUSE_RADIUS and mdist > 1:
                force = (self.MOUSE_RADIUS - mdist) / self.MOUSE_RADIUS
                vx += (mdx / mdist) * force * 0.3
                vy += (mdy / mdist) * force * 0.3

            # Damping
            vx *= 0.95
            vy *= 0.95
            spd = math.hypot(vx, vy)
            if spd > 3:
                vx = (vx / spd) * 3
                vy = (vy / spd) * 3

            mx += vx
            my += vy

            # Edge wrap
            margin = 80
            if mx < -margin:
                mx = w + margin
            elif mx > w + margin:
                mx = -margin
            if my < -margin:
                my = h + margin
            elif my > h + margin:
                my = -margin

            pos[i, 0] = mx
            pos[i, 1] = my
            vel[i, 0] = vx
            vel[i, 1] = vy

    def _draw_connections(self, gl, w, h):
        n = self.PARTICLE_COUNT
        pos = self._pos
        lines = []
        # Spatial grid
        gs = self._grid_size
        grid = {}
        for i in range(n):
            gx = int(pos[i, 0] / gs)
            gy = int(pos[i, 1] / gs)
            key = (gx, gy)
            if key not in grid:
                grid[key] = []
            grid[key].append(i)

        # Check neighbors only in adjacent cells
        checked = set()
        for (gx, gy), indices in grid.items():
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nkey = (gx + dx, gy + dy)
                    if nkey in grid:
                        for i in indices:
                            for j in grid[nkey]:
                                if i >= j:
                                    continue
                                pair = (i, j)
                                if pair in checked:
                                    continue
                                checked.add(pair)
                                dxp = pos[i, 0] - pos[j, 0]
                                dyp = pos[i, 1] - pos[j, 1]
                                dist = math.hypot(dxp, dyp)
                                if dist < self.CONNECTION_DIST:
                                    alpha = (1.0 - dist / self.CONNECTION_DIST) * 0.12
                                    if self._alphas[i] > 0.1 and self._alphas[j] > 0.1:
                                        lines.extend([pos[i, 0], pos[i, 1], pos[j, 0], pos[j, 1]])

        if lines:
            arr = np.array(lines, dtype=np.float32)
            gl.glUseProgram(self._line_program)
            gl.glBindVertexArray(self._line_vao)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._line_vbo)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, arr.nbytes, arr, gl.GL_DYNAMIC_DRAW)
            gl.glDrawArrays(gl.GL_LINES, 0, len(lines) // 2)
            gl.glBindVertexArray(0)
            gl.glUseProgram(0)

    # ─── Public API ────────────────────────────────────────

    def form_panel_border(self, panel_id: str, rect: QRect):
        """Send particles to form a border around a panel"""
        n = self.PARTICLE_COUNT
        x, y, pw, ph = rect.x(), rect.y(), rect.width(), rect.height()
        border_pts = []
        per_side = max(15, int((pw + ph) / 15))
        for i in range(per_side):
            t = i / per_side
            border_pts.append([x + t * pw, y])  # top
            border_pts.append([x + t * pw, y + ph])  # bottom
            border_pts.append([x, y + t * ph])  # left
            border_pts.append([x + pw, y + t * ph])  # right

        self._borders[panel_id] = border_pts

        # Assign particles to border positions
        idxs = random.sample(range(n), min(len(border_pts), n))
        for i, idx in enumerate(idxs):
            if i < len(border_pts):
                self._targets[idx] = border_pts[i]
                self._states[idx] = self.STATE_FORMING

        QTimer.singleShot(800, lambda: self.forming_complete.emit(panel_id))

    def form_panel_content(self, panel_id: str, pixmap):
        """Sample a widget's pixmap and form particles in that shape"""
        img = pixmap.toImage()
        w, h = img.width(), img.height()
        if w < 1 or h < 1:
            return
        # Sample pixels with edge detection
        points = []
        for y in range(0, h, 2):
            for x in range(0, w, 2):
                color = img.pixelColor(x, y)
                brightness = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
                if brightness > 30:
                    points.append([x, y])

        if not points:
            return

        # Assign particles to content positions
        n = self.PARTICLE_COUNT
        idxs = random.sample(range(n), min(len(points), n // 2))
        for i, idx in enumerate(idxs):
            if i < len(points):
                self._targets[idx] = [points[i][0], points[i][1]]
                self._states[idx] = self.STATE_FORMING

    def form_figure(self, name: str, image_data: bytes = None, image_path: str = None):
        """Convert image to nanobot figure"""
        try:
            if image_data:
                img = Image.open(io.BytesIO(image_data))
            elif image_path:
                img = Image.open(image_path)
            else:
                # Check saved figures
                fig_path = FIGURES_DIR / f"{name}.png"
                if fig_path.exists():
                    img = Image.open(str(fig_path))
                else:
                    return False
        except Exception as e:
            logger.error(f"Figure load error: {e}")
            return False

        # Convert to grayscale and sample edge points
        gray = img.convert("L")
        w, h = gray.size

        # Edge detection (simple gradient)
        pixels = np.array(gray, dtype=np.float32)
        grad = np.zeros_like(pixels)
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                gx = pixels[y, x + 1] - pixels[y, x - 1]
                gy = pixels[y + 1, x] - pixels[y - 1, x]
                grad[y, x] = math.hypot(gx, gy)

        threshold = grad.max() * 0.3
        points = np.argwhere(grad > threshold)

        if len(points) < 10:
            # Fallback: sample bright areas
            points = np.argwhere(pixels > 128)

        # Random sample of up to 500 points
        max_pts = min(500, len(points))
        selected = points[np.random.choice(len(points), max_pts, replace=False)]

        # Map to screen coordinates
        margin = 100
        screen_w = self.width()
        screen_h = self.height()
        scale = min((screen_w - margin * 2) / w, (screen_h - margin * 2) / h) * 0.8
        ox = (screen_w - w * scale) / 2
        oy = (screen_h - h * scale) / 2

        n = self.PARTICLE_COUNT
        idxs = random.sample(range(n), min(len(selected), n))
        for i, idx in enumerate(idxs):
            if i < len(selected):
                sy, sx = selected[i]
                self._targets[idx] = [ox + sx * scale, oy + sy * scale]
                self._states[idx] = self.STATE_FIGURING

        self._active_figure = {"name": name, "indices": set(idxs)}
        self._save_figure_sample(name, selected)
        QTimer.singleShot(1500, lambda: self.figure_ready.emit(name))
        return True

    def release_border(self, panel_id: str):
        """Release particles from a border back to idle"""
        if panel_id in self._borders:
            del self._borders[panel_id]
        for i in range(self.PARTICLE_COUNT):
            if self._states[i] == self.STATE_FORMING:
                self._states[i] = self.STATE_IDLE
                self._targets[i] = [random.random() * self.width(),
                                    random.random() * self.height()]

    def release_figure(self):
        """Release figure particles back to idle"""
        if self._active_figure:
            for i in self._active_figure["indices"]:
                self._states[i] = self.STATE_IDLE
                self._targets[i] = [random.random() * self.width(),
                                    random.random() * self.height()]
            self._active_figure = None

    def set_swarm_mode(self, mode: str):
        """Change nanobot behavior: idle, swarm, pulse, construct"""
        n = self.PARTICLE_COUNT
        if mode == "idle":
            pass
        elif mode == "swarm":
            # More energetic movement
            for i in range(n):
                self._vel[i] *= 2.0
        elif mode == "pulse":
            # Synchronized pulsing
            for i in range(n):
                self._phases[i] = i * 0.1 % (math.pi * 2)
        elif mode == "construct":
            # Move to grid formation
            cols = int(math.sqrt(n))
            for i in range(n):
                self._targets[i] = [(i % cols) * 10 + 50, (i // cols) * 10 + 50]
                self._states[i] = self.STATE_FORMING

    def _save_figure_sample(self, name, points):
        try:
            FIGURES_DIR.mkdir(parents=True, exist_ok=True)
            np.save(str(FIGURES_DIR / f"{name}.npy"), points)
        except:
            pass

    def mouseMoveEvent(self, event):
        self._mouse = QPointF(event.position().x(), event.position().y())

    def leaveEvent(self, event):
        self._mouse = QPointF(-9999, -9999)
