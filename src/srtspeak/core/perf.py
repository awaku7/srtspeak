"""Small privacy-conscious performance logging helpers."""

from __future__ import annotations

import json
import sys
from typing import Any


def log_perf(**fields: Any) -> None:
    """Write one structured performance event to stderr without source text."""
    try:
        print(
            "[perf] " + json.dumps(fields, ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
            flush=True,
        )
    except (OSError, TypeError, ValueError):
        # Diagnostics must never interrupt the actual translation/build.
        pass
