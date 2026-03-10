from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectStatus(StrEnum):
    PENDING = "pending"
    ARCHIVING = "archiving"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class SourcePolicy(StrEnum):
    KEEP = "keep"
    MOVE = "move"
    DELETE = "delete"


def coerce_source_policy(value: "SourcePolicy | str") -> SourcePolicy:
    if isinstance(value, SourcePolicy):
        return value
    return SourcePolicy(value)


@dataclass(slots=True)
class AppSettings:
    source_dir: str = r"D:\Projects\ToArchive"
    archive_dir: str = r"E:\Archive"
    archived_source_dir: str = ""
    poll_interval_seconds: int = 30
    generate_checksum: bool = False
    auto_scan: bool = True
    skip_existing_archives: bool = True
    source_policy: SourcePolicy = SourcePolicy.KEEP

    def __post_init__(self) -> None:
        self.source_policy = coerce_source_policy(self.source_policy)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AppSettings":
        source_policy = payload.get("source_policy", SourcePolicy.KEEP)
        return cls(
            source_dir=payload.get("source_dir", r"D:\Projects\ToArchive"),
            archive_dir=payload.get("archive_dir", r"E:\Archive"),
            archived_source_dir=payload.get("archived_source_dir", ""),
            poll_interval_seconds=int(payload.get("poll_interval_seconds", 30)),
            generate_checksum=bool(payload.get("generate_checksum", False)),
            auto_scan=bool(payload.get("auto_scan", True)),
            skip_existing_archives=bool(payload.get("skip_existing_archives", True)),
            source_policy=SourcePolicy(source_policy),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_policy"] = coerce_source_policy(self.source_policy).value
        return payload


@dataclass(slots=True)
class ProjectRecord:
    name: str
    source_path: str
    archive_path: str = ""
    status: ProjectStatus = ProjectStatus.PENDING
    excluded: bool = False
    detail: str = ""
    file_count: int = 0
    total_bytes: int = 0
    checksum_sha256: str = ""
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectRecord":
        return cls(
            name=payload["name"],
            source_path=payload["source_path"],
            archive_path=payload.get("archive_path", ""),
            status=ProjectStatus(payload.get("status", ProjectStatus.PENDING)),
            excluded=bool(payload.get("excluded", False)),
            detail=payload.get("detail", ""),
            file_count=int(payload.get("file_count", 0)),
            total_bytes=int(payload.get("total_bytes", 0)),
            checksum_sha256=payload.get("checksum_sha256", ""),
            updated_at=payload.get("updated_at", utc_now_iso()),
        )


@dataclass(slots=True)
class ArchiveResult:
    project_name: str
    source_path: str
    archive_path: str
    status: ProjectStatus
    detail: str
    file_count: int = 0
    total_bytes: int = 0
    checksum_sha256: str = ""
    partial_path: str = ""
    updated_at: str = field(default_factory=utc_now_iso)

    def to_record(self) -> ProjectRecord:
        return ProjectRecord(
            name=self.project_name,
            source_path=self.source_path,
            archive_path=self.archive_path,
            status=self.status,
            excluded=False,
            detail=self.detail,
            file_count=self.file_count,
            total_bytes=self.total_bytes,
            checksum_sha256=self.checksum_sha256,
            updated_at=self.updated_at,
        )


@dataclass(slots=True)
class ArchivedProjectRecord:
    name: str
    archive_path: str
    target_path: str
    status: str
    detail: str
    archived_at: str = ""
    file_count: int = 0
    total_bytes: int = 0


@dataclass(slots=True)
class RestoreResult:
    project_name: str
    archive_path: str
    target_path: str
    status: str
    detail: str
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class IndexEntry:
    project_name: str
    archive_path: str
    source_path: str
    file_count: int
    total_bytes: int
    checksum_sha256: str
    archived_at: str
    source_policy: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class HistoryEntry:
    timestamp: str
    project_name: str
    status: str
    message: str
    archive_path: str = ""
    source_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "HistoryEntry":
        return cls(
            timestamp=payload["timestamp"],
            project_name=payload.get("project_name", ""),
            status=payload.get("status", ""),
            message=payload.get("message", ""),
            archive_path=payload.get("archive_path", ""),
            source_path=payload.get("source_path", ""),
        )


def path_as_str(path: Path | None) -> str:
    return "" if path is None else str(path)
