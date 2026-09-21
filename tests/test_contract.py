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
    drift = Snapshot("drift", tmp_path, db, snapshot.report_path)
    res = run_contract_checks(drift, "2026-09-21", network=False)
    assert not res.ok and res.failed[0][0] == "schema:predictions"


def test_contract_passes_with_local_results_fixture(snapshot, fixtures_dir):
    from bases_engine.fetch import ResultsClient
    client = ResultsClient(base_url=f"file://{fixtures_dir / 'resultats'}")
    res = run_contract_checks(snapshot, "2026-09-21", results_client=client)
    assert res.ok and not res.skipped, res.summary()


def _with_reason(snapshot, tmp_path, reason, publishable):
    import json
    from bases_engine.fetch import Snapshot
    logs = json.loads(snapshot.report_path.read_text(encoding="utf-8"))
    for h in logs["historical_logs"]:
        if h["race_id"] == "R1C1_21092026_LA CAPELLE":
            h["publication_reason"], h["publishable"] = reason, publishable
    rep = tmp_path / "benchmark_report.json"
    rep.write_text(json.dumps(logs, ensure_ascii=False), encoding="utf-8")
    return Snapshot("test", tmp_path, snapshot.db_path, rep)


def test_priced_ratio_low_is_known(snapshot, tmp_path):
    res = run_contract_checks(_with_reason(snapshot, tmp_path, "PRICED_RATIO_LOW", False), "2026-09-21", network=False, notify_warnings=False)
    assert res.ok and not res.warnings


def test_unknown_reason_non_publishable_is_a_warning(snapshot, tmp_path):
    res = run_contract_checks(_with_reason(snapshot, tmp_path, "NOUVELLE_RAISON", False), "2026-09-21", network=False, notify_warnings=False)
    assert res.ok and len(res.warnings) == 1 and "NOUVELLE_RAISON" in res.warnings[0][1] and "⚠️" in res.summary()


def test_unknown_reason_publishable_is_blocking(snapshot, tmp_path):
    res = run_contract_checks(_with_reason(snapshot, tmp_path, "NOUVELLE_RAISON", True), "2026-09-21", network=False, notify_warnings=False)
    assert not res.ok and "publishable = true" in res.failed[0][0]


def test_warning_is_journalised_in_alertes(snapshot, tmp_path, monkeypatch):
    import bases_engine.notify as notify
    monkeypatch.setattr(notify, "JOURNAL_DIR", tmp_path / "journal")
    res = run_contract_checks(_with_reason(snapshot, tmp_path, "NOUVELLE_RAISON", False), "2026-09-21", network=False)
    assert res.ok
    assert "NOUVELLE_RAISON" in (tmp_path / "journal" / "ALERTES.md").read_text(encoding="utf-8")
