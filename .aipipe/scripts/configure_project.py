#!/usr/bin/env python3
"""Compatibility entry; the implementation lives in the aipipe package."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from aipipe.config import main
if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError) as exc:
        print("Stopped: " + str(exc), file=sys.stderr)
        raise SystemExit(2)
