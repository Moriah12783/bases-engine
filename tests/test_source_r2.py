"""Source moteur R2 (décision du mentor du 25/09/2026) : faux client S3, aucune clé dans la session."""
import hashlib
import io
import json
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bases_engine import config, storage
from bases_engine.fetch import FetchError, get_snapshot, r2_client, source_header

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "fixtures" / "snapshot"
NOW = datetime(2026, 9, 21, 9, 5, tzinfo=timezone.utc)


class FakeS3:
    """head_object / get_object d'un seul objet ; mémorise chaque (Bucket, Key) demandé."""

    def __init__(self, data: bytes, meta: dict):
        self.data, self.meta, self.calls = data, meta, []

    def head_object(self, Bucket, Key):
        self.calls.append(("head", Bucket, Key))
        return {"Metadata": dict(self.meta), "ContentLength": len(self.data)}

    def get_object(self, Bucket, Key):
        self.calls.append(("get", Bucket, Key))
        return {"Metadata": dict(self.meta), "Body": io.BytesIO(self.data)}


def _meta(data: bytes, **over) -> dict:
    m = {"sha256": hashlib.sha256(data).hexdigest(), "pushed-at": "2026-09-21T09:00:00Z", "run-id": "4242", "commit": "abc1234", "counts": "races=32"}
    m.update(over)
    return {k: v for k, v in m.items() if v is not None}


@pytest.fixture
def r2(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOCAL_SNAPSHOT_DIR", None)
    data = (FIX / "turf_bench.db").read_bytes()
    return {"cache": tmp_path / "cache", "data": data}


def test_r2_snapshot_is_verified_and_carries_its_header(r2):
    cli = FakeS3(r2["data"], _meta(r2["data"]))
    snap = get_snapshot(client=cli, cache_dir=r2["cache"])
    assert snap.sha == hashlib.sha256(r2["data"]).hexdigest()
    assert snap.header() == f"Source moteur R2 · sha256 {snap.sha[:12]} · poussée 2026-09-21T09:00:00Z · run 4242 · commit abc1234"
    assert {(b, k) for _, b, k in cli.calls} == {("turf-engine-data", "turf_bench.db")}      # jamais backups/ ni state/
    assert "r2:turf_bench.db" in (r2["cache"] / "downloads.log").read_text()


def test_same_fingerprint_in_cache_is_reused_without_download(r2):
    cli = FakeS3(r2["data"], _meta(r2["data"]))
    get_snapshot(client=cli, cache_dir=r2["cache"]); get_snapshot(client=cli, cache_dir=r2["cache"])
    assert [c[0] for c in cli.calls] == ["head", "get", "head"]


def test_fingerprint_mismatch_is_fatal(r2):
    cli = FakeS3(r2["data"], _meta(r2["data"], sha256="0" * 64))
    with pytest.raises(FetchError, match="≠ métadonnée"):
        get_snapshot(client=cli, cache_dir=r2["cache"])
    assert not list((r2["cache"] / "r2").glob("*/turf_bench.db"))


def test_missing_fingerprint_metadata_is_fatal(r2):
    cli = FakeS3(r2["data"], _meta(r2["data"], sha256=None))
    with pytest.raises(FetchError, match="métadonnée sha256 absente"):
        get_snapshot(client=cli, cache_dir=r2["cache"])


def test_corrupt_database_fails_integrity_check(r2):
    bad = bytearray(r2["data"]); bad[5000:9000] = b"\xff" * 4000; bad = bytes(bad)
    cli = FakeS3(bad, _meta(bad))
    with pytest.raises(FetchError, match="integrity_check|illisible"):
        get_snapshot(client=cli, cache_dir=r2["cache"])


def test_header_tolerates_missing_fields():
    assert source_header({"origine": "r2", "sha256": "f" * 64}) == "Source moteur R2 · sha256 ffffffffffff"
    assert source_header({"origine": "git", "commit": "7483bd25ab"}) == "Source moteur copie Git · commit 7483bd25ab"


def test_missing_r2_secrets_is_an_explicit_error(monkeypatch):
    for v in (config.R2_ACCOUNT_ENV, config.R2_KEY_ID_ENV, config.R2_SECRET_ENV):
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(FetchError, match="secrets R2 absents"):
        r2_client()


def test_no_read_of_the_engine_repository_remains():
    code = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "bases_engine").glob("*.py"))
    code += (ROOT / ".github" / "workflows" / "bases.yml").read_text(encoding="utf-8")
    code = code.replace("jamais backups/ ni state/", "")
    for motif in ("raw.githubusercontent", '"ls-remote"', "turf-engine.git", "benchmark_report.json", "Key=\"backups", "Key=\"state"):
        assert motif not in code, motif


def test_engine_database_is_never_tracked():
    """Seule bases.db est suivie ; l'extrait de test fixtures/snapshot/turf_bench.db (Sprint 1) est l'unique exception,
    signalée au mentor. Toute autre base (dont une copie R2 du cache) fait échouer le test."""
    tracked = subprocess.run(["git", "ls-files", "*.db", "**/*.db"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert set(tracked) <= {"bases.db", "fixtures/snapshot/turf_bench.db"}, tracked
    ign = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "*.db" in ign and "!bases.db" in ign


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("SHADOW_TOKEN", "t" * 32); monkeypatch.setenv("PUBLICATION_MODE", "shadow")
    monkeypatch.setattr(config, "RAPPORTS_DIR", tmp_path / "rapports")
    import bases_engine.notify as notify
    monkeypatch.setattr(notify, "JOURNAL_DIR", tmp_path / "rapports" / "journal")
    monkeypatch.setattr(config, "SITE_DIR", tmp_path / "site")
    return tmp_path / "bases.db"


def _local(tmp_path, **meta) -> Path:
    d = tmp_path / "snap"; d.mkdir()
    shutil.copy(FIX / "turf_bench.db", d / "turf_bench.db")
    src = json.loads((FIX / "source.json").read_text(encoding="utf-8")); src.update(meta)
    (d / "source.json").write_text(json.dumps(src), encoding="utf-8")
    return d


def test_integrity_failure_in_matin_is_red_with_no_edition(tmp_path, monkeypatch, results_client, r2):
    from bases_engine.pipeline import PipelineStop, run_matin
    db = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "CACHE_DIR", r2["cache"])
    cli = FakeS3(r2["data"], _meta(r2["data"], sha256="1" * 64))
    with pytest.raises(PipelineStop):
        run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=db, n_sims=2000, source_client=cli, declencheur="metronome")
    con = storage.connect(db)
    assert con.execute("select status from runs").fetchone()[0] == "SOURCE_INVALIDE"
    assert con.execute("select count(*) from bases_editions").fetchone()[0] == 0


def test_push_before_lock_refuses_the_edition(tmp_path, monkeypatch, results_client):
    from bases_engine.pipeline import run_matin
    db = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "LOCAL_SNAPSHOT_DIR", str(_local(tmp_path, **{"pushed-at": "2026-09-21T06:00:00Z"})))
    assert run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=db, n_sims=2000, declencheur="metronome") == 0
    con = storage.connect(db)
    run = con.execute("select status, error from runs").fetchone()
    assert run["status"] == "SOURCE_SANS_MATIN" and "antérieure ou égale au dernier verrou" in run["error"]
    assert con.execute("select count(*) from bases_editions").fetchone()[0] == 0


def test_old_push_is_only_a_warning_and_header_is_stored(tmp_path, monkeypatch, results_client, capsys):
    from bases_engine.pipeline import run_matin
    db = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "LOCAL_SNAPSHOT_DIR", str(_local(tmp_path, **{"pushed-at": "2026-09-21T07:00:00Z", "run-id": None})))
    assert run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=db, n_sims=2000, declencheur="metronome") == 0
    assert "::warning title=Source moteur ancienne::base poussée il y a 125 min" in capsys.readouterr().out
    con = storage.connect(db)
    src = json.loads(con.execute("select source_json from bases_editions limit 1").fetchone()[0])
    assert src["origine"] == "local" and src["pushed_at"] == "2026-09-21T07:00:00Z" and src["run_id"] is None
    day = json.loads((tmp_path / "site" / "shadow" / ("t" * 32) / "bases" / "2026-09-21.json").read_text(encoding="utf-8"))
    assert day["source"]["entete"].startswith("Source moteur locale · sha256 ") and " · run " not in day["source"]["entete"]
    assert day["source"]["entete"] in (tmp_path / "site" / "shadow" / ("t" * 32) / "index.html").read_text(encoding="utf-8")


def test_lost_day_is_recorded_shown_and_extends_the_window(tmp_path, monkeypatch, results_client):
    from bases_engine.pipeline import run_matin, run_soir
    db = _env(tmp_path, monkeypatch)
    assert run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=db, n_sims=2000, declencheur="metronome") == 0
    con = storage.connect(db)
    assert storage.protocol_start_date(con) == "2026-09-21"
    assert run_matin(day="2026-09-22", now=NOW, results_client=results_client, db_path=db, n_sims=2000, declencheur="metronome") == 0
    assert run_soir(day="2026-09-22", results_client=results_client, db_path=db, n_sims=2000, declencheur="metronome") == 0
    assert storage.journees_perdues(con) == [{"date": "2026-09-22", "motif": "source moteur indisponible", "recorded_at_utc": storage.journees_perdues(con)[0]["recorded_at_utc"]}]
    content = tmp_path / "site" / "shadow" / ("t" * 32)
    assert "journée perdue · source moteur indisponible" in (content / "archive" / "2026-09.html").read_text(encoding="utf-8")
    pal = json.loads((content / "palmares.json").read_text(encoding="utf-8"))
    assert pal["fin_fenetre"] == "2026-10-19"                     # 21/09 + 27 jours + 1 journée perdue
    assert "journées perdues : 1" in (content / "palmares.html").read_text(encoding="utf-8")
    assert not storage.jour_servi(con, "2026-09-22") and storage.jour_servi(con, "2026-09-21")


def test_fingerprint_annex_excludes_only_differing_races(tmp_path, monkeypatch, results_client):
    from bases_engine.__main__ import main
    from bases_engine.pipeline import run_matin
    db = _env(tmp_path, monkeypatch)
    run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=db, n_sims=2000, declencheur="metronome")
    con = sqlite3.connect(FIX / "turf_bench.db")
    ref = {r[0]: r[1] for r in con.execute("""select p.race_id, p.prediction_hash from predictions p join races r using(race_id)
                                              where r.date='2026-09-21' and p.engine_name='NEW_VALUE_ENGINE' and p.horizon='T_MATIN'""")}
    victime = sorted(ref)[0]; ref[victime] = "0" * 64
    rp = tmp_path / "ref.json"; rp.write_text(json.dumps({"empreintes": ref, "source": "test"}), encoding="utf-8")
    assert main(["--db", str(db), "annexe-empreintes", "--date", "2026-09-21", "--reference", str(rp)]) == 0
    c = storage.connect(db)
    assert [r[0] for r in c.execute("select race_id from exclusions_palmares")] == [victime]
    rapport = (tmp_path / "rapports" / "annexe" / "2026-09-21_verification_empreintes.md").read_text(encoding="utf-8")
    assert f"{len(ref) - 1} identique(s), 1 différente(s)" in rapport and "Aucune n'a été recalculée" in rapport
    assert all(r["race_id"] != victime for r in storage.latest_results(c))
