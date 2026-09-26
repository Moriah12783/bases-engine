"""Porte divergente (décision du mentor du 25/09/2026, point 2)."""
from datetime import datetime, timezone

from bases_engine import porte, storage
from bases_engine.eligibility import Abstention, evaluate_race

NOW = datetime(2026, 9, 21, 9, 5, tzinfo=timezone.utc)


def test_gate_verdict_matches_eligibility_gate_on_2026_09_21(snapshot):
    """Même règle que l'éligibilité : verdict ≠ OK exactement quand l'éligibilité s'abstient pour un motif de porte."""
    con = snapshot.connect()
    v = porte.verdicts_du_jour(con, "2026-09-21")
    assert len(v) == 32 and sum(x == "ODDS_DEFAULT" for x in v.values()) == 8
    for rid, verdict in v.items():
        ev = evaluate_race(con, rid, "T_MATIN", mode="matin", now=NOW)
        motif_porte = porte.MOTIFS_PORTE.get(ev.motif) if isinstance(ev, Abstention) else None
        assert (verdict != "OK") == (motif_porte is not None) and (motif_porte in (None, verdict)), (rid, verdict, ev)


def test_comparison_reports_every_kind_of_gap():
    bases = {"A": "OK", "B": "ODDS_DEFAULT", "C": "OK", "D": "OK"}
    moteur = {"A": True, "B": True, "C": False, "E": True}
    assert porte.comparer(bases, moteur) == [("B", "ODDS_DEFAULT", True), ("C", "OK", False), ("D", "OK", None), ("E", "ABSENTE_DE_LA_BASE", True)]
    assert porte.comparer({"A": "OK", "B": "NO_T_MATIN"}, {"A": True, "B": False}) == []


def test_soir_flags_divergent_gate_once_and_counts_it(tmp_path, monkeypatch, results_client, capsys):
    from bases_engine import config
    from bases_engine.pipeline import run_matin, run_soir
    import bases_engine.notify as notify
    monkeypatch.setenv("SHADOW_TOKEN", "t" * 32)
    monkeypatch.setattr(config, "RAPPORTS_DIR", tmp_path / "rapports"); monkeypatch.setattr(config, "SITE_DIR", tmp_path / "site")
    monkeypatch.setattr(notify, "JOURNAL_DIR", tmp_path / "rapports" / "journal")
    db = tmp_path / "bases.db"
    run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=db, n_sims=2000, declencheur="metronome")
    monkeypatch.setattr(porte, "publications_moteur", lambda con, day: {rid: v == "OK" for rid, v in porte.verdicts_du_jour(con, day).items()} | {"R1C1_21092026_LA CAPELLE": False})
    assert run_soir(day="2026-09-21", results_client=results_client, db_path=db, n_sims=2000, declencheur="metronome") == 0
    assert "::warning title=Porte divergente::1 écart(s) sur 32 course(s)" in capsys.readouterr().out
    con = storage.connect(db)
    assert storage.incidents_count(con, "PORTE_DIVERGENTE", "2026-09-21") == 1
    assert "porte divergente" in (tmp_path / "rapports" / "journal" / "2026-09-21.md").read_text(encoding="utf-8")


def test_soir_says_plainly_when_the_engine_publication_source_is_missing(tmp_path, monkeypatch, results_client):
    from bases_engine import config
    from bases_engine.pipeline import run_matin, run_soir
    import bases_engine.notify as notify
    monkeypatch.setenv("SHADOW_TOKEN", "t" * 32)
    monkeypatch.setattr(config, "RAPPORTS_DIR", tmp_path / "rapports"); monkeypatch.setattr(config, "SITE_DIR", tmp_path / "site")
    monkeypatch.setattr(notify, "JOURNAL_DIR", tmp_path / "rapports" / "journal")
    db = tmp_path / "bases.db"
    run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=db, n_sims=2000, declencheur="metronome")
    assert run_soir(day="2026-09-21", results_client=results_client, db_path=db, n_sims=2000, declencheur="metronome") == 0
    assert "comparaison de porte non disponible" in (tmp_path / "rapports" / "journal" / "2026-09-21.md").read_text(encoding="utf-8")
    assert storage.incidents_count(storage.connect(db), "PORTE_DIVERGENTE", "2026-09-21") == 0


def test_gate_parity_on_reference_day_and_gap_report(snapshot, tmp_path):
    """La base synthétique reproduit le 21/09 : parité course par course ; une référence altérée est signalée."""
    import json
    con = snapshot.connect()
    ok, lignes, ecarts = porte.parite(con)
    assert ok and not ecarts and "attendu 20 éligibles / 12 abstentions, obtenu 20 / 12" in lignes[0]
    ref = json.loads(porte.REFERENCE_PARITE.read_text(encoding="utf-8"))
    ref["decisions"]["R1C1_21092026_LA CAPELLE"] = "FIELD_TOO_SMALL"
    p = tmp_path / "ref.json"; p.write_text(json.dumps(ref), encoding="utf-8")
    ok, lignes, ecarts = porte.parite(con, p)
    assert not ok and ecarts == [("R1C1_21092026_LA CAPELLE", "FIELD_TOO_SMALL", "ELIGIBLE")] and "1 écart(s)" in lignes[1]
