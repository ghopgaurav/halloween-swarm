#!/usr/bin/env python
"""One-command entry: `python main.py [--fixture FILE | --dry-run]`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from halloween_swarm.main import run  # noqa: E402

if __name__ == "__main__":
    run()
