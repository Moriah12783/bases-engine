from datetime import datetime, timezone

from bases_engine.eligibility import Abstention, EligibleRace, evaluate_race

NOW_EARLY = datetime(2026, 9, 21, 9, 5, tzinfo=timezone.utc)


def test_morning_gate_mirrors_engine_on_2026_09_21(snapshot):
    con = snapshot.connect()
    ok, abst = [], {}
    for (race_id,) in con.execute("select race_id from races where date='2026-09-21'"):
        ev = evaluate_race(con, race_id, "T_MATIN", mode="matin", now=NOW_EARLY)
        (ok.append(ev) if isinstance(ev, EligibleRace) else abst.setdefault(ev.motif, []).append(ev.race_id))
    assert len(ok) + sum(map(len, abst.values())) == 32
    # Porte du moteur reconstituée sur la base (depuis le 25/09/2026) : 8 courses ODDS_DEFAULT, comme la porte du rapport ; puis §4.1-3/4 :
    # 3 pelotons < 8 partants (Angers C2/C3, Vichy C8) et 1 départ à 09:20 UTC (< now + 20 min).
    assert len(abst["NON_PUBLISHABLE:ODDS_DEFAULT"]) == 8
    assert sorted(abst["FIELD_TOO_SMALL"]) == ["R3C2_21092026_ANGERS", "R3C3_21092026_ANGERS", "R4C8_21092026_VICHY"]
    assert abst["RACE_STARTED"] == ["R3C1_21092026_ANGERS"]
    assert len(ok) == 20
    for r in ok:
        assert 6 <= len(r.candidates) <= 8 and r.active_runners >= 8
        assert abs(sum(r.probs.values()) - 1) < 1e-9
        assert r.prediction_hash and r.lock_time_utc and not r.flags
        assert r.top_m in (4, 5)


def test_race_started_is_abstained(snapshot):
    con = snapshot.connect()
    late = datetime(2026, 9, 21, 23, 0, tzinfo=timezone.utc)
    ev = evaluate_race(con, "R1C1_21092026_LA CAPELLE", "T_MATIN", mode="matin", now=late)
    assert isinstance(ev, Abstention) and ev.motif == "RACE_STARTED"


def test_cancelled_race_is_abstained_in_matin(snapshot, tmp_path):
    import shutil, sqlite3
    from bases_engine.fetch import Snapshot
    db = tmp_path / "turf_bench.db"; shutil.copy(snapshot.db_path, db)
    c = sqlite3.connect(db); c.execute("update races set status='ANNULEE', pmu_statut='COURSE_ANNULEE' where race_id='R1C1_21092026_LA CAPELLE'"); c.commit(); c.close()
    con = Snapshot("x", tmp_path, db, {}).connect()
    ev = evaluate_race(con, "R1C1_21092026_LA CAPELLE", "T_MATIN", mode="matin", now=NOW_EARLY)
    assert isinstance(ev, Abstention) and ev.motif == "NON_PUBLISHABLE:RACE_CANCELLED"


def test_candidates_follow_engine_selection_order(snapshot):
    con = snapshot.connect()
    import json
    sel = con.execute("select selection_json from predictions where race_id='R1C1_21092026_LA CAPELLE' and engine_name='NEW_VALUE_ENGINE' and horizon='T_MATIN'").fetchone()[0]
    ev = evaluate_race(con, "R1C1_21092026_LA CAPELLE", "T_MATIN", mode="matin", now=NOW_EARLY)
    assert ev.engine8 == [int(x) for x in json.loads(sel)][:8]
