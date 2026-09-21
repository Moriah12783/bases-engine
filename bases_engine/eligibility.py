"""Porte d'éligibilité (§4.1) et ensemble candidat / cible (§4.2).

Mode `matin` : miroir strict de la porte de publication du moteur (historical_logs = autorité).
Mode `backtest` : rétrospectif — les courses passées sont toutes `RACE_STARTED` dans historical_logs,
la porte `publishable` et l'heure de départ ne s'appliquent donc pas ; les lignes antérieures au
contrat v2 sont acceptées avec le drapeau `LEGACY_CONTRACT` (jamais dans le pipeline quotidien).
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


def _sel_from_log(log: dict | None, horizon: str) -> list[int] | None:
    sel = (((log or {}).get("editions_moteur") or {}).get(horizon) or {}).get("sel")
    if not sel or not isinstance(sel, str):
        return None
    try:
        return [int(x) for x in sel.split("-") if x != ""]
    except ValueError:
        return None


def evaluate_race(con, race_id: str, horizon: str, log: dict | None, *, mode: str = "matin",
                  now: datetime | None = None) -> EligibleRace | Abstention:
    """Applique §4.1 puis §4.2 à une course. `con` = connexion à l'instantané (lecture seule)."""
    race = con.execute("select * from races where race_id = ?", (race_id,)).fetchone()
    if race is None:
        return Abstention(race_id, "?", "RACE_UNKNOWN")
    date = race["date"]
    flags: list[str] = []

    # 1. Autorité de la porte de publication (mode matin uniquement)
    if mode == "matin":
        if log is None:
            return Abstention(race_id, date, "NON_PUBLISHABLE:ABSENT_HISTORICAL_LOGS")
        if not log.get("publishable") or log.get("publication_reason") != "OK":
            return Abstention(race_id, date, f"NON_PUBLISHABLE:{log.get('publication_reason')}")

    # 2. Prédiction du moteur à l'horizon
    pred = con.execute("select * from predictions where race_id = ? and engine_name = ? and horizon = ?",
                       (race_id, config.ENGINE_NAME, horizon)).fetchone()
    if pred is None:
        return Abstention(race_id, date, "CONTRACT:NO_PREDICTION")
    if pred["contract_version"] != config.CONTRACT_VERSION or not pred["prediction_hash"]:
        if mode == "backtest":
            flags.append("LEGACY_CONTRACT")
        else:
            return Abstention(race_id, date, "CONTRACT")
    if pred["odds_real"] != 1:
        return Abstention(race_id, date, "CONTRACT:ODDS_NOT_REAL")
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
    engine8 = _sel_from_log(log, horizon)
    if engine8 is None:
        engine8 = [int(x) for x in json.loads(pred["selection_json"])][:config.MAX_CANDIDATES]
        flags.append("SEL_FROM_PREDICTIONS")
    engine8 = engine8[:config.MAX_CANDIDATES]
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
