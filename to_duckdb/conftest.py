"""Ensure the to_duckdb directory is on sys.path so schema/crud can be imported."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
