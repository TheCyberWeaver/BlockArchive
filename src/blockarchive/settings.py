from __future__ import annotations

import json
import os
from pathlib import Path

from .models import AppSettings, SourcePolicy


def default_config_dir() -> Path:
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / "BlockArchive"
    return Path.home() / ".blockarchive"


def resolve_archived_source_dir(settings: AppSettings) -> Path:
    if settings.archived_source_dir.strip():
        return Path(settings.archived_source_dir)
    return Path(settings.source_dir).parent / "ArchivedSource"


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_config_dir() / "settings.json"

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return AppSettings.from_dict(payload)

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(settings.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temp_path, self.path)

    def validate(self, settings: AppSettings) -> list[str]:
        errors: list[str] = []
        if not settings.source_dir.strip():
            errors.append("Source folder is required.")
        if not settings.archive_dir.strip():
            errors.append("Archive folder is required.")
        if settings.poll_interval_seconds < 5:
            errors.append("Poll interval must be at least 5 seconds.")
        return errors
