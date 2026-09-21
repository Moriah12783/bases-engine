"""`hebdo` (lundi) : recalibration par (k, top_m) sur l'ensemble noté hors répétitions, nouvelle version de
`params.json` (seuils inchangés jusqu'au verdict), rapport hebdomadaire `rapports/AAAA-Www.md` avec baselines,
fiabilité, état des critères du protocole ; rendement non calculé tant que le mapping `rapports` n'est pas validé."""
from __future__ import annotations

import json
import time
import uuid
from datetime import date as _date, datetime

import numpy as np

from . import config, storage
from .calibration import LadderCalibrator
from .fetch import FetchError, get_snapshot
from .notify import alert, notify
from .params import load_params, save_params
from .scoring import fiabilite
from .util import iso_utc


def _rows(con) -> list[dict]:
    return [r for r in storage.latest_results(con, "T_MATIN")
            if r["ed_mode"] in ("shadow", "live") and not r["repetition"] and not r["ed_repetition"]]


def recalibrate(con, rows: list[dict], day: str, params: dict) -> dict | None:
    """Nouvelle version de params : calibrateurs réajustés par (k, m) sur P brute → réussite observée."""
    if not rows:
        return None
    n_prev = sum(1 for _ in con.execute("select 1 from params where valid_from = ?", (day,)))
    version = f"{day}.{n_prev + 1}"
    new = {**params, "version": version, "valid_from": day, "calibration": {}, "calibration_paliers": params.get("calibration_paliers") or config.CALIB_LEVELS,
           "note": f"Recalibration hebdomadaire du {day} sur {len({r['race_id'] for r in rows})} courses notées (hors répétitions). Seuils de solidité et lambdas inchangés (gelés jusqu'au verdict)."}
    for m in (4, 5):
        sel = [r for r in rows if r["top_m"] == m]
        for k in (1, 2, 3, 4):
            p = np.array([json.loads(r["ladder_json"])[f"top{m}"][str(k)]["p_brute"] for r in sel])
            h = np.array([r[f"hit_k{k}"] or 0 for r in sel], dtype=float)
            cal = LadderCalibrator(new["calibration_paliers"]).fit(p, h) if len(sel) else LadderCalibrator(new["calibration_paliers"])
            d = cal.to_dict()
            new["calibration"][f"k{k}_m{m}"] = d
            storage.insert_calibration(con, iso_utc(), k, m, d["n"], d, version)
    storage.insert_params(con, version, day, new["lambdas"], new["seuils_solidite"], new.get("shrink", config.SHRINK), new["note"])
    save_params(new)
    return new


def _rate(xs):
    return float(np.mean(xs)) if len(xs) else None


def _market_top3(con_snap, race_id: str) -> list[int] | None:
    r = con_snap.execute("select probabilities_json from predictions where race_id=? and engine_name=? and horizon='T_MATIN'",
                         (race_id, config.MARKET_ENGINE)).fetchone()
    if not r or not r[0]:
        return None
    probs = {int(k): float(v) for k, v in json.loads(r[0]).items()}
    return sorted(probs, key=lambda n: -probs[n])[:3]


def weekly_stats(con, rows: list[dict], snap=None) -> dict:
    tgt = [r for r in rows if r["top_m"] == r["ed_top_m"]]
    out = {"n": len({r["race_id"] for r in tgt}), "n_lignes": len(tgt)}
    for k in (1, 2, 3, 4):
        out[f"taux_k{k}"] = _rate([r[f"hit_k{k}"] or 0 for r in tgt])
    out["taux_2of3"] = _rate([r["hit_2of3"] or 0 for r in tgt])
    out["par_solidite"] = {}
    for s in ("A", "B", "C"):
        sel = [r for r in tgt if r["ed_solidite"] == s]
        out["par_solidite"][s] = {"n": len(sel), "taux_3of3": _rate([r["hit_k3"] or 0 for r in sel]), "taux_2of3": _rate([r["hit_2of3"] or 0 for r in sel])}
    pred = np.array([r["p_calibree_k3"] for r in tgt if r["p_calibree_k3"] is not None])
    obs = np.array([r["hit_k3"] or 0 for r in tgt if r["p_calibree_k3"] is not None], dtype=float)
    out["fiabilite"] = fiabilite(pred, obs) if len(pred) else []
    # baselines sur les mêmes courses
    eng, mkt = [], []
    scon = snap.connect() if snap else None
    try:
        for r in tgt:
            placed = set(json.loads(r["arrivee_json"])[: r["top_m"]])
            eng.append(len(set(json.loads(r["engine8_json"])[:3]) & placed) == 3)
            if scon is not None:
                m3 = _market_top3(scon, r["race_id"])
                if m3:
                    mkt.append(len(set(m3) & placed) == 3)
    finally:
        if scon is not None:
            scon.close()
    out["baseline_moteur_3"] = _rate(eng)
    out["baseline_marche_3"] = _rate(mkt)
    out["n_marche"] = len(mkt)
    # état des critères du protocole (informatif jusqu'à l'échéance)
    top2 = out["fiabilite"][-2:] if len(out["fiabilite"]) >= 2 else []
    c1 = all(abs(t["freq_observee"] - t["p_annoncee"]) <= 0.05 and t["n"] >= 60 for t in top2) if top2 else None
    a, c = out["par_solidite"]["A"], out["par_solidite"]["C"]
    c2 = (a["taux_3of3"] is not None and c["taux_3of3"] is not None and a["taux_3of3"] >= 1.8 * c["taux_3of3"] and a["taux_3of3"] >= 0.28) if a["n"] and c["n"] else None
    c3 = (out["taux_k3"] >= out["baseline_moteur_3"] - 0.02) if out["taux_k3"] is not None and out["baseline_moteur_3"] is not None else None
    out["criteres"] = {"calibration": c1, "selectivite": c2, "non_regression": c3,
                       "n_tranches_sup": [t["n"] for t in top2]}
    return out


def _pct(x):
    return "—" if x is None else f"{100 * x:.1f} %"


def weekly_markdown(day: str, stats: dict, params_new: dict | None, start: str | None, n_rep: int) -> str:
    d = datetime.strptime(day, "%Y-%m-%d")
    week = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
    L = [f"# Rapport hebdomadaire bases-engine — {week} (généré le {day})", "",
         f"- Début du protocole : {start or 'non fixé (aucun matin planifié encore)'} · courses notées (T_MATIN, hors répétitions) : **{stats['n']}** · répétitions exclues : {n_rep}",
         f"- Paramètres : {'nouvelle version ' + params_new['version'] + ' (calibrateurs réajustés, seuils et lambdas inchangés)' if params_new else 'inchangés (aucune course notée)'}", ""]
    if stats["n"]:
        L += ["## Échelle des bases (cible publiée)", "", "| 1 base | 2 bases | 3 bases | 4 bases | ≥ 2/3 |", "|---:|---:|---:|---:|---:|",
              f"| {_pct(stats['taux_k1'])} | {_pct(stats['taux_k2'])} | {_pct(stats['taux_k3'])} | {_pct(stats['taux_k4'])} | {_pct(stats['taux_2of3'])} |", "",
              "## Par solidité", "", "| Solidité | n | 3/3 | ≥ 2/3 |", "|---|---:|---:|---:|"]
        L += [f"| {s} | {v['n']} | {_pct(v['taux_3of3'])} | {_pct(v['taux_2of3'])} |" for s, v in stats["par_solidite"].items()]
        L += ["", "## Baselines (3/3, mêmes courses)", "", "| Sélection | n | 3/3 |", "|---|---:|---:|",
              f"| Trio publié | {stats['n']} | {_pct(stats['taux_k3'])} |",
              f"| 3 premiers du moteur | {stats['n']} | {_pct(stats['baseline_moteur_3'])} |",
              f"| 3 plus courtes cotes (MARKET_BASELINE, T_MATIN) | {stats['n_marche']} | {_pct(stats['baseline_marche_3'])} |", "",
              "## Fiabilité de P(3/3) annoncée (recalibrée) vs observée", "", "| Tranche | n | annoncée | observée | écart |", "|---|---:|---:|---:|---:|"]
        L += [f"| {t['tranche']} | {t['n']} | {_pct(t['p_annoncee'])} | {_pct(t['freq_observee'])} | {100 * (t['freq_observee'] - t['p_annoncee']):+.1f} pts |" for t in stats["fiabilite"]]
        cr = stats["criteres"]
        fmt = lambda v: "—" if v is None else ("✅ tenu" if v else "❌ non tenu")
        L += ["", "## Critères du protocole (état courant, informatif jusqu'à l'échéance)", "",
              f"1. Calibration (2 tranches sup., |écart| ≤ 5 pts, n ≥ 60 chacune ; n actuels {cr['n_tranches_sup']}) : {fmt(cr['calibration'])}",
              f"2. Sélectivité (A ≥ 1,8 × C et A ≥ 28 %) : {fmt(cr['selectivite'])}",
              f"3. Non-régression (trio publié ≥ 3 premiers moteur − 2 pts) : {fmt(cr['non_regression'])}"]
    L += ["", "## Rendement des structures de ticket", "", "_Non calculé : le mapping des rapports (`docs/rapports_mapping.md`) n'est pas validé par Steph. Informatif et « non validé » le jour où il le sera._", "",
          "---", "_Aucun chiffre retouché. Les répétitions manuelles antérieures au début du protocole sont exclues._"]
    return "\n".join(L) + "\n"


def run_hebdo(*, day: str | None = None, sha: str | None = None, db_path=config.DB_PATH, recalibrer: bool = True) -> int:
    day = day or _date.today().isoformat()
    run_id = f"hebdo-{day}-{uuid.uuid4().hex[:6]}"
    t0 = time.time()
    con = storage.connect(db_path)
    storage.start_run(con, run_id, "hebdo", None, "hebdo")
    try:
        snap = None
        try:
            snap = get_snapshot(sha)
            con.execute("update runs set snapshot_commit=? where run_id=?", (snap.sha, run_id))
        except FetchError as e:
            notify("alerte", "⚠️ BASES — hebdo sans instantané (baseline marché indisponible)", str(e), date=day)
        rows = _rows(con)
        params = load_params()
        new = recalibrate(con, rows, day, params) if recalibrer else None
        stats = weekly_stats(con, rows, snap)
        n_rep = con.execute("select count(*) from bases_editions where repetition=1").fetchone()[0]
        md = weekly_markdown(day, stats, new, storage.protocol_start_date(con), n_rep)
        d = datetime.strptime(day, "%Y-%m-%d")
        path = config.RAPPORTS_DIR / f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(md, encoding="utf-8")
        if new:
            _append_changelog(day, new["version"], stats["n"])
        notify("hebdo", f"📅 BASES — rapport hebdomadaire {path.stem}", md, date=day)
        storage.finish_run(con, run_id, "OK", races_seen=stats["n"], races_published=0, duration_s=round(time.time() - t0, 1))
        return 0
    except Exception as e:  # noqa: BLE001
        storage.finish_run(con, run_id, "FAILED", error=repr(e), duration_s=round(time.time() - t0, 1))
        alert("arrêt : erreur inattendue dans hebdo", repr(e), date=day)
        raise
    finally:
        con.close()


def _append_changelog(day: str, version: str, n: int) -> None:
    p = config.ROOT / "CHANGELOG.md"
    if not p.exists():
        return
    line = f"\n## {day} — recalibration hebdomadaire automatique\n\n- `params.json` version **{version}** : calibrateurs réajustés par (k, cible) sur {n} courses notées (hors répétitions) ; seuils de solidité et lambdas inchangés. Effet sur les éditions postérieures uniquement.\n"
    p.write_text(p.read_text(encoding="utf-8") + line, encoding="utf-8")
