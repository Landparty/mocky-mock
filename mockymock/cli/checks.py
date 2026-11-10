"""Deprecated alias: this module moved to `mockymock.engine.checks`.

Kept for one minor release so library code importing the old path keeps
working; it warns on first attribute access. Import from
`mockymock.engine.checks` instead."""

from __future__ import annotations

import importlib
import warnings
from typing import Any


def __getattr__(name: str) -> Any:
    warnings.warn(
        "mockymock.cli.checks moved to mockymock.engine.checks",
        DeprecationWarning,
        stacklevel=2,
    )
    return getattr(importlib.import_module("mockymock.engine.checks"), name)
