"""Cas limites volontaires de la fixture synthétique (journée 2026-09-18 « SYNTHESE », scripts/generer_fixture.py)."""
from datetime import datetime, timezone

from bases_engine import porte, storage
from bases_engine.eligibility import Abstention, EligibleRace, evaluate_race
from bases_engine.scoring import arrival_top, cross_check_sqlite, placed_from_course_json

NOW = datetime(2026, 9, 18, 9, 5, tzinfo=timezone.utc)
R = lambda n: f"R9C{n}_18092026_SYNTHESE"


def test_each_edge_case_gets_its_expected_decision(snapshot):
    con = snapshot.connect()
    ev = {n: evaluate_race(con, R(n), "T_MATIN", mode="matin", now=NOW) for n in range(1, 8)}
    assert isinstance(ev[1], EligibleRace) and isinstance(ev[5], EligibleRace)
    motifs = {n: e.motif for n, e in ev.items() if isinstance(e, Abstention)}
    assert motifs == {2: "FIELD_TOO_SMALL", 3: "NO_BET", 4: "CONTRACT:NO_PREDICTION", 6: "PRICED_RATIO", 7: "NON_PUBLISHABLE:ODDS_DEFAULT"}


def test_non_runner_in_engine_selection_is_dropped_from_candidates(snapshot):
    ev = evaluate_race(snapshot.connect(), R(5), "T_MATIN", mode="matin", now=NOW)
    assert 3 in ev.engine8 and 3 not in ev.candidates and 3 not in ev.probs
    assert len(ev.candidates) == 7 and abs(sum(ev.probs.values()) - 1) < 1e-9


def test_gate_verdicts_on_edge_cases(snapshot):
    v = porte.verdicts_du_jour(snapshot.connect(), "2026-09-18")
    assert v[R(4)] == "NO_T_MATIN" and v[R(7)] == "ODDS_DEFAULT"
    assert all(v[R(n)] == "OK" for n in (1, 2, 3, 5, 6))          # no bet, peloton, cotes partielles : filtres propres à Bases


def test_dead_heat_is_scored_on_the_shared_rank_and_cross_checked(snapshot, fixtures_synth):
    import json
    day = json.loads((fixtures_synth / "2026-09-18.json").read_text(encoding="utf-8"))
    c1 = next(c for c in day["courses"] if c["course_id"] == R(1))
    placed, ordre = placed_from_course_json(c1, 3)
    assert placed == {4, 7, 2, 9} and ordre[:4] == [4, 7, 2, 9]         # deux chevaux 3es ex aequo : 4 placés dans le top 3
    con = snapshot.connect()
    assert arrival_top(con, R(1))[0][:4] == [4, 7, 2, 9]
    assert cross_check_sqlite(con, R(1), c1["arrivee"], 4) == (True, "OK")


def test_non_runner_never_counts_as_placed(fixtures_synth):
    import json
    day = json.loads((fixtures_synth / "2026-09-18.json").read_text(encoding="utf-8"))
    c5 = next(c for c in day["courses"] if c["course_id"] == R(5))
    c5 = dict(c5, classement=[{"rang": 1, "num": 3, "dead_heat": False}] + c5["classement"])   # un NP ne peut pas être classé
    placed, _ = placed_from_course_json(c5, 4)
    assert 3 not in placed and placed == {1, 2, 4, 5}


def test_edge_day_end_to_end_matin_then_soir(tmp_path, monkeypatch, fixtures_synth):
    from bases_engine import config
    from bases_engine.fetch import ResultsClient
    from bases_engine.pipeline import run_matin, run_soir
    import bases_engine.notify as notify
    monkeypatch.setenv("SHADOW_TOKEN", "t" * 32)
    monkeypatch.setattr(config, "RAPPORTS_DIR", tmp_path / "rapports"); monkeypatch.setattr(config, "SITE_DIR", tmp_path / "site")
    monkeypatch.setattr(notify, "JOURNAL_DIR", tmp_path / "rapports" / "journal")
    client = ResultsClient(base_url=f"file://{fixtures_synth}")
    db = tmp_path / "bases.db"
    assert run_matin(day="2026-09-18", now=NOW, results_client=client, db_path=db, n_sims=2000, declencheur="metronome") == 0
    con = storage.connect(db)
    assert len(storage.editions_for_day(con, "2026-09-18", "T_MATIN")) == 2
    assert run_soir(day="2026-09-18", results_client=client, db_path=db, n_sims=2000, declencheur="metronome") == 0
    assert storage.results_count(con, "2026-09-18") > 0 and storage.unchecked_count(con, "2026-09-18") == 0
