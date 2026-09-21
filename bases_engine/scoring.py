"""Notation et back-test (§7, sprint 1).

Le back-test rejoue l'échelle sur l'historique de l'instantané, note sur `race_results`
(DEFINITIVE + VERIFIEE_PMU), compare aux baselines, trace la courbe de fiabilité,
ajuste le calibrateur post-sélection par (k, top_m) et calcule les terciles de solidité.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import numpy as np

from . import config
from .compute import ladder_for
from .calibration import LadderCalibrator
from .eligibility import Abstention, EligibleRace, evaluate_race
from .fetch import Snapshot

FIAB_BINS = [0, 0.08, 0.12, 0.16, 0.22, 0.30, 1.0]


def hits(chevaux, arrivee_top: set[int]) -> int:
    return len(set(chevaux) & arrivee_top)


def arrival_top(con, race_id: str) -> tuple[list[int] | None, str | None]:
    """Arrivée définitive vérifiée (numéros classés dans l'ordre), sinon (None, motif)."""
    rr = con.execute("select * from race_results where race_id = ?", (race_id,)).fetchone()
    if rr is None:
        return None, "NO_RESULT"
    if rr["statut"] != "DEFINITIVE":
        return None, f"RESULT_{rr['statut']}"
    if rr["finalite"] != "VERIFIEE_PMU":
        return None, f"RESULT_{rr['finalite']}"
    try:
        arr = [int(x) for x in json.loads(rr["arrival_order_json"])]
    except (ValueError, TypeError):
        return None, "RESULT_INVALID"
    nps = set(json.loads(rr["non_partants_json"] or "[]"))
    arr = [n for n in arr if n not in nps]          # un NP ne compte jamais comme placé
    return arr, None


@dataclass
class RaceRecord:
    race: EligibleRace
    arrivee: list[int]
    ladders: dict = field(default_factory=dict)     # m -> ladder dict


def collect_races(snap: Snapshot, horizon: str, since: str, until: str | None = None) -> tuple[list[RaceRecord], dict]:
    con = snap.connect()
    logs = snap.logs_by_race()
    abst: dict[str, int] = {}
    recs: list[RaceRecord] = []
    try:
        q = "select race_id from races where date >= ? " + ("and date <= ? " if until else "") + "order by date, race_id"
        for (race_id,) in con.execute(q, (since, until) if until else (since,)):
            ev = evaluate_race(con, race_id, horizon, logs.get(race_id), mode="backtest")
            if isinstance(ev, Abstention):
                abst[ev.motif] = abst.get(ev.motif, 0) + 1
                continue
            arr, why = arrival_top(con, race_id)
            if arr is None:
                abst[why] = abst.get(why, 0) + 1
                continue
            if len(arr) < 5:
                abst["RESULT_TOO_SHORT"] = abst.get("RESULT_TOO_SHORT", 0) + 1
                continue
            recs.append(RaceRecord(ev, arr))
    finally:
        con.close()
    return recs, abst


def run_ladders(recs: list[RaceRecord], lambdas, n_sims: int) -> None:
    for r in recs:
        for m in (4, 5):
            r.ladders[m] = ladder_for(r.race, m, lambdas, n_sims=n_sims)


def _rate(xs) -> float | None:
    return float(np.mean(xs)) if len(xs) else None


def fiabilite(pred: np.ndarray, obs: np.ndarray, bins=FIAB_BINS) -> list[dict]:
    out = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (pred >= lo) & (pred < hi)
        if m.sum():
            out.append({"tranche": f"[{lo:.2f},{hi:.2f})", "n": int(m.sum()),
                        "p_annoncee": float(pred[m].mean()), "freq_observee": float(obs[m].mean())})
    return out


def analyse(recs: list[RaceRecord], m: int, *, calib_split: float = 0.5) -> dict:
    """Statistiques pour la cible m : taux par k, baselines, fiabilité brute et recalibrée
    (calibrateur ajusté sur la première moitié chronologique, évalué sur la seconde), terciles."""
    n = len(recs)
    res = {"top_m": m, "n": n}
    if n == 0:
        return res
    tops = [set(r.arrivee[:m]) for r in recs]
    # taux par k
    for k in (1, 2, 3, 4):
        res[f"taux_k{k}"] = _rate([hits(r.ladders[m]["echelle"][k]["chevaux"], t) == k for r, t in zip(recs, tops)])
    res["taux_2of3"] = _rate([hits(r.ladders[m]["echelle"][3]["chevaux"], t) >= 2 for r, t in zip(recs, tops)])
    # baselines
    res["baseline_moteur_3"] = _rate([hits(r.race.engine8[:3], t) == 3 for r, t in zip(recs, tops)])
    mk = [(r, t) for r, t in zip(recs, tops) if r.race.market_probs]
    res["baseline_marche_3"] = _rate([hits(sorted(r.race.market_probs, key=lambda x: -r.race.market_probs[x])[:3], t) == 3 for r, t in mk])
    res["n_marche"] = len(mk)
    res["trio_identique_moteur"] = _rate([set(r.ladders[m]["echelle"][3]["chevaux"]) == set(r.race.engine8[:3]) for r in recs])
    # fiabilité brute (k=3)
    pred3 = np.array([r.ladders[m]["echelle"][3]["p_brute"] for r in recs])
    obs3 = np.array([hits(r.ladders[m]["echelle"][3]["chevaux"], t) == 3 for r, t in zip(recs, tops)], dtype=float)
    res["p3_annoncee_moy"] = float(pred3.mean()); res["p3_observee_moy"] = float(obs3.mean())
    res["fiabilite_brute_k3"] = fiabilite(pred3, obs3)
    # calibrateurs par k : ajustement hors échantillon (split chronologique) + ajustement complet
    split = int(n * calib_split)
    res["calibration"] = {}
    for k in (1, 2, 3, 4):
        pk = np.array([r.ladders[m]["echelle"][k]["p_brute"] for r in recs])
        ok = np.array([hits(r.ladders[m]["echelle"][k]["chevaux"], t) == k for r, t in zip(recs, tops)], dtype=float)
        cal_oos = LadderCalibrator().fit(pk[:split], ok[:split])
        cal_all = LadderCalibrator().fit(pk, ok)
        entry = {"n_fit_oos": int(split), **cal_all.to_dict()}
        if k == 3:
            p_oos = cal_oos.transform(pk[split:])
            entry["fiabilite_recalibree_oos"] = fiabilite(p_oos, ok[split:])
            entry["oos_mode"] = cal_oos.mode
            p_all = cal_all.transform(pk)
            entry["fiabilite_recalibree_in_sample"] = fiabilite(p_all, ok)
            q1, q2 = np.quantile(p_all, [1 / 3, 2 / 3])
            res["seuils_solidite"] = {"A": round(float(q2), 4), "B": round(float(q1), 4)}
            sol = np.where(p_all >= q2, "A", np.where(p_all >= q1, "B", "C"))
            res["par_solidite"] = {s: {"n": int((sol == s).sum()), "taux_3of3": _rate(ok[sol == s]),
                                       "taux_2of3": _rate(np.array([hits(r.ladders[m]["echelle"][3]["chevaux"], t) >= 2 for r, t in zip(recs, tops)])[sol == s])}
                                   for s in ("A", "B", "C")}
        res["calibration"][f"k{k}_m{m}"] = entry
    # par taille de peloton et par étoiles
    def _bucket(cond):
        idx = [i for i, r in enumerate(recs) if cond(r)]
        return {"n": len(idx), "taux_3of3": _rate(obs3[idx]) if idx else None,
                "taux_2of3": _rate([hits(recs[i].ladders[m]["echelle"][3]["chevaux"], tops[i]) >= 2 for i in idx]) if idx else None}
    res["par_peloton"] = {"8-12": _bucket(lambda r: r.race.active_runners <= 12), "13+": _bucket(lambda r: r.race.active_runners >= 13)}
    res["par_etoiles"] = {str(s): _bucket(lambda r, s=s: r.race.confidence_stars == s) for s in (1, 2, 3, 4, 5)}
    res["par_etoiles"]["4-5"] = _bucket(lambda r: (r.race.confidence_stars or 0) >= 4)
    res["par_etoiles"]["sans"] = _bucket(lambda r: r.race.confidence_stars is None)
    res["par_contrat"] = {"v2": _bucket(lambda r: "LEGACY_CONTRACT" not in r.race.flags),
                          "legacy": _bucket(lambda r: "LEGACY_CONTRACT" in r.race.flags)}
    return res


def backtest(snap: Snapshot, *, since: str, horizon: str = "T15", until: str | None = None,
             lambdas=config.DEFAULT_LAMBDAS, n_sims: int = config.N_SIMS) -> dict:
    t0 = time.time()
    recs, abst = collect_races(snap, horizon, since, until)
    run_ladders(recs, lambdas, n_sims)
    out = {"snapshot_commit": snap.sha, "horizon": horizon, "since": since, "until": until,
           "lambdas": list(lambdas), "n_sims": n_sims, "n_courses": len(recs), "abstentions": abst,
           "dates": (min(r.race.date for r in recs), max(r.race.date for r in recs)) if recs else None,
           "par_cible": {m: analyse(recs, m) for m in (4, 5)},
           "n_cible_quinte": sum(1 for r in recs if r.race.top_m == 5),
           "duree_s": None}
    out["duree_s"] = round(time.time() - t0, 1)
    return out
