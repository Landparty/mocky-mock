"""Deprecated alias: this module moved to `mockymock.project.copybook_aliases`.

Kept for one minor release so library code importing the old path keeps
working; it warns on first attribute access. Import from
`mockymock.project.copybook_aliases` instead."""

from __future__ import annotations

import importlib
import warnings
from typing import Any


def __getattr__(name: str) -> Any:
    warnings.warn(
        "mockymock.cli.copybook_aliases moved to mockymock.project.copybook_aliases",
        DeprecationWarning,
        stacklevel=2,
    )
    return getattr(importlib.import_module("mockymock.project.copybook_aliases"), name)
