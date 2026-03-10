from __future__ import annotations

import json
from pathlib import Path

from .models import HistoryEntry


class HistoryStore:
    def __init__(self, archive_dir: Path) -> None:
        self.path = archive_dir / "history.jsonl"

    def append(self, entry: HistoryEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.to_dict(), sort_keys=True) + "\n")

    def read_recent(self, limit: int = 200) -> list[HistoryEntry]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        recent = lines[-limit:]
        return [HistoryEntry.from_dict(json.loads(line)) for line in reversed(recent) if line.strip()]
