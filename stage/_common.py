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




DATA_DIR = Path("../Data")
PUPITRE_ROOT = DATA_DIR / "pupitre_2023" / "srv-data-install"
PUPITRE_DIR = PUPITRE_ROOT / "M9"
PIGBROTHER = DATA_DIR / "pigbrother_2025" / "M10_Overview_251201-0909.tdms"

DB = Path("../to_duckdb/test-magnetdb.duckdb")

FIELD_THRESHOLD = 0.1

PATH_COLUMNS = [
    "overview", "archive", "pupitre", "default", "trigger", "spike",
    "hybrid_kHz", "hybrid_rms", "hybrid_trigger", "hybrid_vprocess",
    "pigbrother_runlog", "pupitre_runlog",
]