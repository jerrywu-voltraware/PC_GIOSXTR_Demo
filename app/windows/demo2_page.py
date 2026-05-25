"""Demo2 page ??port of Flutter ChargingStatusPage2.

Shows a vehicle (Bike / Scooter / No Device), animated wireless charging base,
energy flow into the vehicle battery, a battery percentage panel with a
flashing animation, and engineering-mode buttons for manual scenario testing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QLinearGradient,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..models import DeviceState
from ..resources import resource_path

_LOGO_PATH = "assets/Logo2.png"


class EngMode(Enum):
    NONE = auto()
    CHARGING_SCOOTER = auto()
    CHARGING_BIKE = auto()
    FULL_SCOOTER = auto()
    FULL_BIKE = auto()
    STANDBY_SCOOTER = auto()
    STANDBY_BIKE = auto()
    ENGINEERING = auto()
    NOT_CHARGING = auto()


_BIKE_TABLE = (
    (4518, 9), (4535, 10), (4608, 15), (4661, 20), (4698, 25), (4732, 30),
    (4766, 35), (4811, 40), (4861, 45), (4925, 50), (4994, 55), (5051, 60),
    (5097, 65), (5139, 70), (5197, 75), (5311, 83), (5325, 85), (5344, 90),
    (5353, 92), (5368, 97), (5380, 100),
)

_SCOOTER_TABLE = (
    (3348, 3), (3476, 5), (3592, 10), (3633, 15), (3686, 20), (3734, 25),
    (3775, 30), (3805, 35), (3839, 40), (3878, 45), (3912, 50), (3945, 55),
    (3970, 60), (4018, 65), (4048, 70), (4092, 75), (4131, 80), (4179, 85),
    (4194, 90), (4203, 95), (4223, 100),
)


@dataclass
class _Snapshot:
    pru_type: str
    pru_reg_state: int
    pru_vout: int
    pru_iout: int


def _battery_pct(pru_type: str, vout: int) -> int:
    if pru_type == "0403V1":
        table = _BIKE_TABLE
    elif pru_type == "0404V1":
        table = _SCOOTER_TABLE
    else:
        return 0
    for v_thresh, pct in reversed(table):
        if vout >= v_thresh:
            return pct
    return 0


class _VehicleStage(QWidget):
    """Custom-painted area: glow ring, charging pad, vehicle, energy flow."""

    def __init__(self, *, showcase_mode: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(280, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._showcase_mode = showcase_mode
        self._progress = 0.0
        self._snapshot = _Snapshot("", 0, 0, 0)
        self._is_charging = False
        self._is_full = False
        self._is_engineering = False
        self._show_pad = False
        self._is_bike = False
        self._pru_connected = False

        self._pix_bike = self._load("assets/e-bike.png", remove_white=True) or self._load("app/assets/GIOS0403.png")
        self._pix_scooter = self._load("assets/e-scooter.png", remove_white=True) or self._load("app/assets/GIOS0404.png")
        self._pix_none = self._load("app/assets/No_device_clean.png")
        self._pix_pad = self._load("assets/charging_device.png", remove_white=True)
        # Battery icon position within the vehicle image (x_frac, y_frac).
        self._battery_bike = (0.55, 0.50)
        self._battery_scooter = (0.45, 0.65)
        # Last vehicle draw rect (set during _draw_vehicle, used by _draw_energy_flow).
        self._vehicle_rect: QRectF | None = None
        # Front-wheel anchor as a fraction of the rendered image (x_frac, y_frac).
        # The x value is the front wheel center; the y value is the tire bottom.
        self._front_wheel_bike = (0.77, 0.81)
        self._front_wheel_scooter = (0.76, 0.83)

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(33)
        self._anim_timer.timeout.connect(self._tick)

    @staticmethod
    def _load(rel: str, *, remove_white: bool = False) -> QPixmap | None:
        path = resource_path(rel)
        if not path.exists():
            return None
        if not remove_white:
            pix = QPixmap(str(path))
            return pix if not pix.isNull() else None
        img = QImage(str(path))
        if img.isNull():
            return None
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
        threshold = 235
        ptr = img.bits()
        ptr.setsize(img.sizeInBytes())
        buf = bytearray(ptr.asstring())
        # ARGB32 little-endian in memory: B, G, R, A
        for i in range(0, len(buf), 4):
            if buf[i] >= threshold and buf[i + 1] >= threshold and buf[i + 2] >= threshold:
                buf[i + 3] = 0
        ptr[: len(buf)] = bytes(buf)
        return QPixmap.fromImage(img)

    def update_state(
        self,
        snapshot: _Snapshot,
        *,
        is_charging: bool,
        is_full: bool,
        is_engineering: bool,
        show_pad: bool,
        is_bike: bool,
        pru_connected: bool,
    ) -> None:
        self._snapshot = snapshot
        self._is_charging = is_charging
        self._is_full = is_full
        self._is_engineering = is_engineering
        self._show_pad = show_pad
        self._is_bike = is_bike
        self._pru_connected = pru_connected
        if is_charging or is_full or is_engineering:
            if not self._anim_timer.isActive():
                self._anim_timer.start()
        else:
            self._anim_timer.stop()
            self._progress = 0.0
        self.update()

    def _tick(self) -> None:
        self._progress = (self._progress + 0.02) % 1.0
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = float(self.width())
        h = float(self.height())

        pulse = (
            (math.sin(self._progress * math.pi * 2 - math.pi / 2) + 1) / 2
            if (self._is_charging or self._is_engineering)
            else (0.35 + 0.65 * self._progress if self._is_full else 0.0)
        )

        # Ground oval
        ground_cx = w * 0.50
        ground_cy = h * 0.76
        ground_w = w * 0.72
        ground_h = h * 0.17
        ground_rect = QRectF(ground_cx - ground_w / 2, ground_cy - ground_h / 2, ground_w, ground_h)
        grad_g = QRadialGradient(QPointF(ground_cx, ground_cy), max(ground_w, ground_h) / 2)
        grad_g.setColorAt(0.0, QColor(27, 199, 184, int(255 * (0.12 + 0.08 * pulse))))
        grad_g.setColorAt(0.5, QColor(27, 199, 184, int(255 * 0.04)))
        grad_g.setColorAt(1.0, QColor(27, 199, 184, 0))
        p.setBrush(QBrush(grad_g))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(ground_rect)

        # Halo
        center = QPointF(w / 2, h * 0.50)
        radius = w * (0.56 + 0.18 * pulse) if self._is_full else w * (0.42 + 0.14 * pulse)
        peak_a = (0.12 + 0.26 * pulse) if self._is_full else (0.14 + 0.28 * pulse)
        mid_a = (0.08 + 0.18 * pulse) if self._is_full else (0.06 + 0.16 * pulse)
        grad = QRadialGradient(center, radius)
        c0 = QColor(46, 204, 113) if self._is_full else QColor(37, 199, 183)
        c1 = QColor(123, 216, 143) if self._is_full else QColor(118, 243, 223)
        c2 = QColor(216, 248, 223) if self._is_full else QColor(230, 255, 250)
        c0.setAlpha(int(255 * peak_a))
        c1.setAlpha(int(255 * mid_a))
        c2.setAlpha(int(255 * mid_a * 0.35))
        grad.setColorAt(0.0, c0)
        grad.setColorAt(0.40, c1)
        grad.setColorAt(0.70, c2)
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(grad))
        p.drawEllipse(center, radius, radius)

        # Charging pad + waves are drawn before the vehicle so the tire stays
        # in front of the charger, matching the physical layering.
        if self._show_pad:
            self._draw_pad(p, w, h, pulse)

        # Vehicle
        self._draw_vehicle(p, w, h)

        # Energy flow into vehicle
        if self._is_charging and not self._is_full and self._pru_connected:
            self._draw_energy_flow(p, w, h)

        p.end()

    def _selected_vehicle(self) -> tuple[QPixmap | None, str, tuple[float, float] | None, tuple[float, float]]:
        center_frac = (0.50, 0.50)
        if not self._pru_connected:
            return None, "No Device", None, center_frac
        if self._snapshot.pru_type == "0403V1":
            return self._pix_bike, "E-Bike", self._front_wheel_bike, (0.50, 0.493)
        if self._snapshot.pru_type == "0404V1":
            return self._pix_scooter, "E-Scooter", self._front_wheel_scooter, (0.508, 0.50)
        return None, "Engineering", None, center_frac

    def _vehicle_layout(
        self,
        w: float,
        h: float,
        pix: QPixmap,
        center_frac: tuple[float, float],
        front_frac: tuple[float, float] | None = None,
    ) -> tuple[QPixmap, QRectF]:
        target_w = w * (0.84 if self._showcase_mode else 0.80)
        target_h = h * (0.78 if self._showcase_mode else 0.78)
        scaled = pix.scaled(
            int(target_w),
            int(target_h),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if front_frac is not None:
            pad_rect = self._pad_rect(w, h)
            target_anchor_x = pad_rect.left() + pad_rect.width() * 0.42
            target_anchor_y = pad_rect.bottom() - h * 0.005
            fx, fy = front_frac
            x = target_anchor_x - scaled.width() * fx
            y = target_anchor_y - scaled.height() * fy
        else:
            center_x = w * 0.50
            center_y = h * (0.56 if self._showcase_mode else 0.58)
            cx, cy = center_frac
            x = center_x - scaled.width() * cx
            y = center_y - scaled.height() * cy
        return scaled, QRectF(x, y, scaled.width(), scaled.height())

    def _draw_vehicle(self, p: QPainter, w: float, h: float) -> None:
        pix, label_fallback, front_frac, center_frac = self._selected_vehicle()
        if pix is not None:
            scaled, rect = self._vehicle_layout(w, h, pix, center_frac, front_frac)
            p.drawPixmap(int(rect.left()), int(rect.top()), scaled)
            self._vehicle_rect = rect
        else:
            self._vehicle_rect = None
            p.setPen(QPen(QColor("#E67E22"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            font = QFont(p.font())
            font.setPointSize(16)
            font.setBold(True)
            p.setFont(font)
            p.drawText(QRectF(0, h * 0.35, w, 40), Qt.AlignmentFlag.AlignCenter, label_fallback)

    def _pad_rect(self, w: float, h: float) -> QRectF:
        pad_cx = w * (0.72 if self._showcase_mode else 0.72)
        pad_cy = h * (0.60 if self._showcase_mode else 0.68)
        pad_w = w * (0.13 if self._showcase_mode else 0.15)
        pad_h = h * (0.32 if self._showcase_mode else 0.36)
        return QRectF(pad_cx - pad_w / 2, pad_cy - pad_h / 2, pad_w, pad_h)

    def _draw_pad(self, p: QPainter, w: float, h: float, pulse: float) -> None:
        pad_rect = self._pad_rect(w, h)
        pad_cx = pad_rect.center().x()
        pad_cy = pad_rect.center().y()

        if self._pix_pad is not None:
            scaled = self._pix_pad.scaled(
                int(pad_rect.width()),
                int(pad_rect.height()),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = pad_cx - scaled.width() / 2
            y = pad_rect.bottom() - scaled.height()
            p.drawPixmap(int(x), int(y), scaled)
        else:
            grad = QLinearGradient(pad_rect.left(), pad_rect.top(), pad_rect.right(), pad_rect.top())
            grad.setColorAt(0.0, QColor(0x9B, 0x74, 0x44))
            grad.setColorAt(0.5, QColor(0xC7, 0x9A, 0x5B))
            grad.setColorAt(1.0, QColor(0x8A, 0x63, 0x38))
            p.setBrush(QBrush(grad))
            p.setPen(QPen(QColor(0x5D, 0x4A, 0x35, int(255 * 0.92)), 2))
            p.drawRoundedRect(pad_rect, 14, 14)
            icon_color = QColor(0x00, 0xA6, 0xC8, int(255 * 0.92))
            cx = pad_rect.center().x()
            cy = pad_rect.top() + pad_rect.height() * 0.27
            r = pad_rect.width() * 0.30
            p.setPen(QPen(icon_color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            arc_rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
            p.drawArc(arc_rect, int(202 * 16), int(280 * 16))
            bolt = QPainterPath()
            rw = pad_rect.width()
            rh = pad_rect.height()
            bolt.moveTo(cx + rw * 0.02, cy - rh * 0.10)
            bolt.lineTo(cx - rw * 0.08, cy + rh * 0.02)
            bolt.lineTo(cx + rw * 0.01, cy + rh * 0.02)
            bolt.lineTo(cx - rw * 0.04, cy + rh * 0.13)
            bolt.lineTo(cx + rw * 0.10, cy - rh * 0.03)
            bolt.lineTo(cx + rw * 0.02, cy - rh * 0.03)
            bolt.closeSubpath()
            p.setBrush(QBrush(icon_color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPath(bolt)

        # Wave arcs
        if not self._is_full:
            for i in range(3):
                wave_t = ((self._progress + i / 3) % 1.0) if self._is_charging else i / 3
                alpha = (1.0 - wave_t) * 0.55 if self._is_charging else 0.18
                color = QColor(0x18, 0xFF, 0xFF, int(255 * alpha))
                p.setPen(QPen(color, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.setBrush(Qt.BrushStyle.NoBrush)
                wave_w = w * (0.10 + 0.22 * wave_t)
                wave_h = h * (0.16 + 0.22 * wave_t)
                wcx = pad_cx - w * 0.02 * wave_t
                wave_rect = QRectF(wcx - wave_w / 2, pad_cy - wave_h / 2, wave_w, wave_h)
                p.drawArc(wave_rect, int(112 * 16), int(137 * 16))

    def _draw_energy_flow(self, p: QPainter, w: float, h: float) -> None:
        if self._vehicle_rect is None:
            return
        pad_rect = self._pad_rect(w, h)
        vr = self._vehicle_rect

        def vpt(fx: float, fy: float) -> QPointF:
            return QPointF(vr.left() + vr.width() * fx,
                           vr.top() + vr.height() * fy)

        if self._is_bike:
            # Front wheel/fork -> head tube -> battery icon on the down tube.
            front_hub = vpt(0.775, 0.60)
            fork_lower = vpt(0.746, 0.527)
            fork_upper = vpt(0.721, 0.453)
            head_tube = vpt(0.693, 0.379)
            top_tube = vpt(0.669, 0.343)
            frame_bend = vpt(0.641, 0.372)
            battery_entry = vpt(0.602, 0.442)
            node = vpt(0.55, 0.50)
            waypoints = [
                front_hub,
                fork_lower,
                fork_upper,
                head_tube,
                top_tube,
                frame_bend,
                battery_entry,
                node,
            ]
        else:
            front_hub = vpt(0.76, 0.70)
            bend = vpt(0.55, 0.65)
            node = vpt(0.50, 0.745)
            waypoints = [front_hub, bend, node]

        p.setBrush(Qt.BrushStyle.NoBrush)

        # Reverse-explosion charge effect: many solid particles start from a wide field
        # around the bike and collapse inward to the battery.
        ring_count = 48
        for i in range(ring_count):
            t = (self._progress * 0.62 + i / ring_count) % 1.0
            ease = 1.0 - (1.0 - t) ** 2
            outward = 1.0 - ease
            angle = i * 2.39996 + self._progress * math.pi * 0.18
            shell = 0.58 + 0.42 * ((i * 37) % ring_count) / (ring_count - 1)
            wobble = math.sin((self._progress * 1.6 + i * 0.23) * math.pi * 2)
            radius_x = w * (0.055 + 0.135 * shell) * outward
            radius_y = h * (0.050 + 0.135 * shell) * outward
            pt = QPointF(
                node.x() + math.cos(angle) * radius_x + wobble * w * 0.010 * outward,
                node.y() + math.sin(angle) * radius_y - wobble * h * 0.008 * outward,
            )

            pulse = 0.72 + 0.34 * math.sin((self._progress * 1.4 + i / ring_count) * math.pi * 2)
            size_mix = 0.72 + 0.46 * (((i * 19) % ring_count) / (ring_count - 1))
            dot_r = (2.4 + 8.8 * outward) * pulse * size_mix
            glow_r = dot_r + 5.2
            alpha = int(255 * (0.36 + 0.56 * outward))

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(0x18, 0xFF, 0xFF, int(alpha * 0.18))))
            p.drawEllipse(pt, glow_r, glow_r)

            p.setBrush(QBrush(QColor(0x18, 0xFF, 0xFF, alpha)))
            p.drawEllipse(pt, dot_r, dot_r)

        # Battery node
        p.setBrush(QBrush(QColor(0x18, 0xFF, 0xFF, int(255 * 0.28))))
        p.drawEllipse(node, 12, 12)
        p.setBrush(QBrush(QColor(0x18, 0xFF, 0xFF, int(255 * 0.82))))
        p.drawEllipse(node, 5, 5)
        p.setBrush(QBrush(QColor(255, 255, 255)))
        p.drawEllipse(node, 2.2, 2.2)


class _BatteryIcon(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(40, 90)
        self._pct = 0

    def set_pct(self, pct: int) -> None:
        self._pct = max(0, min(100, pct))
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = self.width()
        h = self.height()
        cap_w = int(w * 0.45)
        cap_h = 6
        cap_rect = QRectF((w - cap_w) / 2, 0, cap_w, cap_h)
        body_rect = QRectF(2, cap_h, w - 4, h - cap_h - 2)
        p.setBrush(QBrush(QColor("#4C5A5D")))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(cap_rect, 2, 2)
        p.setBrush(QBrush(QColor("#FFFFFF")))
        p.setPen(QPen(QColor("#4C5A5D"), 2))
        p.drawRoundedRect(body_rect, 4, 4)

        inner = body_rect.adjusted(3, 3, -3, -3)
        fill_h = inner.height() * self._pct / 100.0
        fill_rect = QRectF(inner.left(), inner.bottom() - fill_h, inner.width(), fill_h)
        if self._pct >= 60:
            color = QColor("#27AE60")
        elif self._pct >= 25:
            color = QColor("#F1C40F")
        else:
            color = QColor("#E74C3C")
        p.setBrush(QBrush(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(fill_rect, 3, 3)


def _make_logo_label(*, height: int) -> QLabel:
    label = QLabel()
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    pix = QPixmap(str(resource_path(_LOGO_PATH)))
    if not pix.isNull():
        scaled = pix.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(scaled)
        label.setFixedSize(scaled.size())
    else:
        label.setText("VOLTRAWARE")
        label.setStyleSheet("font-size: 22px; font-weight: 800; color: #1F77B4;")
    return label


class _ShowcaseDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("全螢幕模式")
        self.setStyleSheet("background-color: #FBFCFD;")
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.logo_label = _make_logo_label(height=64)
        top.addWidget(self.logo_label, 0, Qt.AlignmentFlag.AlignLeft)
        top.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(96)
        cancel_btn.clicked.connect(self.reject)
        top.addWidget(cancel_btn)
        root.addLayout(top)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(24)

        self.panel = QFrame()
        self._panel_style = (
            "QFrame { background: rgba(255, 255, 255, 235); "
            "border: 2px solid #DCEAE8; border-radius: 16px; }"
        )
        self._panel_empty_style = "QFrame { background: transparent; border: 0; }"
        self.panel.setStyleSheet(self._panel_style)
        self.panel.setFixedSize(520, 190)
        panel_layout = QHBoxLayout(self.panel)
        self.panel_layout = panel_layout
        panel_layout.setContentsMargins(26, 20, 26, 20)
        panel_layout.setSpacing(24)
        self.battery_icon = _BatteryIcon()
        self.battery_icon.setFixedSize(72, 150)
        panel_layout.addWidget(self.battery_icon)
        text_col = QVBoxLayout()
        self.panel_text_col = text_col
        text_col.setSpacing(8)
        self.device_label = QLabel("-")
        self.device_label.setStyleSheet("font-size: 16px; color: #546E7A; font-weight: 800;")
        self.pct_label = QLabel("0%")
        self.pct_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.pct_label.setStyleSheet("font-size: 74px; font-weight: 800; color: #202124;")
        self.status_label = QLabel("Standby")
        self.status_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #4C5A5D;")
        self.detail_label = QLabel("Ready")
        self.detail_label.setStyleSheet("font-size: 17px; color: #78909C; font-weight: 700;")
        text_col.addWidget(self.device_label)
        text_col.addWidget(self.pct_label)
        text_col.addWidget(self.status_label)
        text_col.addStretch(1)
        text_col.addWidget(self.detail_label)
        panel_layout.addLayout(text_col, 1)

        self.left_rail = QWidget()
        self.left_rail.setFixedWidth(600)
        left_layout = QVBoxLayout(self.left_rail)
        left_layout.setContentsMargins(32, 0, 20, 0)
        left_layout.addStretch(2)
        left_layout.addWidget(self.panel, 0, Qt.AlignmentFlag.AlignHCenter)
        left_layout.addStretch(3)

        self.stage = _VehicleStage(showcase_mode=True)
        body_layout.addWidget(self.left_rail)
        body_layout.addWidget(self.stage, 1)
        root.addWidget(body, 1)
        self._resize_showcase_elements()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_showcase_elements()

    def _resize_showcase_elements(self) -> None:
        width = max(1, self.width())
        height = max(1, self.height())
        rail_w = max(460, min(620, int(width * 0.29)))
        panel_w = max(420, min(540, rail_w - 70, int(width * 0.25)))
        panel_h = max(198, min(244, int(panel_w * 0.45), int(height * 0.25)))
        icon_w = max(58, min(76, int(panel_w * 0.14)))
        icon_h = max(124, min(panel_h - 36, int(icon_w * 2.05)))
        pct_px = max(58, min(78, int(panel_w * 0.14)))
        device_px = max(18, min(24, int(panel_w * 0.043)))
        status_px = max(16, min(21, int(panel_w * 0.038)))
        detail_px = max(14, min(18, int(panel_w * 0.032)))

        self.left_rail.setFixedWidth(rail_w)
        self.panel.setFixedSize(panel_w, panel_h)
        self.panel_layout.setContentsMargins(24, 18, 24, 18)
        self.panel_layout.setSpacing(max(18, int(panel_w * 0.045)))
        self.panel_text_col.setSpacing(max(5, int(panel_h * 0.035)))
        self.battery_icon.setFixedSize(icon_w, icon_h)
        self.device_label.setStyleSheet(f"font-size: {device_px}px; color: #546E7A; font-weight: 800;")
        self.device_label.setMinimumHeight(int(device_px * 1.45))
        self.pct_label.setStyleSheet(f"font-size: {pct_px}px; font-weight: 800; color: #202124;")
        self.pct_label.setMinimumHeight(int(pct_px * 1.55))
        self.status_label.setStyleSheet(f"font-size: {status_px}px; font-weight: 800; color: #4C5A5D;")
        self.detail_label.setStyleSheet(f"font-size: {detail_px}px; color: #78909C; font-weight: 700;")

    def apply_snapshot(
        self,
        snapshot: _Snapshot,
        *,
        is_charging: bool,
        is_full: bool,
        is_engineering: bool,
        show_pad: bool,
        is_bike: bool,
        pru_connected: bool,
        pct: int,
        icon_pct: int,
        show_panel: bool,
        device_text: str,
        status_text: str,
        detail_text: str,
    ) -> None:
        self.stage.update_state(
            snapshot,
            is_charging=is_charging,
            is_full=is_full,
            is_engineering=is_engineering,
            show_pad=show_pad,
            is_bike=is_bike,
            pru_connected=pru_connected,
        )
        self.panel.setStyleSheet(self._panel_style if show_panel else self._panel_empty_style)
        self.battery_icon.setVisible(show_panel)
        self.device_label.setVisible(show_panel)
        self.pct_label.setVisible(show_panel)
        self.status_label.setVisible(show_panel)
        self.detail_label.setVisible(show_panel)
        self.battery_icon.set_pct(icon_pct)
        self.device_label.setText(device_text)
        self.pct_label.setText(f"{pct}%")
        self.status_label.setText(status_text)
        self.detail_label.setText(detail_text)


class _ShowcaseTile(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "QFrame { background: rgba(255, 255, 255, 210); "
            "border: 1px solid #DCEAE8; border-radius: 12px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.stage = _VehicleStage(showcase_mode=True)
        layout.addWidget(self.stage, 1)

        panel = QFrame()
        panel.setStyleSheet("QFrame { background: white; border: 1px solid #E8F1EF; border-radius: 8px; }")
        panel_layout = QHBoxLayout(panel)
        panel_layout.setContentsMargins(12, 8, 12, 8)
        panel_layout.setSpacing(12)
        self.battery_icon = _BatteryIcon()
        self.battery_icon.setFixedSize(42, 90)
        panel_layout.addWidget(self.battery_icon)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        self.device_label = QLabel("-")
        self.device_label.setStyleSheet("font-size: 17px; color: #546E7A; font-weight: 800;")
        self.pct_label = QLabel("0%")
        self.pct_label.setMinimumHeight(52)
        self.pct_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.pct_label.setStyleSheet("font-size: 42px; font-weight: 800; color: #202124;")
        self.status_label = QLabel("Standby")
        self.status_label.setStyleSheet("font-size: 13px; font-weight: 800; color: #4C5A5D;")
        self.detail_label = QLabel("Ready")
        self.detail_label.setStyleSheet("font-size: 12px; color: #78909C; font-weight: 700;")
        for label in (self.device_label, self.status_label, self.detail_label):
            label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        text_col.addWidget(self.device_label)
        text_col.addWidget(self.pct_label)
        text_col.addWidget(self.status_label)
        text_col.addWidget(self.detail_label)
        panel_layout.addLayout(text_col, 1)
        layout.addWidget(panel)

    def apply_snapshot(
        self,
        snapshot: _Snapshot,
        *,
        is_charging: bool,
        is_full: bool,
        is_engineering: bool,
        show_pad: bool,
        is_bike: bool,
        pru_connected: bool,
        pct: int,
        icon_pct: int,
        device_text: str,
        status_text: str,
        detail_text: str,
    ) -> None:
        self.stage.update_state(
            snapshot,
            is_charging=is_charging,
            is_full=is_full,
            is_engineering=is_engineering,
            show_pad=show_pad,
            is_bike=is_bike,
            pru_connected=pru_connected,
        )
        self.battery_icon.set_pct(icon_pct)
        self.device_label.setText(device_text)
        self.pct_label.setText(f"{pct}%")
        self.status_label.setText(status_text)
        self.detail_label.setText(detail_text)


class _MultiShowcaseDialog(QDialog):
    def __init__(self, *, layout_mode: str, addresses: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("全螢幕模式")
        self.setStyleSheet("background-color: #FBFCFD;")
        self.layout_mode = layout_mode
        self.addresses = addresses[:4]
        self.tiles: dict[str, _ShowcaseTile] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(10)

        top = QHBoxLayout()
        self.logo_label = _make_logo_label(height=64)
        top.addWidget(self.logo_label, 0, Qt.AlignmentFlag.AlignLeft)
        top.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(112)
        cancel_btn.clicked.connect(self.reject)
        top.addWidget(cancel_btn)
        root.addLayout(top)

        self.grid = QGridLayout()
        self.grid.setContentsMargins(18, 10, 18, 18)
        self.grid.setSpacing(14)
        root.addLayout(self.grid, 1)
        self._build_grid()

    def _grid_shape(self) -> tuple[int, int, int]:
        count = max(1, min(4, len(self.addresses)))
        mode = self.layout_mode
        if mode == "single":
            return 1, 1, 1
        if mode == "split":
            return 1, 2, min(count, 2)
        if mode == "quad":
            return 2, 2, count
        if count == 1:
            return 1, 1, 1
        if count == 2:
            return 1, 2, 2
        return 2, 2, count

    def _build_grid(self) -> None:
        rows, cols, shown = self._grid_shape()
        for row in range(rows):
            self.grid.setRowStretch(row, 1)
        for col in range(cols):
            self.grid.setColumnStretch(col, 1)
        for index, address in enumerate(self.addresses[:shown]):
            tile = _ShowcaseTile()
            self.tiles[address] = tile
            self.grid.addWidget(tile, index // cols, index % cols)
        for index in range(shown, rows * cols):
            filler = QLabel("VOLTRAWARE")
            filler.setAlignment(Qt.AlignmentFlag.AlignCenter)
            filler.setStyleSheet("font-size: 26px; font-weight: 800; color: #D6E6E8;")
            self.grid.addWidget(filler, index // cols, index % cols)

    def apply_payloads(self, payloads: dict[str, dict[str, object]]) -> None:
        for address, tile in self.tiles.items():
            payload = payloads.get(address)
            if payload is None:
                continue
            tile.apply_snapshot(**payload)


class _ShowcaseChooserDialog(QDialog):
    def __init__(self, entries: list[tuple[str, str]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("全螢幕模式設定")
        self.setMinimumWidth(420)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel("選擇要顯示的 PTU")
        title.setStyleSheet("font-size: 15px; font-weight: 800; color: #102A33;")
        root.addWidget(title)

        self.checks: dict[str, QCheckBox] = {}
        for index, (address, label) in enumerate(entries):
            check = QCheckBox(label)
            check.setChecked(index < 4)
            self.checks[address] = check
            root.addWidget(check)

        self.layout_combo = QComboBox()
        self.layout_combo.addItem("自動", "auto")
        self.layout_combo.addItem("單台", "single")
        self.layout_combo.addItem("左右分割", "split")
        self.layout_combo.addItem("四宮格", "quad")
        root.addWidget(QLabel("版面"))
        root.addWidget(self.layout_combo)

        hint = QLabel("第一版最多同時顯示 4 台。超過 4 台請先取消部分裝置。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #66757C;")
        root.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        start_btn = buttons.addButton("開始全螢幕模式", QDialogButtonBox.ButtonRole.AcceptRole)
        start_btn.clicked.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def selected_addresses(self) -> list[str]:
        return [address for address, check in self.checks.items() if check.isChecked()]

    def selected_layout_mode(self) -> str:
        return str(self.layout_combo.currentData() or "auto")

    def _accept_if_valid(self) -> None:
        selected = self.selected_addresses()
        if not selected:
            return
        if len(selected) > 4:
            return
        self.accept()


class Demo2Page(QWidget):
    def __init__(
        self,
        *,
        engineering_mode: bool = False,
        demo_use_fake_data: bool = True,
        demo_device_name: str = "MMEU",
        demo_ebike_pct: int = 76,
        demo_escooter_pct: int = 81,
        demo_device_battery_pcts: dict[str, int] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setStyleSheet("background-color: #FBFCFD;")
        self._engineering_mode_enabled = engineering_mode
        self._demo_use_fake_data = demo_use_fake_data
        self._demo_device_name = demo_device_name.strip() or "MMEU"
        self._demo_ebike_pct = self._clamp_pct(demo_ebike_pct)
        self._demo_escooter_pct = self._clamp_pct(demo_escooter_pct)
        self._demo_device_battery_pcts = self._clean_device_pcts(demo_device_battery_pcts or {})
        self._preview_device_name = ""
        self._preview_device_number: int | None = None
        self._eng_mode = EngMode.NONE
        self._battery_flash_state = False
        self._battery_pct_cached = 0
        self._showcase_states: dict[str, DeviceState] = {}
        self._showcase_active_address = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.logo_label = _make_logo_label(height=48)
        header.addWidget(self.logo_label, 0, Qt.AlignmentFlag.AlignLeft)
        header.addStretch(1)
        self.showcase_btn = QToolButton()
        self.showcase_btn.setText("⛶")
        self.showcase_btn.setToolTip("全螢幕模式")
        self.showcase_btn.setAutoRaise(True)
        self.showcase_btn.clicked.connect(self._open_showcase)
        header.addWidget(self.showcase_btn)
        root.addLayout(header)

        self.stage = _VehicleStage()
        root.addWidget(self.stage, 1)
        self._showcase_dialog: _ShowcaseDialog | _MultiShowcaseDialog | None = None

        self.panel = QFrame()
        self._panel_style = "QFrame { background: white; border: 1px solid #E8F1EF; border-radius: 8px; }"
        self._panel_empty_style = "QFrame { background: transparent; border: 0; }"
        self.panel.setStyleSheet(self._panel_style)
        self.panel.setFixedHeight(156)
        panel_layout = QHBoxLayout(self.panel)
        panel_layout.setContentsMargins(16, 12, 16, 12)
        self.battery_icon = _BatteryIcon()
        panel_layout.addWidget(self.battery_icon)
        panel_layout.addSpacing(14)
        text_col = QVBoxLayout()
        self.device_label = QLabel("-")
        self.device_label.setMinimumHeight(24)
        self.device_label.setStyleSheet("font-size: 16px; color: #546E7A; font-weight: 800;")
        self.pct_label = QLabel("0%")
        self.pct_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.pct_label.setMinimumHeight(60)
        self.pct_label.setStyleSheet("font-size: 36px; font-weight: 800; color: #202124;")
        self.status_label = QLabel("Standby")
        self.status_label.setStyleSheet("font-size: 12px; font-weight: 700; color: #4C5A5D;")
        self.detail_label = QLabel("Ready")
        self.detail_label.setStyleSheet("font-size: 11px; color: #90A4AE; font-weight: 600;")
        text_col.addWidget(self.device_label)
        text_col.addWidget(self.pct_label)
        text_col.addWidget(self.status_label)
        text_col.addStretch(1)
        text_col.addWidget(self.detail_label)
        panel_layout.addLayout(text_col, 1)
        root.addWidget(self.panel)

        # Internal engineering controls. Hidden unless the app is launched with
        # engineering mode enabled.
        self.engineering_controls = QWidget()
        eng_row = QHBoxLayout(self.engineering_controls)
        eng_row.setContentsMargins(0, 0, 0, 0)
        eng_row.setSpacing(6)
        self._eng_buttons: dict[EngMode, QPushButton] = {}
        for mode, label in (
            (EngMode.CHARGING_SCOOTER, "Scooter Charging"),
            (EngMode.CHARGING_BIKE, "Bike Charging"),
            (EngMode.FULL_SCOOTER, "Scooter Full"),
            (EngMode.FULL_BIKE, "Bike Full"),
            (EngMode.STANDBY_SCOOTER, "Scooter Standby"),
            (EngMode.STANDBY_BIKE, "Bike Standby"),
            (EngMode.ENGINEERING, "Engineering"),
            (EngMode.NOT_CHARGING, "No Device"),
        ):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked, m=mode: self._set_eng_mode(m))
            self._eng_buttons[mode] = btn
            eng_row.addWidget(btn)
        clear_btn = QPushButton("Clear (Live Data)")
        clear_btn.clicked.connect(lambda: self._set_eng_mode(EngMode.NONE))
        eng_row.addWidget(clear_btn)
        root.addWidget(self.engineering_controls)
        self.engineering_controls.setVisible(self._engineering_mode_enabled)

        self._restyle_eng_buttons()

        # Battery flash timer (1 Hz)
        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(1000)
        self._flash_timer.timeout.connect(self._toggle_flash)

    def _set_eng_mode(self, mode: EngMode) -> None:
        if not self._engineering_mode_enabled and mode != EngMode.NONE:
            return
        self._eng_mode = mode
        for m, btn in self._eng_buttons.items():
            btn.setChecked(m == mode and mode != EngMode.NONE)
        self._restyle_eng_buttons()
        self.refresh(self._last_state)

    def set_engineering_mode(self, enabled: bool) -> None:
        self._engineering_mode_enabled = enabled
        self.engineering_controls.setVisible(enabled)
        if not enabled:
            self._set_eng_mode(EngMode.NONE)

    def set_demo_settings(
        self,
        *,
        use_fake_data: bool,
        device_name: str,
        ebike_pct: int,
        escooter_pct: int,
        device_battery_pcts: dict[str, int] | None = None,
    ) -> None:
        self._demo_use_fake_data = use_fake_data
        self._demo_device_name = device_name.strip() or "MMEU"
        self._demo_ebike_pct = self._clamp_pct(ebike_pct)
        self._demo_escooter_pct = self._clamp_pct(escooter_pct)
        if device_battery_pcts is not None:
            self._demo_device_battery_pcts = self._clean_device_pcts(device_battery_pcts)
        self.refresh(self._last_state)

    def set_preview_device(self, name: str, number: int | None) -> None:
        self._preview_device_name = name
        self._preview_device_number = number
        self.refresh(self._last_state)

    def set_showcase_states(self, states: dict[str, DeviceState], active_address: str) -> None:
        self._showcase_states = dict(states)
        self._showcase_active_address = active_address
        self._refresh_showcase()

    def _open_showcase(self) -> None:
        if self._showcase_dialog is not None and self._showcase_dialog.isVisible():
            self._showcase_dialog.raise_()
            return
        entries = self._showcase_entries()
        if len(entries) > 1:
            chooser = _ShowcaseChooserDialog(entries, self.window())
            if chooser.exec() != QDialog.DialogCode.Accepted:
                return
            self._open_multi_showcase(chooser.selected_addresses(), chooser.selected_layout_mode())
            return
        dialog = _ShowcaseDialog(self.window())
        self._showcase_dialog = dialog
        dialog.finished.connect(self._clear_showcase_dialog)
        self._refresh_showcase()
        dialog.showFullScreen()

    def _open_multi_showcase(self, addresses: list[str], layout_mode: str = "auto") -> None:
        selected = [address for address in addresses if address in self._showcase_states][:4]
        if not selected:
            return
        dialog = _MultiShowcaseDialog(layout_mode=layout_mode, addresses=selected, parent=self.window())
        self._showcase_dialog = dialog
        dialog.finished.connect(self._clear_showcase_dialog)
        self._refresh_showcase()
        dialog.showFullScreen()

    def _clear_showcase_dialog(self) -> None:
        self._showcase_dialog = None

    def _showcase_entries(self) -> list[tuple[str, str]]:
        entries: list[tuple[str, str]] = []
        for address, state in self._showcase_states.items():
            snap = self._snapshot_for(state)
            label = self._device_text(state, snap, self._eng_mode == EngMode.ENGINEERING)
            entries.append((address, label))
        return entries

    def _restyle_eng_buttons(self) -> None:
        for btn in self._eng_buttons.values():
            sel = btn.isChecked()
            btn.setStyleSheet(
                "QPushButton {"
                f" background: {'#546E7A' if sel else 'white'};"
                f" color: {'white' if sel else '#37474F'};"
                f" border: 1px solid {'#546E7A' if sel else '#CFD8DC'};"
                " border-radius: 6px; padding: 6px 10px;"
                " font-size: 11px; font-weight: 600;"
                "}"
            )

    def _snapshot_for(self, state: DeviceState) -> _Snapshot:
        match self._eng_mode:
            case EngMode.CHARGING_SCOOTER:
                return _Snapshot("0404V1", 4, 3970, 1200)
            case EngMode.CHARGING_BIKE:
                return _Snapshot("0403V1", 4, 5097, 1200)
            case EngMode.FULL_SCOOTER:
                return _Snapshot("0404V1", 4, 4223, 0)
            case EngMode.FULL_BIKE:
                return _Snapshot("0403V1", 4, 5380, 0)
            case EngMode.STANDBY_SCOOTER:
                return _Snapshot("0404V1", 4, 3970, 0)
            case EngMode.STANDBY_BIKE:
                return _Snapshot("0403V1", 4, 5097, 0)
            case EngMode.ENGINEERING:
                return _Snapshot("ENGINEERING", 4, 3970, 0)
            case EngMode.NOT_CHARGING:
                return _Snapshot("0404V1", 0, 3970, 0)
            case _:
                return _Snapshot(
                    state.pru_type_string,
                    state.pru_reg_item_state,
                    state.pru_dyn_vout,
                    state.pru_dyn_iout,
                )

    def _toggle_flash(self) -> None:
        self._battery_flash_state = not self._battery_flash_state
        self._update_battery_icon()
        self._refresh_showcase()

    @staticmethod
    def _clamp_pct(value: int) -> int:
        return max(0, min(100, int(value)))

    def _clean_device_pcts(self, values: dict[str, int]) -> dict[str, int]:
        cleaned: dict[str, int] = {}
        for address, pct in values.items():
            address_text = str(address).strip()
            if address_text:
                cleaned[address_text] = self._clamp_pct(pct)
        return cleaned

    def _display_battery_pct(
        self,
        snap: _Snapshot,
        *,
        pru_connected: bool,
        is_charging: bool,
        address: str = "",
    ) -> int:
        if not pru_connected:
            return 0
        if self._demo_use_fake_data and is_charging:
            if address and address in self._demo_device_battery_pcts:
                return self._demo_device_battery_pcts[address]
            if snap.pru_type == "0403V1":
                return self._demo_ebike_pct
            if snap.pru_type == "0404V1":
                return self._demo_escooter_pct
        return _battery_pct(snap.pru_type, snap.pru_vout)

    def _update_battery_icon(self) -> None:
        self.battery_icon.set_pct(self._animated_battery_pct(self._battery_pct_cached))

    def _animated_battery_pct(self, pct: int) -> int:
        if pct == 100:
            return 100
        thresholds = (0, 25, 50, 75, 100)
        lo, hi = 0, 100
        for i in range(len(thresholds) - 1):
            if thresholds[i] <= pct < thresholds[i + 1]:
                lo, hi = thresholds[i], thresholds[i + 1]
                break
        return hi if self._battery_flash_state else lo

    _last_state: DeviceState | None = None

    def refresh(self, state: DeviceState | None) -> None:
        if state is None:
            state = DeviceState()
        self._last_state = state
        snap = self._snapshot_for(state)

        pru_connected = snap.pru_reg_state >= 4
        is_charging = pru_connected and snap.pru_iout > 0
        is_engineering = self._eng_mode == EngMode.ENGINEERING
        is_bike = snap.pru_type == "0403V1"
        pct = self._display_battery_pct(
            snap,
            pru_connected=pru_connected,
            is_charging=is_charging,
            address=state.device_address,
        )
        is_full = (
            self._eng_mode == EngMode.FULL_BIKE
            or self._eng_mode == EngMode.FULL_SCOOTER
            or (pru_connected and snap.pru_iout == 0 and pct == 100)
        )

        show_pad = is_charging or is_full or (pru_connected and not is_engineering) or (
            not pru_connected and not is_engineering
        )
        self._apply_visual_state(
            self.stage,
            snap,
            is_charging=is_charging,
            is_full=is_full,
            is_engineering=is_engineering,
            show_pad=show_pad,
            is_bike=is_bike,
            pru_connected=pru_connected,
        )
        self._refresh_showcase()

        # Battery panel
        self._battery_pct_cached = pct
        should_flash = is_charging and pct != 100
        if should_flash:
            if not self._flash_timer.isActive():
                self._flash_timer.start()
        else:
            self._flash_timer.stop()
            self._battery_flash_state = False
        self._update_battery_icon()

        show_panel = pru_connected and not is_engineering
        self.panel.setStyleSheet(self._panel_style if show_panel else self._panel_empty_style)
        self.battery_icon.setVisible(show_panel)
        self.device_label.setVisible(show_panel)
        self.pct_label.setVisible(show_panel)
        self.status_label.setVisible(show_panel)
        self.detail_label.setVisible(show_panel)
        self.pct_label.setText(f"{pct}%")
        self.device_label.setText(self._device_text(state, snap, is_engineering))
        self.status_label.setText(self._status_text(pru_connected, is_charging, is_full, is_engineering))
        self.detail_label.setText(self._vehicle_detail(snap.pru_type, is_engineering))

    def _refresh_showcase(self) -> None:
        if self._showcase_dialog is None:
            return
        if isinstance(self._showcase_dialog, _MultiShowcaseDialog):
            payloads: dict[str, dict[str, object]] = {}
            for address in self._showcase_dialog.addresses:
                state = self._showcase_states.get(address)
                if state is not None:
                    payload, _show_panel = self._showcase_payload_for(state)
                    payloads[address] = payload
            self._showcase_dialog.apply_payloads(payloads)
            return
        if self._last_state is None:
            return
        payload, show_panel = self._showcase_payload_for(self._last_state)
        self._showcase_dialog.apply_snapshot(
            **payload,
            show_panel=show_panel,
        )

    def _showcase_payload_for(self, state: DeviceState) -> tuple[dict[str, object], bool]:
        snap = self._snapshot_for(state)
        pru_connected = snap.pru_reg_state >= 4
        is_charging = pru_connected and snap.pru_iout > 0
        is_engineering = self._eng_mode == EngMode.ENGINEERING
        is_bike = snap.pru_type == "0403V1"
        pct = self._display_battery_pct(
            snap,
            pru_connected=pru_connected,
            is_charging=is_charging,
            address=state.device_address,
        )
        is_full = (
            self._eng_mode == EngMode.FULL_BIKE
            or self._eng_mode == EngMode.FULL_SCOOTER
            or (pru_connected and snap.pru_iout == 0 and pct == 100)
        )
        show_pad = is_charging or is_full or (pru_connected and not is_engineering) or (
            not pru_connected and not is_engineering
        )
        return (
            {
                "snapshot": snap,
                "is_charging": is_charging,
                "is_full": is_full,
                "is_engineering": is_engineering,
                "show_pad": show_pad,
                "is_bike": is_bike,
                "pru_connected": pru_connected,
                "pct": pct,
                "icon_pct": self._animated_battery_pct(pct),
                "device_text": self._device_text(state, snap, is_engineering),
                "status_text": self._status_text(pru_connected, is_charging, is_full, is_engineering),
                "detail_text": self._vehicle_detail(snap.pru_type, is_engineering),
            },
            pru_connected and not is_engineering,
        )

    @staticmethod
    def _apply_visual_state(
        stage: _VehicleStage,
        snapshot: _Snapshot,
        *,
        is_charging: bool,
        is_full: bool,
        is_engineering: bool,
        show_pad: bool,
        is_bike: bool,
        pru_connected: bool,
    ) -> None:
        stage.update_state(
            snapshot,
            is_charging=is_charging,
            is_full=is_full,
            is_engineering=is_engineering,
            show_pad=show_pad,
            is_bike=is_bike,
            pru_connected=pru_connected,
        )

    @staticmethod
    def _status_text(pru_connected: bool, is_charging: bool, is_full: bool, is_eng: bool) -> str:
        if not pru_connected:
            return "No Device"
        if is_eng:
            return "Engineering Mode"
        if is_full:
            return "Wireless Charging Complete"
        if is_charging:
            return "Wireless Charging"
        return "Standby - Not Charging"

    @staticmethod
    def _vehicle_detail(pru_type: str, is_eng: bool) -> str:
        if pru_type == "0403V1":
            return "E-Bike Connected"
        if pru_type == "0404V1":
            return "E-Scooter Connected"
        if is_eng:
            return "Engineering Mode"
        return "Ready"

    def _device_text(self, state: DeviceState, snap: _Snapshot, is_eng: bool) -> str:
        name = (state.device_name or "").strip()
        number = state.device_number
        if not name and number is None:
            name = self._preview_device_name.strip()
            number = self._preview_device_number
        if number is None:
            name, number = self._split_device_number(name)
        if self._demo_use_fake_data:
            name = self._demo_device_name
        return self._format_device_text(name, number, snap, is_eng)

    @staticmethod
    def _split_device_number(name: str) -> tuple[str, int | None]:
        base, sep, suffix = name.rpartition("#")
        if sep and suffix.strip().isdigit():
            return base.strip(), int(suffix.strip())
        return name, None

    @staticmethod
    def _format_device_text(name: str, number: int | None, snap: _Snapshot, is_eng: bool) -> str:
        if number is not None:
            number_text = f"#{number}"
            if number_text in name:
                base_name = name.replace(number_text, "").strip()
            else:
                base_name = name
            return f"{base_name or 'Device'}  {number_text}"
        if name:
            return name
        if snap.pru_type == "0403V1":
            return "E-Bike Demo"
        if snap.pru_type == "0404V1":
            return "E-Scooter Demo"
        if is_eng:
            return "Engineering Demo"
        return "Device"
