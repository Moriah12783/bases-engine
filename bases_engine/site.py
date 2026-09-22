"""Site statique (sprint 4) : page du jour avec lignes dépliables et résultats, pages par journée, archives mensuelles,
palmarès, navigation par dates, recherche (mini-script inline facultatif). Tout sous le chemin ombre en mode shadow.

Aucun calcul ici : lecture de bases.db, rendu HTML. Le palmarès ne compte que DEFINITIVE + VERIFIEE_PMU."""
from __future__ import annotations

import html
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from . import config, storage
from .publish import (NEUTRAL_HTML, _archive, build_day_contract, palmares_and_fiabilite, race_label, sort_courses,
                      write_day_contract)
from .util import iso_utc

CSS = """:root{--bg:#0b0b0d;--panel:#141416;--line:#2a2a2e;--gold:#c9a227;--gold2:#e6c65a;--ink:#e8e1cf;--mute:#9a9482;--a:#3fae6b;--b:#c9a227;--c:#8a6f6f;--ok:#3fae6b;--ko:#b05555}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:Georgia,'Times New Roman',serif;line-height:1.45}
header{padding:24px 16px 10px;border-bottom:1px solid var(--line);text-align:center}header h1{margin:0;font-weight:400;letter-spacing:.12em;color:var(--gold);font-size:1.5rem}
header p{margin:6px 0 0;color:var(--mute);font-size:.95rem}main{max-width:960px;margin:0 auto;padding:16px}
a{color:var(--gold)}.meta{color:var(--mute);font-size:.9rem;margin:8px 0 12px}
.legende{color:var(--mute);font-size:.86rem;border-left:2px solid var(--gold);padding-left:10px;margin:0 0 14px}
nav.dates{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 14px}nav.dates a,nav.dates span{display:inline-block;border:1px solid var(--line);border-radius:14px;padding:3px 10px;font-size:.84rem;color:var(--ink);text-decoration:none;background:var(--panel)}
nav.dates a.cur{border-color:var(--gold);color:var(--gold2)}nav.dates small{color:var(--mute)}
.compteur{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:10px 0 16px}.compteur div{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px;text-align:center}
.compteur b{display:block;font-size:1.25rem;color:var(--gold2);font-weight:400}.compteur span{color:var(--mute);font-size:.82rem}
.recherche{width:100%;background:var(--panel);border:1px solid var(--line);border-radius:8px;color:var(--ink);padding:8px 10px;font-family:inherit;font-size:.95rem;margin:0 0 12px}
details.course{background:var(--panel);border:1px solid var(--line);border-radius:10px;margin:8px 0}details.course[open]{border-color:#3a3a40}
summary{list-style:none;cursor:pointer;padding:10px 14px;display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center}summary::-webkit-details-marker{display:none}
summary .lib{color:var(--gold2);min-width:150px}summary .h{color:var(--mute);font-size:.9rem}summary .bases{font-size:1.15rem;letter-spacing:.05em;color:#fff}
summary .struct{color:var(--mute);font-size:.88rem}summary .res{margin-left:auto;font-size:.9rem;border:1px solid var(--line);border-radius:6px;padding:1px 8px}
.res.ok{color:var(--ok);border-color:var(--ok)}.res.ko{color:var(--ko);border-color:var(--ko)}.res.att{color:var(--mute)}.res.prov{color:var(--gold2);border-color:var(--gold)}
.sol{display:inline-block;border:1px solid var(--line);border-radius:6px;padding:1px 8px;font-size:.82rem}.sol.A{color:var(--a);border-color:var(--a)}.sol.B{color:var(--b);border-color:var(--b)}.sol.C{color:var(--c);border-color:var(--c)}
.pin{display:inline-block;background:var(--gold);color:#0b0b0d;border-radius:6px;padding:1px 8px;font-size:.76rem}
.fiche{padding:0 14px 14px;border-top:1px solid var(--line)}.fiche .sel{color:var(--mute);font-size:.92rem}.fiche .when{color:var(--mute);font-size:.9rem;margin-top:8px}
table{width:100%;border-collapse:collapse;font-size:.92rem;margin-top:8px}th,td{padding:5px 6px;text-align:right;border-bottom:1px solid var(--line)}th:first-child,td:first-child{text-align:left}th{color:var(--mute);font-weight:400}
.structure{margin-top:8px;color:var(--gold2)}.resultat{margin-top:10px;padding:10px;border:1px dashed var(--line);border-radius:8px}.resultat h3{margin:0 0 6px;font-size:.95rem;font-weight:400;color:var(--gold)}
.resultat ul{margin:4px 0 0 18px;padding:0}.resultat li{margin:2px 0}
h2.sec{font-weight:400;color:var(--gold);margin-top:28px;font-size:1.1rem}footer{color:var(--mute);font-size:.85rem;text-align:center;padding:24px 16px;border-top:1px solid var(--line);margin-top:24px}
.pal{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px}.pal div{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px;text-align:center}
.pal b{display:block;font-size:1.3rem;color:var(--gold2);font-weight:400}.pal span{color:var(--mute);font-size:.82rem}"""

SEARCH_JS = """<script>(function(){var i=document.getElementById('q');if(!i)return;i.addEventListener('input',function(){var q=i.value.toLowerCase().trim();
document.querySelectorAll('details.course').forEach(function(d){d.style.display=(!q||(d.dataset.search||'').indexOf(q)>=0)?'':'none';});});})();</script>"""

LEGENDE = ("Tous à l'arrivée = les chevaux indiqués finissent tous dans les 4 (ou 5) premiers ; Tous sauf un = un seul d'entre eux peut manquer. "
           "Pourcentages estimés, recalibrés sur l'historique. Solidité : A = tiers supérieur des probabilités du trio, B = tiers médian, "
           "C = tiers inférieur (abstention sur bases fixes). Résultats : « provisoire » tant que le PMU n'a pas déclaré l'arrivée définitive ; "
           "le palmarès ne compte que les arrivées définitives vérifiées. Mode shadow : édition d'essai non diffusée aux abonnés.")


def _pct(x) -> str:
    return "—" if x is None else f"{100 * x:.0f} %"


def _fr(day: str) -> str:
    return datetime.strptime(day, "%Y-%m-%d").strftime("%d/%m/%Y")


# ----------------------------------------------------------------------------
# Résultat d'une course (affichage)
# ----------------------------------------------------------------------------

def resultat_course(course: dict, res: dict | None, statut: dict | None) -> dict:
    """Verdict lisible : badge court pour la ligne, bloc détaillé pour la fiche."""
    m = course["top_m"]
    if statut and (statut.get("annulee") or statut.get("statut") == "ANNULEE"):
        return {"badge": "annulée", "classe": "att", "bloc": None, "compte": False}
    if not res:
        code = (statut or {}).get("statut") or "EN_ATTENTE"
        return {"badge": "en attente" if code in ("EN_ATTENTE", None) else code.lower(), "classe": "att", "bloc": None, "compte": False}
    hits = json.loads(res.get("hits_json") or "{}")
    n3 = hits.get("n_in_k3", 0)
    prov = res.get("statut") == "PROVISOIRE"
    badge = ("3/3 ✓" if n3 == 3 else f"{n3}/3") + (" (provisoire)" if prov else "")
    classe = "prov" if prov else ("ok" if n3 == 3 else "ko")
    arrivee = json.loads(res.get("arrivee_json") or "[]")
    placed = set(arrivee[:m])
    verdicts = []
    for k in ("1", "2", "3", "4"):
        chevaux = course["echelle"][k]["chevaux"]
        n_in = len(set(chevaux) & placed)
        verdicts.append(f"{k} base{'s' if k != '1' else ''} ({' - '.join(map(str, chevaux))}) : {n_in} sur {k} à l'arrivée")
    st = course["structure_recommandee"]
    if st.get("code") == "ABSTENTION" or not st.get("bases"):
        v_struct = "abstention sur bases fixes : pas de verdict"
    else:
        cible = st.get("cible_affichee") or m
        placed_s = set(arrivee[:cible])
        n_in = len(set(st["bases"]) & placed_s)
        v_struct = (f"{st['texte']} → " + ("réussie" if n_in == len(st["bases"]) else "manquée") + f" ({n_in} sur {len(st['bases'])} bases dans les {cible} premiers)")
    return {"badge": badge, "classe": classe, "compte": not prov,
            "bloc": {"arrivee": arrivee[:m], "statut": (res.get("statut") or "") + (f" · {statut.get('pmu_statut')}" if statut and statut.get("pmu_statut") else ""),
                     "finalite": res.get("finalite"), "verdicts": verdicts, "structure": v_struct,
                     "non_partants": json.loads(res.get("non_partants_json") or "[]")}}


# ----------------------------------------------------------------------------
# Rendu d'une journée
# ----------------------------------------------------------------------------

def _card_body(c: dict, r: dict) -> str:
    b, e, st = c["base_des_bases"], c["echelle"], c["structure_recommandee"]
    H = [f"<div class='fiche'><div class='when'>{html.escape(c['depart_affiche'] or '')} · {html.escape(c['paris_libelle'])} · {c['partants']} partants · {c['moteur']['etoiles'] or '?'}★ · cible top {c['top_m']}</div>",
         f"<div class='sel'>Sélection moteur : {' - '.join(map(str, c['moteur']['selection_8']))}</div>"]
    if c.get("associes"):
        H.append(f"<div class='sel'>Associés : {' - '.join(map(str, c['associes']))}</div>")
    H.append("<table><tr><th>Échelle</th><th>1 base</th><th>2 bases</th><th>3 bases</th><th>4 bases</th></tr>")
    H.append("<tr><td>Chevaux</td>" + "".join(f"<td>{' - '.join(map(str, e[k]['chevaux']))}</td>" for k in ("1", "2", "3", "4")) + "</tr>")
    H.append("<tr><td>Tous à l'arrivée</td>" + "".join(f"<td>{_pct(e[k]['p_calibree'])} ({k} sur {k})</td>" for k in ("1", "2", "3", "4")) + "</tr>")
    H.append("<tr><td>Tous sauf un</td><td>—</td>" + "".join(f"<td>{_pct(e[k]['p_k_moins_1'])} ({int(k) - 1} sur {k})</td>" for k in ("2", "3", "4")) + "</tr></table>")
    if c.get("echelle_top3"):
        e3 = c["echelle_top3"]
        H.append("<div class='sel' style='margin-top:6px'>Échelle cible top 3 (Trio / Couplé placé, brute) : " + " · ".join(f"{k} base{'s' if k != '1' else ''} {' - '.join(map(str, e3[k]['chevaux']))} {_pct(e3[k]['p_brute'])}" for k in ("1", "2", "3")) + "</div>")
    H.append(f"<div class='structure'>Structure recommandée : {html.escape(st['texte'])} ({html.escape(st['motif'])}{', pari ' + html.escape(st['pari']) if st.get('pari') else ''})</div>")
    if r["bloc"]:
        bl = r["bloc"]
        H.append(f"<div class='resultat'><h3>Résultat — {html.escape(bl['statut'])}{' · ' + html.escape(bl['finalite']) if bl.get('finalite') else ''}</h3>")
        H.append(f"<div>Arrivée (top {c['top_m']}) : <b>{' - '.join(map(str, bl['arrivee'])) or '—'}</b>" + (f" · non-partants : {' - '.join(map(str, bl['non_partants']))}" if bl["non_partants"] else "") + "</div>")
        H.append("<ul>" + "".join(f"<li>{html.escape(v)}</li>" for v in bl["verdicts"]) + "</ul>")
        H.append(f"<div style='margin-top:6px;color:var(--gold2)'>Structure recommandée : {html.escape(bl['structure'])}</div></div>")
    H.append("</div>")
    return "".join(H)


def render_day_page(day: str, contract: dict, results: dict, statuts: dict, nav: list[dict], *, mode: str, root: str) -> str:
    """`root` = préfixe relatif vers la racine du contenu ('' pour index.html, '../' pour jours/*.html)."""
    courses = sort_courses(contract["courses"])
    n_notees = n_3 = n_2 = n_prov = 0
    lines = []
    for c in courses:
        r = resultat_course(c, results.get(c["course_id"]), statuts.get(c["course_id"]))
        if r["bloc"]:
            n_notees += 1
            n3 = json.loads(results[c["course_id"]].get("hits_json") or "{}").get("n_in_k3", 0)
            n_3 += int(n3 == 3); n_2 += int(n3 >= 2); n_prov += int(not r["compte"])
        b, st = c["base_des_bases"], c["structure_recommandee"]
        pin = "<span class='pin'>Quinté+</span>" if "QUINTE_PLUS" in (c.get("paris_offerts") or []) else ""
        search = html.escape(" ".join(str(x) for x in (c["libelle"], c["course_id"], c["paris_libelle"], b["solidite"], st["texte"])).lower(), quote=True)
        lines.append(f"<details class='course' data-search=\"{search}\"><summary>{pin}<span class='lib'>{html.escape(c['libelle'])}</span>"
                     f"<span class='h'>{html.escape(c['depart_affiche'] or '')}</span><span class='h'>{html.escape(st.get('pari') or c['paris_libelle'])}</span>"
                     f"<span class='bases'>{' - '.join(map(str, b['chevaux']))}</span><span class='sol {b['solidite']}'>solidité {b['solidite']}</span>"
                     f"<span class='struct'>{html.escape(st['texte'].split(' · ')[0].split(' : ')[-1])}</span><span class='res {r['classe']}'>{html.escape(r['badge'])}</span></summary>"
                     + _card_body(c, r) + "</details>")
    H = ["<!doctype html><html lang='fr'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
         "<meta name='robots' content='noindex'>" if mode == "shadow" else "",
         f"<title>Elite Turf · Bases · {_fr(day)}</title><style>{CSS}</style></head><body>",
         f"<header><h1>ELITE TURF · BASE DES BASES</h1><p>Édition du {_fr(day)} · horizon matin · mode {html.escape(mode)}</p></header><main>",
         f"<p class='legende'>{LEGENDE}</p>",
         _nav_html(nav, day, root),
         f"<div class='compteur'><div><b>{n_3}</b><span>3/3 réussis sur {n_notees} notées</span></div><div><b>{n_2}</b><span>≥ 2/3 sur {n_notees} notées</span></div>"
         f"<div><b>{len(courses)}</b><span>courses éligibles</span></div><div><b>{len(contract['abstentions'])}</b><span>abstentions</span></div>"
         + (f"<div><b>{n_prov}</b><span>provisoires</span></div>" if n_prov else "") + "</div>",
         f"<p class='meta'>Source moteur commit <code>{(contract['source']['commit'] or '')[:10]}</code> · paramètres {html.escape(str(contract['parametres']['version']))} · généré le {contract['genere_le_utc']} · heures en GMT (= Abidjan/Dakar) et Paris.</p>",
         "<input class='recherche' id='q' type='search' placeholder='Rechercher un hippodrome, une réunion (R1), un numéro (C3)…' aria-label='Recherche'>"]
    H += lines or ["<p class='meta'>Aucune course éligible ce jour.</p>"]
    if contract["abstentions"]:
        H.append("<h2 class='sec'>Abstentions du jour</h2><table><tr><th>Course</th><th style='text-align:left'>Motif</th></tr>"
                 + "".join(f"<tr><td>{html.escape(race_label(a['course_id']))}</td><td style='text-align:left'>{html.escape(a.get('motif_libelle') or a['motif'])}</td></tr>" for a in contract["abstentions"]) + "</table>")
    H.append(f"</main><footer>{html.escape(contract['avertissement'])}<br><a href='{root}palmares.html'>Palmarès</a> · <a href='{root}archive/{day[:7]}.html'>Archive {day[:7]}</a> · "
             f"<a href='{root}bases/{day}.json'>bases/{day}.json</a> · <a href='{root}palmares.json'>palmares.json</a> · <a href='{root}fiabilite.json'>fiabilite.json</a></footer>{SEARCH_JS}</body></html>")
    return "\n".join(H)


def _nav_html(nav: list[dict], current: str, root: str) -> str:
    items = []
    for n in nav:
        lbl = {0: "aujourd'hui", 1: "hier"}.get(n["delta"], _fr(n["date"])[:5])
        cls = " class='cur'" if n["date"] == current else ""
        if n["n"]:
            items.append(f"<a{cls} href='{root}jours/{n['date']}.html'>{lbl} <small>({n['n']})</small></a>")
        else:
            items.append(f"<span>{lbl} <small>(0)</small></span>")
    return "<nav class='dates'>" + "".join(items) + f"<a href='{root}palmares.html'>palmarès</a></nav>"


def build_nav(con, today: str, days: int = 14) -> list[dict]:
    counts = {r[0]: r[1] for r in con.execute("select date, count(*) from bases_editions where horizon='T_MATIN' and mode in ('shadow','live') and superseded_by is null group by 1")}
    d0 = datetime.strptime(today, "%Y-%m-%d")
    return [{"date": (d0 - timedelta(days=i)).strftime("%Y-%m-%d"), "delta": i, "n": counts.get((d0 - timedelta(days=i)).strftime("%Y-%m-%d"), 0)} for i in range(days)]


# ----------------------------------------------------------------------------
# Archives mensuelles et palmarès
# ----------------------------------------------------------------------------

def render_month_page(month: str, days: list[dict], *, mode: str) -> str:
    rows = "".join(f"<tr><td><a href='../jours/{d['date']}.html'>{_fr(d['date'])}</a></td><td>{d['n']}</td><td>{d['notees']}</td><td>{d['k3']}</td><td>{d['k2']}</td></tr>" for d in days)
    return (f"<!doctype html><html lang='fr'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>{'<meta name=robots content=noindex>' if mode == 'shadow' else ''}"
            f"<title>Elite Turf · Bases · archive {month}</title><style>{CSS}</style></head><body><header><h1>ELITE TURF · BASE DES BASES</h1><p>Archive {month} · mode {html.escape(mode)}</p></header><main>"
            f"<p class='meta'><a href='../index.html'>← édition du jour</a> · <a href='../palmares.html'>palmarès</a></p>"
            f"<table><tr><th>Journée</th><th>Courses</th><th>Notées (définitives)</th><th>3/3</th><th>≥ 2/3</th></tr>{rows or '<tr><td colspan=5>aucune journée</td></tr>'}</table>"
            f"</main><footer>Aucun chiffre retouché.</footer></body></html>")


def render_palmares_page(pal: dict, fiab: dict, *, mode: str) -> str:
    g = pal.get("global", {})
    H = [f"<!doctype html><html lang='fr'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>{'<meta name=robots content=noindex>' if mode == 'shadow' else ''}",
         f"<title>Elite Turf · Bases · palmarès</title><style>{CSS}</style></head><body><header><h1>ELITE TURF · BASE DES BASES</h1><p>Palmarès depuis le {pal.get('depuis') or '—'} · mode {html.escape(mode)} · non retouché</p></header><main>",
         "<p class='meta'><a href='index.html'>← édition du jour</a></p>",
         f"<p class='legende'>Compteurs depuis le début du protocole, arrivées définitives vérifiées uniquement. Répétitions manuelles exclues : {pal.get('repetitions_exclues', 0)} édition(s). Abstentions comptées : {pal.get('abstentions', 0)}.</p>",
         "<h2 class='sec'>Par barreau</h2><div class='pal'>" + "".join(f"<div><b>{_pct(g.get(f'taux_{k}'))}</b><span>{lbl} · n = {g.get('n', 0)}</span></div>" for k, lbl in (("k1", "1 base"), ("k2", "2 bases"), ("k3", "3 bases"), ("k4", "4 bases"), ("2of3", "≥ 2/3"))) + "</div>",
         "<h2 class='sec'>Par solidité</h2><table><tr><th>Solidité</th><th>n</th><th>1 base</th><th>2 bases</th><th>3 bases</th><th>4 bases</th><th>≥ 2/3</th></tr>"
         + "".join(f"<tr><td>{html.escape(s)}</td><td>{v['n']}</td><td>{_pct(v['taux_k1'])}</td><td>{_pct(v['taux_k2'])}</td><td>{_pct(v['taux_k3'])}</td><td>{_pct(v['taux_k4'])}</td><td>{_pct(v['taux_2of3'])}</td></tr>" for s, v in (pal.get("par_solidite") or {}).items()) + "</table>",
         "<h2 class='sec'>Par cible</h2><table><tr><th>Cible</th><th>n</th><th>3 bases</th><th>≥ 2/3</th></tr>"
         + "".join(f"<tr><td>{html.escape(s)}</td><td>{v['n']}</td><td>{_pct(v['taux_k3'])}</td><td>{_pct(v['taux_2of3'])}</td></tr>" for s, v in (pal.get("par_cible") or {}).items()) + "</table>"]
    if fiab.get("tranches"):
        H.append("<h2 class='sec'>Fiabilité de la probabilité annoncée (3 bases)</h2><table><tr><th>Tranche</th><th>n</th><th>annoncée</th><th>observée</th></tr>"
                 + "".join(f"<tr><td>{t['tranche']}</td><td>{t['n']}</td><td>{_pct(t['p_annoncee'])}</td><td>{_pct(t['freq_observee'])}</td></tr>" for t in fiab["tranches"]) + "</table>")
    if pal.get("par_jour"):
        H.append("<h2 class='sec'>Par journée</h2><table><tr><th>Journée</th><th>n</th><th>3/3</th><th>≥ 2/3</th></tr>"
                 + "".join(f"<tr><td><a href='jours/{d}.html'>{_fr(d)}</a></td><td>{v['n']}</td><td>{v['k3']}</td><td>{v['k2of3']}</td></tr>" for d, v in sorted(pal["par_jour"].items(), reverse=True)) + "</table>")
    H.append("</main><footer>Aucun chiffre retouché ni filtré. <a href='palmares.json'>palmares.json</a> · <a href='fiabilite.json'>fiabilite.json</a></footer></body></html>")
    return "\n".join(H)


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------

def build_site(con, day: str, params: dict, *, mode: str, shadow_token: str | None, dry_run: bool = False, site_dir: Path | None = None) -> str:
    """Régénère tout le contenu : index (dernière journée publiée), jours/*.html, archive/*.html, palmares.html, JSON."""
    site_dir = site_dir or config.SITE_DIR
    site_dir.mkdir(parents=True, exist_ok=True)
    if mode == "shadow":
        (site_dir / "index.html").write_text(NEUTRAL_HTML, encoding="utf-8")
        if not shadow_token:
            return "mode ombre sans SHADOW_TOKEN : page neutre seule, contenu ombre non généré"
        content = site_dir / "shadow" / shadow_token
    else:
        content = site_dir
    (content / "jours").mkdir(parents=True, exist_ok=True)
    (content / "archive").mkdir(parents=True, exist_ok=True)
    pal, fiab = palmares_and_fiabilite(con)
    days = [r[0] for r in con.execute("select distinct date from bases_editions where horizon='T_MATIN' and mode in ('shadow','live') order by date")]
    if day not in days:
        days.append(day)
    per_month = defaultdict(list)
    nav = build_nav(con, day)                      # mêmes pastilles sur toutes les pages : aujourd'hui, hier, 14 jours
    for d in sorted(days):
        contract = build_day_contract(con, d, "T_MATIN", None, params, mode=mode)
        write_day_contract(content, contract)
        results = storage.display_results_for_day(con, d)
        statuts = storage.course_statuts_for_day(con, d)
        (content / "jours" / f"{d}.html").write_text(render_day_page(d, contract, results, statuts, nav, mode=mode, root="../"), encoding="utf-8")
        notees = [r for r in results.values() if r.get("statut") == "DEFINITIVE"]
        per_month[d[:7]].append({"date": d, "n": len(contract["courses"]), "notees": len(notees),
                                 "k3": sum(r["hit_k3"] or 0 for r in notees), "k2": sum(r["hit_2of3"] or 0 for r in notees)})
        if d == day:
            (content / "index.html").write_text(render_day_page(d, contract, results, statuts, nav, mode=mode, root=""), encoding="utf-8")
    for month, rows in per_month.items():
        (content / "archive" / f"{month}.html").write_text(render_month_page(month, sorted(rows, key=lambda x: x["date"], reverse=True), mode=mode), encoding="utf-8")
    (content / "palmares.html").write_text(render_palmares_page(pal, fiab, mode=mode), encoding="utf-8")
    (content / "palmares.json").write_text(json.dumps(pal, ensure_ascii=False, indent=1), encoding="utf-8")
    (content / "fiabilite.json").write_text(json.dumps(fiab, ensure_ascii=False, indent=1), encoding="utf-8")
    _archive(content, con)
    where = "site/shadow/<jeton>/" if mode == "shadow" else "site/"
    return f"{where}index.html, jours/{day}.html, archive/{day[:7]}.html, palmares.html, bases/{day}.json" + (" (dry-run : déploiement sauté)" if dry_run else "")
