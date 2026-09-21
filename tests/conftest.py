import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURES = ROOT / "fixtures"
# Les tests n'ont besoin d'aucun réseau : instantané figé dans fixtures/snapshot/.
os.environ.setdefault("BASES_LOCAL_SNAPSHOT_DIR", str(FIXTURES / "snapshot"))
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
    return get_snapshot(local_dir=FIXTURES / "snapshot")


@pytest.fixture
def results_client(fixtures_dir):
    from bases_engine.fetch import ResultsClient
    return ResultsClient(base_url=f"file://{fixtures_dir / 'resultats'}")
