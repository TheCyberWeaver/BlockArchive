# BlockArchive

BlockArchive is a Windows desktop app for safely turning many small-file project folders into one uncompressed `.tar` archive per project.

The app follows the workflow described in the development guide:

- watches or scans a source folder such as `D:\Projects\ToArchive`
- writes archives to a destination such as `E:\Archive`
- treats each first-level folder as one project
- writes `ProjectName.tar.partial` first, verifies it, then atomically renames it to `ProjectName.tar`
- keeps the source intact until the archive is fully finalized
- maintains `index.json` and `history.jsonl`

## Features

- uncompressed per-project tar archives
- failure-safe `.partial` workflow
- retry for failed projects
- stale partial detection and cleanup
- optional SHA-256 checksum generation
- post-success source policy:
  - keep source
  - move source to `ArchivedSource`
  - delete source
- lightweight PySide6 desktop UI with dashboard, settings, and history

## Install

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

## Run

```powershell
blockarchive
```

You can also run:

```powershell
python -m blockarchive
```

## Default behavior

- source folder: `D:\Projects\ToArchive`
- archive folder: `E:\Archive`
- poll interval: 30 seconds
- source policy: keep source
- checksums: disabled
- skip if `ProjectName.tar` already exists

Settings are stored in the user profile under `%APPDATA%\BlockArchive\settings.json` on Windows.

Archive metadata is written into the selected archive destination:

- `index.json`
- `history.jsonl`
- optional `ProjectName.tar.sha256`

## Test

Backend verification uses the standard library test runner:

```powershell
python -m unittest discover -s tests
```
