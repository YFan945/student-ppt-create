#!/usr/bin/env python3
"""Compatibility command path for the main-session production tools."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from direct_production import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
