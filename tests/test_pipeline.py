"""Bout-en-bout hors réseau : matin (dry-run puis ombre), idempotence, remplacement, soir (notation JSON)."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bases_engine import config, storage
from bases_engine.fetch import Snapshot
from bases_engine.pipeline import PipelineStop, run_matin, run_soir

NOW = datetime(2026, 9, 21, 9, 5, tzinfo=timezone.utc)
N_SIMS = 3_000


@pytest.fixture
def env(tmp_path, monkeypatch, fixtures_dir):
    monkeypatch.setenv("SHADOW_TOKEN", "t" * 32)
    monkeypatch.setenv("PUBLICATION_MODE", "shadow")
    monkeypatch.setattr(config, "RAPPORTS_DIR", tmp_path / "rapports")
    import bases_engine.notify as notify
    monkeypatch.setattr(notify, "JOURNAL_DIR", tmp_path / "rapports" / "journal")
    import bases_engine.publish as publish
    monkeypatch.setattr(publish, "SITE_DIR", tmp_path / "site")
    return {"db": tmp_path / "bases.db", "site": tmp_path / "site", "rapports": tmp_path / "rapports"}


def test_matin_dry_run_then_shadow_is_idempotent(env, results_client, capsys):
    rc = run_matin(day="2026-09-21", dry_run=True, now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS)
    assert rc == 0
    con = storage.connect(env["db"])
    eds = storage.editions_for_day(con, "2026-09-21", "T_MATIN")
    assert len(eds) == 20 and all(e["published_at_utc"] is None for e in eds)
    assert con.execute("select count(*) from abstentions").fetchone()[0] == 12
    # rejeu en mode ombre : aucun doublon, published_at renseigné, site généré
    rc = run_matin(day="2026-09-21", dry_run=False, now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS)
    assert rc == 0
    eds2 = storage.editions_for_day(con, "2026-09-21", "T_MATIN")
    assert len(eds2) == 20 and all(e["published_at_utc"] for e in eds2)
    assert {e["ladder_json"] for e in eds} == {e["ladder_json"] for e in eds2}          # même calcul, même graine
    site = env["site"]
    assert "Service en préparation" in (site / "index.html").read_text(encoding="utf-8")
    content = site / "shadow" / ("t" * 32)
    day = json.loads((content / "bases" / "2026-09-21.json").read_text(encoding="utf-8"))
    assert day["contract_version"] == 1 and len(day["courses"]) == 20 and len(day["abstentions"]) == 12
    c = day["courses"][0]
    assert set(c) >= {"course_id", "slug", "libelle", "depart_utc", "depart_affiche", "pari_cible", "top_m", "moteur", "echelle", "base_des_bases", "trios_alternatifs", "structure_recommandee", "drapeaux"}
    assert " " not in c["slug"] and c["moteur"]["prediction_hash"] and c["moteur"]["lock_time_utc"]
    assert all(0 <= c["echelle"][k]["p_calibree"] <= 1 for k in ("1", "2", "3", "4"))
    assert (content / "palmares.json").exists() and (content / "fiabilite.json").exists()
    html = (content / "index.html").read_text(encoding="utf-8")
    assert "BASE DES BASES" in html and "LA CAPELLE - R1C1" in html and "GMT" in html
    journal = (env["rapports"] / "journal" / "2026-09-21.md").read_text(encoding="utf-8")
    assert "édition du matin" in journal and "Base des bases" in journal and "Abstentions" in journal
    assert con.execute("select count(*) from journal_days where status='OK'").fetchone()[0] == 1
    # exécutions manuelles (non planifiées) avant le début du protocole : répétitions, hors palmarès
    assert storage.protocol_start_date(con) is None
    assert all(e["repetition"] == 1 for e in eds2)
    pal = json.loads((content / "palmares.json").read_text(encoding="utf-8"))
    assert pal["depuis"] is None and pal["editions_publiees"] == 0 and pal["repetitions_exclues"] == 20
    assert "RÉPÉTITION" in journal
    assert con.execute("select count(*) from runs where command='matin' and status='OK'").fetchone()[0] == 2
    con.close()


def test_matin_supersedes_previous_commit(env, results_client, snapshot, monkeypatch):
    run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS)
    other = Snapshot("abcdef0123456789", snapshot.dir, snapshot.db_path, snapshot.report_path)
    import bases_engine.pipeline as pl
    monkeypatch.setattr(pl, "get_snapshot", lambda sha=None, **kw: other)
    run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS)
    con = storage.connect(env["db"])
    assert con.execute("select count(*) from bases_editions where superseded_by is not null").fetchone()[0] == 20
    assert len(storage.editions_for_day(con, "2026-09-21", "T_MATIN")) == 20
    assert {e["snapshot_commit"] for e in storage.editions_for_day(con, "2026-09-21", "T_MATIN")} == {"abcdef0123456789"}
    con.close()


def test_matin_stops_on_contract_failure(env, monkeypatch):
    from bases_engine.fetch import FetchError

    class Down:
        def manifest(self):
            raise FetchError("HTTP 403")
    with pytest.raises(PipelineStop) as e:
        run_matin(day="2026-09-21", now=NOW, results_client=Down(), db_path=env["db"], n_sims=N_SIMS)
    assert e.value.code == 2
    alertes = (env["rapports"] / "journal" / "ALERTES.md").read_text(encoding="utf-8")
    assert "manifeste index.json" in alertes
    con = storage.connect(env["db"])
    assert con.execute("select count(*) from bases_editions").fetchone()[0] == 0
    assert con.execute("select status from runs").fetchone()[0] == "CONTRACT_FAILED"


def test_matin_snapshot_late_when_date_missing(env, results_client):
    rc = run_matin(day="2026-09-22", now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS, max_wait=0)
    assert rc == 0
    con = storage.connect(env["db"])
    assert con.execute("select status from runs").fetchone()[0] == "SNAPSHOT_LATE"
    assert "SNAPSHOT_LATE" in (env["rapports"] / "journal" / "ALERTES.md").read_text(encoding="utf-8")


def test_soir_scores_from_public_json(env, results_client):
    """Le 20/09 est passé : matin strict n'a rien publié, mais la mesure T15 crée des éditions rétrospectives
    que le soir note sur le JSON public (contrôle croisé SQLite)."""
    rc = run_soir(day="2026-09-20", results_client=results_client, db_path=env["db"], n_sims=N_SIMS)
    assert rc == 0
    con = storage.connect(env["db"])
    n_mesure = con.execute("select count(*) from bases_editions where mode='mesure' and horizon='T15'").fetchone()[0]
    assert n_mesure > 20
    rows = con.execute("select * from bases_results where horizon='T15'").fetchall()
    # une ligne par cible m = 4 et m = 5 ; une course du 20/09 a moins de 4 classés (non notée, motif journalisé)
    assert len(rows) % 2 == 0 and 2 * (n_mesure - 2) <= len(rows) < 2 * n_mesure
    assert all(r["checked_against_sqlite"] == 1 and r["source"] == "RESULTATS_JSON" for r in rows)
    r5 = [r for r in rows if r["top_m"] == 5]
    assert 0.05 < sum(r["hit_k3"] for r in r5) / len(r5) < 0.6
    assert all(r["hit_k1"] >= r["hit_k2"] >= r["hit_k3"] >= r["hit_k4"] for r in rows)
    assert con.execute("select empreinte_sha256 from results_manifest where date='2026-09-20'").fetchone()[0]
    # second passage : empreinte inchangée → aucune relecture, aucune re-notation
    before = results_client.requests_made
    rc = run_soir(day="2026-09-20", results_client=results_client, db_path=env["db"], n_sims=N_SIMS)
    assert rc == 0 and results_client.requests_made == before + 2     # manifeste du contrat + manifeste du soir, aucune journée relue
    assert len(con.execute("select * from bases_results").fetchall()) == len(rows)
    journal = (env["rapports"] / "journal" / "2026-09-20.md").read_text(encoding="utf-8")
    assert "bilan du 20/09" in journal and "mesure T15" in journal


def test_scoring_rules_dead_heat_and_np():
    from bases_engine.scoring import placed_from_course_json, score_edition
    course = {"classement": [{"rang": 1, "num": 3}, {"rang": 2, "num": 9}, {"rang": 2, "num": 7, "dead_heat": True},
                             {"rang": 4, "num": 10}, {"rang": 5, "num": 5}, {"rang": 6, "num": 11}],
              "non_partants": [{"num": 5}]}
    placed, arr = placed_from_course_json(course, 4)
    assert placed == {3, 9, 7, 10} and arr == [3, 7, 9, 10, 11]
    placed5, _ = placed_from_course_json(course, 5)
    assert 5 not in placed5 and placed5 == {3, 9, 7, 10}          # le NP ne compte jamais comme placé
    ladder = {"1": {"chevaux": [3]}, "2": {"chevaux": [3, 9]}, "3": {"chevaux": [3, 9, 11]}, "4": {"chevaux": [3, 9, 7, 11]}}
    h = score_edition(ladder, placed)
    assert (h["hit_k1"], h["hit_k2"], h["hit_k3"], h["hit_k4"], h["hit_2of3"]) == (1, 1, 0, 0, 1)


def test_cli_matin_offline(capsys, env):
    from bases_engine import __main__ as cli
    rc = cli.main(["--db", str(env["db"]), "matin", "--date", "2026-09-21", "--dry-run", "--no-network", "--now", "2026-09-21T09:05:00Z", "--n-sims", "2000"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "édition du matin" in out and "20 éligibles" in out


def test_scheduled_matin_fixes_protocol_start_and_marks_no_repetition(env, results_client, tmp_path, fixtures_dir):
    from bases_engine.protocol import PLACEHOLDER, PLACEHOLDER_COMMIT, start_date_in_file
    proto = tmp_path / "PROTOCOLE_PREENREGISTRE.md"
    proto.write_text(f"# Protocole\n\n{PLACEHOLDER}\n\n{PLACEHOLDER_COMMIT}\n", encoding="utf-8")
    rc = run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS, scheduled=True, protocol_path=proto)
    assert rc == 0
    con = storage.connect(env["db"])
    assert storage.protocol_start_date(con) == "2026-09-21" and start_date_in_file(proto) == "2026-09-21"
    assert "à renseigner" not in proto.read_text(encoding="utf-8") and "à l'activation : `" in proto.read_text(encoding="utf-8")
    assert all(e["repetition"] == 0 for e in storage.editions_for_day(con, "2026-09-21", "T_MATIN"))
    # un second matin planifié ne réécrit jamais la date
    rc = run_matin(day="2026-09-22", now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS, scheduled=True, protocol_path=proto, max_wait=0)
    assert storage.protocol_start_date(con) == "2026-09-21" and start_date_in_file(proto) == "2026-09-21"
    assert "début du protocole" in (env["rapports"] / "journal" / "2026-09-21.md").read_text(encoding="utf-8")


def test_hebdo_recalibrates_and_reports(env, results_client, snapshot, tmp_path, monkeypatch):
    """Éditions T_MATIN rétrospectives du 20/09 (simulant un protocole démarré le 20/09), notation le soir, puis hebdo."""
    import bases_engine.pipeline as pl
    from bases_engine import config
    from bases_engine.hebdo import run_hebdo
    import bases_engine.params as params_mod
    monkeypatch.setattr(config, "PARAMS_PATH", tmp_path / "params.json")
    monkeypatch.setattr(params_mod, "config", config)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    con = storage.connect(env["db"])
    storage.set_meta(con, "protocole_debut", "2026-09-20")
    n = pl._mesure_horizon(con, snapshot, "2026-09-20", "T_MATIN", N_SIMS)
    con.execute("update bases_editions set mode='shadow', repetition=0")
    con.commit(); con.close()
    assert n > 20
    assert run_soir(day="2026-09-20", results_client=results_client, db_path=env["db"], n_sims=N_SIMS) == 0
    con = storage.connect(env["db"])
    scored = con.execute("select count(*) from bases_results where horizon='T_MATIN' and repetition=0").fetchone()[0]
    assert scored > 40
    con.close()
    assert run_hebdo(day="2026-09-21", db_path=env["db"]) == 0
    con = storage.connect(env["db"])
    assert con.execute("select version from params order by rowid desc limit 1").fetchone()[0] == "2026-09-21.1"
    assert con.execute("select count(*) from calibration where params_version='2026-09-21.1'").fetchone()[0] == 8
    saved = json.loads((tmp_path / "params.json").read_text(encoding="utf-8"))
    assert saved["version"] == "2026-09-21.1" and saved["calibration"]["k3_m4"]["mode"] == "fixe"   # n < 150 → palier fixe
    md = (env["rapports"] / "2026-W39.md").read_text(encoding="utf-8")
    assert "Baselines" in md and "3 premiers du moteur" in md and "Critères du protocole" in md and "Non calculé" in md
    assert "trio publié diffère des 3 premiers du moteur" in md and "Courses concernées" in md
    assert "2026-09-21.1" in (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8") if (tmp_path / "CHANGELOG.md").exists() else True


def test_presentation_structure_and_order(env, results_client):
    from bases_engine.params import structure_libelle
    from bases_engine.publish import sort_courses
    lad = {"2": {"chevaux": [1, 2]}, "3": {"chevaux": [1, 2, 3]}}
    assert structure_libelle("A", 5, ["QUINTE_PLUS", "QUARTE_PLUS"], lad)["texte"] == "3 bases + XX avec les associés"
    assert structure_libelle("A", 4, ["QUARTE_PLUS", "MULTI"], lad)["texte"] == "3 bases + X avec les associés"
    m = structure_libelle("A", 4, ["MULTI", "DEUX_SUR_QUATRE"], lad)
    assert m["texte"] == "Multi en 5 ou 6 autour des 3 bases" and m["bases"] == [1, 2, 3]
    d = structure_libelle("A", 4, ["DEUX_SUR_QUATRE"], lad)
    assert d["texte"] == "2sur4 avec les 2 bases" and d["bases"] == [1, 2] and d["barreau"] == 2
    t = structure_libelle("A", 4, ["TRIO", "COUPLE_PLACE"], lad, {"2": {"chevaux": [1, 3], "p_brute": 0.412}})
    assert t["texte"] == "Trio ou Couplé placé : 2 bases + X · P(les 2 bases dans les 3 premiers) = 41 % (estimation brute, non recalibrée)"
    assert t["bases"] == [1, 3] and t["barreau"] == 2 and t["cible_affichee"] == 3
    b = structure_libelle("B", 5, ["QUINTE_PLUS"], lad)
    assert b["texte"] == "2 bases + XXX avec les associés" and b["bases"] == [1, 2] and b["code"] == "2B_XXX"
    assert structure_libelle("C", 4, ["QUARTE_PLUS"], lad)["code"] == "ABSTENTION"
    run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS)
    day = json.loads((env["site"] / "shadow" / ("t" * 32) / "bases" / "2026-09-21.json").read_text(encoding="utf-8"))
    cs = sort_courses(day["courses"])
    assert "QUINTE_PLUS" in cs[0]["paris_offerts"] and cs[0]["course_id"] == "R1C1_21092026_LA CAPELLE"
    sols = [c["base_des_bases"]["solidite"] for c in cs[1:]]
    assert sols == sorted(sols)
    for c in cs:
        st = c["structure_recommandee"]
        assert st["code"] in ("3B_XX", "3B_X", "2B_XXX", "2B_XX", "ABSTENTION")
        if st["bases"]:
            assert set(c["associes"]) == set(c["moteur"]["selection_8"]) - set(st["bases"])
        assert c["paris_libelle"] != "paris non renseignés"
        if not any(x in c["paris_offerts"] for x in ("QUINTE_PLUS", "QUARTE_PLUS", "MULTI", "MINI_MULTI")) and st["code"] != "ABSTENTION":
            assert st["barreau"] == 2 and len(st["bases"]) == 2
    html = (env["site"] / "shadow" / ("t" * 32) / "index.html").read_text(encoding="utf-8")
    assert "Tous à l'arrivée (k/k)" in html and "Un manquant au plus" in html and "Sélection moteur" in html and "Associés" in html
    assert "Abstentions du jour" in html and "moins de 8 partants" in html and "TOP4" not in html and "Quinté+ du jour" in html
    assert "Mode shadow" in html


def test_trio_only_race_gets_top3_ladder(env, results_client):
    """Vichy R4C3 du 21/09 : Trio et Couplé placé seulement → échelle cible top 3 additive, structure sur les 3 premiers,
    solidité et cible inchangées (top 4)."""
    run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS)
    day = json.loads((env["site"] / "shadow" / ("t" * 32) / "bases" / "2026-09-21.json").read_text(encoding="utf-8"))
    by_id = {c["course_id"]: c for c in day["courses"]}
    c = by_id["R4C3_21092026_VICHY"]
    assert set(c["paris_offerts"]) == {"TRIO", "COUPLE_PLACE"} and c["top_m"] == 4
    assert "echelle_top3" in c and c["note_top3"]
    e3 = c["echelle_top3"]
    assert 0 < e3["2"]["p_brute"] < e3["1"]["p_brute"] <= 1 and e3["4"]["p_brute"] == 0.0     # 4 chevaux dans les 3 premiers : impossible
    st = c["structure_recommandee"]
    if st["code"] != "ABSTENTION":
        assert st["texte"].startswith("Trio ou Couplé placé : 2 bases + X · P(les 2 bases dans les 3 premiers) = ")
        assert "estimation brute, non recalibrée" in st["texte"] and st["bases"] == e3["2"]["chevaux"]
        assert set(c["associes"]) == set(c["moteur"]["selection_8"]) - set(st["bases"])
    assert c["base_des_bases"]["solidite"] in "ABC" and "echelle_top5" in c
    # les autres courses n'ont pas d'échelle top 3
    assert "echelle_top3" not in by_id["R1C1_21092026_LA CAPELLE"]
    html = (env["site"] / "shadow" / ("t" * 32) / "index.html").read_text(encoding="utf-8")
    assert "dans les 3 premiers" in html
