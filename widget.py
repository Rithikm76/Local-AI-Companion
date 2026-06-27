import sys
import math
from PyQt5.QtWidgets import (
    QApplication, QWidget, QTextEdit,
    QLineEdit, QPushButton, QFrame,
    QVBoxLayout, QHBoxLayout
)
from PyQt5.QtCore import Qt, QPoint, QTimer
from PyQt5.QtGui import QPainter, QRadialGradient, QColor, QBrush


# ── Dimensions ────────────────────────────────────────
ORB_AREA    = 100   # the square that holds the orb
BUBBLE_W    = 280
BUBBLE_H    = 320
TOTAL_W     = BUBBLE_W + ORB_AREA   # 380 — orb right of bubble... wait
# Actually: bubble left, orb bottom-right
# Total widget when open: width=BUBBLE_W+padding, height=BUBBLE_H+ORB_AREA


class PeriWidget(QWidget):

    def __init__(self):
        super().__init__()

        # ── Window setup ──────────────────────────────
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        # ── Dimensions ────────────────────────────────
        self.orb_size    = 60
        self.orb_padding = 20
        self.orb_area    = self.orb_size + self.orb_padding * 2  # 100
        self.bubble_w    = 280
        self.bubble_h    = 320

        # Expanded widget dimensions
        self.exp_w = self.bubble_w + 20        # 300 — 20px right margin for orb
        self.exp_h = self.bubble_h + self.orb_area  # 420

        # ── Colors ────────────────────────────────────
        self.color_core      = QColor("#4FC3F7")
        self.color_ring      = QColor("#0288D1")
        self.color_highlight = QColor("#E3F2FD")
        self.color_accent    = QColor("#80DEEA")

        # ── State ─────────────────────────────────────
        self._bubble_open    = False
        self._is_thinking    = False
        self._pulse_time     = 0.0
        self._glow_intensity = 0.0
        self._dragging       = False
        self._drag_offset    = QPoint()
        self._brain          = None

        # ── Default position: right side, 1/3 from top ─
        screen = QApplication.primaryScreen().geometry()
        self._closed_x = screen.width() - self.orb_area - 40
        self._closed_y = int(screen.height() * 0.3)
        self.setFixedSize(self.orb_area, self.orb_area)
        self.move(self._closed_x, self._closed_y)

        # ── Build bubble UI ───────────────────────────
        self._build_bubble()

        # ── Pulse timer ───────────────────────────────
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    # ── UI construction ───────────────────────────────

    def _build_bubble(self):
        self.bubble = QFrame(self)
        self.bubble.setFixedSize(self.bubble_w, self.bubble_h)
        self.bubble.setStyleSheet("""
            QFrame {
                background-color: rgba(13, 17, 78, 235);
                border-radius: 16px;
                border: 1px solid rgba(79, 195, 247, 0.35);
            }
        """)
        self.bubble.hide()

        layout = QVBoxLayout(self.bubble)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(8)

        # Chat display
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setStyleSheet("""
            QTextEdit {
                background: transparent;
                color: #E3F2FD;
                font-family: Arial;
                font-size: 13px;
                border: none;
            }
            QScrollBar:vertical {
                background: rgba(255,255,255,0.05);
                width: 4px;
                border-radius: 2px;
            }
            QScrollBar::handle:vertical {
                background: rgba(79,195,247,0.4);
                border-radius: 2px;
            }
        """)
        layout.addWidget(self.chat_display)

        # Input row
        input_frame = QFrame()
        input_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(255,255,255,0.07);
                border-radius: 10px;
            }
        """)
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(10, 4, 4, 4)
        input_layout.setSpacing(6)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Talk to PERI...")
        self.input_field.setStyleSheet("""
            QLineEdit {
                background: transparent;
                color: #E3F2FD;
                font-size: 13px;
                border: none;
                padding: 4px 0;
            }
        """)
        self.input_field.returnPressed.connect(self._send_message)

        send_btn = QPushButton("→")
        send_btn.setFixedSize(30, 30)
        send_btn.setCursor(Qt.PointingHandCursor)
        send_btn.setStyleSheet("""
            QPushButton {
                background-color: #0288D1;
                color: white;
                border-radius: 15px;
                font-size: 15px;
                border: none;
            }
            QPushButton:hover {
                background-color: #4FC3F7;
            }
            QPushButton:pressed {
                background-color: #01579B;
            }
        """)
        send_btn.clicked.connect(self._send_message)

        input_layout.addWidget(self.input_field)
        input_layout.addWidget(send_btn)
        layout.addWidget(input_frame)

    # ── Animation tick ────────────────────────────────

    def _tick(self):
        speed = 0.05 if self._is_thinking else 0.025
        self._pulse_time     += speed
        self._glow_intensity  = (math.sin(self._pulse_time) + 1) / 2

        if self._is_thinking:
            self.color_core = self.color_accent
        else:
            self.color_core = QColor("#4FC3F7")

        self.update()

    # ── Bubble toggle ─────────────────────────────────

    def _toggle_bubble(self):
        self._bubble_open = not self._bubble_open

        if self._bubble_open:
            # Save current orb screen position (top-left of orb area)
            orb_screen = self.mapToGlobal(QPoint(0, 0))

            # Expand widget: bubble above-left, orb bottom-right
            # New widget top-left: move left by bubble_w, move up by bubble_h
            new_x = orb_screen.x() - self.bubble_w + 20
            new_y = orb_screen.y() - self.bubble_h

            # Clamp to screen bounds
            screen = QApplication.primaryScreen().geometry()
            new_x = max(0, min(new_x, screen.width()  - self.exp_w))
            new_y = max(0, min(new_y, screen.height() - self.exp_h))

            self.setFixedSize(self.exp_w, self.exp_h)
            self.move(new_x, new_y)

            # Position bubble at top-left of expanded widget
            self.bubble.move(0, 0)
            self.bubble.show()
            self.input_field.setFocus()

        else:
            # Collapse: find where orb is now (bottom-right of expanded widget)
            orb_screen_x = self.x() + self.exp_w - self.orb_area + 20
            orb_screen_y = self.y() + self.exp_h - self.orb_area

            self.bubble.hide()
            self.setFixedSize(self.orb_area, self.orb_area)
            self.move(orb_screen_x, orb_screen_y)

    # ── Messaging ─────────────────────────────────────

    def _send_message(self):
        text = self.input_field.text().strip()
        if not text:
            return

        self.input_field.clear()
        self.input_field.setEnabled(False)
        self._append_message("You", text, "#E3F2FD")
        self._set_thinking(True)

        if self._brain is None:
            from brain import Brain
            self._brain = Brain()

        self._brain.respond(
            text,
            on_reply=self._on_reply,
            on_error=self._on_error
        )

    def _on_reply(self, reply):
        self._set_thinking(False)
        self._append_message("PERI", reply, "#4FC3F7")
        self.input_field.setEnabled(True)
        self.input_field.setFocus()

    def _on_error(self, error):
        self._set_thinking(False)
        self._append_message("PERI", f"Something went wrong: {error}", "#EF9A9A")
        self.input_field.setEnabled(True)

    def _append_message(self, sender, text, color):
        html = (
            f'<p style="margin:6px 0">'
            f'<span style="color:{color};font-weight:bold">{sender}</span><br>'
            f'<span style="color:#E3F2FD">{text}</span>'
            f'</p>'
        )
        self.chat_display.append(html)

    def _set_thinking(self, thinking):
        self._is_thinking = thinking

    # ── Painting ──────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Orb center: bottom-right of widget
        if self._bubble_open:
            cx = self.exp_w - self.orb_area // 2 + 20
            cy = self.exp_h - self.orb_area // 2
        else:
            cx = self.orb_area // 2
            cy = self.orb_area // 2

        orb_radius = self.orb_size // 2

        # Outer glow
        glow_r = orb_radius + 8 + (self._glow_intensity * 6)
        glow_opacity = 0.2 + (self._glow_intensity * 0.25)

        glow = QRadialGradient(cx, cy, glow_r)
        c1 = QColor(self.color_ring); c1.setAlphaF(glow_opacity)
        c2 = QColor(self.color_ring); c2.setAlphaF(0.0)
        glow.setColorAt(0.5, c1)
        glow.setColorAt(1.0, c2)

        painter.setBrush(QBrush(glow))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(
            int(cx - glow_r), int(cy - glow_r),
            int(glow_r * 2),  int(glow_r * 2)
        )

        # Core orb
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
            cx - orb_radius, cy - orb_radius,
            self.orb_size, self.orb_size
        )

    # ── Mouse events ──────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return

        # Detect if click landed on the orb
        if self._bubble_open:
            cx = self.exp_w - self.orb_area // 2 + 20
            cy = self.exp_h - self.orb_area // 2
        else:
            cx = self.orb_area // 2
            cy = self.orb_area // 2

        dx = event.x() - cx
        dy = event.y() - cy
        on_orb = (dx * dx + dy * dy) <= (self.orb_size // 2) ** 2

        if on_orb:
            self._toggle_bubble()
        else:
            self._dragging = True
            self._drag_offset = event.globalPos() - self.frameGeometry().topLeft()

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
