"""File I/O utilities for safe persistence."""

from __future__ import annotations

import os
from pathlib import Path  # noqa: TC003 — used at runtime


def atomic_write(path: Path, content: str) -> None:
    """Write content to a file atomically using temp file + rename.

    Prevents data corruption if the process crashes or two agents write
    concurrently. On both POSIX and Windows, ``os.replace`` is atomic
    at the filesystem level.
    """
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)
