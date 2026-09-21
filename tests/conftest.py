import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURES = ROOT / "fixtures"
# Les tests n'ont besoin d'aucun réseau : instantané figé dans fixtures/snapshot/.
os.environ.setdefault("BASES_LOCAL_SNAPSHOT_DIR", str(FIXTURES / "snapshot"))
os.environ.setdefault("BASES_CACHE_DIR", str(ROOT / ".cache" / "tests"))

import pytest  # noqa: E402


@pytest.fixture
def fixtures_dir():
    return FIXTURES


@pytest.fixture
def snapshot():
    from bases_engine.fetch import get_snapshot
    return get_snapshot(local_dir=FIXTURES / "snapshot")
