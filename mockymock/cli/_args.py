"""argparse building blocks the subcommands' `register_*` functions share:
value types with a readable error, and the help formatter."""

from __future__ import annotations

import argparse
import math
import re


def _timeout_seconds(value: str) -> int:
    """argparse `type=` for `--timeout`: a whole number of seconds, at
    least 1. coreutils `timeout 0` disables the container-side kill, so a
    hung binary outlived its `docker exec` as an orphan at 100% CPU, and a
    negative value made `timeout` itself fail with exit 125 (issue
    #306)."""
    try:
        seconds = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}") from None
    if seconds < 1:
        raise argparse.ArgumentTypeError("--timeout must be at least 1 second")
    return seconds


def _percent(value: str) -> float:
    """argparse `type=` for a percentage gate (`--coverage-fail-under`,
    `--fail-under`): a finite number from 0 to
    100. A plain `type=float` took `nan` -- every `<` comparison with it
    is false, so `--coverage-fail-under nan` silently never failed, and
    `mutate --fail-under nan` crashed with a traceback after the whole
    mutation run -- and took `150`, a gate no suite can ever pass."""
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid number: {value!r}") from None
    if not math.isfinite(number) or not 0 <= number <= 100:
        raise argparse.ArgumentTypeError(
            f"must be a percentage from 0 to 100, got {value!r}"
        )
    return number


def _positive_seconds(value: str) -> float:
    """argparse `type=` for the runner's `--poll-interval` and
    `--suite-timeout`: a finite number of seconds above 0. A negative
    poll interval crashed the runner on its first idle `sleep()`, 0 made
    it claim jobs in a busy loop against the backend, and a timeout of 0
    or less killed every suite before it started."""
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid number: {value!r}") from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError(
            f"must be a number of seconds above 0, got {value!r}"
        )
    return seconds


_SUITE_NAME_RE = re.compile(r"[A-Za-z0-9_-]+")


def _suite_name(value: str) -> str:
    """argparse `type=` for `--name` (#336): NAME becomes the middle of
    `<program>.<NAME>.cut`, so it must be one plain word -- a `/` would
    create folders no command pairs back to the program, and `..` would
    write outside the tests folder."""
    if not _SUITE_NAME_RE.fullmatch(value):
        raise argparse.ArgumentTypeError(
            f"invalid suite name {value!r}: NAME becomes the middle of "
            "<program>.<NAME>.cut, so use only letters, digits, '-' and '_'"
        )
    return value
