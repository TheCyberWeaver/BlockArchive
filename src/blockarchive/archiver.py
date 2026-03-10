from __future__ import annotations

import hashlib
import os
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path

from .models import AppSettings, ArchiveResult, ProjectStatus, SourcePolicy, path_as_str
from .settings import resolve_archived_source_dir


INVALID_WINDOWS_NAME_CHARS = '<>:"/\\|?*'


class ArchiveError(RuntimeError):
    """Raised when archive creation fails."""


@dataclass(slots=True)
class ProjectStats:
    file_count: int
    total_bytes: int


def sanitize_project_name(name: str) -> str:
    sanitized = "".join("_" if char in INVALID_WINDOWS_NAME_CHARS else char for char in name).strip()
    sanitized = sanitized.rstrip(". ")
    return sanitized or "project"


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def scan_project_stats(source_dir: Path) -> ProjectStats:
    file_count = 0
    total_bytes = 0
    for file_path in sorted(source_dir.rglob("*")):
        if file_path.is_file():
            file_count += 1
            total_bytes += file_path.stat().st_size
    return ProjectStats(file_count=file_count, total_bytes=total_bytes)


class ProjectArchiver:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.archive_dir = Path(settings.archive_dir)

    def final_archive_path(self, source_dir: Path) -> Path:
        archive_name = sanitize_project_name(source_dir.name)
        return self.archive_dir / f"{archive_name}.tar"

    def partial_archive_path(self, source_dir: Path) -> Path:
        archive_name = sanitize_project_name(source_dir.name)
        return self.archive_dir / f"{archive_name}.tar.partial"

    def checksum_path(self, source_dir: Path) -> Path:
        archive_name = sanitize_project_name(source_dir.name)
        return self.archive_dir / f"{archive_name}.tar.sha256"

    def archive_project(self, source_dir: Path, *, allow_retry: bool = False) -> ArchiveResult:
        if not source_dir.exists() or not source_dir.is_dir():
            return ArchiveResult(
                project_name=source_dir.name,
                source_path=str(source_dir),
                archive_path="",
                status=ProjectStatus.FAILED,
                detail="Source project folder is missing.",
            )

        self.archive_dir.mkdir(parents=True, exist_ok=True)
        final_path = self.final_archive_path(source_dir)
        partial_path = self.partial_archive_path(source_dir)

        if final_path.exists() and self.settings.skip_existing_archives:
            return ArchiveResult(
                project_name=source_dir.name,
                source_path=str(source_dir),
                archive_path=str(final_path),
                status=ProjectStatus.SKIPPED,
                detail="Archive already exists.",
                partial_path=path_as_str(partial_path if partial_path.exists() else None),
            )

        if partial_path.exists() and not allow_retry:
            return ArchiveResult(
                project_name=source_dir.name,
                source_path=str(source_dir),
                archive_path=str(final_path),
                status=ProjectStatus.FAILED,
                detail="Stale partial archive detected. Retry or clean partials before archiving again.",
                partial_path=str(partial_path),
            )

        if partial_path.exists() and allow_retry:
            partial_path.unlink()

        stats = scan_project_stats(source_dir)

        try:
            self._write_archive(source_dir, partial_path)
            self._verify_archive(source_dir, partial_path)
            archive_size = partial_path.stat().st_size
            if archive_size <= 0:
                raise ArchiveError("Archive verification failed because the tar file is empty.")

            os.replace(partial_path, final_path)
            detail = "Archive completed successfully."
            checksum_sha256 = ""
            warnings: list[str] = []
            if self.settings.generate_checksum:
                try:
                    checksum_sha256 = compute_sha256(final_path)
                    self._write_checksum_file(final_path, checksum_sha256)
                except Exception as exc:
                    warnings.append(f"Checksum generation failed: {exc}")
            try:
                policy_note = self._apply_source_policy(source_dir)
                if policy_note:
                    warnings.append(policy_note)
            except Exception as exc:
                warnings.append(f"Archive finalized, but source policy could not be applied: {exc}")
            if warnings:
                detail = f"{detail} {' '.join(warnings)}"
            return ArchiveResult(
                project_name=source_dir.name,
                source_path=str(source_dir),
                archive_path=str(final_path),
                status=ProjectStatus.SUCCESS,
                detail=detail,
                file_count=stats.file_count,
                total_bytes=stats.total_bytes,
                checksum_sha256=checksum_sha256,
            )
        except Exception as exc:
            return ArchiveResult(
                project_name=source_dir.name,
                source_path=str(source_dir),
                archive_path=str(final_path),
                status=ProjectStatus.FAILED,
                detail=str(exc),
                file_count=stats.file_count,
                total_bytes=stats.total_bytes,
                partial_path=str(partial_path) if partial_path.exists() else "",
            )

    def list_stale_partials(self) -> list[Path]:
        if not self.archive_dir.exists():
            return []
        return sorted(self.archive_dir.glob("*.partial"))

    def cleanup_stale_partials(self) -> list[Path]:
        removed: list[Path] = []
        for partial in self.list_stale_partials():
            partial.unlink(missing_ok=True)
            removed.append(partial)
        return removed

    def _write_archive(self, source_dir: Path, partial_path: Path) -> None:
        with partial_path.open("wb") as raw_handle:
            with tarfile.open(fileobj=raw_handle, mode="w", format=tarfile.PAX_FORMAT) as tar_handle:
                tar_handle.add(source_dir, arcname=source_dir.name, recursive=False)
                for current_root, directories, files in os.walk(source_dir):
                    current = Path(current_root)
                    directories.sort()
                    files.sort()
                    for directory in directories:
                        full_path = current / directory
                        arcname = full_path.relative_to(source_dir.parent)
                        tar_handle.add(full_path, arcname=str(arcname), recursive=False)
                    for file_name in files:
                        full_path = current / file_name
                        arcname = full_path.relative_to(source_dir.parent)
                        tar_handle.add(full_path, arcname=str(arcname), recursive=False)
            raw_handle.flush()
            os.fsync(raw_handle.fileno())

    def _verify_archive(self, source_dir: Path, partial_path: Path) -> None:
        try:
            with tarfile.open(partial_path, mode="r:") as tar_handle:
                members = tar_handle.getmembers()
        except tarfile.TarError as exc:
            raise ArchiveError(f"Archive verification failed: {exc}") from exc

        if not any(member.name == source_dir.name for member in members):
            raise ArchiveError("Archive verification failed because the project root folder is missing.")

    def _write_checksum_file(self, final_path: Path, checksum_sha256: str) -> None:
        checksum_path = final_path.with_suffix(final_path.suffix + ".sha256")
        temp_path = checksum_path.with_suffix(checksum_path.suffix + ".tmp")
        temp_path.write_text(f"{checksum_sha256} *{final_path.name}\n", encoding="utf-8")
        os.replace(temp_path, checksum_path)

    def _apply_source_policy(self, source_dir: Path) -> str:
        if self.settings.source_policy is SourcePolicy.KEEP:
            return ""

        if self.settings.source_policy is SourcePolicy.MOVE:
            destination_root = resolve_archived_source_dir(self.settings)
            destination_root.mkdir(parents=True, exist_ok=True)
            destination_path = destination_root / source_dir.name
            if destination_path.exists():
                raise ArchiveError(f"Archive succeeded, but archived source destination already exists: {destination_path}")
            shutil.move(str(source_dir), str(destination_path))
            return f"Source moved to {destination_path}."

        if self.settings.source_policy is SourcePolicy.DELETE:
            shutil.rmtree(source_dir)
            return "Source folder deleted after successful finalization."

        return ""
