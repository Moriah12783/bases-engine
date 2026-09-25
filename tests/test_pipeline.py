"""Bout-en-bout hors réseau : matin (dry-run puis ombre), idempotence, remplacement, soir (notation JSON)."""
import json
import os
import time
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
    monkeypatch.setattr(config, "SITE_DIR", tmp_path / "site")          # lu à l'appel par site.build_site
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
    other = Snapshot("abcdef0123456789", snapshot.dir, snapshot.db_path, dict(snapshot.source, sha256="abcdef0123456789"))
    import bases_engine.pipeline as pl
    monkeypatch.setattr(pl, "get_snapshot", lambda **kw: other)
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


def test_matin_without_todays_t_matin_abstains_and_is_not_served(env, results_client, capsys):
    """Garde de fraîcheur (1b) : pas de T_MATIN du jour dans la base lue → abstention motivée, annotation, aucune édition,
    job vert ; la passe n'est pas « servie », la frappe planifiée suivante retente au lieu de sortir en répétition."""
    for decl in ("metronome", "metronome"):
        assert run_matin(day="2026-09-22", now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS, declencheur=decl) == 0
    con = storage.connect(env["db"])
    assert [r[0] for r in con.execute("select status from runs where command='matin' order by started_at_utc")] == ["SOURCE_SANS_MATIN", "SOURCE_SANS_MATIN"]
    assert con.execute("select count(*) from bases_editions").fetchone()[0] == 0
    assert "::warning title=Source sans matin du jour::source sans matin du jour : aucune prédiction T_MATIN du 2026-09-22" in capsys.readouterr().out
    assert "source sans matin du jour" in (env["rapports"] / "journal" / "ALERTES.md").read_text(encoding="utf-8")
    con.close()


def test_soir_scores_from_public_json(env, results_client):
    """Le 20/09 est passé : matin strict n'a rien publié, mais la mesure T15 crée des éditions rétrospectives
    que le soir note sur le JSON public (contrôle croisé SQLite)."""
    rc = run_soir(day="2026-09-20", results_client=results_client, db_path=env["db"], n_sims=N_SIMS)
    assert rc == 0
    con = storage.connect(env["db"])
    n_mesure = con.execute("select count(*) from bases_editions where mode='mesure' and horizon='T15'").fetchone()[0]
    assert n_mesure > 20
    per_h = dict(con.execute("select horizon, count(*) from bases_editions where mode='mesure' group by 1").fetchall())
    assert set(per_h) == {"T90", "T30", "T15"} and all(v > 20 for v in per_h.values())
    assert all(r[0] == 1 for r in con.execute("select repetition from bases_editions where mode='mesure'"))   # avant le début du protocole
    assert con.execute("select count(*) from bases_results where horizon='T90'").fetchone()[0] > 40
    assert con.execute("select count(*) from bases_results where non_partants_json is null").fetchone()[0] == 0
    rows = con.execute("select * from bases_results where horizon='T15'").fetchall()
    # une ligne par cible m = 4 et m = 5 ; une course du 20/09 a moins de 4 classés (non notée, motif journalisé)
    assert len(rows) % 2 == 0 and 2 * (n_mesure - 2) <= len(rows) < 2 * n_mesure
    assert all(r["repetition"] == 1 for r in rows)
    assert all(r["checked_against_sqlite"] == 1 and r["source"] == "RESULTATS_JSON" for r in rows)
    r5 = [r for r in rows if r["top_m"] == 5]
    assert 0.05 < sum(r["hit_k3"] for r in r5) / len(r5) < 0.6
    assert all(r["hit_k1"] >= r["hit_k2"] >= r["hit_k3"] >= r["hit_k4"] for r in rows)
    assert con.execute("select empreinte_sha256 from results_manifest where date='2026-09-20'").fetchone()[0]
    # second passage : empreinte inchangée → aucune relecture, aucune re-notation
    total_before = con.execute("select count(*) from bases_results").fetchone()[0]
    before = results_client.requests_made
    rc = run_soir(day="2026-09-20", results_client=results_client, db_path=env["db"], n_sims=N_SIMS)
    assert rc == 0 and results_client.requests_made == before + 2     # manifeste du contrat + manifeste du soir, aucune journée relue
    assert con.execute("select count(*) from bases_results").fetchone()[0] == total_before
    journal = (env["rapports"] / "journal" / "2026-09-20.md").read_text(encoding="utf-8")
    assert "bilan du 20/09" in journal and "mesure intrajournée T90/T30/T15" in journal


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
    rc = run_matin(day="2026-09-22", now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS, scheduled=True, protocol_path=proto)
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
    assert con.execute("select count(*) from bases_editions where mode='mesure' and repetition=0 and horizon='T90'").fetchone()[0] > 20
    con.close()
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
    assert "Évolution intrajournée" in md and "| T90 |" in md and "| T30 |" in md and "| T15 |" in md
    from bases_engine.hebdo import intraday_stats
    con = storage.connect(env["db"])
    intra = intraday_stats(con)
    assert intra["n_matin"] > 20 and all(intra["horizons"][h]["n_communes"] > 20 for h in ("T90", "T30", "T15"))
    assert 0 <= intra["bases_np"] <= intra["n_matin"]
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
    assert "Tous à l'arrivée</td>" in html and "Tous sauf un</td><td>—</td>" in html and "(3 sur 3)" in html and "(2 sur 3)" in html
    assert "<details class='course'" in html and "<summary>" in html and "en attente" in html
    assert "k/k" not in html and "k−1" not in html and "Sélection moteur" in html and "Associés" in html
    assert "Tous sauf un = un seul d'entre eux peut manquer" in html
    journal = (env["rapports"] / "journal" / "2026-09-21.md").read_text(encoding="utf-8")
    assert "Tous à l'arrivée : " in journal and "Tous sauf un : — · " in journal and "(1 sur 2)" in journal and "k/k" not in journal
    assert "Courses écartées du jour (non éligibles)" in html and "moins de 8 partants" in html and "TOP4" not in html and "Quinté+" in html
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


# ----------------------------------------------------------------------------
# Sprint 4 : passe horaire, résultats partiels, journée annulée, navigation
# ----------------------------------------------------------------------------

def _results_dir_with(tmp_path, fixtures_dir, mutate):
    """Copie de la fixture résultats avec une journée 2026-09-20 modifiée (empreintes recalculées)."""
    import shutil
    from bases_engine.util import sha256_json_compact
    d = tmp_path / "resultats"
    shutil.copytree(fixtures_dir / "resultats", d)
    day = json.loads((d / "2026-09-20.json").read_text(encoding="utf-8"))
    mutate(day["courses"])
    day["empreinte_sha256"] = sha256_json_compact(day["courses"])
    (d / "2026-09-20.json").write_text(json.dumps(day, ensure_ascii=False), encoding="utf-8")
    man = json.loads((d / "index.json").read_text(encoding="utf-8"))
    man["journees"]["2026-09-20"]["empreinte_sha256"] = day["empreinte_sha256"]
    (d / "index.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    from bases_engine.fetch import ResultsClient
    return ResultsClient(base_url=f"file://{d}")


def _seed_published_day(env, snapshot, day="2026-09-20"):
    """Éditions T_MATIN rétrospectives du 20/09 marquées publiées (mode shadow) pour tester l'affichage des résultats."""
    import bases_engine.pipeline as pl
    con = storage.connect(env["db"])
    storage.set_meta(con, "protocole_debut", day)
    n = pl._mesure_horizon(con, snapshot, day, "T_MATIN", N_SIMS)
    con.execute("update bases_editions set mode='shadow', repetition=0")
    con.execute("insert or replace into journal_days(date, horizon, snapshot_commit, run_id, published_at_utc, mode, status) values (?,?,?,?,?,?,?)",
                (day, "T_MATIN", snapshot.sha, "test", "2026-09-20T09:00:00Z", "shadow", "OK"))
    con.commit(); con.close()
    return n


def test_resultats_partial_day_provisoire_and_annulee(env, snapshot, tmp_path, fixtures_dir):
    from bases_engine.pipeline import run_resultats
    n = _seed_published_day(env, snapshot)
    ids = []

    def mutate(courses):
        eds = [c for c in courses]
        # 1re course : provisoire ; 2e : annulée ; 3e : en attente (pas de classement) ; reste : définitives
        for i, c in enumerate(eds):
            if i == 0:
                c["statut"] = {"code": "PROVISOIRE", "definitive": False, "finalite": None, "annulee": False, "pmu_statut": "ARRIVEE_PROVISOIRE"}
            elif i == 1:
                c["statut"] = {"code": "ANNULEE", "definitive": False, "finalite": None, "annulee": True, "pmu_statut": "COURSE_ANNULEE"}
                c["classement"], c["arrivee"] = [], []
            elif i == 2:
                c["statut"] = {"code": "EN_ATTENTE", "definitive": False, "finalite": None, "annulee": False, "pmu_statut": "PROGRAMMEE"}
                c["classement"], c["arrivee"] = [], []
            ids.append(c["course_id"])
    client = _results_dir_with(tmp_path, fixtures_dir, mutate)
    assert run_resultats(day="2026-09-20", results_client=client, db_path=env["db"]) == 0
    con = storage.connect(env["db"])
    st = storage.course_statuts_for_day(con, "2026-09-20")
    assert st[ids[0]]["statut"] == "PROVISOIRE" and st[ids[1]]["annulee"] == 1 and st[ids[2]]["statut"] == "EN_ATTENTE"
    res = storage.display_results_for_day(con, "2026-09-20")
    assert all(r["checked_against_sqlite"] == 0 for r in res.values())          # passe horaire : pas de contrôle croisé
    assert ids[1] not in res and ids[2] not in res
    statuts = {r["statut"] for r in res.values()}
    assert "DEFINITIVE" in statuts
    # le palmarès ne compte que DEFINITIVE + VERIFIEE_PMU
    from bases_engine.publish import palmares_and_fiabilite
    pal, _ = palmares_and_fiabilite(con)
    n_def = sum(1 for r in res.values() if r["statut"] == "DEFINITIVE" and r["finalite"] == "VERIFIEE_PMU")
    assert pal["global"]["n"] == n_def and n_def < len(res) + 2
    # page du jour : badges, compteur, résultats, statut provisoire affiché tel quel
    content = env["site"] / "shadow" / ("t" * 32)
    page = (content / "jours" / "2026-09-20.html").read_text(encoding="utf-8")
    assert "annulée" in page and "en attente" in page and "(provisoire)" in page and "3/3 réussis sur" in page
    assert "Résultat — DEFINITIVE" in page and "Arrivée (top" in page and "arrivée</li>" in page and "Structure recommandée : " in page
    assert "provisoires</span>" in page
    # second passage : empreinte inchangée → rien relu, aucune nouvelle ligne
    before = con.execute("select count(*) from bases_results").fetchone()[0]
    reqs = client.requests_made
    assert run_resultats(day="2026-09-20", results_client=client, db_path=env["db"]) == 0
    assert client.requests_made == reqs + 1 and con.execute("select count(*) from bases_results").fetchone()[0] == before
    # le soir relit la journée (notations non contrôlées) et contrôle avec SQLite
    assert run_soir(day="2026-09-20", results_client=client, db_path=env["db"], n_sims=N_SIMS) == 0
    res2 = storage.display_results_for_day(con, "2026-09-20")
    assert all(r["checked_against_sqlite"] == 1 for r in res2.values() if r["statut"] == "DEFINITIVE")
    journal = (env["rapports"] / "journal" / "2026-09-20.md").read_text(encoding="utf-8")
    assert "passe horaire" in journal and "provisoires" in journal


def test_navigation_archive_palmares_pages(env, snapshot, results_client):
    from bases_engine.pipeline import run_resultats
    _seed_published_day(env, snapshot)
    assert run_resultats(day="2026-09-20", results_client=results_client, db_path=env["db"]) == 0
    run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS)
    content = env["site"] / "shadow" / ("t" * 32)
    index = (content / "index.html").read_text(encoding="utf-8")
    assert "Édition du 21/09/2026" in index and "href='jours/2026-09-20.html'" in index and "href='jours/2026-09-21.html'" in index
    assert "aujourd'hui" in index and "hier" in index and "id='q'" in index and "palmares.html" in index and "archive/2026-09.html" in index
    j20 = (content / "jours" / "2026-09-20.html").read_text(encoding="utf-8")
    assert "href='../jours/2026-09-21.html'" in j20 and "href='../palmares.html'" in j20 and "3/3 réussis sur" in j20
    arch = (content / "archive" / "2026-09.html").read_text(encoding="utf-8")
    assert "jours/2026-09-20.html" in arch and "jours/2026-09-21.html" in arch and "<th>3/3</th>" in arch
    pal = (content / "palmares.html").read_text(encoding="utf-8")
    assert "Par barreau" in pal and "Par solidité" in pal and "Répétitions manuelles exclues" in pal and "Par journée" in pal
    assert "Palmarès depuis le 20/09/2026 · mode shadow" in pal
    for page in (index, j20, arch, pal):
        assert "{pal." not in page and "{html." not in page and "{month}" not in page and "{_fr(" not in page
    assert "Archive 2026-09 · mode shadow" in arch
    assert "Palmarès depuis le 20/09/2026" in index and "courses écartées (non éligibles)" in index and "abstention sur bases fixes" in index
    assert (content / "bases" / "2026-09-20.json").exists() and (content / "bases" / "2026-09-21.json").exists()


def test_soir_self_heals_previous_days(env, snapshot, results_client):
    """Le 20/09 a une édition du matin mais ni notation ni mesure (soir manqué) : le soir du 21/09 rattrape tout, idempotent."""
    _seed_published_day(env, snapshot, "2026-09-20")
    assert run_soir(day="2026-09-21", results_client=results_client, db_path=env["db"], n_sims=N_SIMS) == 0
    con = storage.connect(env["db"])
    assert storage.results_count(con, "2026-09-20") > 40 and storage.unchecked_count(con, "2026-09-20") == 0
    assert con.execute("select count(*) from bases_editions where date='2026-09-20' and mode='mesure' and horizon='T90'").fetchone()[0] > 20
    journal = (env["rapports"] / "journal" / "2026-09-21.md").read_text(encoding="utf-8")
    assert "Rattrapage — journée du 20/09 : mesure intrajournée complétée" in journal and "notation complétée (notation non faite" in journal
    n_res, n_eds = storage.results_count(con, "2026-09-20"), con.execute("select count(*) from bases_editions").fetchone()[0]
    reqs = results_client.requests_made
    assert run_soir(day="2026-09-21", results_client=results_client, db_path=env["db"], n_sims=N_SIMS) == 0
    assert storage.results_count(con, "2026-09-20") == n_res and con.execute("select count(*) from bases_editions").fetchone()[0] == n_eds
    assert results_client.requests_made == reqs + 2          # contrat + manifeste : aucune journée relue
    journal = (env["rapports"] / "journal" / "2026-09-21.md").read_text(encoding="utf-8")
    assert "Rattrapage : rien à compléter" in journal


def test_favicon_copied_and_linked_on_every_page(env, snapshot, results_client):
    from bases_engine.pipeline import run_resultats
    _seed_published_day(env, snapshot)
    run_resultats(day="2026-09-20", results_client=results_client, db_path=env["db"])
    run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS)
    site = env["site"]
    for name in ("favicon.svg", "favicon.ico", "favicon-32.png", "apple-touch-icon.png", "favicon-512.png"):
        assert (site / name).exists() and (site / name).stat().st_size > 0
    content = site / "shadow" / ("t" * 32)
    pages = [site / "index.html", content / "index.html", content / "jours" / "2026-09-20.html", content / "archive" / "2026-09.html", content / "palmares.html"]
    for p in pages:
        t = p.read_text(encoding="utf-8")
        for tag in ('href="/favicon.svg"', 'sizes="32x32" href="/favicon-32.png"', 'rel="shortcut icon" href="/favicon.ico"',
                    'rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png"', '<meta name="theme-color" content="#0A0A0A">'):
            assert tag in t, (p, tag)


# ----------------------------------------------------------------------------
# Métronome : passes planifiées (cron | metronome), répétition rapide, garde-fou, compteur
# ----------------------------------------------------------------------------

def test_manual_then_metronome_is_fast_repetition(env, results_client, tmp_path, capsys):
    from bases_engine.protocol import PLACEHOLDER, PLACEHOLDER_COMMIT
    proto = tmp_path / "PROTOCOLE.md"; proto.write_text(f"{PLACEHOLDER}\n{PLACEHOLDER_COMMIT}\n", encoding="utf-8")
    assert run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS, declencheur="manuel", protocol_path=proto) == 0
    con = storage.connect(env["db"])
    n_ed = con.execute("select count(*) from bases_editions").fetchone()[0]
    page_before = (env["site"] / "shadow" / ("t" * 32) / "index.html").read_text(encoding="utf-8")
    t0 = time.time()
    assert run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS, declencheur="metronome", protocol_path=proto) == 0
    assert time.time() - t0 < 5
    assert con.execute("select count(*) from bases_editions").fetchone()[0] == n_ed
    assert storage.protocol_start_date(con) is None and "à renseigner" in proto.read_text(encoding="utf-8")
    assert (env["site"] / "shadow" / ("t" * 32) / "index.html").read_text(encoding="utf-8") == page_before
    runs = con.execute("select declencheur, mode, status from runs where command='matin' order by started_at_utc").fetchall()
    assert [tuple(r) for r in runs] == [("manuel", "shadow", "OK"), ("metronome", "repetition", "OK")]
    journal = (env["rapports"] / "journal" / "2026-09-21.md").read_text(encoding="utf-8")
    assert "répétition (déjà servie)" in journal and "run matin-2026-09-21" in journal
    assert "Métronome silencieux" not in capsys.readouterr().out


def test_metronome_first_fixes_start_then_cron_is_repetition_without_warning(env, results_client, tmp_path, capsys):
    from bases_engine.protocol import PLACEHOLDER, PLACEHOLDER_COMMIT, start_date_in_file
    proto = tmp_path / "PROTOCOLE.md"; proto.write_text(f"{PLACEHOLDER}\n{PLACEHOLDER_COMMIT}\n", encoding="utf-8")
    assert run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS, declencheur="metronome", protocol_path=proto) == 0
    con = storage.connect(env["db"])
    assert storage.protocol_start_date(con) == "2026-09-21" and start_date_in_file(proto) == "2026-09-21"
    assert all(r[0] == 0 and r[1] == "metronome" for r in con.execute("select repetition, declencheur from bases_editions"))
    capsys.readouterr()
    assert run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS, declencheur="cron", protocol_path=proto) == 0
    out = capsys.readouterr().out
    assert "Métronome silencieux" not in out
    assert con.execute("select mode from runs where declencheur='cron'").fetchone()[0] == "repetition"


def test_cron_without_metronome_serves_and_warns(env, results_client, tmp_path, capsys):
    from bases_engine.protocol import PLACEHOLDER, PLACEHOLDER_COMMIT
    proto = tmp_path / "PROTOCOLE.md"; proto.write_text(f"{PLACEHOLDER}\n{PLACEHOLDER_COMMIT}\n", encoding="utf-8")
    assert run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS, declencheur="cron", protocol_path=proto) == 0
    out = capsys.readouterr().out
    assert "::warning title=Métronome silencieux::matin 2026-09-21 servie par le filet GitHub" in out
    con = storage.connect(env["db"])
    assert storage.protocol_start_date(con) == "2026-09-21"           # le filet fait le travail utile
    journal = (env["rapports"] / "journal" / "2026-09-21.md").read_text(encoding="utf-8")
    assert "METRONOME_SILENCIEUX" in journal
    assert con.execute("select count(*) from bases_editions where repetition=0").fetchone()[0] == 20


def test_planned_soir_twice_is_fast_repetition_and_hebdo_counts_metronome(env, snapshot, results_client, tmp_path, monkeypatch):
    from bases_engine import config
    from bases_engine.hebdo import run_hebdo
    monkeypatch.setattr(config, "PARAMS_PATH", tmp_path / "params.json"); monkeypatch.setattr(config, "ROOT", tmp_path)
    _seed_published_day(env, snapshot, "2026-09-20")
    assert run_soir(day="2026-09-20", results_client=results_client, db_path=env["db"], n_sims=N_SIMS, declencheur="metronome") == 0
    t0 = time.time()
    assert run_soir(day="2026-09-20", results_client=results_client, db_path=env["db"], n_sims=N_SIMS, declencheur="cron") == 0
    assert time.time() - t0 < 5
    con = storage.connect(env["db"])
    assert [tuple(r) for r in con.execute("select declencheur, mode from runs where command='soir' order by started_at_utc")] == [("metronome", "shadow"), ("cron", "repetition")]
    # un soir manuel ne bloque pas le soir planifié suivant
    assert run_soir(day="2026-09-21", results_client=results_client, db_path=env["db"], n_sims=N_SIMS, declencheur="manuel") == 0
    assert run_soir(day="2026-09-21", results_client=results_client, db_path=env["db"], n_sims=N_SIMS, declencheur="metronome") == 0
    assert con.execute("select mode from runs where command='soir' and day='2026-09-21' and declencheur='metronome'").fetchone()[0] == "shadow"
    run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS, declencheur="metronome")
    assert run_hebdo(day="2026-09-21", db_path=env["db"], declencheur="cron") == 0
    md = (env["rapports"] / "2026-W39.md").read_text(encoding="utf-8")
    assert "Métronome : **1** jour(s) servi(s) par le métronome, **0** par le filet GitHub, **6** manqué(s)." in md


def test_persistent_fingerprint_gap_is_reported(env, snapshot, tmp_path, fixtures_dir, capsys, monkeypatch):
    """Écart manifeste ↔ journée persistant : silencieux 2 passes, annotation à la 3e ; le soir signale d'office ; compteur hebdo."""
    import shutil
    from bases_engine.fetch import ResultsClient
    from bases_engine.pipeline import run_resultats
    from bases_engine.hebdo import run_hebdo
    from bases_engine import config
    monkeypatch.setattr(config, "PARAMS_PATH", tmp_path / "params.json"); monkeypatch.setattr(config, "ROOT", tmp_path)
    _seed_published_day(env, snapshot, "2026-09-20")
    d = tmp_path / "res"; shutil.copytree(fixtures_dir / "resultats", d)
    m = json.loads((d / "index.json").read_text(encoding="utf-8")); m["journees"]["2026-09-20"]["empreinte_sha256"] = "9" * 64
    (d / "index.json").write_text(json.dumps(m), encoding="utf-8")            # manifeste durablement incohérent
    client = ResultsClient(base_url=f"file://{d}")
    for i in (1, 2):
        assert run_resultats(day="2026-09-20", results_client=client, db_path=env["db"]) == 0
        assert "Écart d'empreinte persistant" not in capsys.readouterr().out
    assert run_resultats(day="2026-09-20", results_client=client, db_path=env["db"]) == 0
    assert "::warning title=Écart d'empreinte persistant::journée 2026-09-20" in capsys.readouterr().out
    con = storage.connect(env["db"])
    assert storage.ecart_empreinte_consecutifs(con, "2026-09-20") == 3
    assert con.execute("select count(*) from incidents where kind='ECART_EMPREINTE_PERSISTANT'").fetchone()[0] == 1
    assert "ECART_EMPREINTE_PERSISTANT" in (env["rapports"] / "journal" / "ALERTES.md").read_text(encoding="utf-8")
    assert run_soir(day="2026-09-20", results_client=client, db_path=env["db"], n_sims=N_SIMS) == 0
    assert "jusqu'à la passe soir" in capsys.readouterr().out
    assert con.execute("select count(*) from incidents where kind='ECART_EMPREINTE_PERSISTANT'").fetchone()[0] == 2
    assert run_hebdo(day="2026-09-21", db_path=env["db"]) == 0
    assert "Écarts d'empreinte persistants (manifeste ↔ journée, 7 derniers jours) : **2**." in (env["rapports"] / "2026-W39.md").read_text(encoding="utf-8")
    # manifeste réparé : lecture réussie, compteur consécutif remis à zéro
    shutil.copy(fixtures_dir / "resultats" / "index.json", d / "index.json")
    assert run_resultats(day="2026-09-20", results_client=client, db_path=env["db"]) == 0
    assert storage.ecart_empreinte_consecutifs(con, "2026-09-20") == 0


def test_site_built_marker_only_when_content_regenerated(env, results_client, tmp_path, monkeypatch):
    """Le workflow ne déploie que si ce marqueur existe : jamais en dry-run, en répétition ni en ombre sans jeton
    (sinon `site/` = page neutre seule → déploiement = effacement des pages shadow en ligne, incident du 23/09/2026)."""
    from bases_engine.params import load_params
    from bases_engine.protocol import PLACEHOLDER, PLACEHOLDER_COMMIT
    from bases_engine.site import build_site, site_built_marker
    proto = tmp_path / "PROTOCOLE.md"; proto.write_text(f"{PLACEHOLDER}\n{PLACEHOLDER_COMMIT}\n", encoding="utf-8")
    marker = site_built_marker(); marker.unlink(missing_ok=True)
    assert run_matin(day="2026-09-21", dry_run=True, now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS, protocol_path=proto) == 0
    assert not marker.exists()                                        # dry-run : rien à déployer
    assert run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS, declencheur="manuel", protocol_path=proto) == 0
    assert marker.exists() and "shadow 2026-09-21" in marker.read_text(encoding="utf-8")
    marker.unlink()
    assert run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS, declencheur="metronome", protocol_path=proto) == 0
    assert not marker.exists()                                        # répétition : site non reconstruit → pas de déploiement
    con = storage.connect(env["db"])
    assert con.execute("select mode from runs where command='matin' and declencheur='metronome'").fetchone()[0] == "repetition"
    build_site(con, "2026-09-21", load_params(), mode="shadow", shadow_token=None)
    assert not marker.exists()                                        # ombre sans jeton : page neutre seule, jamais déployée
    build_site(con, "2026-09-21", load_params(), mode="shadow", shadow_token="t" * 32)
    assert marker.exists()
    con.close()


def test_nav_pills_show_integer_counts(env, results_client):
    """Régression du 25/09/2026 (commit cbe4ade « Update site.py ») : build_nav renvoyait la ligne SQLite entière au lieu du
    nombre, la pastille affichait « hier ( ) ». Le compte doit être un entier et apparaître dans la pastille."""
    from bases_engine.site import _nav_html, build_nav
    assert run_matin(day="2026-09-21", now=NOW, results_client=results_client, db_path=env["db"], n_sims=N_SIMS) == 0
    con = storage.connect(env["db"])
    nav = build_nav(con, "2026-09-22")
    hier = next(n for n in nav if n["date"] == "2026-09-21")
    assert isinstance(hier["n"], int) and hier["n"] == 20
    html = _nav_html(nav, "2026-09-22", "")
    assert "<small>(20)</small>" in html and "sqlite3.Row" not in html
    con.close()


def test_soir_without_predictions_of_the_day_still_self_heals(env, snapshot, results_client):
    """Incident du 25/09/2026 : la base du moteur n'a aucune prédiction du jour (matin en échec de contrat, aucune édition).
    Le soir ne doit pas s'arrêter pour ce seul motif : rien à noter pour J, mais rattrapage J-1..J-7 et site. Les filets cron
    sortent ensuite en répétition sans téléchargement."""
    _seed_published_day(env, snapshot, "2026-09-20")
    assert run_soir(day="2026-09-22", results_client=results_client, db_path=env["db"], n_sims=N_SIMS, declencheur="metronome") == 0
    con = storage.connect(env["db"])
    assert con.execute("select status from runs where command='soir' and day='2026-09-22'").fetchone()[0] == "OK"
    assert storage.results_count(con, "2026-09-20") > 40                        # J-2 rattrapé malgré l'absence de prédictions pour J
    journal = (env["rapports"] / "journal" / "2026-09-22.md").read_text(encoding="utf-8")
    assert "soir sans prédiction du jour" in journal and "Rattrapage — journée du 20/09" in journal
    assert run_soir(day="2026-09-22", results_client=results_client, db_path=env["db"], n_sims=N_SIMS, declencheur="cron") == 0
    assert con.execute("select mode from runs where command='soir' and day='2026-09-22' and declencheur='cron'").fetchone()[0] == "repetition"
    con.close()


def test_soir_still_blocks_on_predictions_outside_contract(env, results_client, monkeypatch):
    """L'exception du soir est étroite : des prédictions du jour présentes mais hors contrat v2 restent bloquantes."""
    import bases_engine.pipeline as pipeline
    from bases_engine.contract import CHECK_PREDICTIONS, ContractResult
    monkeypatch.setattr(pipeline, "run_contract_checks",
                        lambda *a, **k: ContractResult(failed=[(CHECK_PREDICTIONS, "3 ligne(s) hors contrat v2")], jour_sans_predictions=False))
    with pytest.raises(PipelineStop):
        run_soir(day="2026-09-22", results_client=results_client, db_path=env["db"], n_sims=N_SIMS)
    con = storage.connect(env["db"])
    assert con.execute("select status from runs where command='soir'").fetchone()[0] == "CONTRACT_FAILED"
    con.close()
