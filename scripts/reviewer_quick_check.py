#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from patchrail.reviewer_quick_check import main


ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    raise SystemExit(main(root=ROOT))
