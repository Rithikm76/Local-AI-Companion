import sys
import math
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QPoint, QTimer
from PyQt5.QtGui import QPainter, QRadialGradient, QColor, QBrush


class PeriWidget(QWidget):

    def __init__(self):
        super().__init__()

        # ── Window flags ──────────────────────────────
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        # ── Size ──────────────────────────────────────
        self.orb_size = 60
        self.padding = 20
        self.setFixedSize(
            self.orb_size + self.padding * 2,
            self.orb_size + self.padding * 2
        )

        # ── Colors ────────────────────────────────────
        self.color_core = QColor("#4FC3F7")
        self.color_ring = QColor("#0288D1")
        self.color_highlight = QColor("#E3F2FD")

        # ── State ─────────────────────────────────────
        self._pulse_time = 0.0
        self._glow_intensity = 0.0
        self._dragging = False
        self._drag_offset = QPoint()

        # ── Default position: top right ───────────────
        screen = QApplication.primaryScreen().geometry()
        x = screen.width() - self.width() - 40
        y = 120
        self.move(x, y)

        # ── Pulse timer ───────────────────────────────
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)  # ~60fps

    # ── Animation tick ────────────────────────────────

    def _tick(self):
        self._pulse_time += 0.025
        # sine wave: oscillates smoothly between 0.0 and 1.0
        self._glow_intensity = (math.sin(self._pulse_time) + 1) / 2
        self.update()  # triggers paintEvent

    # ── Drawing ───────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        cx = self.width() // 2
        cy = self.height() // 2
        orb_radius = self.orb_size // 2

        # Outer glow — size and opacity pulse with sine wave
        glow_radius = orb_radius + 8 + (self._glow_intensity * 6)
        glow_opacity = 0.2 + (self._glow_intensity * 0.25)

        glow = QRadialGradient(cx, cy, glow_radius)
        ring_inner = QColor(self.color_ring)
        ring_inner.setAlphaF(glow_opacity)
        ring_outer = QColor(self.color_ring)
        ring_outer.setAlphaF(0.0)
        glow.setColorAt(0.5, ring_inner)
        glow.setColorAt(1.0, ring_outer)

        painter.setBrush(QBrush(glow))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(
            int(cx - glow_radius),
            int(cy - glow_radius),
            int(glow_radius * 2),
            int(glow_radius * 2)
        )

        # Core orb — radial gradient, off-center highlight
        core = QRadialGradient(
            cx - orb_radius * 0.3,
            cy - orb_radius * 0.3,
            orb_radius
        )
        core.setColorAt(0.0, self.color_highlight)
        core.setColorAt(0.4, self.color_core)
        core.setColorAt(1.0, self.color_ring)

        painter.setBrush(QBrush(core))
        painter.drawEllipse(
            cx - orb_radius,
            cy - orb_radius,
            self.orb_size,
            self.orb_size
        )

    # ── Dragging ──────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_offset = (
                event.globalPos() - self.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.move(event.globalPos() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False


# ── Entry point ───────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    peri = PeriWidget()
    peri.show()
    sys.exit(app.exec_())
