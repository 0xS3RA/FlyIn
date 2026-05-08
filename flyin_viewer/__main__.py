from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from flyin_viewer.main_window import MainWindow
from flyin_viewer.runner import run_cli


def _run_gui(maps_root: Path | None) -> int:
    """Start graphical map viewer."""
    root_arg: Path | None = None
    if maps_root is not None and maps_root.is_dir():
        root_arg = maps_root

    app = QApplication(sys.argv)
    window = MainWindow(maps_root=root_arg)
    window.show()
    return app.exec()


def main() -> None:
    """Project entry point."""
    parser = argparse.ArgumentParser(
        description="Fly-in drone routing simulator"
    )
    parser.add_argument(
        "map", nargs="?", help="Map file path for terminal simulation"
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch graphical viewer mode instead of terminal simulation",
    )
    parser.add_argument(
        "--maps-root",
        default=None,
        help="Maps root directory for GUI mode (optional)",
    )
    args = parser.parse_args()

    if args.gui:
        maps_root = (
            Path(args.maps_root).expanduser().resolve()
            if args.maps_root
            else None
        )
        raise SystemExit(_run_gui(maps_root))
    if not args.map:
        parser.error("map file path is required in terminal mode")
    map_path = Path(args.map).expanduser().resolve()
    raise SystemExit(run_cli(map_path))


if __name__ == "__main__":
    main()
