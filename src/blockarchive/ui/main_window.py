from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..manager import ArchiveManager
from ..models import AppSettings, HistoryEntry, ProjectRecord, ProjectStatus, SourcePolicy
from .worker import ArchiveWorker


class MainWindow(QMainWindow):
    scan_requested = Signal()
    run_queue_requested = Signal()
    retry_requested = Signal()
    cleanup_requested = Signal()
    set_excluded_requested = Signal(object, bool)
    save_settings_requested = Signal(object)

    def __init__(self, manager: ArchiveManager) -> None:
        super().__init__()
        self.manager = manager
        self.setWindowTitle("BlockArchive")
        self.resize(1180, 760)

        self._worker_thread = QThread(self)
        self._worker = ArchiveWorker(manager)
        self._worker.moveToThread(self._worker_thread)

        self.scan_requested.connect(self._worker.scan_queue)
        self.run_queue_requested.connect(self._worker.run_queue)
        self.retry_requested.connect(self._worker.retry_failed)
        self.cleanup_requested.connect(self._worker.cleanup_stale_partials)
        self.set_excluded_requested.connect(self._worker.set_excluded)
        self.save_settings_requested.connect(self._worker.save_settings)

        self._worker.snapshot_updated.connect(self._render_projects)
        self._worker.history_updated.connect(self._render_history)
        self._worker.stale_partials_updated.connect(self._render_stale_partials)
        self._worker.settings_updated.connect(self._load_settings_into_form)
        self._worker.info_message.connect(self._show_status_message)

        self._build_ui()
        self._apply_window_style()
        self._worker_thread.started.connect(self._worker.start)
        self._worker_thread.start()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._worker_thread.quit()
        self._worker_thread.wait(3000)
        super().closeEvent(event)

    def _build_ui(self) -> None:
        self.setStatusBar(QStatusBar())
        self._build_toolbar()

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(14)

        self.summary_banner = QLabel("Watching source and archive folders.")
        self.summary_banner.setObjectName("banner")
        root_layout.addWidget(self.summary_banner)

        self.tab_widget = QTabWidget()
        self.tab_widget.addTab(self._build_dashboard_tab(), "Dashboard")
        self.tab_widget.addTab(self._build_settings_tab(), "Settings")
        self.tab_widget.addTab(self._build_history_tab(), "History")
        root_layout.addWidget(self.tab_widget)

        self.setCentralWidget(root)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Actions")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        scan_action = QAction("Scan Now", self)
        scan_action.triggered.connect(self.scan_requested.emit)
        toolbar.addAction(scan_action)

        run_action = QAction("Run Queue", self)
        run_action.triggered.connect(self.run_queue_requested.emit)
        toolbar.addAction(run_action)

        retry_action = QAction("Retry Failed", self)
        retry_action.triggered.connect(self.retry_requested.emit)
        toolbar.addAction(retry_action)

        cleanup_action = QAction("Clean Partials", self)
        cleanup_action.triggered.connect(self.cleanup_requested.emit)
        toolbar.addAction(cleanup_action)

    def _build_dashboard_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(14)

        paths_group = QGroupBox("Folders")
        paths_layout = QGridLayout(paths_group)
        self.source_value = QLabel("")
        self.archive_value = QLabel("")
        self.source_value.setWordWrap(True)
        self.archive_value.setWordWrap(True)
        paths_layout.addWidget(QLabel("Source"), 0, 0)
        paths_layout.addWidget(self.source_value, 0, 1)
        paths_layout.addWidget(QLabel("Archive"), 1, 0)
        paths_layout.addWidget(self.archive_value, 1, 1)
        layout.addWidget(paths_group)

        stats_row = QHBoxLayout()
        self.pending_card = self._make_metric_card("Pending")
        self.running_card = self._make_metric_card("Archiving")
        self.success_card = self._make_metric_card("Success")
        self.failed_card = self._make_metric_card("Failed")
        stats_row.addWidget(self.pending_card["frame"])
        stats_row.addWidget(self.running_card["frame"])
        stats_row.addWidget(self.success_card["frame"])
        stats_row.addWidget(self.failed_card["frame"])
        layout.addLayout(stats_row)

        button_row = QHBoxLayout()
        scan_button = QPushButton("Scan now")
        scan_button.clicked.connect(self.scan_requested.emit)
        run_button = QPushButton("Run queue")
        run_button.clicked.connect(self.run_queue_requested.emit)
        retry_button = QPushButton("Retry failed")
        retry_button.clicked.connect(self.retry_requested.emit)
        exclude_button = QPushButton("Exclude selected")
        exclude_button.clicked.connect(lambda: self._set_selected_excluded(True))
        include_button = QPushButton("Include selected")
        include_button.clicked.connect(lambda: self._set_selected_excluded(False))
        open_archive_button = QPushButton("Open archive folder")
        open_archive_button.clicked.connect(lambda: self._open_folder(self.archive_value.text()))
        open_source_button = QPushButton("Open source folder")
        open_source_button.clicked.connect(lambda: self._open_folder(self.source_value.text()))
        clean_button = QPushButton("Clean partials")
        clean_button.clicked.connect(self.cleanup_requested.emit)
        for button in [
            scan_button,
            run_button,
            retry_button,
            exclude_button,
            include_button,
            open_archive_button,
            open_source_button,
            clean_button,
        ]:
            button_row.addWidget(button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.partial_label = QLabel("No stale partial archives detected.")
        self.partial_label.setWordWrap(True)
        layout.addWidget(self.partial_label)

        self.project_table = QTableWidget(0, 8)
        self.project_table.setHorizontalHeaderLabels(
            ["Project", "Queue", "Status", "Files", "Size", "Archive", "Updated", "Detail"]
        )
        self.project_table.setAlternatingRowColors(True)
        self.project_table.verticalHeader().setVisible(False)
        self.project_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.project_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.project_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.project_table, 1)

        return tab

    def _build_settings_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(14)

        form_group = QGroupBox("Configuration")
        form_layout = QFormLayout(form_group)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.source_edit = QLineEdit()
        self.archive_edit = QLineEdit()
        self.archived_source_edit = QLineEdit()
        self.poll_interval_spin = QSpinBox()
        self.poll_interval_spin.setRange(5, 86400)
        self.generate_checksum_check = QCheckBox("Generate .sha256 checksum files")
        self.auto_scan_check = QCheckBox("Automatically scan on an interval")
        self.skip_existing_check = QCheckBox("Skip projects if matching archive already exists")
        self.source_policy_combo = QComboBox()
        self.source_policy_combo.addItem("Keep source", SourcePolicy.KEEP)
        self.source_policy_combo.addItem("Move source to ArchivedSource", SourcePolicy.MOVE)
        self.source_policy_combo.addItem("Delete source after success", SourcePolicy.DELETE)

        form_layout.addRow("Source folder", self._path_row(self.source_edit, self._browse_source))
        form_layout.addRow("Archive folder", self._path_row(self.archive_edit, self._browse_archive))
        form_layout.addRow(
            "Archived source folder",
            self._path_row(self.archived_source_edit, self._browse_archived_source),
        )
        form_layout.addRow("Poll interval (seconds)", self.poll_interval_spin)
        form_layout.addRow("Source policy", self.source_policy_combo)
        form_layout.addRow("", self.generate_checksum_check)
        form_layout.addRow("", self.auto_scan_check)
        form_layout.addRow("", self.skip_existing_check)
        layout.addWidget(form_group)

        notes = QTextEdit()
        notes.setReadOnly(True)
        notes.setPlainText(
            "Safety model:\n"
            "- Source folders remain untouched until the tar archive is written, verified, and renamed from .partial.\n"
            "- Failed writes leave the source folder intact.\n"
            "- Retry Failed removes stale .partial files only for projects being retried.\n"
            "- Index and history are written into the selected archive folder."
        )
        layout.addWidget(notes)

        save_button = QPushButton("Save settings")
        save_button.clicked.connect(self._save_settings)
        layout.addWidget(save_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return tab

    def _build_history_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(14)

        self.history_table = QTableWidget(0, 4)
        self.history_table.setHorizontalHeaderLabels(["Timestamp", "Project", "Status", "Message"])
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.history_table)
        return tab

    def _make_metric_card(self, title: str) -> dict[str, QWidget | QLabel]:
        frame = QFrame()
        frame.setObjectName("metricCard")
        layout = QVBoxLayout(frame)
        title_label = QLabel(title)
        title_label.setObjectName("metricTitle")
        value_label = QLabel("0")
        value_label.setObjectName("metricValue")
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        return {"frame": frame, "value": value_label}

    def _path_row(self, line_edit: QLineEdit, browse_handler) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(line_edit)
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(browse_handler)
        layout.addWidget(browse_button)
        return container

    def _browse_source(self) -> None:
        self._browse_into(self.source_edit)

    def _browse_archive(self) -> None:
        self._browse_into(self.archive_edit)

    def _browse_archived_source(self) -> None:
        self._browse_into(self.archived_source_edit)

    def _browse_into(self, line_edit: QLineEdit) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select Folder", line_edit.text() or str(Path.home()))
        if selected:
            line_edit.setText(selected)

    def _save_settings(self) -> None:
        settings = AppSettings(
            source_dir=self.source_edit.text().strip(),
            archive_dir=self.archive_edit.text().strip(),
            archived_source_dir=self.archived_source_edit.text().strip(),
            poll_interval_seconds=self.poll_interval_spin.value(),
            generate_checksum=self.generate_checksum_check.isChecked(),
            auto_scan=self.auto_scan_check.isChecked(),
            skip_existing_archives=self.skip_existing_check.isChecked(),
            source_policy=self.source_policy_combo.currentData(),
        )
        self.save_settings_requested.emit(settings)

    def _load_settings_into_form(self, settings: AppSettings) -> None:
        self.source_edit.setText(settings.source_dir)
        self.archive_edit.setText(settings.archive_dir)
        self.archived_source_edit.setText(settings.archived_source_dir)
        self.poll_interval_spin.setValue(settings.poll_interval_seconds)
        self.generate_checksum_check.setChecked(settings.generate_checksum)
        self.auto_scan_check.setChecked(settings.auto_scan)
        self.skip_existing_check.setChecked(settings.skip_existing_archives)

        index = self.source_policy_combo.findData(settings.source_policy)
        if index >= 0:
            self.source_policy_combo.setCurrentIndex(index)
        self.source_value.setText(settings.source_dir)
        self.archive_value.setText(settings.archive_dir)

    def _render_projects(self, records: list[ProjectRecord]) -> None:
        source_warning = next(
            (record for record in records if record.name.startswith("Source folder") and record.status == ProjectStatus.FAILED),
            None,
        )
        visible_records = [record for record in records if not record.name.startswith("Source folder")]
        self.project_table.setRowCount(len(visible_records))
        counts = {
            ProjectStatus.PENDING: 0,
            ProjectStatus.ARCHIVING: 0,
            ProjectStatus.SUCCESS: 0,
            ProjectStatus.FAILED: 0,
        }

        for row, record in enumerate(visible_records):
            counts[record.status] = counts.get(record.status, 0) + 1
            values = [
                record.name,
                "excluded" if record.excluded else "queued",
                record.status.value,
                str(record.file_count),
                self._format_bytes(record.total_bytes),
                record.archive_path,
                record.updated_at.replace("T", " ").split("+")[0],
                record.detail,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 1 and record.excluded:
                    item.setForeground(QColor("#8c1d18"))
                if column == 2:
                    item.setForeground(self._status_color(record.status))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, record.source_path)
                self.project_table.setItem(row, column, item)

        self.pending_card["value"].setText(str(counts[ProjectStatus.PENDING]))
        self.running_card["value"].setText(str(counts[ProjectStatus.ARCHIVING]))
        self.success_card["value"].setText(str(counts[ProjectStatus.SUCCESS]))
        self.failed_card["value"].setText(str(counts[ProjectStatus.FAILED]))

        if source_warning is not None:
            self.summary_banner.setText(f"{source_warning.detail} {source_warning.source_path}")
        else:
            total_projects = len(visible_records)
            self.summary_banner.setText(
                f"{total_projects} project(s) tracked. "
                f"{counts[ProjectStatus.PENDING]} pending, "
                f"{counts[ProjectStatus.ARCHIVING]} archiving, "
                f"{counts[ProjectStatus.SUCCESS]} successful, "
                f"{counts[ProjectStatus.FAILED]} failed. "
                f"{sum(1 for record in visible_records if record.excluded)} excluded."
            )

    def _set_selected_excluded(self, excluded: bool) -> None:
        selected_paths: list[str] = []
        for item in self.project_table.selectedItems():
            if item.column() != 0:
                continue
            source_path = item.data(Qt.ItemDataRole.UserRole)
            if source_path:
                selected_paths.append(source_path)
        unique_paths = list(dict.fromkeys(selected_paths))
        if not unique_paths:
            self._show_status_message("Select one or more queued projects first.")
            return
        self.set_excluded_requested.emit(unique_paths, excluded)

    def _render_history(self, history_entries: list[HistoryEntry]) -> None:
        self.history_table.setRowCount(len(history_entries))
        for row, entry in enumerate(history_entries):
            values = [
                entry.timestamp.replace("T", " ").split("+")[0],
                entry.project_name,
                entry.status,
                entry.message,
            ]
            for column, value in enumerate(values):
                self.history_table.setItem(row, column, QTableWidgetItem(value))

    def _render_stale_partials(self, partials: list[str]) -> None:
        if not partials:
            self.partial_label.setText("No stale partial archives detected.")
            return
        joined = "\n".join(partials[:3])
        suffix = "" if len(partials) <= 3 else f"\n... and {len(partials) - 3} more"
        self.partial_label.setText(
            f"Stale partial archive(s) detected: {len(partials)}\n{joined}{suffix}"
        )

    def _open_folder(self, path: str) -> None:
        if not path:
            return
        if not Path(path).exists():
            QMessageBox.warning(self, "Folder Missing", f"Folder does not exist:\n{path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _show_status_message(self, message: str) -> None:
        self.statusBar().showMessage(message, 8000)

    def _apply_window_style(self) -> None:
        QApplication.instance().setFont(QFont("Segoe UI Variable", 10))
        self.setStyleSheet(
            """
            QMainWindow {
                background: #eef2f7;
                color: #14202b;
            }
            QToolBar {
                background: #dbe5f0;
                color: #14202b;
                border: 0;
                spacing: 8px;
                padding: 8px 18px;
            }
            QToolButton {
                background: #ffffff;
                color: #14202b;
                border: 1px solid #a8b9cb;
                border-radius: 10px;
                padding: 8px 12px;
            }
            QToolButton:hover {
                background: #f4f8fc;
            }
            QTabWidget::pane {
                border: 1px solid #bcc9d6;
                background: #f8fbfe;
                border-radius: 14px;
            }
            QTabBar::tab {
                background: #e7eef6;
                color: #213244;
                padding: 10px 16px;
                margin: 6px;
                border-radius: 10px;
            }
            QTabBar::tab:selected {
                background: #1f5f8b;
                color: #ffffff;
            }
            QGroupBox, QFrame#metricCard {
                background: #ffffff;
                color: #14202b;
                border: 1px solid #c6d2de;
                border-radius: 16px;
                margin-top: 4px;
                padding: 12px;
            }
            QLabel#banner {
                background: #16324a;
                color: #ffffff;
                border-radius: 16px;
                padding: 14px 16px;
                font-size: 14px;
                font-weight: 600;
            }
            QLabel#metricTitle {
                color: #4b6074;
                font-size: 12px;
                text-transform: uppercase;
            }
            QLabel#metricValue {
                color: #101820;
                font-size: 28px;
                font-weight: 700;
            }
            QPushButton {
                background: #1f5f8b;
                color: #ffffff;
                border: 1px solid #184c70;
                border-radius: 10px;
                padding: 10px 14px;
                min-width: 88px;
            }
            QPushButton:hover {
                background: #184c70;
            }
            QLineEdit, QComboBox, QSpinBox, QTextEdit, QTableWidget {
                background: #ffffff;
                color: #14202b;
                selection-background-color: #1f5f8b;
                selection-color: #ffffff;
                border: 1px solid #b7c6d5;
                border-radius: 10px;
                padding: 6px;
            }
            QComboBox QAbstractItemView {
                background: #ffffff;
                color: #14202b;
                selection-background-color: #1f5f8b;
                selection-color: #ffffff;
                border: 1px solid #b7c6d5;
            }
            QCheckBox, QLabel, QGroupBox, QStatusBar {
                color: #14202b;
            }
            QHeaderView::section {
                background: #dbe5f0;
                color: #14202b;
                padding: 8px;
                border: 0;
                border-bottom: 1px solid #bcc9d6;
            }
            QTableWidget {
                gridline-color: #d7e0ea;
                alternate-background-color: #f4f8fc;
            }
            QTextEdit {
                background: #f8fbfe;
            }
            QStatusBar {
                background: #dbe5f0;
            }
            """
        )

    @staticmethod
    def _status_color(status: ProjectStatus) -> QColor:
        palette = {
            ProjectStatus.PENDING: QColor("#8a6100"),
            ProjectStatus.ARCHIVING: QColor("#0e4b7a"),
            ProjectStatus.SUCCESS: QColor("#1f6a3a"),
            ProjectStatus.FAILED: QColor("#8c1d18"),
            ProjectStatus.SKIPPED: QColor("#5f5a52"),
        }
        return palette.get(status, QColor("#22201c"))

    @staticmethod
    def _format_bytes(size: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{size} B"
