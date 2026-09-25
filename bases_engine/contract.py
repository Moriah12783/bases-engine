"""Tests de contrat (§4.4) : bloquants, exécutés avant tout calcul.

Un échec = arrêt, exit code ≠ 0, alerte, aucune publication.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import config
from .fetch import FetchError, ResultsClient, Snapshot

REQUIRED_COLUMNS = {
    "predictions": ["race_id", "engine_name", "horizon", "selection_json", "bases_json", "outsider_num",
                    "probabilities_json", "metadata_json", "odds_real", "priced_ratio", "confidence_stars",
                    "confidence_label", "is_no_bet", "smart_tickets_json", "contract_version",
                    "prediction_hash", "lock_time_utc", "created_at"],
    "races": ["race_id", "date", "meeting_number", "race_number", "name", "hippodrome", "discipline",
              "distance", "declared_runners", "start_time_utc", "scheduled_start_time", "pmu_statut",
              "status", "bets_json"],
    "runners": ["race_id", "num", "horse_name", "is_non_partant", "music", "driver_jockey", "trainer",
                "shoeing", "blinkers", "morning_odds", "odds_t15", "final_odds", "odds_is_real"],
    "race_results": ["race_id", "arrival_order_json", "ranking_json", "disqualified_json",
                     "non_partants_json", "statut", "finalite", "version", "nb_corrections", "updated_at"],
    "rapports": ["race_id", "bet_type", "combination", "dividend"],
}
REQUIRED_LOG_KEYS = ["race_id", "date", "course", "publishable", "publication_reason", "editions_moteur"]


CHECK_PREDICTIONS = "contract_version=2 (prédictions du jour)"


@dataclass
class ContractResult:
    passed: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)   # (nom du test, détail)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[tuple[str, str]] = field(default_factory=list)  # non bloquants, comptés et journalisés
    jour_sans_predictions: bool = False   # aucune prédiction du jour dans la base du moteur (le soir ne s'arrête pas pour ce seul motif)

    @property
    def ok(self) -> bool:
        return not self.failed

    def summary(self) -> str:
        lines = [f"✅ {t}" for t in self.passed]
        lines += [f"⛔ {t} — {d}" for t, d in self.failed]
        lines += [f"⚠️ {t} — {d}" for t, d in self.warnings]
        lines += [f"⏭️ {t} — {d}" for t, d in self.skipped]
        return "\n".join(lines)


def _check(res: ContractResult, name: str, cond: bool, detail: str = "") -> None:
    (res.passed.append(name) if cond else res.failed.append((name, detail)))


def run_contract_checks(snap: Snapshot, date: str, *, results_client: ResultsClient | None = None,
                        network: bool = True, notify_warnings: bool = True) -> ContractResult:
    res = ContractResult()
    con = snap.connect()
    try:
        # 1. Tables et colonnes
        tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        for table, cols in REQUIRED_COLUMNS.items():
            if table not in tables:
                res.failed.append((f"schema:{table}", "table absente"))
                continue
            have = {r[1] for r in con.execute(f"pragma table_info('{table}')")}
            missing = [c for c in cols if c not in have]
            _check(res, f"schema:{table}", not missing, f"colonnes absentes : {missing}")
        if res.failed:
            return res

        # 2. contract_version = 2 sur toutes les prédictions du jour
        rows = con.execute("""select p.engine_name, p.horizon, p.contract_version from predictions p
                               join races r using(race_id) where r.date = ?""", (date,)).fetchall()
        bad = [(r["engine_name"], r["horizon"]) for r in rows if r["contract_version"] != config.CONTRACT_VERSION]
        res.jour_sans_predictions = not rows
        _check(res, CHECK_PREDICTIONS, bool(rows) and not bad,
               "aucune prédiction du jour" if not rows else f"{len(bad)} ligne(s) hors contrat v2 : {sorted(set(bad))[:5]}")

        # 3. Somme des probabilités
        bad_sum = []
        for r in con.execute("""select p.race_id, p.engine_name, p.horizon, p.probabilities_json from predictions p
                                 join races r using(race_id) where r.date = ? and p.engine_name = ?""",
                             (date, config.ENGINE_NAME)):
            try:
                probs = json.loads(r["probabilities_json"] or "{}")
                s = sum(float(v) for v in probs.values())
            except (ValueError, TypeError):
                s = float("nan")
            if not probs or abs(s - 1.0) > config.PROB_SUM_TOL:
                bad_sum.append((r["race_id"], r["horizon"], round(s, 4)))
        _check(res, "probabilities_json somme à 1 ± 0,01", not bad_sum, f"{bad_sum[:5]}")
    finally:
        con.close()

    # 4. historical_logs
    try:
        logs = snap.historical_logs()
    except (OSError, ValueError) as e:
        res.failed.append(("historical_logs lisible", str(e)))
        return res
    today = [h for h in logs if h.get("date") == date]
    _check(res, "historical_logs contient la date J", bool(today), f"0 course pour {date}")
    if res.jour_sans_predictions and today:
        # incident du 25/09/2026 : rapport du moteur à jour (courses du jour listées), base SQLite du moteur non rafraîchie
        detail = (f"aucune prédiction du jour dans la base du moteur alors que son rapport liste {len(today)} course(s) pour {date} "
                  "— base du moteur non rafraîchie, à signaler au développeur du moteur")
        res.failed = [(n, detail if n == CHECK_PREDICTIONS else d) for n, d in res.failed]
    missing_keys = sorted({k for h in today for k in REQUIRED_LOG_KEYS if k not in h})
    _check(res, "historical_logs : clés attendues", not missing_keys, f"clés absentes : {missing_keys}")
    # publication_reason : le drapeau `publishable` est l'autorité, la raison est informative.
    # Valeur inconnue avec publishable = false → AVERTISSEMENT (compté, listé, journalisé, non bloquant) ;
    # valeur inconnue avec publishable = true → BLOQUANT (une course serait publiée pour une raison que l'on ne comprend pas).
    unknown_pub = {}
    unknown_nonpub = {}
    for h in logs:
        r = str(h.get("publication_reason"))
        if r in config.KNOWN_PUBLICATION_REASONS:
            continue
        (unknown_pub if h.get("publishable") else unknown_nonpub).setdefault(r, []).append(h.get("race_id"))
    _check(res, "publication_reason inconnue avec publishable = true", not unknown_pub,
           "valeurs inconnues sur des courses publiables : " + ", ".join(f"{k} ({len(v)} course(s), ex. {v[0]})" for k, v in sorted(unknown_pub.items())))
    if unknown_nonpub:
        detail = "valeurs inconnues sur des courses NON publiables (informatif) : " + ", ".join(
            f"{k} × {len(v)} (ex. {v[0]})" for k, v in sorted(unknown_nonpub.items()))
        res.warnings.append(("publication_reason inconnue avec publishable = false", detail))
        if notify_warnings:
            from .notify import notify
            notify("alerte", f"⚠️ BASES — avertissement contrat (non bloquant) — commit {snap.sha[:10]}", detail, date=date)

    # 5. Manifeste public
    if not network:
        res.skipped.append(("manifeste index.json", "réseau désactivé (--no-network) — test NON exécuté"))
    else:
        try:
            man = (results_client or ResultsClient()).manifest()
            _check(res, "manifeste index.json répond avec empreinte_sha256",
                   isinstance(man, dict) and bool(_find_fingerprint(man)), "clé empreinte_sha256 absente")
        except FetchError as e:
            res.failed.append(("manifeste index.json", str(e)))
    return res


def _find_fingerprint(obj) -> bool:
    """Le manifeste porte `empreinte_sha256` au niveau racine et/ou par journée."""
    if isinstance(obj, dict):
        if "empreinte_sha256" in obj:
            return True
        return any(_find_fingerprint(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_find_fingerprint(v) for v in obj)
    return False
