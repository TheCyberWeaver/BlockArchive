from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
import shutil


WORKSPACE_TEMP_ROOT = Path(__file__).resolve().parent / ".tmp"
WORKSPACE_TEMP_ROOT.mkdir(exist_ok=True)


@contextmanager
def workspace_tempdir():
    temp_dir = WORKSPACE_TEMP_ROOT / f"case-{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
