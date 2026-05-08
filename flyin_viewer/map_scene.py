from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtCore import QObject
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
)

from flyin_viewer.colors import resolve_color, zone_accent
from flyin_viewer.parser import Hub, MapData


def _drone_palette() -> list[QColor]:
    return [
        QColor("#ffc107"),
        QColor("#03a9f4"),
        QColor("#e91e63"),
        QColor("#76ff03"),
        QColor("#9c27b0"),
        QColor("#ff5722"),
        QColor("#00bcd4"),
        QColor("#cddc39"),
        QColor("#3f51b5"),
        QColor("#795548"),
        QColor("#eceff1"),
        QColor("#ff9800"),
    ]


class _HubItem(QGraphicsEllipseItem):
    def __init__(
        self, hub: Hub, cell: float, radius: float, show_label: bool
    ) -> None:
        self.hub_name = hub.name
        cx = hub.x * cell
        cy = -hub.y * cell
        r = radius
        if hub.kind == "start":
            r *= 1.15
        elif hub.kind == "end":
            r *= 1.12

        super().__init__(-r, -r, 2 * r, 2 * r)
        self.setPos(cx, cy)
        self.setZValue(2)

        fill = resolve_color(hub.attrs.get("color"))
        if hub.zone == "blocked":
            fill = fill.darker(180)

        self.setBrush(fill)
        zc, zw = zone_accent(hub.zone)
        if zw > 0:
            line_style = (
                Qt.PenStyle.DashLine
                if hub.zone == "restricted"
                else Qt.PenStyle.SolidLine
            )
            self.setPen(QPen(zc, zw, line_style))
        else:
            self.setPen(QPen(QColor("#263238"), 1.5))

        tip_parts = [
            f"{hub.name} ({hub.kind})",
            f"({hub.x:g}, {hub.y:g})  zone={hub.zone}",
        ]
        if hub.attrs:
            tip_parts.append(
                ", ".join(f"{k}={v}" for k, v in sorted(hub.attrs.items())),
            )
        self.setToolTip("\n".join(tip_parts))

        if show_label:
            font = QFont("Sans Serif", 8)
            font.setHintingPreference(
                QFont.HintingPreference.PreferFullHinting
            )
            label = QGraphicsSimpleTextItem(hub.name, self)
            label.setFont(font)
            label.setBrush(QColor("#eceff1"))
            br = label.boundingRect()
            label.setPos(-br.width() / 2, r + 4)

            cap = hub.attrs.get("max_drones")
            if cap:
                cap_txt = QGraphicsSimpleTextItem(f"max:{cap}", self)
                cap_txt.setFont(QFont("Sans Serif", 7))
                cap_txt.setBrush(QColor("#bdbdbd"))
                br2 = cap_txt.boundingRect()
                cap_txt.setPos(-br2.width() / 2, r + 4 + br.height())


def _edge_color(hub_a: Hub, hub_b: Hub) -> QColor:
    ca = resolve_color(hub_a.attrs.get("color"))
    cb = resolve_color(hub_b.attrs.get("color"))
    return QColor(
        (ca.red() + cb.red()) // 2,
        (ca.green() + cb.green()) // 2,
        (ca.blue() + cb.blue()) // 2,
        220,
    )


class MapGraphicsScene(QGraphicsScene):
    """Cached map layer (edges + hubs); drones are redrawn on updates."""

    def __init__(
        self,
        parent: QObject | None = None,
        cell: float = 90.0,
        node_radius: float = 16.0,
    ) -> None:
        super().__init__(parent)
        self.cell = cell
        self.node_radius = node_radius
        self._static_key: tuple[Path, bool] | None = None
        self._cached_data: MapData | None = None
        self._drone_graphics: list[
            QGraphicsEllipseItem | QGraphicsSimpleTextItem
        ] = []

    def _remove_drone_items(self) -> None:
        for it in self._drone_graphics:
            self.removeItem(it)
        self._drone_graphics.clear()

    def _build_static_layer(self, data: MapData, show_labels: bool) -> None:
        for conn in data.connections:
            ha = data.hubs[conn.a]
            hb = data.hubs[conn.b]
            x1, y1 = ha.x * self.cell, -ha.y * self.cell
            x2, y2 = hb.x * self.cell, -hb.y * self.cell
            line = QGraphicsLineItem(x1, y1, x2, y2)
            pen = QPen(
                _edge_color(ha, hb),
                2.0 if conn.max_link_capacity is None else 3.5,
            )
            if conn.max_link_capacity is not None:
                pen.setStyle(Qt.PenStyle.DotLine)
                pen.setWidthF(4.5)
            line.setPen(pen)
            line.setZValue(0)
            self.addItem(line)

            if conn.max_link_capacity is not None:
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                t = QGraphicsSimpleTextItem(f"c={conn.max_link_capacity}")
                t.setBrush(QColor("#ffeb3b"))
                t.setFont(QFont("Monospace", 8, QFont.Weight.Bold))
                t.setPos(mx + 4, my - 18)
                t.setZValue(1)
                self.addItem(t)

        for hub in data.hubs.values():
            self.addItem(
                _HubItem(hub, self.cell, self.node_radius, show_labels)
            )

    def _hub_center(self, hub: Hub) -> tuple[float, float]:
        return hub.x * self.cell, -hub.y * self.cell

    def set_map(
        self,
        data: MapData | None,
        show_labels: bool = True,
        drone_positions: list[str] | None = None,
        drone_positions_from: list[str] | None = None,
        drone_move_blend: float = 1.0,
    ) -> None:
        """Interpolate drones from previous to current hub positions."""
        if data is None:
            self.clear()
            self._static_key = None
            self._cached_data = None
            self._drone_graphics.clear()
            return

        path_key = Path(data.path).resolve()
        scene_key = (path_key, show_labels)
        if self._static_key != scene_key:
            self.clear()
            self._drone_graphics.clear()
            self._static_key = scene_key
            self._cached_data = data
            self._build_static_layer(data, show_labels)
        else:
            self._cached_data = data
            self._remove_drone_items()

        blend = max(0.0, min(1.0, float(drone_move_blend)))
        self._draw_drones_interpolated(
            data,
            drone_positions if drone_positions is not None else [],
            drone_positions_from,
            blend,
        )
        self._frame_scene()

    def _orbit_radius(self, hub: Hub) -> float:
        if hub.kind == "start":
            return self.node_radius * 1.38
        if hub.kind == "end":
            return self.node_radius * 1.32
        return self.node_radius * 1.22

    def _draw_drones_interpolated(
        self,
        data: MapData,
        drone_positions: list[str],
        from_positions: list[str] | None,
        blend: float,
    ) -> None:
        if not drone_positions:
            return

        palette = _drone_palette()
        n = len(drone_positions)
        marker_d = max(12.0, min(22.0, self.cell * 0.2 + 6.0))
        font_px = max(8, min(13, int(marker_d * 0.78)))

        from_ok = (
            from_positions is not None
            and len(from_positions) == n
            and blend <= 1.0 - 1e-6
        )

        moving_ids: dict[int, tuple[float, float, float, float]] = {}
        if from_ok:
            assert from_positions is not None
            for i in range(n):
                a = from_positions[i]
                b = drone_positions[i]
                if a != b and a in data.hubs and b in data.hubs:
                    xa, ya = self._hub_center(data.hubs[a])
                    xb, yb = self._hub_center(data.hubs[b])
                    moving_ids[i] = (xa, ya, xb, yb)

        grouped_by_hub: dict[str, list[int]] = {}
        for i in range(n):
            if i in moving_ids:
                continue
            hn = drone_positions[i]
            if hn in data.hubs:
                grouped_by_hub.setdefault(hn, []).append(i)

        hubs_slots: dict[int, tuple[float, float]] = {}
        slots = 11
        for hub_name in sorted(grouped_by_hub.keys()):
            indices = grouped_by_hub[hub_name]
            hub = data.hubs[hub_name]
            ox, oy = self._hub_center(hub)
            orbit = self._orbit_radius(hub)
            indices.sort(key=int)
            for j, drone_id in enumerate(indices):
                ring = j // slots
                k = j % slots
                ang = (2 * math.pi * k) / slots + 0.1 * ring
                rr = orbit + ring * (marker_d + 6)
                hubs_slots[drone_id] = (
                    ox + rr * math.cos(ang),
                    oy + rr * math.sin(ang),
                )

        for drone_id in range(n):
            if drone_id in moving_ids:
                xa, ya, xb, yb = moving_ids[drone_id]
                vx, vy = xb - xa, yb - ya
                length = math.hypot(vx, vy) or 1.0
                ux, uy = vx / length, vy / length
                px, py = -uy, ux
                stagger = (((drone_id % 43) - 21) / 10.5) * 4.25
                cx = xa + ux * length * blend + px * stagger
                cy = ya + uy * length * blend + py * stagger
            elif drone_id in hubs_slots:
                cx, cy = hubs_slots[drone_id]
            else:
                hn = drone_positions[drone_id]
                if hn not in data.hubs:
                    continue
                cx, cy = self._hub_center(data.hubs[hn])

            ell = QGraphicsEllipseItem(
                -marker_d / 2, -marker_d / 2, marker_d, marker_d
            )
            ell.setPos(cx, cy)
            col = palette[drone_id % len(palette)]
            ell.setBrush(col)
            ell.setPen(QPen(QColor("#fafafa"), 2.85))
            ell.setZValue(120)
            hn_now = drone_positions[drone_id]
            ell.setToolTip(f"Drone {drone_id} • hub « {hn_now} »")
            self.addItem(ell)
            self._drone_graphics.append(ell)

            lab = QGraphicsSimpleTextItem(str(drone_id), ell)
            lab.setBrush(QColor("#1a237e"))
            lab.setFont(QFont("Sans Serif", font_px, QFont.Weight.Bold))
            lr = lab.boundingRect()
            lab.setPos(-lr.width() / 2, -lr.height() / 2 + 0.5)
            lab.setZValue(121)
            self._drone_graphics.append(lab)

    def _frame_scene(self) -> None:
        if not self.items():
            return
        self.setSceneRect(self.itemsBoundingRect().adjusted(-60, -60, 60, 60))
