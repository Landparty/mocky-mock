"""Deprecated alias: this module moved to `mockymock.engine.mainframe_export`.

Kept for one minor release so library code importing the old path keeps
working; it warns on first attribute access. Import from
`mockymock.engine.mainframe_export` instead."""

from __future__ import annotations

import importlib
import warnings
from typing import Any


def __getattr__(name: str) -> Any:
    warnings.warn(
        "mockymock.cli.mainframe_export moved to mockymock.engine.mainframe_export",
        DeprecationWarning,
        stacklevel=2,
    )
    return getattr(importlib.import_module("mockymock.engine.mainframe_export"), name)
