#!/usr/bin/env python3
"""Compatibility entry point for the pre-v0.1 loyalty-intel-digest CLI."""

from __future__ import annotations

import sys

from loyalty_radar.engine import *  # noqa: F403
from loyalty_radar.engine import main as legacy_main

if __name__ == "__main__":
    print(
        "run_digest.py is retained for compatibility; prefer `loyalty-radar run`.",
        file=sys.stderr,
    )
    raise SystemExit(legacy_main())

