import pytest

from bases_engine.contract import run_contract_checks
from bases_engine.fetch import FetchError


class _OKClient:
    def manifest(self):
        return {"journees": [{"date": "2026-09-21", "empreinte_sha256": "abc"}]}


class _DownClient:
    def manifest(self):
        raise FetchError("HTTP 403")


def test_contract_passes_on_frozen_snapshot(snapshot):
    res = run_contract_checks(snapshot, "2026-09-21", results_client=_OKClient())
    assert res.ok, res.summary()
    assert not res.skipped


def test_contract_fails_when_manifest_unreachable(snapshot):
    res = run_contract_checks(snapshot, "2026-09-21", results_client=_DownClient())
    assert not res.ok
    assert any(name == "manifeste index.json" for name, _ in res.failed)


def test_contract_no_network_is_explicitly_skipped(snapshot):
    res = run_contract_checks(snapshot, "2026-09-21", network=False)
    assert res.ok and res.skipped and "NON exécuté" in res.skipped[0][1]


def test_contract_fails_on_unknown_date(snapshot):
    res = run_contract_checks(snapshot, "2030-01-01", network=False)
    assert not res.ok
    assert any("date J" in name or "contract_version" in name for name, _ in res.failed)


def test_contract_detects_schema_drift(snapshot, tmp_path):
    import shutil
    import sqlite3
    from bases_engine.fetch import Snapshot
    db = tmp_path / "turf_bench.db"
    shutil.copy(snapshot.db_path, db)
    con = sqlite3.connect(db)
    con.execute("alter table predictions rename column prediction_hash to hash_prediction")
    con.commit(); con.close()
    drift = Snapshot("drift", tmp_path, db, {"origine": "local", "sha256": "drift"})
    res = run_contract_checks(drift, "2026-09-21", network=False)
    assert not res.ok and res.failed[0][0] == "schema:predictions"


def test_contract_passes_with_local_results_fixture(snapshot, fixtures_dir):
    from bases_engine.fetch import ResultsClient
    client = ResultsClient(base_url=f"file://{fixtures_dir / 'resultats'}")
    res = run_contract_checks(snapshot, "2026-09-21", results_client=client)
    assert res.ok and not res.skipped, res.summary()


def test_day_without_predictions_is_explained_with_source_header(snapshot):
    """Aucune prédiction du jour dans la base lue : le motif cite l'en-tête de la source (base R2, empreinte, poussée)."""
    from bases_engine.contract import CHECK_PREDICTIONS
    res = run_contract_checks(snapshot, "2026-09-22", network=False)
    assert res.jour_sans_predictions
    detail = dict(res.failed)[CHECK_PREDICTIONS]
    assert "aucune prédiction du jour dans la base du moteur lue" in detail and "sha256 " in detail and "poussée 2026-09-21T09:00:00Z" in detail
    assert "copie Git" not in detail and "développeur du moteur" not in detail
