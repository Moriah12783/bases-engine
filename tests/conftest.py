import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURES = ROOT / "fixtures"
# Les tests n'ont besoin d'aucun réseau : base « moteur » synthétique générée à chaque session (jamais committée,
# décision du mentor du 25/09/2026) par scripts/generer_fixture.py, dans un répertoire temporaire.
import importlib.util as _ilu  # noqa: E402
_spec = _ilu.spec_from_file_location("generer_fixture", ROOT / "scripts" / "generer_fixture.py")
_gen = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_gen)
SYNTH = Path(tempfile.mkdtemp(prefix="bases-fixture-"))
SNAPSHOT_DIR = _gen.generer(SYNTH)
RESULTATS_SYNTH = SYNTH / "resultats"
os.environ["BASES_LOCAL_SNAPSHOT_DIR"] = str(SNAPSHOT_DIR)
os.environ.setdefault("BASES_CACHE_DIR", str(ROOT / ".cache" / "tests"))
_TMP = Path(tempfile.mkdtemp(prefix="bases-tests-"))
os.environ.setdefault("BASES_RAPPORTS_DIR", str(_TMP / "rapports"))
os.environ.setdefault("BASES_SITE_DIR", str(_TMP / "site"))
os.environ.setdefault("BASES_DB_PATH", str(_TMP / "bases.db"))
os.environ.setdefault("BASES_RESULTS_LOCAL_DIR", str(FIXTURES / "resultats"))
os.environ.setdefault("NOTIFY_CHANNELS", "summary,journal")
os.environ.pop("GITHUB_STEP_SUMMARY", None)

import pytest  # noqa: E402


@pytest.fixture
def fixtures_dir():
    return FIXTURES


@pytest.fixture
def snapshot():
    from bases_engine.fetch import get_snapshot
    return get_snapshot(local_dir=SNAPSHOT_DIR)


@pytest.fixture
def results_client(fixtures_dir):
    from bases_engine.fetch import ResultsClient
    return ResultsClient(base_url=f"file://{fixtures_dir / 'resultats'}")


@pytest.fixture
def fixtures_synth():
    """JSON publics de résultats de la journée synthétique de cas limites (2026-09-18)."""
    return RESULTATS_SYNTH

