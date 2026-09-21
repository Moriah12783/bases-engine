"""Bout-en-bout (hors réseau) : back-test sur l'extrait figé, calcul d'édition, CLI."""
import json

import pytest

from bases_engine import __main__ as cli
from bases_engine.compute import compute_edition
from bases_engine.eligibility import EligibleRace, evaluate_race
from bases_engine.params import load_params, solidite, structure_for
from bases_engine.scoring import backtest


def test_backtest_on_fixture_is_consistent(snapshot):
    bt = backtest(snapshot, since="2026-09-20", until="2026-09-20", horizon="T15", n_sims=4_000)
    assert bt["n_courses"] > 10
    a5, a4 = bt["par_cible"][5], bt["par_cible"][4]
    for a in (a5, a4):
        assert a["n"] == bt["n_courses"]
        assert 1 >= a["taux_k1"] >= a["taux_k2"] >= a["taux_k3"] >= a["taux_k4"] >= 0
        assert a["taux_2of3"] >= a["taux_k3"]
        assert a["calibration"]["k3_m%d" % a["top_m"]]["mode"] == "fixe"      # n < 150 → facteur fixe
        assert a["seuils_solidite"]["A"] >= a["seuils_solidite"]["B"]
    assert a5["taux_k3"] >= a4["taux_k3"]          # top 5 est plus facile que top 4
    assert "RESULT" not in json.dumps(bt["abstentions"]) or bt["abstentions"]


def test_compute_edition_is_reproducible(snapshot):
    con = snapshot.connect()
    log = snapshot.logs_by_race()["R1C1_21092026_LA CAPELLE"]
    ev = evaluate_race(con, "R1C1_21092026_LA CAPELLE", "T_MATIN", log, mode="backtest")
    assert isinstance(ev, EligibleRace)
    params = {"version": "test", "lambdas": [1.0, 0.81, 0.65, 0.55, 0.5], "shrink": 0.85, "calibration": {},
              "seuils_solidite": {"top5": {"A": 0.30, "B": 0.18}, "top4": {"A": 0.20, "B": 0.10}}}
    e1 = compute_edition(ev, params, n_sims=5_000)
    e2 = compute_edition(ev, params, n_sims=5_000)
    assert e1["ladders"] == e2["ladders"]
    lad = e1["ladders"][ev.top_m]["echelle"]
    assert all(set(lad[k]["chevaux"]) <= set(ev.candidates) for k in (1, 2, 3, 4))
    assert lad[3]["p_calibree"] == pytest.approx(lad[3]["p_brute"] * 0.85)   # palier fixe faute d'historique
    assert e1["solidite"] in "ABC" and e1["structure"]["code"]


def test_solidite_and_structure_rules():
    params = {"seuils_solidite": {"top5": {"A": 0.30, "B": 0.18}}}
    assert solidite(0.31, params, 5) == "A" and solidite(0.2, params, 5) == "B" and solidite(0.1, params, 5) == "C"
    assert solidite(0.5, params, 4) == "?"                            # seuils absents → jamais inventés
    assert structure_for("A", 5)["code"] == "3B_XX" and structure_for("B", 4)["code"] == "2B_XX"
    assert structure_for("C", 5)["code"] == "ABSTENTION"


def test_cli_contract_check_offline(capsys):
    rc = cli.main(["contract-check", "--date", "2026-09-21", "--no-network"])
    out = capsys.readouterr().out
    assert rc == 0 and "sauté" in out


def test_cli_sprint2_commands_are_stubs(capsys):
    assert cli.main(["matin"]) == 3
