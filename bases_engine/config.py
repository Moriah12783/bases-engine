"""Configuration du service (variables d'environnement, chemins, constantes)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("BASES_ROOT", Path(__file__).resolve().parent.parent))

# --- Source moteur : base vivante sur R2, lecture seule (décision du mentor du 25/09/2026) ------------
# Contrat de lecture : l'objet turf_bench.db du bucket turf-engine-data, rien d'autre (jamais backups/ ni state/),
# et les JSON publics de résultats. Aucune lecture du dépôt turf-engine (ni ls-remote, ni fichiers bruts).
R2_BUCKET = os.environ.get("BASES_R2_BUCKET", "turf-engine-data")
R2_OBJECT = "turf_bench.db"                      # clé fixe : aucune autre clé du bucket n'est lue
R2_ACCOUNT_ENV = "CLOUDFLARE_ACCOUNT_ID"         # point d'accès https://<compte>.r2.cloudflarestorage.com
R2_KEY_ID_ENV, R2_SECRET_ENV = "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"
R2_MAX_RETRIES, R2_RETRY_DELAY_S = 3, 30.0      # écart d'empreinte : jusqu'à 3 nouvelles lectures à 30 s, puis job rouge
SOURCE_STALE_WARN_S = 3600                      # pushed-at plus vieux qu'une heure : avertissement seulement
LOCAL_SNAPSHOT_DIR = os.environ.get("BASES_LOCAL_SNAPSHOT_DIR")          # base + source.json déjà présents (tests, hors-ligne)
DB_FILENAME = "turf_bench.db"
DOWNLOAD_BUDGET_PER_DAY = 4
CACHE_DIR = Path(os.environ.get("BASES_CACHE_DIR", ROOT / ".cache"))

# --- Résultats publics ------------------------------------------------------------
RESULTS_BASE_URL = os.environ.get("BASES_RESULTS_BASE_URL", "https://prono.elite-turf.fr/resultats")
RESULTS_MIN_INTERVAL_S = 60.0

# --- Moteur et horizons --------------------------------------------------------------
ENGINE_NAME = "NEW_VALUE_ENGINE"
MARKET_ENGINE = "MARKET_BASELINE"
HORIZONS = ("T_MATIN", "T90", "T30", "T15")
KNOWN_PUBLICATION_REASONS = {"OK", "RACE_STARTED", "ODDS_DEFAULT", "RACE_CANCELLED", "PRICED_RATIO_LOW", "BEFORE_0630"}
CONTRACT_VERSION = 2

# --- Éligibilité (§4.1-4.2) ---------------------------------------------------------------
MIN_PRICED_RATIO = 0.9
MIN_FIELD = 8
MIN_CANDIDATES = 6
MAX_CANDIDATES = 8
START_MARGIN_MIN = 20
PROB_SUM_TOL = 0.01

# Paris utiles pour la structure de ticket (ordre de priorité d'affichage) et libellés français
PARIS_UTILES = ("QUINTE_PLUS", "QUARTE_PLUS", "MULTI", "MINI_MULTI", "DEUX_SUR_QUATRE", "TRIO", "COUPLE_PLACE")
PARIS_LIBELLES = {"QUINTE_PLUS": "Quinté+", "QUARTE_PLUS": "Quarté+", "MULTI": "Multi", "MINI_MULTI": "Mini Multi",
                  "DEUX_SUR_QUATRE": "2sur4", "TRIO": "Trio", "COUPLE_PLACE": "Couplé placé"}

# --- Favicon (présentation) : fichiers copiés depuis assets/favicon/ à la racine de site/, balises du <head> commun ---
FAVICON_DIR = ROOT / "assets" / "favicon"
FAVICON_FILES = ("favicon.svg", "favicon.ico", "favicon-32.png", "apple-touch-icon.png", "favicon-512.png")
FAVICON_HEAD = ('<link rel="icon" type="image/svg+xml" href="/favicon.svg">'
                '<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">'
                '<link rel="shortcut icon" href="/favicon.ico">'
                '<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">'
                '<meta name="theme-color" content="#0A0A0A">')

# --- Calcul (§4.3) ------------------------------------------------------------------------
N_SIMS = 40_000
DEFAULT_LAMBDAS = (1.0, 0.81, 0.65, 0.55, 0.50)
SHRINK = 0.85                      # facteur fixe du palier « fixe »
CALIB_MIN_N = 150                 # (historique) — remplacé par CALIB_LEVELS
# Échelle d'estimateurs de recalibration (décision mentor 21/09/2026), par (k, top_m) selon n :
CALIB_LEVELS = {
    "fixe": {"n_max": 150, "facteur": 0.85},
    "ratio": {"n_min": 150, "n_max": 300, "bornes": [0.60, 1.00]},
    "logit": {"n_min": 300, "n_max": 1000},
    "isotonique": {"n_min": 1000},
}

# --- Stockage ---------------------------------------------------------------------------------
DB_PATH = Path(os.environ.get("BASES_DB_PATH", ROOT / "bases.db"))
PARAMS_PATH = ROOT / "params.json"
RAPPORTS_DIR = Path(os.environ.get("BASES_RAPPORTS_DIR", ROOT / "rapports"))
SITE_DIR = Path(os.environ.get("BASES_SITE_DIR", ROOT / "site"))
