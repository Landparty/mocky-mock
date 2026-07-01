"""Temporary sandbox directories for compiling and running COBOL programs."""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def sandbox_dir() -> Iterator[Path]:
    """Yield a fresh temp directory, removed on exit."""
    path = Path(tempfile.mkdtemp(prefix="mockymock-"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
