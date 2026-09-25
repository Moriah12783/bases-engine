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


def test_day_without_predictions_is_a_warning_not_a_failure(snapshot):
    """Contrat de lecture (25/09/2026) : échec seulement sur une colonne attendue absente ou renommée, ou un contract_version
    inattendu. Une journée sans prédiction est un avertissement ; la garde de fraîcheur du matin décide de l'édition."""
    res = run_contract_checks(snapshot, "2030-01-01", network=False)
    assert res.ok and res.jour_sans_predictions
    assert any(n == "prédictions du jour" and "sha256 " in d for n, d in res.warnings)


def test_added_columns_and_tables_are_ignored(snapshot, tmp_path):
    import shutil
    import sqlite3
    from bases_engine.fetch import Snapshot
    db = tmp_path / "turf_bench.db"; shutil.copy(snapshot.db_path, db)
    con = sqlite3.connect(db)
    con.execute("alter table predictions add column nouvelle_colonne TEXT"); con.execute("create table nouvelle_table (x INTEGER)")
    con.execute("drop table rapports")                               # table non lue par Bases : sa disparition est sans effet
    con.commit(); con.close()
    res = run_contract_checks(Snapshot("ajout", tmp_path, db, {}), "2026-09-21", network=False)
    assert res.ok, res.summary()


def test_unexpected_contract_version_is_blocking(snapshot, tmp_path):
    import shutil
    import sqlite3
    from bases_engine.contract import CHECK_PREDICTIONS
    from bases_engine.fetch import Snapshot
    db = tmp_path / "turf_bench.db"; shutil.copy(snapshot.db_path, db)
    con = sqlite3.connect(db)
    con.execute("update predictions set contract_version=3 where race_id in (select race_id from races where date='2026-09-21')")
    con.commit(); con.close()
    res = run_contract_checks(Snapshot("v3", tmp_path, db, {}), "2026-09-21", network=False)
    assert not res.ok and res.failed[0][0] == CHECK_PREDICTIONS


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




def test_every_column_read_is_an_expected_column():
    """Les colonnes lues nommément (éligibilité, notation) sont exactement couvertes par REQUIRED_COLUMNS."""
    from bases_engine.contract import REQUIRED_COLUMNS
    from bases_engine.eligibility import PRED_COLS, RACE_COLS
    assert {c.strip() for c in RACE_COLS.split(",")} <= set(REQUIRED_COLUMNS["races"])
    assert {c.strip() for c in PRED_COLS.split(",")} <= set(REQUIRED_COLUMNS["predictions"])
    assert {"statut", "finalite", "arrival_order_json", "non_partants_json"} <= set(REQUIRED_COLUMNS["race_results"])
