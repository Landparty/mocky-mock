"""Deprecated alias: this module moved to `mockymock.project.config`.

Kept for one minor release so library code importing the old path keeps
working; it warns on first attribute access. Import from
`mockymock.project.config` instead."""

from __future__ import annotations

import importlib
import warnings
from typing import Any


def __getattr__(name: str) -> Any:
    warnings.warn(
        "mockymock.cli.config moved to mockymock.project.config",
        DeprecationWarning,
        stacklevel=2,
    )
    return getattr(importlib.import_module("mockymock.project.config"), name)
