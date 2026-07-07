"""Temporary sandbox directories for compiling and running COBOL programs."""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def sandbox_dir(root: Path | None = None) -> Iterator[Path]:
    """Yield a fresh temp directory, removed on exit.

    With `root`, the sandbox is created under that directory (created if
    missing). The Docker toolchain requires this: only paths under its
    bind-mounted work root are visible inside the container."""
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="mockymock-", dir=root))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@contextmanager
def sandbox_dir_maybe_kept(root: Path | None, keep: bool) -> Iterator[Path]:
    """Like `sandbox_dir`, but when `keep` is True the directory is left on
    disk (and never deleted) instead of being cleaned up on exit."""
    if not keep:
        with sandbox_dir(root=root) as path:
            yield path
        return
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
    yield Path(tempfile.mkdtemp(prefix="mockymock-", dir=root))
