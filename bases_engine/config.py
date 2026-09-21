"""Configuration du service (variables d'environnement, chemins, constantes)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("BASES_ROOT", Path(__file__).resolve().parent.parent))

# --- Source moteur (lecture seule, dépôt public) ---------------------------------
ENGINE_REPO = "Moriah12783/turf-engine"
ENGINE_GIT_URL = os.environ.get("BASES_ENGINE_GIT_URL", f"https://github.com/{ENGINE_REPO}.git")
ENGINE_BRANCH = "main"
# Source alternative (§12) : base d'URL des fichiers bruts, ou répertoire local (tests / hors-ligne).
SOURCE_BASE_URL = os.environ.get("BASES_SOURCE_BASE_URL", f"https://raw.githubusercontent.com/{ENGINE_REPO}")
LOCAL_SNAPSHOT_DIR = os.environ.get("BASES_LOCAL_SNAPSHOT_DIR")          # ex. .cache/<sha> déjà rempli
DB_FILENAME = os.environ.get("BASES_DB_FILENAME", "turf_bench.db")        # peut être turf_bench.db.gz
REPORT_FILENAME = os.environ.get("BASES_REPORT_FILENAME", "benchmark_report.json")
DOWNLOAD_BUDGET_PER_DAY = 4
CACHE_DIR = Path(os.environ.get("BASES_CACHE_DIR", ROOT / ".cache"))

# --- Résultats publics ------------------------------------------------------------
RESULTS_BASE_URL = os.environ.get("BASES_RESULTS_BASE_URL", "https://prono.elite-turf.fr/resultats")
RESULTS_MIN_INTERVAL_S = 60.0

# --- Moteur et horizons --------------------------------------------------------------
ENGINE_NAME = "NEW_VALUE_ENGINE"
MARKET_ENGINE = "MARKET_BASELINE"
HORIZONS = ("T_MATIN", "T90", "T30", "T15")
KNOWN_PUBLICATION_REASONS = {"OK", "RACE_STARTED", "ODDS_DEFAULT", "RACE_CANCELLED"}
CONTRACT_VERSION = 2

# --- Éligibilité (§4.1-4.2) ---------------------------------------------------------------
MIN_PRICED_RATIO = 0.9
MIN_FIELD = 8
MIN_CANDIDATES = 6
MAX_CANDIDATES = 8
START_MARGIN_MIN = 20
PROB_SUM_TOL = 0.01

# --- Calcul (§4.3) ------------------------------------------------------------------------
N_SIMS = 40_000
DEFAULT_LAMBDAS = (1.0, 0.81, 0.65, 0.55, 0.50)
SHRINK = 0.85
CALIB_MIN_N = 150

# --- Stockage ---------------------------------------------------------------------------------
DB_PATH = Path(os.environ.get("BASES_DB_PATH", ROOT / "bases.db"))
PARAMS_PATH = ROOT / "params.json"
RAPPORTS_DIR = ROOT / "rapports"
