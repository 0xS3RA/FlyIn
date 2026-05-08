from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QFont,
    QMouseEvent,
    QPainter,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from flyin_viewer.map_scene import MapGraphicsScene
from flyin_viewer.parser import MapData, MapParseError, load_map
from flyin_viewer.simulation import DroneSimulation, SimulationError


def _default_maps_root() -> Path:
    here = Path(__file__).resolve().parent.parent
    for name in ("maps", "map"):
        p = here / name
        if p.is_dir():
            return p
    return here


def discover_map_files(root: Path) -> list[tuple[str, Path]]:
    if not root.is_dir():
        return []
    pairs: list[tuple[str, Path]] = []
    for p in sorted(root.rglob("*.txt")):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        category = rel.parts[0] if len(rel.parts) > 1 else "(racine)"
        pairs.append((category, p))
    pairs.sort(key=lambda x: (x[0].lower(), x[1].name.lower()))
    return pairs


_STAG_THRESHOLD = 500


class MapGraphicsView(QGraphicsView):
    def __init__(
        self,
        scene: MapGraphicsScene,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(scene, parent)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate
        )
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.angleDelta().y() == 0:
            return
        factor = 1.12 if event.angleDelta().y() > 0 else 1 / 1.12
        self.scale(factor, factor)

    def reset_view(self) -> None:
        self.resetTransform()
        if self.scene() and self.scene().items():
            self.fitInView(
                self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio
            )

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.reset_view()
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self.scene() and self.scene().items():
            self.fitInView(
                self.scene().sceneRect(),
                Qt.AspectRatioMode.KeepAspectRatio,
            )


class MainWindow(QMainWindow):
    def __init__(self, maps_root: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("FlyIn - Drone map viewer and simulation")
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(1320, int(available.width() * 0.95))
            height = min(820, int(available.height() * 0.92))
            self.resize(width, height)
        else:
            self.resize(1320, 820)

        self._maps_root = (
            Path(maps_root) if maps_root else _default_maps_root()
        )
        self._current: MapData | None = None
        self._sim: DroneSimulation | None = None
        self._deadlock_announced = False

        self._scene = MapGraphicsScene(self)
        self._view = MapGraphicsView(self._scene)

        self._sim_timer = QTimer(self)
        self._sim_timer.timeout.connect(self._advance_sim_tick)

        self._drone_anim_timer = QTimer(self)
        self._drone_anim_timer.timeout.connect(self._on_drone_anim_frame)

        self._anim_from_positions: list[str] | None = None
        self._anim_tick = 0
        self._anim_total = 1
        self._resume_sim_after_anim = False

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Maps"])
        self._tree.setMinimumWidth(268)
        self._tree.itemSelectionChanged.connect(self._on_select)

        self._lbl_root = QLabel(str(self._maps_root))
        self._lbl_root.setWordWrap(True)
        self._lbl_root.setFrameShape(QFrame.Shape.StyledPanel)

        self._details = QPlainTextEdit()
        self._details.setReadOnly(True)
        self._details.setFrameShape(QFrame.Shape.StyledPanel)
        self._details.setFont(QFont("Monospace", 9))
        self._details.setMinimumHeight(140)
        self._details.setMaximumHeight(220)

        self._chk_labels = QCheckBox("Show hub labels")
        self._chk_labels.setChecked(True)
        self._chk_labels.stateChanged.connect(lambda _: self._refresh_scene())

        self._lbl_sim_banner = QLabel("Select a map.")
        self._lbl_sim_banner.setWordWrap(True)
        self._lbl_sim_banner.setMinimumHeight(96)

        self._btn_sim_reset = QPushButton("Reset")
        self._btn_sim_reset.clicked.connect(self._on_sim_reset)
        self._btn_sim_reset.setEnabled(False)

        self._btn_sim_step = QPushButton("Step ▶")
        self._btn_sim_step.clicked.connect(self._on_sim_step)
        self._btn_sim_step.setEnabled(False)

        row_btns = QHBoxLayout()
        row_btns.addWidget(self._btn_sim_reset)
        row_btns.addWidget(self._btn_sim_step)

        self._chk_sim_play = QCheckBox("Lecture automatique")
        self._chk_sim_play.toggled.connect(self._on_sim_play_toggled)

        self._spin_sim_delay = QSpinBox()
        self._spin_sim_delay.setRange(35, 3000)
        self._spin_sim_delay.setValue(380)
        self._spin_sim_delay.setSuffix(" ms")
        self._spin_sim_delay.setMinimumWidth(100)
        self._spin_sim_delay.valueChanged.connect(self._on_spin_delay_changed)

        row_auto = QHBoxLayout()
        row_auto.addWidget(self._chk_sim_play)
        row_auto.addWidget(QLabel("Delay:"))
        row_auto.addWidget(self._spin_sim_delay)
        row_auto.addStretch()

        legend = QLabel(
            "<b>Map legend</b><br/>"
            "· numbered markers = drones<br/>"
            "· orange / cyan outline for "
            "<i>restricted</i> / <i>priority</i> zones<br/>"
            "· dotted edges = <code>max_link_capacity</code> "
            "(<code>c=n</code>)<br/>"
            "<b>Simulation</b><br/>"
            "· heuristic: shortest distance from goal "
            "(restricted = cost 2 on entry)<br/>"
            "· enforces <code>max_drones</code> and link "
            "capacity at each step<br/>"
            "· movements are animated between two hubs (interpolation)<br/>"
            "· double-click map: fit view"
        )
        legend.setWordWrap(True)

        side = QWidget()
        v = QVBoxLayout(side)
        v.addWidget(QLabel("<b>Maps folder</b>"))
        v.addWidget(self._lbl_root)
        v.addWidget(self._tree)
        v.addWidget(self._chk_labels)
        v.addWidget(QLabel("<b>Simulation</b>"))
        v.addLayout(row_btns)
        v.addLayout(row_auto)
        v.addWidget(self._lbl_sim_banner)
        v.addWidget(legend)
        v.addWidget(QLabel("<b>File details</b>"))
        v.addWidget(self._details)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(side)
        split.addWidget(self._view)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)

        act_open = QAction("Choose maps folder...", self)
        act_open.triggered.connect(self._pick_folder)
        act_fit = QAction("Fit view", self)
        act_fit.triggered.connect(self._view.reset_view)
        act_step = QAction("Simulation - step", self)
        act_step.triggered.connect(self._on_sim_step)
        act_reset = QAction("Simulation - reset", self)
        act_reset.triggered.connect(self._on_sim_reset)
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self.close)

        m_file = self.menuBar().addMenu("File")
        m_file.addAction(act_open)
        m_file.addSeparator()
        m_file.addAction(act_quit)
        m_sim = self.menuBar().addMenu("Simulation")
        m_sim.addAction(act_reset)
        m_sim.addAction(act_step)
        m_view = self.menuBar().addMenu("View")
        m_view.addAction(act_fit)

        self._populate_tree()

    def _pick_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self,
            "Folder containing map files",
            str(self._maps_root),
        )
        if d:
            self._maps_root = Path(d)
            self._lbl_root.setText(str(self._maps_root))
            self._populate_tree()

    def _pause_auto_play(self) -> None:
        """Stop only autoplay timer and uncheck the autoplay box."""
        self._sim_timer.stop()
        self._chk_sim_play.blockSignals(True)
        self._chk_sim_play.setChecked(False)
        self._chk_sim_play.blockSignals(False)

    def _halt_all_sim_visual(self) -> None:
        """Stop all simulation visuals and queued animation state."""
        self._sim_timer.stop()
        self._drone_anim_timer.stop()
        self._anim_from_positions = None
        self._resume_sim_after_anim = False
        self._chk_sim_play.blockSignals(True)
        self._chk_sim_play.setChecked(False)
        self._chk_sim_play.blockSignals(False)
        self._btn_sim_step.setEnabled(self._sim is not None)

    def _set_sim_widgets_enabled(self, enabled: bool) -> None:
        self._btn_sim_reset.setEnabled(enabled)
        self._btn_sim_step.setEnabled(enabled)
        self._chk_sim_play.setEnabled(enabled)
        self._spin_sim_delay.setEnabled(enabled)

    def _populate_tree(self) -> None:
        self._halt_all_sim_visual()
        self._sim = None
        self._set_sim_widgets_enabled(False)
        self._lbl_sim_banner.setText("Select a map to enable simulation.")

        self._tree.clear()
        self._current = None
        by_cat: dict[str, list[Path]] = {}
        for cat, p in discover_map_files(self._maps_root):
            by_cat.setdefault(cat, []).append(p)

        for cat in sorted(by_cat.keys(), key=str.lower):
            parent_item = QTreeWidgetItem([cat])
            parent_item.setExpanded(True)
            parent_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            for path in by_cat[cat]:
                child = QTreeWidgetItem([path.name])
                child.setData(0, Qt.ItemDataRole.UserRole, str(path))
                parent_item.addChild(child)
            self._tree.addTopLevelItem(parent_item)

        self._scene.set_map(None)
        self._details.setPlainText(
            "Select a file in the tree.\n\n"
            "Maps describe a graph of hubs (zones), drones "
            "(defined by nb_drones), and links that may "
            "include a maximum capacity (max_link_capacity)."
        )
        self.statusBar().showMessage(f"Root: {self._maps_root}")

    def _on_select(self) -> None:
        items = self._tree.selectedItems()
        if not items:
            return
        it = items[0]
        path_s = it.data(0, Qt.ItemDataRole.UserRole)
        if not path_s:
            return
        path = Path(path_s)
        self._halt_all_sim_visual()
        try:
            self._current = load_map(path)
        except MapParseError as e:
            QMessageBox.warning(self, "Parse error", str(e))
            self._current = None
            self._sim = None
            self._scene.set_map(None)
            self._details.setPlainText(str(e))
            self._set_sim_widgets_enabled(False)
            self._lbl_sim_banner.setText("Invalid map.")
            return

        try:
            self._sim = DroneSimulation(self._current)
        except SimulationError as e:
            QMessageBox.warning(self, "Simulation", str(e))
            self._sim = None
            self._set_sim_widgets_enabled(False)
        else:
            self._set_sim_widgets_enabled(True)

        self._deadlock_announced = False
        self._refresh_scene()
        self._fill_details()
        self._update_sim_banner()
        self._view.reset_view()
        self.statusBar().showMessage(str(path))

    def _refresh_scene(
        self,
        *,
        drone_positions_from: list[str] | None = None,
        drone_move_blend: float = 1.0,
    ) -> None:
        show = self._chk_labels.isChecked()
        pos = self._sim.positions if self._sim else None
        self._scene.set_map(
            self._current,
            show_labels=show,
            drone_positions=pos,
            drone_positions_from=drone_positions_from,
            drone_move_blend=drone_move_blend,
        )
        self._view.viewport().update()

    def _update_sim_banner(self, last_moves: int | None = None) -> None:
        if self._current is None or self._sim is None:
            return
        s = self._sim
        n = self._current.nb_drones
        at_goal = sum(1 for x in s.positions if x == s.goal_name())

        tail = ""
        if last_moves is not None:
            tail = f" - last step: {last_moves} move(s)"
        unreachable = ""
        if s.unreachable_goal:
            unreachable = (
                "<br/><b>Warning</b>: goal is unreachable "
                "from start in this graph."
            )

        self._lbl_sim_banner.setText(
            f"At goal: <b>{at_goal}/{n}</b> drones at '{s.goal_name()}' "
            f"- turn: <b>{s.turn_index}</b>{tail}{unreachable}"
        )

    def _check_sim_outcome(self) -> None:
        if not self._sim:
            return
        if self._sim.all_at_goal():
            self._pause_auto_play()
            self.statusBar().showMessage("All drones reached the goal.")
            return
        if (
            self._sim.stagnant(_STAG_THRESHOLD)
            and not self._deadlock_announced
        ):
            self._deadlock_announced = True
            self._pause_auto_play()
            QMessageBox.information(
                self,
                "Simulation",
                "Stopped: too many consecutive turns without movement.\n"
                "This map may block this heuristic, or require "
                "another scheduling strategy.",
            )

    @staticmethod
    def _smoothstep(t: float) -> float:
        t = max(0.0, min(1.0, t))
        return t * t * (3.0 - 2.0 * t)

    def _anim_duration_frames(
        self, before: list[str], after: list[str]
    ) -> int:
        md = self._current
        if not md:
            return 18
        cell = self._scene.cell
        longest = 80.0
        for ha_n, hb_n in zip(before, after):
            if ha_n == hb_n:
                continue
            ha = md.hubs.get(ha_n)
            hb = md.hubs.get(hb_n)
            if not ha or not hb:
                continue
            dx = (hb.x - ha.x) * cell
            dy = (hb.y - ha.y) * cell
            longest = max(longest, math.hypot(dx, dy))
        n = int(14 + longest / 22.0)
        return max(14, min(42, n))

    def _start_drone_move_animation(
        self, before: list[str], last_moves: int
    ) -> None:
        self._update_sim_banner(last_moves=last_moves)
        if not self._current or self._sim is None:
            self._refresh_scene()
            self._check_sim_outcome()
            return
        after = list(self._sim.positions)
        if before == after:
            self._refresh_scene()
            self._check_sim_outcome()
            return

        self._anim_from_positions = before
        self._anim_tick = 0
        self._anim_total = self._anim_duration_frames(before, after)

        running_sim = self._sim_timer.isActive()
        self._sim_timer.stop()
        self._resume_sim_after_anim = running_sim

        self._btn_sim_step.setEnabled(False)
        ms = max(14, min(42, self._spin_sim_delay.value() // 10))
        self._drone_anim_timer.start(ms)

    def _on_drone_anim_frame(self) -> None:
        if (
            self._anim_from_positions is None
            or self._sim is None
            or self._current is None
        ):
            self._drone_anim_timer.stop()
            self._finish_drone_move_animation()
            return

        self._anim_tick += 1
        t_lin = min(1.0, self._anim_tick / float(max(1, self._anim_total)))
        blend = self._smoothstep(t_lin)

        self._refresh_scene(
            drone_positions_from=self._anim_from_positions,
            drone_move_blend=blend,
        )
        self._view.viewport().update()

        if t_lin >= 1.0 - 1e-6:
            self._finish_drone_move_animation()

    def _finish_drone_move_animation(self) -> None:
        self._drone_anim_timer.stop()
        self._anim_from_positions = None
        self._refresh_scene()
        self._btn_sim_step.setEnabled(self._sim is not None)

        if self._resume_sim_after_anim and self._chk_sim_play.isChecked():
            self._resume_sim_after_anim = False
            if self._sim and not self._sim.all_at_goal():
                self._sim_timer.start(max(35, self._spin_sim_delay.value()))
        else:
            self._resume_sim_after_anim = False

        self._check_sim_outcome()

    def _advance_sim_tick(self) -> None:
        if self._drone_anim_timer.isActive():
            return
        if not self._sim or self._sim.all_at_goal():
            self._pause_auto_play()
            return
        before = list(self._sim.positions)
        r = self._sim.step()
        self._start_drone_move_animation(before, r.drones_moved)
        self._check_sim_outcome()

    def _on_sim_step(self) -> None:
        if self._drone_anim_timer.isActive():
            return
        if not self._sim or self._sim.all_at_goal():
            return
        before = list(self._sim.positions)
        r = self._sim.step()
        self._start_drone_move_animation(before, r.drones_moved)
        self._check_sim_outcome()

    def _on_sim_reset(self) -> None:
        if not self._sim:
            return
        self._halt_all_sim_visual()
        self._sim.reset()
        self._deadlock_announced = False
        self._refresh_scene()
        self._update_sim_banner()

    def _on_sim_play_toggled(self, on: bool) -> None:
        if not self._sim:
            return
        if on:
            if self._sim.all_at_goal():
                self._chk_sim_play.blockSignals(True)
                self._chk_sim_play.setChecked(False)
                self._chk_sim_play.blockSignals(False)
                return
            self._sim_timer.start(max(35, self._spin_sim_delay.value()))
        else:
            self._sim_timer.stop()

    def _on_spin_delay_changed(self, _v: int) -> None:
        if self._sim_timer.isActive():
            self._sim_timer.start(max(35, self._spin_sim_delay.value()))

    def _fill_details(self) -> None:
        m = self._current
        if not m:
            return
        lines = [
            f"File: {m.path.name}",
            f"Path: {m.path}",
            "",
            f"Number of drones (nb_drones): {m.nb_drones}",
            f"Hubs: {len(m.hubs)}",
            f"Connections: {len(m.connections)}",
            "",
            "-- Hubs --",
        ]
        if self._sim is not None and self._sim.unreachable_goal:
            lines.append("")
            lines.append("(Simulation: goal distance is infinite from start.)")
        for name in sorted(m.hubs.keys()):
            h = m.hubs[name]
            extras = ""
            if h.attrs:
                extras = (
                    "  ["
                    + " ".join(f"{k}={v}" for k, v in sorted(h.attrs.items()))
                    + "]"
                )
            lines.append(
                f"· {name} ({h.kind}) ({h.x:g}, {h.y:g}) zone={h.zone}{extras}"
            )
        lines.append("")
        lines.append("-- Connections --")
        for c in m.connections:
            cap = (
                f"  [max_link_capacity={c.max_link_capacity}]"
                if c.max_link_capacity is not None
                else ""
            )
            lines.append(f"· {c.a} — {c.b}{cap}")
        self._details.setPlainText("\n".join(lines))
