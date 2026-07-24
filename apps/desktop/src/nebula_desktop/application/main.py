from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from nebula_desktop.application.window import MainWindow


def main(project_path: str | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    initial_path = Path(project_path).resolve() if project_path is not None else None
    if initial_path is None and len(sys.argv) > 1:
        initial_path = Path(sys.argv[1]).resolve()
    window = MainWindow(initial_path)
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
