from pathlib import Path

from python_magnetrun.data_dirs import PIGBROTHER_DATA_DIR, PUPITRE_DATA_DIR

ROOT           = Path(__file__).resolve().parent.parent
RESULTS_DIR    = ROOT / "stage/results"

PUPITRE_DIR    = Path(PUPITRE_DATA_DIR)
PIGBROTHER_DIR = Path(PIGBROTHER_DATA_DIR)

PIGBROTHER     = PIGBROTHER_DIR / "M10" / "Overview" / "M10_Overview_251201-0909.tdms"

DB = Path("../to_duckdb/test-magnetdb.duckdb")

FIELD_THRESHOLD = 0.1

def print_title(title):

    print("\n" + (" " + title + " ").center(80, "=") + "\n")
