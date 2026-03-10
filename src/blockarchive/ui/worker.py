from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ..manager import ArchiveManager
from ..models import AppSettings


class ArchiveWorker(QObject):
    snapshot_updated = Signal(object)
    archives_updated = Signal(object)
    history_updated = Signal(object)
    stale_partials_updated = Signal(object)
    settings_updated = Signal(object)
    info_message = Signal(str)

    def __init__(self, manager: ArchiveManager) -> None:
        super().__init__()
        self.manager = manager
        self._busy = False
        self._timer: QTimer | None = None

    @Slot()
    def start(self) -> None:
        self.settings_updated.emit(self.manager.settings)
        self._emit_state()
        self._restart_timer()
        if self.manager.settings.auto_scan:
            self.scan_queue()

    @Slot()
    def scan_queue(self) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            self.manager.discover_projects()
            self.manager.discover_archives()
        except Exception as exc:  # pragma: no cover - UI guardrail
            self.info_message.emit(str(exc))
        finally:
            self._busy = False
            self._emit_state()

    @Slot()
    def run_queue(self) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            self.manager.process_pending()
        except Exception as exc:  # pragma: no cover - UI guardrail
            self.info_message.emit(str(exc))
        finally:
            self._busy = False
            self._emit_state()

    @Slot()
    def retry_failed(self) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            self.manager.retry_failed()
        except Exception as exc:  # pragma: no cover - UI guardrail
            self.info_message.emit(str(exc))
        finally:
            self._busy = False
            self._emit_state()

    @Slot()
    def cleanup_stale_partials(self) -> None:
        removed = self.manager.cleanup_stale_partials()
        if removed:
            self.info_message.emit(f"Removed {len(removed)} stale partial archive(s).")
        self._emit_state()

    @Slot(object)
    def save_settings(self, settings: AppSettings) -> None:
        errors = self.manager.save_settings(settings)
        if errors:
            self.info_message.emit("\n".join(errors))
            return
        self.info_message.emit("Settings saved.")
        self.settings_updated.emit(self.manager.settings)
        self._restart_timer()
        self.scan_queue()

    @Slot(object, bool)
    def set_excluded(self, source_paths: list[str], excluded: bool) -> None:
        self.manager.set_excluded(source_paths, excluded)
        self._emit_state()

    @Slot()
    def refresh_archives(self) -> None:
        self.manager.discover_archives()
        self._emit_state()

    @Slot(object)
    def restore_archives(self, archive_paths: list[str]) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            self.manager.restore_archives(archive_paths)
        except Exception as exc:  # pragma: no cover - UI guardrail
            self.info_message.emit(str(exc))
        finally:
            self._busy = False
            self._emit_state()

    def _restart_timer(self) -> None:
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self.scan_queue)
        self._timer.stop()
        if self.manager.settings.auto_scan:
            self._timer.start(self.manager.settings.poll_interval_seconds * 1000)

    def _emit_state(self) -> None:
        self.snapshot_updated.emit(self.manager.snapshot())
        self.archives_updated.emit(self.manager.available_archives())
        self.history_updated.emit(self.manager.recent_history())
        self.stale_partials_updated.emit(self.manager.stale_partials())
