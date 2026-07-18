"""Cancellation token for cooperative stop."""

from __future__ import annotations


class BuildCancelled(Exception):
    """User-requested cooperative cancellation."""


class CancellationToken:
    def __init__(self) -> None:
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True

    def check(self) -> None:
        if self._cancelled:
            raise BuildCancelled("build cancelled")
