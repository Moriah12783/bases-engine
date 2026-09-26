"""Comparaison quotidienne entre la porte de publication reconstituée par Bases et ce que le moteur a publié
(décision du mentor du 25/09/2026, point 2).

La porte reconstituée copie la logique d'un autre développeur (propriétaire : développeur Radar) ; elle doit évoluer
après le 06/10/2026. Chaque soir, Bases compare ses verdicts de porte du jour à la publication réelle du moteur.
Au premier écart : annotation « Porte divergente », ligne au journal, incident compté dans l'hebdo (PORTE_DIVERGENTE).

Verdicts de porte (indépendants de l'heure : le moteur décide à T_MATIN) :
  OK · RACE_CANCELLED · ODDS_DEFAULT · NO_T_MATIN — mêmes règles que `eligibility.evaluate_race` en mode matin.
"""
from __future__ import annotations

from pathlib import Path

from . import config
from .eligibility import PRED_COLS, RACE_COLS

# Motif d'abstention de l'éligibilité (mode matin) → verdict de porte ; tout autre motif relève des filtres propres à Bases.
MOTIFS_PORTE = {"NON_PUBLISHABLE:RACE_CANCELLED": "RACE_CANCELLED", "NON_PUBLISHABLE:ODDS_DEFAULT": "ODDS_DEFAULT",
                "CONTRACT:NO_PREDICTION": "NO_T_MATIN"}


def verdict_porte(con, race_id: str) -> str:
    """Verdict de la porte reconstituée pour une course (connexion à la base du moteur, colonnes nommées)."""
    race = con.execute(f"select {RACE_COLS} from races where race_id = ?", (race_id,)).fetchone()
    if race is None:
        return "RACE_UNKNOWN"
    if str(race["status"] or "").upper() == "ANNULEE" or str(race["pmu_statut"] or "").upper() == "COURSE_ANNULEE":
        return "RACE_CANCELLED"
    pred = con.execute(f"select {PRED_COLS} from predictions where race_id = ? and engine_name = ? and horizon = 'T_MATIN'",
                       (race_id, config.ENGINE_NAME)).fetchone()
    if pred is None:
        n_run, n_reel = con.execute("select count(*), sum(coalesce(odds_is_real, 0)) from runners where race_id = ?", (race_id,)).fetchone()
        return "ODDS_DEFAULT" if n_run and not n_reel else "NO_T_MATIN"
    if pred["contract_version"] == config.CONTRACT_VERSION and pred["prediction_hash"] and pred["odds_real"] != 1:
        return "ODDS_DEFAULT"
    return "OK"


def verdicts_du_jour(con, day: str) -> dict[str, str]:
    return {rid: verdict_porte(con, rid) for (rid,) in con.execute(
        "select race_id from races where date = ? order by meeting_number, race_number", (day,))}


def publications_moteur(con, day: str) -> dict[str, bool] | None:
    """Courses du jour réellement publiées par le moteur (race_id → publiée).

    Source à désigner (décision en attente) : la décision de publication du moteur ne figure ni dans la base R2 ni dans
    les JSON publics de résultats, les deux seules sources du contrat de lecture. Tant qu'elle manque : None."""
    return None


def comparer(bases: dict[str, str], moteur: dict[str, bool]) -> list[tuple[str, str, bool | None]]:
    """Écarts : Bases dit OK et le moteur n'a pas publié, ou l'inverse, ou course absente d'un côté."""
    ecarts = []
    for rid in sorted(set(bases) | set(moteur)):
        v, pub = bases.get(rid), moteur.get(rid)
        if v is None or pub is None or (v == "OK") != pub:
            ecarts.append((rid, v or "ABSENTE_DE_LA_BASE", pub))
    return ecarts


# ----------------------------------------------------------------------------
# Test de parité de la porte sur la base réelle (décision du mentor du 25/09/2026, point 1)
# ----------------------------------------------------------------------------

REFERENCE_PARITE = config.ROOT / "fixtures" / "synthetique" / "parite_2026-09-21.json"


def parite(con, reference_path=None) -> tuple[bool, list[str], list[tuple[str, str, str]]]:
    """Rejoue l'éligibilité (mode matin, instant de référence) sur la journée de référence et compare course par course
    aux décisions enregistrées (21/09/2026 : 20 éligibles, 12 abstentions). Retourne (parité, lignes de rapport, écarts)."""
    import json
    from collections import Counter
    from datetime import datetime
    from .eligibility import Abstention, evaluate_race
    import sqlite3
    ref = json.loads(Path(reference_path or REFERENCE_PARITE).read_text(encoding="utf-8"))
    now = datetime.fromisoformat(ref["maintenant_utc"].replace("Z", "+00:00"))
    # Rejeu « à l'instant de référence » : la base est en ajout seul ; une prédiction verrouillée après cet instant n'existait pas
    # pour la passe rejouée. Copie en mémoire sans ces lignes (la base lue n'est jamais modifiée ; aucune logique de porte changée).
    au = sqlite3.connect(":memory:"); con.backup(au); au.row_factory = sqlite3.Row
    borne = now.strftime("%Y-%m-%dT%H:%M:%S")
    posterieures = [tuple(r) for r in au.execute(
        """select p.race_id, p.horizon, p.lock_time_utc from predictions p join races r using(race_id)
           where r.date = ? and p.engine_name = ? and replace(p.lock_time_utc, 'Z', '') > ?""", (ref["date"], config.ENGINE_NAME, borne))]
    au.execute("delete from predictions where replace(lock_time_utc, 'Z', '') > ?", (borne,))
    obtenu = {}
    for (rid,) in au.execute("select race_id from races where date = ? order by race_id", (ref["date"],)):
        ev = evaluate_race(au, rid, ref["horizon"], mode="matin", now=now)
        obtenu[rid] = ev.motif if isinstance(ev, Abstention) else "ELIGIBLE"
    au.close()
    attendu = ref["decisions"]
    # Sans T_MATIN à l'instant de référence, « cotes par défaut » et « pas d'édition T_MATIN » sont la même décision de porte
    # (pas d'édition) : seul le drapeau de cote des partants, mis à jour dans la journée (table non « ajout seul »), les distingue.
    sans_t_matin = {"NON_PUBLISHABLE:ODDS_DEFAULT", "CONTRACT:NO_PREDICTION"}
    equivalents = [rid for rid in sorted(set(attendu) & set(obtenu))
                   if attendu[rid] != obtenu[rid] and {attendu[rid], obtenu[rid]} <= sans_t_matin]
    ecarts = [(rid, attendu.get(rid, "ABSENTE"), obtenu.get(rid, "ABSENTE")) for rid in sorted(set(attendu) | set(obtenu))
              if attendu.get(rid) != obtenu.get(rid) and rid not in equivalents]
    ca, co = Counter(attendu.values()), Counter(obtenu.values())
    lignes = [f"Journée de référence {ref['date']} à {ref['maintenant_utc']} ({ref['horizon']}) : "
              f"attendu {ca.get('ELIGIBLE', 0)} éligibles / {sum(ca.values()) - ca.get('ELIGIBLE', 0)} abstentions, "
              f"obtenu {co.get('ELIGIBLE', 0)} / {sum(co.values()) - co.get('ELIGIBLE', 0)}",
              "Parité : " + ("✅ identique course par course" if not ecarts else f"⛔ {len(ecarts)} écart(s)")]
    if equivalents:
        lignes.append(f"Motif équivalent (pas de T_MATIN à l'instant de référence ; cotes des partants mises à jour depuis) : {', '.join(equivalents)}")
    t_matin_post = [x for x in posterieures if x[1] == ref["horizon"]]
    lignes.append(f"Prédictions du moteur verrouillées après l'instant de référence (écartées du rejeu) : {len(posterieures)}"
                  + (f", dont {len(t_matin_post)} {ref['horizon']} : " + ", ".join(f"{r} ({l})" for r, _, l in t_matin_post[:10]) if t_matin_post else ""))
    for rid, a, o in ecarts[:20]:
        pr = con.execute("select lock_time_utc, odds_real, priced_ratio from predictions where race_id=? and engine_name=? and horizon=?",
                         (rid, config.ENGINE_NAME, ref["horizon"])).fetchone()
        n_run, n_reel = con.execute("select count(*), sum(coalesce(odds_is_real, 0)) from runners where race_id=?", (rid,)).fetchone()
        lignes.append(f"  {rid} : attendu {a}, obtenu {o} · {ref['horizon']} "
                      + (f"verrou {pr['lock_time_utc']}, odds_real {pr['odds_real']}, priced_ratio {pr['priced_ratio']}" if pr else "absente")
                      + f" · partants à cote réelle {n_reel or 0}/{n_run}")
    return not ecarts, lignes, ecarts

