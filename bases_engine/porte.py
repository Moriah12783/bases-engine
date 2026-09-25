"""Comparaison quotidienne entre la porte de publication reconstituée par Bases et ce que le moteur a publié
(décision du mentor du 25/09/2026, point 2).

La porte reconstituée copie la logique d'un autre développeur (propriétaire : développeur Radar) ; elle doit évoluer
après le 06/10/2026. Chaque soir, Bases compare ses verdicts de porte du jour à la publication réelle du moteur.
Au premier écart : annotation « Porte divergente », ligne au journal, incident compté dans l'hebdo (PORTE_DIVERGENTE).

Verdicts de porte (indépendants de l'heure : le moteur décide à T_MATIN) :
  OK · RACE_CANCELLED · ODDS_DEFAULT · NO_T_MATIN — mêmes règles que `eligibility.evaluate_race` en mode matin.
"""
from __future__ import annotations

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
