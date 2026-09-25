"""Porte d'éligibilité (§4.1) et ensemble candidat / cible (§4.2).

Source : la base vivante du moteur (R2) uniquement, depuis le 25/09/2026 (le rapport public n'est plus lu).
Mode `matin` : porte de publication du moteur reconstituée sur les champs de la base, avec les mêmes motifs :
course annulée (`races.status` = ANNULEE ou `pmu_statut` = COURSE_ANNULEE) → RACE_CANCELLED ; cotes non réelles
(`odds_real` ≠ 1, ou pas de T_MATIN et aucune cote réelle chez les partants) → ODDS_DEFAULT ; T_MATIN non verrouillée (absente) → CONTRACT:NO_PREDICTION ; départ passé ou
à moins de 20 minutes → RACE_STARTED. Sélection moteur = `predictions.selection_json` (identique à la sélection
du rapport public sur 574 courses sur 574 comparées, 08/09 → 24/09/2026).
Mode `backtest` : rétrospectif — l'heure de départ ne s'applique pas ; les lignes antérieures au contrat v2 sont
acceptées avec le drapeau `LEGACY_CONTRACT` (jamais dans le pipeline quotidien).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import config


@dataclass
class EligibleRace:
    race_id: str
    date: str
    horizon: str
    top_m: int
    pari_cible: str
    start_time_utc: str | None
    scheduled_start_time: str | None
    discipline: str | None
    declared_runners: int
    active_runners: int
    engine8: list[int]                # sélection moteur (≤ 8, ordre du moteur)
    candidates: list[int]             # engine8 valides (présents dans p, non NP)
    probs: dict[int, float]           # renormalisées après retrait des NP
    prediction_hash: str | None
    lock_time_utc: str | None
    confidence_stars: int | None
    priced_ratio: float | None
    flags: list[str] = field(default_factory=list)
    market_probs: dict[int, float] | None = None
    paris_offerts: list[str] = field(default_factory=list)   # codes bets_json utiles, dans l'ordre de priorité


# Colonnes lues nommément dans la base du moteur (jamais SELECT *) : l'ajout de colonnes ou de tables est libre côté moteur.
RACE_COLS = "race_id, date, status, pmu_statut, start_time_utc, scheduled_start_time, discipline, declared_runners, bets_json"
PRED_COLS = ("contract_version, prediction_hash, odds_real, priced_ratio, is_no_bet, probabilities_json, selection_json, "
             "lock_time_utc, confidence_stars")


@dataclass
class Abstention:
    race_id: str
    date: str
    motif: str


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def evaluate_race(con, race_id: str, horizon: str, *, mode: str = "matin",
                  now: datetime | None = None) -> EligibleRace | Abstention:
    """Applique §4.1 puis §4.2 à une course. `con` = connexion à la base du moteur (lecture seule)."""
    race = con.execute(f"select {RACE_COLS} from races where race_id = ?", (race_id,)).fetchone()
    if race is None:
        return Abstention(race_id, "?", "RACE_UNKNOWN")
    date = race["date"]
    flags: list[str] = []

    # 1. Porte de publication reconstituée sur la base (mode matin uniquement)
    if mode == "matin" and (str(race["status"] or "").upper() == "ANNULEE" or str(race["pmu_statut"] or "").upper() == "COURSE_ANNULEE"):
        return Abstention(race_id, date, "NON_PUBLISHABLE:RACE_CANCELLED")

    # 2. Prédiction du moteur à l'horizon
    pred = con.execute(f"select {PRED_COLS} from predictions where race_id = ? and engine_name = ? and horizon = ?",
                       (race_id, config.ENGINE_NAME, horizon)).fetchone()
    if pred is None:
        if mode == "matin":
            n_run, n_reel = con.execute("select count(*), sum(coalesce(odds_is_real, 0)) from runners where race_id = ?", (race_id,)).fetchone()
            if n_run and not n_reel:                     # aucune cote réelle : la porte du moteur la classe ODDS_DEFAULT
                return Abstention(race_id, date, "NON_PUBLISHABLE:ODDS_DEFAULT")
        return Abstention(race_id, date, "CONTRACT:NO_PREDICTION")
    if pred["contract_version"] != config.CONTRACT_VERSION or not pred["prediction_hash"]:
        if mode == "backtest":
            flags.append("LEGACY_CONTRACT")
        else:
            return Abstention(race_id, date, "CONTRACT")
    if pred["odds_real"] != 1:
        return Abstention(race_id, date, "NON_PUBLISHABLE:ODDS_DEFAULT" if mode == "matin" else "CONTRACT:ODDS_NOT_REAL")
    if pred["priced_ratio"] is None:
        if mode != "backtest":
            return Abstention(race_id, date, "PRICED_RATIO")
    elif pred["priced_ratio"] < config.MIN_PRICED_RATIO:
        return Abstention(race_id, date, "PRICED_RATIO")
    if pred["is_no_bet"] == 1:
        return Abstention(race_id, date, "NO_BET")
    try:
        probs_raw = {int(k): float(v) for k, v in json.loads(pred["probabilities_json"] or "{}").items()}
    except (ValueError, TypeError):
        return Abstention(race_id, date, "CONTRACT:PROBABILITIES_INVALID")
    if not probs_raw or abs(sum(probs_raw.values()) - 1.0) > config.PROB_SUM_TOL:
        return Abstention(race_id, date, "CONTRACT:PROBABILITIES_SUM")

    # 3. Heure de départ (mode matin)
    if mode == "matin":
        start = _parse_dt(race["start_time_utc"])
        now = now or datetime.now(timezone.utc)
        if start is None or start <= now + timedelta(minutes=config.START_MARGIN_MIN):
            return Abstention(race_id, date, "RACE_STARTED")

    # 4. Taille du peloton
    nps = {r["num"] for r in con.execute("select num from runners where race_id = ? and is_non_partant = 1", (race_id,))}
    probs = {n: p for n, p in probs_raw.items() if n not in nps}
    if len(probs) < config.MIN_FIELD:
        return Abstention(race_id, date, "FIELD_TOO_SMALL")
    declared = race["declared_runners"] or len(probs_raw)
    if declared - len(nps) < config.MIN_FIELD:
        return Abstention(race_id, date, "FIELD_TOO_SMALL")
    tot = sum(probs.values())
    probs = {n: p / tot for n, p in probs.items()}

    # §4.2 candidats
    try:
        engine8 = [int(x) for x in json.loads(pred["selection_json"] or "[]")][:config.MAX_CANDIDATES]
    except (ValueError, TypeError):
        return Abstention(race_id, date, "CONTRACT:SELECTION_INVALID")
    candidates = [n for n in engine8 if n in probs]
    if len(candidates) < config.MIN_CANDIDATES:
        return Abstention(race_id, date, "CANDIDATES_TOO_FEW")

    # cible
    try:
        codes = {b.get("code") for b in json.loads(race["bets_json"] or "[]")}
    except (ValueError, TypeError):
        codes = set()
    if "QUINTE_PLUS" in codes:
        top_m, cible = 5, "QUINTE_PLUS"
    else:
        top_m, cible = 4, "QUARTE_PLUS" if "QUARTE_PLUS" in codes else ("MULTI" if "MULTI" in codes else "TOP4")
    paris = [c for c in config.PARIS_UTILES if c in codes]

    market = con.execute("select probabilities_json from predictions where race_id = ? and engine_name = ? and horizon = ?",
                         (race_id, config.MARKET_ENGINE, horizon)).fetchone()
    market_probs = None
    if market and market["probabilities_json"]:
        try:
            market_probs = {int(k): float(v) for k, v in json.loads(market["probabilities_json"]).items() if int(k) not in nps}
        except (ValueError, TypeError):
            market_probs = None

    return EligibleRace(
        race_id=race_id, date=date, horizon=horizon, top_m=top_m, pari_cible=cible,
        start_time_utc=race["start_time_utc"], scheduled_start_time=race["scheduled_start_time"],
        discipline=race["discipline"], declared_runners=declared, active_runners=len(probs),
        engine8=engine8, candidates=candidates, probs=probs, prediction_hash=pred["prediction_hash"],
        lock_time_utc=pred["lock_time_utc"], confidence_stars=pred["confidence_stars"],
        priced_ratio=pred["priced_ratio"], flags=flags, market_probs=market_probs, paris_offerts=paris)
