"""Génère la fixture synthétique de test : base « moteur » limitée aux colonnes lues par Bases + journée de cas limites.

Décision du mentor du 25/09/2026 : plus aucun extrait de la base du moteur dans le dépôt. La base de test est générée à chaque
session de tests (tests/conftest.py) dans un répertoire temporaire, jamais committée.

Entrées : fixtures/synthetique/programme_public.json (données publiques PMU des 20 et 21/09/2026 : programme, partants,
non-partants, cotes du matin, paris offerts, arrivées, horizons auxquels le moteur a publié). Toutes les sorties du moteur
(probabilités, sélections, empreintes, verrous, étoiles) sont synthétisées avec une graine fixe.

Journée 2026-09-18 « SYNTHESE » (cas limites volontaires) :
  R9C1 nominale, ex-aequo à la 3e place · R9C2 moins de 8 partants · R9C3 no bet · R9C4 T_MATIN absent (cotes réelles)
  R9C5 non-partant dans la sélection du moteur · R9C6 cotes manquantes (taux de cotes réelles 0,67) · R9C7 aucune cote, pas de T_MATIN

Usage : python scripts/generer_fixture.py <répertoire de sortie>   → <sortie>/snapshot/{turf_bench.db,source.json}
                                                                     <sortie>/resultats/{index.json,2026-09-18.json}
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "fixtures" / "synthetique" / "programme_public.json"
ENGINE, MARKET = "NEW_VALUE_ENGINE", "MARKET_BASELINE"
SCHEMA = """
CREATE TABLE races (race_id TEXT PRIMARY KEY, date TEXT, meeting_number INTEGER, race_number INTEGER, status TEXT, pmu_statut TEXT,
                    start_time_utc TEXT, scheduled_start_time TEXT, discipline TEXT, declared_runners INTEGER, bets_json TEXT);
CREATE TABLE runners (race_id TEXT, num INTEGER, is_non_partant INTEGER, odds_is_real INTEGER);
CREATE TABLE predictions (race_id TEXT, engine_name TEXT, horizon TEXT, contract_version INTEGER, prediction_hash TEXT, odds_real INTEGER,
                          priced_ratio REAL, is_no_bet INTEGER, probabilities_json TEXT, selection_json TEXT, lock_time_utc TEXT, confidence_stars INTEGER);
CREATE TABLE race_results (race_id TEXT PRIMARY KEY, statut TEXT, finalite TEXT, arrival_order_json TEXT, non_partants_json TEXT);
"""
PARIS_QUARTE = ["SIMPLE_GAGNANT", "SIMPLE_PLACE", "COUPLE_PLACE", "TRIO", "DEUX_SUR_QUATRE", "MULTI", "QUARTE_PLUS"]


def _rng(*key) -> random.Random:
    return random.Random(int(hashlib.sha256("|".join(map(str, key)).encode()).hexdigest()[:16], 16))


def _probs(race: dict, horizon: str, engine: str) -> dict[int, float]:
    rng = _rng(race["race_id"], horizon, engine)
    sigma = 0.35 if engine == ENGINE else 0.10
    raw = {}
    for p in race["partants"]:
        if p["np"]:
            continue
        cote = p.get("cote_matin") or 15.0
        raw[p["num"]] = (1.0 / max(cote, 1.1)) * math.exp(rng.gauss(0.0, sigma))
    tot = sum(raw.values())
    probs = {n: round(v / tot, 6) for n, v in raw.items()}
    last = max(probs, key=probs.get)
    probs[last] = round(probs[last] + (1.0 - sum(probs.values())), 6)
    return probs


def _lock(race: dict, horizon: str) -> str:
    if horizon == "T_MATIN":
        return f"{race['date']}T06:30:{20 + _rng(race['race_id'], 'lock').randint(0, 29):02d}.000000"
    start = datetime.fromisoformat(race["depart_utc"].replace("Z", "+00:00"))
    return (start - timedelta(minutes={"T90": 90, "T30": 30, "T15": 15}[horizon])).strftime("%Y-%m-%dT%H:%M:%S.000000")


def _cas_limites() -> list[dict]:
    def course(n, depart, nb=12, **kw):
        cotes = [2.5, 4.0, 5.5, 7.0, 9.0, 11.0, 14.0, 18.0, 22.0, 30.0, 40.0, 60.0]
        partants = [{"num": i + 1, "np": 0, "cote_reelle": 1, "cote_matin": cotes[i % len(cotes)]} for i in range(nb)]
        base = {"race_id": f"R9C{n}_18092026_SYNTHESE", "date": "2026-09-18", "reunion": 9, "course": n, "hippodrome": "SYNTHESE",
                "discipline": "PLAT", "distance": 2000, "depart_utc": f"2026-09-18T{depart}:00Z", "depart_affiche": f"{depart} GMT",
                "status": "SCHEDULED", "pmu_statut": "PROGRAMMEE", "partants_declares": nb, "paris": PARIS_QUARTE, "partants": partants,
                "arrivee": None, "arrivee_statut": None, "arrivee_finalite": None,
                "horizons_publies": {ENGINE: ["T_MATIN"], MARKET: ["T_MATIN"]}}
        base.update(kw)
        return base
    c1 = course(1, "12:00", arrivee=[4, 7, 2, 9, 1, 5], arrivee_statut="DEFINITIVE", arrivee_finalite="VERIFIEE_PMU", ex_aequo=[2, 9])
    c2 = course(2, "12:30", nb=7)
    c3 = course(3, "13:00", no_bet=True)
    c4 = course(4, "13:30", horizons_publies={ENGINE: [], MARKET: ["T_MATIN"]})
    c5 = course(5, "14:00", np_dans_selection=3, arrivee=[1, 2, 4, 5, 6, 7], arrivee_statut="DEFINITIVE", arrivee_finalite="VERIFIEE_PMU")
    c5["partants"][2]["np"] = 1
    c6 = course(6, "14:30")
    for p in c6["partants"][8:]:
        p["cote_reelle"], p["cote_matin"] = 0, None
    c7 = course(7, "15:00", horizons_publies={ENGINE: [], MARKET: []})
    for p in c7["partants"]:
        p["cote_reelle"], p["cote_matin"] = 0, None
    return [c1, c2, c3, c4, c5, c6, c7]


def generer(out: Path) -> Path:
    out = Path(out)
    snap = out / "snapshot"; res = out / "resultats"
    snap.mkdir(parents=True, exist_ok=True); res.mkdir(parents=True, exist_ok=True)
    db = snap / "turf_bench.db"
    db.unlink(missing_ok=True)
    courses = json.loads(SPEC.read_text(encoding="utf-8"))["courses"] + _cas_limites()
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    for r in courses:
        rid = r["race_id"]
        con.execute("insert into races values (?,?,?,?,?,?,?,?,?,?,?)", (rid, r["date"], r["reunion"], r["course"], r["status"], r["pmu_statut"],
                    r["depart_utc"], r["depart_affiche"], r["discipline"], r["partants_declares"], json.dumps([{"code": c} for c in r["paris"]])))
        con.executemany("insert into runners values (?,?,?,?)", [(rid, p["num"], p["np"], p["cote_reelle"]) for p in r["partants"]])
        actifs = [p for p in r["partants"] if not p["np"]]
        odds_real = int(any(p["cote_reelle"] for p in actifs))
        priced = round(sum(p["cote_reelle"] for p in actifs) / len(actifs), 2) if actifs else 0.0
        for engine, horizons in r["horizons_publies"].items():
            for h in horizons:
                probs = _probs(r, h, engine)
                sel = sorted(probs, key=lambda n: (-probs[n], n))[:8]
                if engine == ENGINE and r.get("np_dans_selection"):
                    sel = sel[:1] + [r["np_dans_selection"]] + sel[1:7]
                pj = json.dumps({str(n): v for n, v in probs.items()}, sort_keys=True)
                con.execute("insert into predictions values (?,?,?,?,?,?,?,?,?,?,?,?)", (
                    rid, engine, h, 2, hashlib.sha256(f"{rid}|{engine}|{h}|{pj}".encode()).hexdigest(), odds_real, priced,
                    int(bool(r.get("no_bet")) and engine == ENGINE), pj, json.dumps(sel), _lock(r, h), min(5, 1 + int(max(probs.values()) * 10))))
        if r.get("arrivee"):
            con.execute("insert into race_results values (?,?,?,?,?)", (rid, r["arrivee_statut"], r["arrivee_finalite"], json.dumps(r["arrivee"]),
                        json.dumps([p["num"] for p in r["partants"] if p["np"]])))
    con.commit(); con.close()
    sha = hashlib.sha256(db.read_bytes()).hexdigest()
    (snap / "source.json").write_text(json.dumps({"sha256": sha, "pushed-at": "2026-09-21T09:00:00Z", "run-id": "fixture-synthetique",
                                                  "commit": "synthetique", "counts": f"courses={len(courses)}"}), encoding="utf-8")
    _resultats_cas_limites(res, [c for c in courses if c["date"] == "2026-09-18" and c.get("arrivee")])
    return snap


def _resultats_cas_limites(res: Path, courses: list[dict]) -> None:
    """JSON publics de résultats (même format que /resultats/) pour les courses terminées du 18/09 : ex-aequo et non-partant."""
    sys.path.insert(0, str(ROOT))
    from bases_engine.util import sha256_json_compact
    out = []
    for c in courses:
        rang, classement = 0, []
        ex = set(c.get("ex_aequo") or [])
        for i, num in enumerate(c["arrivee"]):
            rang = rang if (num in ex and classement and classement[-1]["num"] in ex) else i + 1
            classement.append({"rang": rang, "num": num, "nom": f"CHEVAL {num}", "dead_heat": num in ex})
        nps = [{"num": p["num"]} for p in c["partants"] if p["np"]]
        out.append({"course_id": c["race_id"], "identite": {"date": c["date"], "reunion": c["reunion"], "course": c["course"], "code": f"R{c['reunion']}C{c['course']}",
                                                            "hippodrome": c["hippodrome"], "heure_depart_utc": c["depart_utc"]},
                    "statut": {"code": "DEFINITIVE", "definitive": True, "finalite": "VERIFIEE_PMU", "annulee": False, "pmu_statut": "ARRIVEE_DEFINITIVE_COMPLETE"},
                    "classement": classement, "arrivee": c["arrivee"], "non_classes": [], "non_partants": nps,
                    "correction": {"version": 1, "nb_corrections": 0, "historique": []}})
    fp = sha256_json_compact(out)
    (res / "2026-09-18.json").write_text(json.dumps({"schema_version": "1.1", "date_course": "2026-09-18", "nb_courses": len(out),
                                                     "compte_par_statut": {"DEFINITIVE": len(out)}, "empreinte_sha256": fp, "courses": out}), encoding="utf-8")
    (res / "index.json").write_text(json.dumps({"schema_version": "1.1", "journees": {"2026-09-18": {"nb_courses": len(out), "empreinte_sha256": fp,
                                                "compte_par_statut": {"DEFINITIVE": len(out)}}}}), encoding="utf-8")


if __name__ == "__main__":
    print(generer(Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/fixture-bases")))
