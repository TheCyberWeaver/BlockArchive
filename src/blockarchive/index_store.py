from __future__ import annotations

import json
import os
from pathlib import Path

from .models import IndexEntry


class IndexStore:
    def __init__(self, archive_dir: Path) -> None:
        self.path = archive_dir / "index.json"

    def load(self) -> list[IndexEntry]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        archives = payload.get("archives", [])
        return [IndexEntry(**item) for item in archives]

    def upsert(self, entry: IndexEntry) -> None:
        current = {item.archive_path: item for item in self.load()}
        current[entry.archive_path] = entry
        self._write(list(current.values()))

    def _write(self, entries: list[IndexEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "archives": [entry.to_dict() for entry in sorted(entries, key=lambda item: item.project_name.lower())],
        }
        temp_path = self.path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temp_path, self.path)
