"""Adapter interface.

To add support for a new agent CLI, subclass SessionAdapter, implement
discover() and parse(), and register it in adapters/__init__.py. Adapters
must be tolerant: unknown fields are ignored, malformed lines are skipped,
and a partially parsed session is better than a crash.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ctxprof.models import Session


class SessionAdapter(ABC):
    """Parses one agent CLI's native transcripts into normalized Sessions."""

    name: str = "base"

    @abstractmethod
    def discover(self, data_dir: Path | None = None) -> list[Path]:
        """Return transcript files available on this machine."""

    @abstractmethod
    def parse(self, path: Path) -> Session | None:
        """Parse one transcript file. Return None if it holds no usable steps."""
