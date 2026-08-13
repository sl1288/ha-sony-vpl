# ruff: noqa: INP001  # pytest rootdir conftest, deliberately not a package
"""Pytest configuration for the Sony VPL custom component.

Puts this directory on ``sys.path`` so the tests can import the component as
``custom_components.sony_vpl``, the same name Home Assistant loads it under.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
