"""Rapports Markdown (sprint 1 : back-test ; sprint 3 : hebdomadaire)."""
from __future__ import annotations


def _pct(x) -> str:
    return "—" if x is None else f"{100 * x:.1f} %"


def _fiab_table(rows: list[dict]) -> str:
    if not rows:
        return "_aucune donnée_\n"
    out = ["| Tranche P annoncée | n | P annoncée moy. | Fréquence observée | Écart |", "|---|---:|---:|---:|---:|"]
    for r in rows:
        out.append(f"| {r['tranche']} | {r['n']} | {_pct(r['p_annoncee'])} | {_pct(r['freq_observee'])} | {100 * (r['freq_observee'] - r['p_annoncee']):+.1f} pts |")
    return "\n".join(out) + "\n"


def backtest_markdown(bt: dict) -> str:
    L = []
    L.append(f"# Back-test bases-engine — horizon {bt['horizon']} — depuis {bt['since']}" + (f" jusqu'au {bt['until']}" if bt.get("until") else ""))
    L.append("")
    L.append(f"- Instantané moteur : commit `{bt['snapshot_commit']}`")
    L.append(f"- Courses notées : **{bt['n_courses']}**" + (f" ({bt['dates'][0]} → {bt['dates'][1]})" if bt.get("dates") else "") + f" · dont cible Quinté+ (m = 5) : {bt['n_cible_quinte']}")
    L.append(f"- Lambdas : {bt['lambdas']} · simulations par course : {bt['n_sims']} · durée : {bt['duree_s']} s")
    L.append(f"- Courses écartées : " + ", ".join(f"{k} = {v}" for k, v in sorted(bt["abstentions"].items())) if bt["abstentions"] else "- Courses écartées : aucune")
    L.append("")
    L.append("Notation sur `race_results` de l'instantané (DEFINITIVE + VERIFIEE_PMU), non-partants jamais placés. "
             "Toutes les courses du back-test étant passées, la porte `publishable` n'est pas appliquée (rétrospectif) ; "
             "les lignes antérieures au contrat v2 portent le drapeau `LEGACY_CONTRACT`.")
    L.append("")
    for m in (5, 4):
        a = bt["par_cible"][m]
        if not a.get("n"):
            continue
        L.append(f"## Cible top {m} ({'Quinté+' if m == 5 else 'Quarté / Multi'}) — n = {a['n']}")
        L.append("")
        L.append("### Échelle des bases (taux de réussite k/k)")
        L.append("")
        L.append("| k | 1 base | 2 bases | 3 bases | 4 bases | ≥ 2/3 |")
        L.append("|---|---:|---:|---:|---:|---:|")
        L.append(f"| taux observé | {_pct(a['taux_k1'])} | {_pct(a['taux_k2'])} | {_pct(a['taux_k3'])} | {_pct(a['taux_k4'])} | {_pct(a['taux_2of3'])} |")
        L.append("")
        L.append("### Baselines (3/3 dans le top " + str(m) + ")")
        L.append("")
        L.append("| Sélection | n | 3/3 |")
        L.append("|---|---:|---:|")
        L.append(f"| Trio joint (échelle k = 3) | {a['n']} | {_pct(a['taux_k3'])} |")
        L.append(f"| 3 premiers du moteur | {a['n']} | {_pct(a['baseline_moteur_3'])} |")
        L.append(f"| 3 plus courtes cotes (MARKET_BASELINE) | {a['n_marche']} | {_pct(a['baseline_marche_3'])} |")
        L.append("")
        L.append(f"Trio joint identique aux 3 premiers du moteur : {_pct(a['trio_identique_moteur'])} des courses.")
        L.append("")
        L.append(f"### Fiabilité P(3/3) brute — annoncée moy. {_pct(a['p3_annoncee_moy'])} vs observée {_pct(a['p3_observee_moy'])}")
        L.append("")
        L.append(_fiab_table(a["fiabilite_brute_k3"]))
        c3 = a["calibration"]["k3_m%d" % m]
        L.append(f"### Fiabilité P(3/3) recalibrée, hors échantillon (calibrateur ajusté sur les {c3['n_fit_oos']} premières courses, mode `{c3['oos_mode']}`, évalué sur les suivantes)")
        L.append("")
        L.append(_fiab_table(c3["fiabilite_recalibree_oos"]))
        L.append(f"### Fiabilité P(3/3) recalibrée, en échantillon (calibrateur complet, mode `{c3['mode']}`, n = {c3['n']})")
        L.append("")
        L.append(_fiab_table(c3["fiabilite_recalibree_in_sample"]))
        s = a["seuils_solidite"]
        L.append(f"### Terciles de P(3/3) recalibrée → seuils de solidité : A ≥ {s['A']:.4f} · B ≥ {s['B']:.4f}")
        L.append("")
        L.append("| Solidité | n | 3/3 | ≥ 2/3 |")
        L.append("|---|---:|---:|---:|")
        for k in ("A", "B", "C"):
            b = a["par_solidite"][k]
            L.append(f"| {k} | {b['n']} | {_pct(b['taux_3of3'])} | {_pct(b['taux_2of3'])} |")
        L.append("")
        L.append("### Par taille de peloton (partants actifs)")
        L.append("")
        L.append("| Peloton | n | 3/3 | ≥ 2/3 |")
        L.append("|---|---:|---:|---:|")
        for k, b in a["par_peloton"].items():
            L.append(f"| {k} | {b['n']} | {_pct(b['taux_3of3'])} | {_pct(b['taux_2of3'])} |")
        L.append("")
        L.append("### Par étoiles de confiance du moteur")
        L.append("")
        L.append("| Étoiles | n | 3/3 | ≥ 2/3 |")
        L.append("|---|---:|---:|---:|")
        for k, b in a["par_etoiles"].items():
            L.append(f"| {k} | {b['n']} | {_pct(b['taux_3of3'])} | {_pct(b['taux_2of3'])} |")
        L.append("")
        L.append("### Par contrat de la prédiction")
        L.append("")
        L.append("| Contrat | n | 3/3 | ≥ 2/3 |")
        L.append("|---|---:|---:|---:|")
        for k, b in a["par_contrat"].items():
            L.append(f"| {k} | {b['n']} | {_pct(b['taux_3of3'])} | {_pct(b['taux_2of3'])} |")
        L.append("")
    L.append("---")
    L.append("_Aucun chiffre retouché. Rendements non calculés (mapping `rapports` non validé, cf. §3.2 du brief)._")
    return "\n".join(L) + "\n"
