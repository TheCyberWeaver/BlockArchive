from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blockarchive.manager import ArchiveManager
from blockarchive.models import AppSettings, ProjectStatus, SourcePolicy
from blockarchive.settings import SettingsStore


class ArchiveManagerTests(unittest.TestCase):
    def test_scan_only_queues_and_run_queue_writes_index_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "ToArchive"
            archive_root = root / "Archive"
            project_dir = source_root / "ProjectA"
            project_dir.mkdir(parents=True)
            (project_dir / "notes.txt").write_text("hello", encoding="utf-8")

            settings_store = SettingsStore(root / "settings.json")
            settings_store.save(
                AppSettings(
                    source_dir=str(source_root),
                    archive_dir=str(archive_root),
                    auto_scan=False,
                )
            )

            manager = ArchiveManager(settings_store)
            snapshot = manager.scan_and_process()

            self.assertEqual(len(snapshot), 1)
            self.assertEqual(snapshot[0].status, ProjectStatus.PENDING)
            self.assertFalse((archive_root / "ProjectA.tar").exists())

            snapshot = manager.process_pending()
            self.assertEqual(snapshot[0].status, ProjectStatus.SUCCESS)

            index_payload = json.loads((archive_root / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(index_payload["archives"][0]["project_name"], "ProjectA")
            history_lines = (archive_root / "history.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(history_lines), 1)
            history_entry = json.loads(history_lines[0])
            self.assertEqual(history_entry["status"], "success")

    def test_move_source_policy_moves_source_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "ToArchive"
            archive_root = root / "Archive"
            archived_source_root = root / "ArchivedSource"
            project_dir = source_root / "ProjectB"
            project_dir.mkdir(parents=True)
            (project_dir / "notes.txt").write_text("hello", encoding="utf-8")

            settings_store = SettingsStore(root / "settings.json")
            settings_store.save(
                AppSettings(
                    source_dir=str(source_root),
                    archive_dir=str(archive_root),
                    archived_source_dir=str(archived_source_root),
                    auto_scan=False,
                    source_policy=SourcePolicy.MOVE,
                )
            )

            manager = ArchiveManager(settings_store)
            manager.scan_and_process()
            snapshot = manager.process_pending()

            self.assertEqual(snapshot[0].status, ProjectStatus.SUCCESS)
            self.assertFalse(project_dir.exists())
            self.assertTrue((archived_source_root / "ProjectB").exists())
            self.assertTrue((archive_root / "ProjectB.tar").exists())

    def test_excluded_project_is_not_processed_when_queue_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "ToArchive"
            archive_root = root / "Archive"
            project_a = source_root / "ProjectA"
            project_b = source_root / "ProjectB"
            project_a.mkdir(parents=True)
            project_b.mkdir(parents=True)
            (project_a / "a.txt").write_text("a", encoding="utf-8")
            (project_b / "b.txt").write_text("b", encoding="utf-8")

            settings_store = SettingsStore(root / "settings.json")
            settings_store.save(
                AppSettings(
                    source_dir=str(source_root),
                    archive_dir=str(archive_root),
                    auto_scan=False,
                )
            )

            manager = ArchiveManager(settings_store)
            snapshot = manager.scan_and_process()
            excluded_source = next(record.source_path for record in snapshot if record.name == "ProjectB")
            manager.set_excluded([excluded_source], True)

            snapshot = manager.process_pending()

            statuses = {record.name: record.status for record in snapshot}
            excluded_flags = {record.name: record.excluded for record in snapshot}
            self.assertEqual(statuses["ProjectA"], ProjectStatus.SUCCESS)
            self.assertEqual(statuses["ProjectB"], ProjectStatus.PENDING)
            self.assertTrue(excluded_flags["ProjectB"])
            self.assertTrue((archive_root / "ProjectA.tar").exists())
            self.assertFalse((archive_root / "ProjectB.tar").exists())


if __name__ == "__main__":
    unittest.main()
