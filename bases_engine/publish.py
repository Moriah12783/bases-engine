"""Publication (§6) : contrat JSON `bases/AAAA-MM-JJ.json` (annexe B, contract_version 1), site statique
noir et or (mode shadow : racine neutre + contenu sous site/shadow/<jeton>/ ; mode live : racine),
`palmares.json`, `fiabilite.json`, `archive/AAAA-MM.json`. Le palmarès n'est jamais retouché ni filtré."""
from __future__ import annotations

import html
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from . import config, storage
from .scoring import FIAB_BINS
from .util import iso_utc, race_label, race_slug

SITE_DIR = config.SITE_DIR
CONTRACT_VERSION = 1


def _flags(ed: dict) -> dict:
    out = {}
    for f in json.loads(ed.get("flags_json") or "[]"):
        if ":" in f:
            k, v = f.split(":", 1)
            out[k] = v
    return out


def edition_to_course(ed: dict) -> dict:
    lad = json.loads(ed["ladder_json"])
    target = lad["cible"]
    fl = _flags(ed)
    other = "top4" if ed["top_m"] == 5 else "top5"
    stars = fl.get("etoiles")
    return {
        "course_id": ed["race_id"], "slug": ed["race_slug"], "libelle": race_label(ed["race_id"]),
        "depart_utc": None if fl.get("depart_utc") in (None, "None") else fl.get("depart_utc"),
        "depart_affiche": fl.get("depart"), "discipline": fl.get("discipline"),
        "partants": int(fl["partants"]) if fl.get("partants", "").isdigit() else None,
        "pari_cible": fl.get("pari_cible"), "top_m": ed["top_m"],
        "moteur": {"selection_8": json.loads(ed["engine8_json"]), "etoiles": int(stars) if stars and stars.isdigit() else None,
                   "prediction_hash": ed["prediction_hash"], "lock_time_utc": ed["lock_time_utc"]},
        "echelle": {k: {"chevaux": v["chevaux"], "p_brute": round(v["p_brute"], 4), "p_calibree": round(v["p_calibree"], 4),
                        "p_k_moins_1": round(v["p_k_moins_1"], 4)} for k, v in target.items()},
        f"echelle_{other}": {k: {"chevaux": v["chevaux"], "p_brute": round(v["p_brute"], 4), "p_calibree": round(v["p_calibree"], 4),
                                 "p_k_moins_1": round(v["p_k_moins_1"], 4)} for k, v in lad[other].items()},
        "base_des_bases": {"chevaux": target["3"]["chevaux"], "p_calibree_3sur3": round(target["3"]["p_calibree"], 4),
                           "p_calibree_2sur3": round(target["3"]["p_k_moins_1"], 4), "solidite": ed["solidite"]},
        "trios_alternatifs": [{"chevaux": t["chevaux"], "p_brute": round(t["p_brute"], 4)} for t in json.loads(ed["trios_json"])[1:5]],
        "structure_recommandee": _structure(ed["structure_code"], ed["solidite"], ed["top_m"]),
        "drapeaux": [f for f in json.loads(ed.get("flags_json") or "[]") if ":" not in f],
        "edition_id": ed["edition_id"], "snapshot_commit": ed["snapshot_commit"], "params_version": ed["params_version"],
    }


def _structure(code: str, solid: str, top_m: int) -> dict:
    from .params import structure_for
    st = structure_for(solid, top_m)
    st["code"] = code or st["code"]
    return st


def build_day_contract(con, day: str, horizon: str, snapshot_commit: str | None, params: dict, *, mode: str) -> dict:
    eds = storage.editions_for_day(con, day, horizon)
    eds = [e for e in eds if e["mode"] in ("shadow", "live")]
    sha = snapshot_commit or (eds[0]["snapshot_commit"] if eds else None)
    abst = [{"course_id": r["race_id"], "motif": r["motif"]} for r in con.execute(
        "select race_id, motif from abstentions where date=? and horizon=? and snapshot_commit=? order by race_id", (day, horizon, sha or ""))]
    calib = {k: {"n": v.get("n"), "mode": v.get("mode")} for k, v in (params.get("calibration") or {}).items()}
    return {
        "contract_version": CONTRACT_VERSION, "date": day, "mode": mode, "genere_le_utc": iso_utc(),
        "source": {"depot": config.ENGINE_REPO, "commit": sha, "moteur": config.ENGINE_NAME, "horizon": horizon},
        "parametres": {"version": params.get("version"), "lambdas": params.get("lambdas"),
                       "seuils_solidite": params.get("seuils_solidite"), "calibration": calib},
        "courses": [edition_to_course(e) for e in eds],
        "abstentions": abst,
        "avertissement": "Probabilités estimées, palmarès non retouché. Aucun résultat n'est garanti ; jouez de façon responsable.",
    }


# ----------------------------------------------------------------------------
# Palmarès et fiabilité (jamais filtrés)
# ----------------------------------------------------------------------------

def _rates(rows: list[dict]) -> dict:
    n = len(rows)
    out = {"n": n}
    for k in ("k1", "k2", "k3", "k4"):
        hits = sum(r[f"hit_{k}"] or 0 for r in rows)
        out[k] = hits
        out[f"taux_{k}"] = round(hits / n, 4) if n else None
    h = sum(r["hit_2of3"] or 0 for r in rows)
    out["k2of3"] = h
    out["taux_2of3"] = round(h / n, 4) if n else None
    return out


def palmares_and_fiabilite(con, horizon: str = "T_MATIN") -> tuple[dict, dict]:
    rows = [r for r in storage.latest_results(con, horizon)
            if r["ed_mode"] in ("shadow", "live") and r["top_m"] == r["ed_top_m"] and not r["repetition"] and not r["ed_repetition"]]
    depuis = storage.protocol_start_date(con)
    par_jour = defaultdict(list)
    par_sol = defaultdict(list)
    par_m = defaultdict(list)
    for r in rows:
        par_jour[r["date"]].append(r)
        par_sol[r["ed_solidite"] or "?"].append(r)
        par_m[str(r["top_m"])].append(r)
    n_abst = con.execute("select count(*) from abstentions where horizon=? and date >= ?", (horizon, depuis or "9999")).fetchone()[0]
    n_editions = con.execute("select count(*) from bases_editions where horizon=? and superseded_by is null and mode in ('shadow','live') and repetition=0", (horizon,)).fetchone()[0]
    n_rep = con.execute("select count(*) from bases_editions where horizon=? and repetition=1", (horizon,)).fetchone()[0]
    pal = {
        "genere_le_utc": iso_utc(), "horizon": horizon, "depuis": depuis,
        "note": "Compteurs glissants depuis le début du protocole (premier matin planifié). Les répétitions manuelles antérieures sont exclues. Aucun chiffre retouché ni filtré.",
        "repetitions_exclues": n_rep,
        "editions_publiees": n_editions, "abstentions": n_abst, "global": _rates(rows),
        "par_solidite": {s: _rates(v) for s, v in sorted(par_sol.items())},
        "par_cible": {f"top{m}": _rates(v) for m, v in sorted(par_m.items())},
        "par_jour": {d: {**_rates(v), "par_solidite": {s: _rates([x for x in v if (x["ed_solidite"] or "?") == s]) for s in ("A", "B", "C")}} for d, v in sorted(par_jour.items())},
    }
    # Fiabilité : P(3/3) annoncée (recalibrée) vs observée, par tranche, sur la cible publiée
    tranches = []
    for lo, hi in zip(FIAB_BINS[:-1], FIAB_BINS[1:]):
        sel = [r for r in rows if r["p_calibree_k3"] is not None and lo <= r["p_calibree_k3"] < hi]
        if sel:
            tranches.append({"tranche": f"[{lo:.2f},{hi:.2f})", "n": len(sel),
                             "p_annoncee": round(sum(r["p_calibree_k3"] for r in sel) / len(sel), 4),
                             "freq_observee": round(sum(r["hit_k3"] or 0 for r in sel) / len(sel), 4)})
    fiab = {"genere_le_utc": iso_utc(), "horizon": horizon, "k": 3, "n": len(rows), "tranches": tranches,
            "note": "P annoncée = probabilité recalibrée publiée le matin ; fréquence observée sur les courses notées (JSON public, DEFINITIVE + VERIFIEE_PMU)."}
    return pal, fiab


# ----------------------------------------------------------------------------
# Site
# ----------------------------------------------------------------------------

NEUTRAL_HTML = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>Elite Turf — Bases</title>
<style>body{margin:0;background:#0b0b0d;color:#e8e1cf;font-family:Georgia,'Times New Roman',serif;display:flex;min-height:100vh;align-items:center;justify-content:center;text-align:center}
h1{font-weight:400;letter-spacing:.08em;color:#c9a227}p{color:#9a9482}</style></head>
<body><main><h1>ELITE TURF · BASES</h1><p>Service en préparation.</p></main></body></html>
"""

CSS = """:root{--bg:#0b0b0d;--panel:#141416;--line:#2a2a2e;--gold:#c9a227;--gold2:#e6c65a;--ink:#e8e1cf;--mute:#9a9482;--a:#3fae6b;--b:#c9a227;--c:#8a6f6f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:Georgia,'Times New Roman',serif;line-height:1.45}
header{padding:28px 16px 12px;border-bottom:1px solid var(--line);text-align:center}header h1{margin:0;font-weight:400;letter-spacing:.12em;color:var(--gold);font-size:1.5rem}
header p{margin:6px 0 0;color:var(--mute);font-size:.95rem}main{max-width:960px;margin:0 auto;padding:16px}
.meta{color:var(--mute);font-size:.9rem;margin:8px 0 18px}.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:12px 0}
.card h2{margin:0 0 4px;font-size:1.05rem;font-weight:400;color:var(--gold2)}.card .when{color:var(--mute);font-size:.9rem}
.bases{font-size:1.6rem;letter-spacing:.06em;margin:8px 0;color:#fff}.sol{display:inline-block;border:1px solid var(--line);border-radius:6px;padding:2px 8px;font-size:.85rem;margin-left:8px}
.sol.A{color:var(--a);border-color:var(--a)}.sol.B{color:var(--b);border-color:var(--b)}.sol.C{color:var(--c);border-color:var(--c)}
table{width:100%;border-collapse:collapse;font-size:.92rem;margin-top:8px}th,td{padding:5px 6px;text-align:right;border-bottom:1px solid var(--line)}th:first-child,td:first-child{text-align:left}
th{color:var(--mute);font-weight:400}.struct{margin-top:8px;color:var(--gold2)}.abst{color:var(--mute);font-size:.9rem}
footer{color:var(--mute);font-size:.85rem;text-align:center;padding:24px 16px;border-top:1px solid var(--line);margin-top:24px}
.pal{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px}.pal div{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px;text-align:center}
.pal b{display:block;font-size:1.3rem;color:var(--gold2);font-weight:400}.pal span{color:var(--mute);font-size:.82rem}"""


def _pct(x) -> str:
    return "—" if x is None else f"{100 * x:.0f} %"


def render_index(contract: dict, pal: dict, fiab: dict, *, mode: str) -> str:
    d = datetime.strptime(contract["date"], "%Y-%m-%d")
    order = {"A": 0, "B": 1, "C": 2}
    courses = sorted(contract["courses"], key=lambda c: (order.get(c["base_des_bases"]["solidite"], 3), c["depart_utc"] or ""))
    H = [f"<!doctype html><html lang='fr'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
         "<meta name='robots' content='noindex'>" if mode == "shadow" else "",
         f"<title>Elite Turf · Bases · {d:%d/%m/%Y}</title><style>{CSS}</style></head><body>",
         f"<header><h1>ELITE TURF · BASE DES BASES</h1><p>Édition du {d:%d/%m/%Y} · horizon matin · mode {html.escape(mode)}</p></header><main>",
         f"<p class='meta'>Source moteur commit <code>{(contract['source']['commit'] or '')[:10]}</code> · paramètres {html.escape(str(contract['parametres']['version']))} · généré le {contract['genere_le_utc']} · {len(courses)} courses éligibles · {len(contract['abstentions'])} abstentions. Heures en GMT (= Abidjan/Dakar) et Paris.</p>"]
    for c in courses:
        b, e = c["base_des_bases"], c["echelle"]
        H.append(f"<section class='card'><h2>{html.escape(c['libelle'])}</h2><div class='when'>{html.escape(c['depart_affiche'] or '')} · {html.escape(c['pari_cible'] or '')} (top {c['top_m']}) · {c['partants']} partants · {c['moteur']['etoiles'] or '?'}★</div>")
        H.append(f"<div class='bases'>{' - '.join(map(str, b['chevaux']))}<span class='sol {b['solidite']}'>solidité {b['solidite']}</span></div>")
        H.append("<table><tr><th>Échelle</th><th>1 base</th><th>2 bases</th><th>3 bases</th><th>4 bases</th></tr>")
        H.append("<tr><td>Chevaux</td>" + "".join(f"<td>{' - '.join(map(str, e[k]['chevaux']))}</td>" for k in ("1", "2", "3", "4")) + "</tr>")
        H.append("<tr><td>P(tous placés)</td>" + "".join(f"<td>{_pct(e[k]['p_calibree'])}</td>" for k in ("1", "2", "3", "4")) + "</tr>")
        H.append("<tr><td>P(au moins k−1)</td>" + "".join(f"<td>{_pct(e[k]['p_k_moins_1'])}</td>" for k in ("1", "2", "3", "4")) + "</tr></table>")
        H.append(f"<div class='struct'>Structure recommandée : {html.escape(c['structure_recommandee']['texte'])} ({html.escape(c['structure_recommandee']['motif'])})</div></section>")
    if contract["abstentions"]:
        H.append("<p class='abst'>Abstentions : " + ", ".join(f"{html.escape(race_label(a['course_id']))} ({html.escape(a['motif'])})" for a in contract["abstentions"]) + "</p>")
    g = pal.get("global", {})
    H.append(f"<h2 style='font-weight:400;color:var(--gold);margin-top:28px'>Palmarès depuis le {pal.get('depuis') or '—'} (non retouché)</h2>")
    H.append("<div class='pal'>" + "".join(f"<div><b>{_pct(g.get(f'taux_{k}'))}</b><span>{lbl} · n = {g.get('n', 0)}</span></div>" for k, lbl in (("k1", "1 base"), ("k2", "2 bases"), ("k3", "3 bases"), ("k4", "4 bases"), ("2of3", "≥ 2/3")))
             + f"<div><b>{pal.get('abstentions', 0)}</b><span>abstentions</span></div></div>")
    if pal.get("par_solidite"):
        H.append("<table><tr><th>Solidité</th><th>n</th><th>3/3</th><th>≥ 2/3</th></tr>" + "".join(
            f"<tr><td>{html.escape(s)}</td><td>{v['n']}</td><td>{_pct(v['taux_k3'])}</td><td>{_pct(v['taux_2of3'])}</td></tr>" for s, v in pal["par_solidite"].items()) + "</table>")
    if fiab.get("tranches"):
        H.append("<h2 style='font-weight:400;color:var(--gold);margin-top:20px'>Fiabilité de P(3/3) annoncée</h2><table><tr><th>Tranche</th><th>n</th><th>annoncée</th><th>observée</th></tr>"
                 + "".join(f"<tr><td>{t['tranche']}</td><td>{t['n']}</td><td>{_pct(t['p_annoncee'])}</td><td>{_pct(t['freq_observee'])}</td></tr>" for t in fiab["tranches"]) + "</table>")
    H.append(f"</main><footer>{html.escape(contract['avertissement'])}<br>Données : <a href='bases/{contract['date']}.json' style='color:var(--gold)'>bases/{contract['date']}.json</a> · palmares.json · fiabilite.json</footer></body></html>")
    return "\n".join(H)


def write_day_contract(content_dir: Path, contract: dict) -> Path:
    p = content_dir / "bases" / f"{contract['date']}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(contract, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def _archive(content_dir: Path, con, horizon: str = "T_MATIN") -> None:
    months = defaultdict(list)
    for r in con.execute("select distinct date from journal_days where horizon=? and status='OK' order by date", (horizon,)):
        months[r[0][:7]].append(r[0])
    for month, days in months.items():
        out = {"mois": month, "journees": []}
        for d in days:
            p = content_dir / "bases" / f"{d}.json"
            if p.exists():
                c = json.loads(p.read_text(encoding="utf-8"))
                out["journees"].append({"date": d, "commit": c["source"]["commit"], "n_courses": len(c["courses"]), "n_abstentions": len(c["abstentions"]),
                                        "courses": [{"course_id": x["course_id"], "base_des_bases": x["base_des_bases"], "structure": x["structure_recommandee"]["code"]} for x in c["courses"]]})
        (content_dir / "archive").mkdir(parents=True, exist_ok=True)
        (content_dir / "archive" / f"{month}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


def build_site(contract: dict, pal: dict, fiab: dict, *, mode: str, shadow_token: str | None, con, dry_run: bool = False,
               site_dir: Path | None = None) -> str:
    site_dir = site_dir or SITE_DIR
    site_dir.mkdir(parents=True, exist_ok=True)
    if mode == "shadow":
        (site_dir / "index.html").write_text(NEUTRAL_HTML, encoding="utf-8")
        if not shadow_token:
            return "mode ombre sans SHADOW_TOKEN : page neutre seule, contenu ombre non généré"
        content = site_dir / "shadow" / shadow_token
    else:
        content = site_dir
    content.mkdir(parents=True, exist_ok=True)
    write_day_contract(content, contract)
    (content / "index.html").write_text(render_index(contract, pal, fiab, mode=mode), encoding="utf-8")
    (content / "palmares.json").write_text(json.dumps(pal, ensure_ascii=False, indent=1), encoding="utf-8")
    (content / "fiabilite.json").write_text(json.dumps(fiab, ensure_ascii=False, indent=1), encoding="utf-8")
    _archive(content, con)
    where = f"site/shadow/<jeton>/" if mode == "shadow" else "site/"
    return f"{where}index.html, bases/{contract['date']}.json, palmares.json, fiabilite.json" + (" (dry-run : déploiement sauté)" if dry_run else "")
