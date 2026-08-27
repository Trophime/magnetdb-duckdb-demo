import json
import duckdb
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import time

from rich.progress import Progress

from python_magnetrun.MagnetRun import MagnetRun, load_mrun
from python_magnetrun.signature import Signature




ROOT           = Path(__file__).resolve().parent.parent
RESULTS_DIR    = ROOT / "stage/results"

RECORDS_DIR    = Path("/mnt/LNCMIG-Data/records")
PUPITRE_DIR    = RECORDS_DIR / "srv-data-install"
PIGBROTHER_DIR = RECORDS_DIR / "pbsurv"

PIGBROTHER     = PIGBROTHER_DIR / "M10" / "Overview" / "M10_Overview_251201-0909.tdms"

DB = Path("../to_duckdb/test-magnetdb.duckdb")

FIELD_THRESHOLD = 0.1

def print_title(title):

    print("\n" + (" " + title + " ").center(80, "=") + "\n")