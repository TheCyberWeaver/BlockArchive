from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from blockarchive.manager import ArchiveManager
from blockarchive.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("BlockArchive")
    app.setOrganizationName("BlockArchive")
    window = MainWindow(ArchiveManager())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
