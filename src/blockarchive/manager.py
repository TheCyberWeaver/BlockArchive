from __future__ import annotations

from pathlib import Path

from .archiver import ProjectArchiver, scan_project_stats
from .history_store import HistoryStore
from .index_store import IndexStore
from .models import (
    AppSettings,
    ArchivedProjectRecord,
    HistoryEntry,
    IndexEntry,
    ProjectRecord,
    ProjectStatus,
    utc_now_iso,
)
from .settings import SettingsStore


class ArchiveManager:
    def __init__(self, settings_store: SettingsStore | None = None) -> None:
        self.settings_store = settings_store or SettingsStore()
        self.settings = self.settings_store.load()
        self.records: dict[str, ProjectRecord] = {}
        self.archive_records: dict[str, ArchivedProjectRecord] = {}
        self._refresh_supporting_stores()

    def _refresh_supporting_stores(self) -> None:
        self.archiver = ProjectArchiver(self.settings)
        archive_dir = Path(self.settings.archive_dir)
        self.index_store = IndexStore(archive_dir)
        self.history_store = HistoryStore(archive_dir)

    def save_settings(self, settings: AppSettings) -> list[str]:
        errors = self.settings_store.validate(settings)
        if errors:
            return errors
        self.settings = settings
        self.settings_store.save(settings)
        self._refresh_supporting_stores()
        return []

    def snapshot(self) -> list[ProjectRecord]:
        return sorted(self.records.values(), key=lambda record: (record.status != ProjectStatus.ARCHIVING, record.name.lower()))

    def recent_history(self, limit: int = 200) -> list[HistoryEntry]:
        return self.history_store.read_recent(limit=limit)

    def available_archives(self) -> list[ArchivedProjectRecord]:
        return sorted(self.archive_records.values(), key=lambda record: record.name.lower())

    def stale_partials(self) -> list[str]:
        return [str(path) for path in self.archiver.list_stale_partials()]

    def cleanup_stale_partials(self) -> list[str]:
        removed = self.archiver.cleanup_stale_partials()
        if removed:
            self.history_store.append(
                HistoryEntry(
                    timestamp=utc_now_iso(),
                    project_name="",
                    status="cleanup",
                    message=f"Removed {len(removed)} stale partial archive(s).",
                    archive_path=self.settings.archive_dir,
                    source_path=self.settings.source_dir,
                )
            )
        return [str(path) for path in removed]

    def scan_and_process(self) -> list[ProjectRecord]:
        self.discover_projects()
        self.discover_archives()
        return self.snapshot()

    def discover_projects(self) -> list[ProjectRecord]:
        source_dir = Path(self.settings.source_dir)
        if not source_dir.exists():
            self.records["__source__missing__"] = ProjectRecord(
                name="Source folder",
                source_path=str(source_dir),
                status=ProjectStatus.FAILED,
                detail="Source folder does not exist.",
                updated_at=utc_now_iso(),
            )
            return self.snapshot()

        self.records.pop("__source__missing__", None)
        live_paths: set[str] = set()
        for project_path in sorted(path for path in source_dir.iterdir() if path.is_dir()):
            live_paths.add(str(project_path))
            existing = self.records.get(str(project_path))
            final_archive_path = self.archiver.final_archive_path(project_path)
            partial_archive_path = self.archiver.partial_archive_path(project_path)

            if existing and existing.status in {ProjectStatus.ARCHIVING, ProjectStatus.FAILED, ProjectStatus.SUCCESS}:
                continue

            try:
                stats = scan_project_stats(project_path)
            except OSError as exc:
                self.records[str(project_path)] = ProjectRecord(
                    name=project_path.name,
                    source_path=str(project_path),
                    archive_path=str(final_archive_path),
                    status=ProjectStatus.FAILED,
                    detail=str(exc),
                    updated_at=utc_now_iso(),
                )
                continue

            status = ProjectStatus.PENDING
            detail = "Waiting to archive."
            if final_archive_path.exists() and self.settings.skip_existing_archives:
                status = ProjectStatus.SKIPPED
                detail = "Archive already exists."
            elif partial_archive_path.exists():
                status = ProjectStatus.FAILED
                detail = "Stale partial archive detected."

            self.records[str(project_path)] = ProjectRecord(
                name=project_path.name,
                source_path=str(project_path),
                archive_path=str(final_archive_path),
                status=status,
                excluded=existing.excluded if existing else False,
                detail=detail,
                file_count=stats.file_count,
                total_bytes=stats.total_bytes,
                updated_at=utc_now_iso(),
            )

        for key, record in list(self.records.items()):
            if key.startswith("__"):
                continue
            if record.source_path and key not in live_paths and record.status not in {ProjectStatus.SUCCESS, ProjectStatus.SKIPPED}:
                self.records.pop(key, None)
        return self.snapshot()

    def discover_archives(self) -> list[ArchivedProjectRecord]:
        archive_dir = Path(self.settings.archive_dir)
        source_dir = Path(self.settings.source_dir)
        index_entries = {entry.archive_path: entry for entry in self.index_store.load()}
        self.archive_records = {}

        if not archive_dir.exists():
            return self.available_archives()

        for archive_path in sorted(archive_dir.glob("*.tar")):
            entry = index_entries.get(str(archive_path))
            project_name = entry.project_name if entry else archive_path.stem
            target_path = Path(entry.source_path) if entry else source_dir / project_name
            status = "ready"
            detail = "Ready to restore into the source folder."
            if target_path.exists():
                status = "source-exists"
                detail = "A source folder with the same name already exists."

            self.archive_records[str(archive_path)] = ArchivedProjectRecord(
                name=project_name,
                archive_path=str(archive_path),
                target_path=str(target_path),
                status=status,
                detail=detail,
                archived_at=entry.archived_at if entry else "",
                file_count=entry.file_count if entry else 0,
                total_bytes=entry.total_bytes if entry else archive_path.stat().st_size,
            )
        return self.available_archives()

    def process_pending(self, *, allow_retry: bool = False) -> list[ProjectRecord]:
        pending = [
            record for record in self.snapshot()
            if record.status == ProjectStatus.PENDING
            and not record.excluded
            and record.source_path
            and not record.name.startswith("Source folder")
        ]
        for record in pending:
            record.status = ProjectStatus.ARCHIVING
            record.detail = "Creating archive..."
            record.updated_at = utc_now_iso()

            result = self.archiver.archive_project(Path(record.source_path), allow_retry=allow_retry)
            updated = result.to_record()
            self.records[record.source_path] = updated
            self._append_history(updated)
            if updated.status == ProjectStatus.SUCCESS:
                self.index_store.upsert(
                    IndexEntry(
                        project_name=updated.name,
                        archive_path=updated.archive_path,
                        source_path=updated.source_path,
                        file_count=updated.file_count,
                        total_bytes=updated.total_bytes,
                        checksum_sha256=updated.checksum_sha256,
                        archived_at=updated.updated_at,
                        source_policy=self.settings.source_policy.value,
                    )
                )
        return self.snapshot()

    def set_excluded(self, source_paths: list[str], excluded: bool) -> list[ProjectRecord]:
        for source_path in source_paths:
            record = self.records.get(source_path)
            if record is None:
                continue
            if record.status not in {ProjectStatus.PENDING, ProjectStatus.FAILED, ProjectStatus.SKIPPED}:
                continue
            record.excluded = excluded
            if record.status == ProjectStatus.PENDING:
                record.detail = "Excluded from queue." if excluded else "Waiting to archive."
            record.updated_at = utc_now_iso()
            self.records[source_path] = record
        return self.snapshot()

    def retry_failed(self) -> list[ProjectRecord]:
        retryable = [
            record for record in self.snapshot()
            if record.status == ProjectStatus.FAILED and record.source_path and Path(record.source_path).exists()
        ]
        for record in retryable:
            partial_path = self.archiver.partial_archive_path(Path(record.source_path))
            if partial_path.exists():
                partial_path.unlink()
            record.status = ProjectStatus.PENDING
            record.detail = "Retry queued."
            record.updated_at = utc_now_iso()
            self.records[record.source_path] = record
        return self.snapshot()

    def restore_archives(self, archive_paths: list[str]) -> list[ArchivedProjectRecord]:
        source_root = Path(self.settings.source_dir)
        for archive_path in archive_paths:
            archive_record = self.archive_records.get(archive_path)
            result = self.archiver.restore_archive(Path(archive_path), target_root=source_root)
            current = archive_record or ArchivedProjectRecord(
                name=result.project_name,
                archive_path=result.archive_path,
                target_path=result.target_path,
                status=result.status,
                detail=result.detail,
            )
            current.status = result.status
            current.detail = result.detail
            current.target_path = result.target_path
            self.archive_records[archive_path] = current
            self.history_store.append(
                HistoryEntry(
                    timestamp=result.updated_at,
                    project_name=result.project_name,
                    status=result.status,
                    message=result.detail,
                    archive_path=result.archive_path,
                    source_path=result.target_path,
                )
            )
        self.discover_projects()
        self.discover_archives()
        return self.available_archives()

    def _append_history(self, record: ProjectRecord) -> None:
        self.history_store.append(
            HistoryEntry(
                timestamp=record.updated_at,
                project_name=record.name,
                status=record.status.value,
                message=record.detail,
                archive_path=record.archive_path,
                source_path=record.source_path,
            )
        )
