"""Deprecated alias: this module moved to `mockymock.project.ai_mode`.

Kept for one minor release so library code importing the old path keeps
working; it warns on first attribute access. Import from
`mockymock.project.ai_mode` instead."""

from __future__ import annotations

import importlib
import warnings
from typing import Any


def __getattr__(name: str) -> Any:
    warnings.warn(
        "mockymock.cli.ai_mode moved to mockymock.project.ai_mode",
        DeprecationWarning,
        stacklevel=2,
    )
    return getattr(importlib.import_module("mockymock.project.ai_mode"), name)
