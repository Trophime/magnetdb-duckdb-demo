"""
stress_map.py  (tutorial shim)
=======================================
This script is kept for backward compatibility and tutorial use.
The full implementation now lives in ../stress_map.py and is accessible
through the unified CLI (run from the to_duckdb/ directory):

    python magnetdb.py hoop-stress barchart <site> [options]
    python magnetdb.py hoop-stress history  <site> [options]
    python magnetdb.py hoop-stress stats    <site> [options]
    python magnetdb.py hoop-stress fatigue  <site> [options]

Run ``python magnetdb.py hoop-stress --help`` for full usage.

For a step-by-step explanation of how the chain works (DuckDB →
geometry YAML → magnettools → stress computation), see:

    README_student_stress_map.md
    student_statheures_note.md
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stress_map import main

if __name__ == "__main__":
    main()
