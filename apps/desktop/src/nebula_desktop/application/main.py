from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from nebula_desktop.application.assets import asset_path
from nebula_desktop.application.window import MainWindow


def main(project_path: str | None = None) -> int:
    app = cast(QApplication | None, QApplication.instance()) or QApplication(sys.argv)
    app.setOrganizationName("NebulaMaster")
    app.setApplicationName("Desktop")
    icon_file = asset_path("nebula-master-icon.png")
    if icon_file.is_file():
        app.setWindowIcon(QIcon(str(icon_file)))
    initial_path = Path(project_path).resolve() if project_path is not None else None
    if initial_path is None and len(sys.argv) > 1:
        initial_path = Path(sys.argv[1]).resolve()
    window = MainWindow(initial_path)
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
