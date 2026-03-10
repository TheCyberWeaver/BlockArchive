from __future__ import annotations

import tarfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blockarchive.archiver import ProjectArchiver
from blockarchive.models import AppSettings, ProjectStatus
from test_support import workspace_tempdir


class ProjectArchiverTests(unittest.TestCase):
    def test_settings_accept_string_source_policy(self) -> None:
        settings = AppSettings(
            source_dir="D:\\Projects\\ToArchive",
            archive_dir="E:\\Archive",
            source_policy="keep",
        )

        self.assertEqual(settings.to_dict()["source_policy"], "keep")

    def test_archive_success_writes_tar_and_preserves_source(self) -> None:
        with workspace_tempdir() as root:
            source_root = root / "ToArchive"
            archive_root = root / "Archive"
            project_dir = source_root / "ProjectA"
            project_dir.mkdir(parents=True)
            (project_dir / "notes.txt").write_text("hello", encoding="utf-8")
            (project_dir / "assets").mkdir()
            (project_dir / "assets" / "image.bin").write_bytes(b"\x00\x01\x02")

            archiver = ProjectArchiver(
                AppSettings(
                    source_dir=str(source_root),
                    archive_dir=str(archive_root),
                )
            )

            result = archiver.archive_project(project_dir)

            self.assertEqual(result.status, ProjectStatus.SUCCESS)
            self.assertTrue(project_dir.exists())
            final_archive = archive_root / "ProjectA.tar"
            self.assertTrue(final_archive.exists())
            self.assertFalse((archive_root / "ProjectA.tar.partial").exists())

            with tarfile.open(final_archive, "r:") as tar_handle:
                members = {member.name for member in tar_handle.getmembers()}
            self.assertIn("ProjectA", members)
            self.assertIn("ProjectA/notes.txt", members)
            self.assertIn("ProjectA/assets/image.bin", members)

    def test_retry_is_required_when_stale_partial_exists(self) -> None:
        with workspace_tempdir() as root:
            source_root = root / "ToArchive"
            archive_root = root / "Archive"
            project_dir = source_root / "ProjectB"
            project_dir.mkdir(parents=True)
            (project_dir / "file.txt").write_text("hello", encoding="utf-8")
            archive_root.mkdir()
            stale_partial = archive_root / "ProjectB.tar.partial"
            stale_partial.write_text("incomplete", encoding="utf-8")

            archiver = ProjectArchiver(
                AppSettings(
                    source_dir=str(source_root),
                    archive_dir=str(archive_root),
                )
            )

            result = archiver.archive_project(project_dir)

            self.assertEqual(result.status, ProjectStatus.FAILED)
            self.assertIn("Stale partial archive detected", result.detail)
            self.assertTrue(project_dir.exists())
            self.assertTrue(stale_partial.exists())

    def test_failed_write_leaves_partial_and_source_intact(self) -> None:
        with workspace_tempdir() as root:
            source_root = root / "ToArchive"
            archive_root = root / "Archive"
            project_dir = source_root / "ProjectC"
            project_dir.mkdir(parents=True)
            (project_dir / "file.txt").write_text("hello", encoding="utf-8")

            archiver = ProjectArchiver(
                AppSettings(
                    source_dir=str(source_root),
                    archive_dir=str(archive_root),
                )
            )

            def failing_write(source_dir: Path, partial_path: Path) -> None:
                partial_path.parent.mkdir(parents=True, exist_ok=True)
                partial_path.write_text("partial", encoding="utf-8")
                raise OSError("Disk disappeared")

            archiver._write_archive = failing_write  # type: ignore[method-assign]

            result = archiver.archive_project(project_dir)

            self.assertEqual(result.status, ProjectStatus.FAILED)
            self.assertTrue(project_dir.exists())
            self.assertTrue((archive_root / "ProjectC.tar.partial").exists())
            self.assertFalse((archive_root / "ProjectC.tar").exists())
            self.assertIn("Disk disappeared", result.detail)


if __name__ == "__main__":
    unittest.main()
