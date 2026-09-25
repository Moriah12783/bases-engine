"""Tests de contrat (§4.4) : bloquants, exécutés avant tout calcul.

Un échec = arrêt, exit code ≠ 0, alerte, aucune publication.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import config
from .fetch import FetchError, ResultsClient, Snapshot

# Colonnes effectivement lues par Bases, tables par table (contrat de lecture accepté par la session moteur le 25/09/2026).
# Colonnes ou tables ajoutées : ignorées. Échec seulement sur une colonne attendue absente ou renommée, ou un
# contract_version inattendu ; le reste (somme des probabilités, journée sans prédiction) est un avertissement.
REQUIRED_COLUMNS = {
    "predictions": ["race_id", "engine_name", "horizon", "contract_version", "prediction_hash", "odds_real", "priced_ratio",
                    "is_no_bet", "probabilities_json", "selection_json", "lock_time_utc", "confidence_stars"],
    "races": ["race_id", "date", "meeting_number", "race_number", "status", "pmu_statut", "start_time_utc",
              "scheduled_start_time", "discipline", "declared_runners", "bets_json"],
    "runners": ["race_id", "num", "is_non_partant", "odds_is_real"],
    "race_results": ["race_id", "statut", "finalite", "arrival_order_json", "non_partants_json"],
}

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

        # 2. contract_version = 2 sur les prédictions du jour présentes (bloquant) ; aucune prédiction du jour = avertissement
        rows = con.execute("""select p.engine_name, p.horizon, p.contract_version from predictions p
                               join races r using(race_id) where r.date = ?""", (date,)).fetchall()
        bad = [(r["engine_name"], r["horizon"]) for r in rows if r["contract_version"] != config.CONTRACT_VERSION]
        res.jour_sans_predictions = not rows
        if rows:
            _check(res, CHECK_PREDICTIONS, not bad, f"{len(bad)} ligne(s) hors contrat v2 : {sorted(set(bad))[:5]}")

        # 3. Somme des probabilités : avertissement (la course concernée est de toute façon écartée par l'éligibilité)
        bad_sum = []
        for r in con.execute("""select p.race_id, p.horizon, p.probabilities_json from predictions p
                                 join races r using(race_id) where r.date = ? and p.engine_name = ?""",
                             (date, config.ENGINE_NAME)):
            try:
                probs = json.loads(r["probabilities_json"] or "{}")
                s_ = sum(float(v) for v in probs.values())
            except (ValueError, TypeError):
                s_ = float("nan")
            if not probs or abs(s_ - 1.0) > config.PROB_SUM_TOL:
                bad_sum.append((r["race_id"], r["horizon"], round(s_, 4)))
        if bad_sum:
            res.warnings.append(("probabilities_json somme à 1 ± 0,01", f"{len(bad_sum)} ligne(s) : {bad_sum[:5]}"))
    finally:
        con.close()

    if res.jour_sans_predictions:
        res.warnings.append(("prédictions du jour", f"aucune prédiction du jour dans la base du moteur lue ({snap.header()})"))

    # 4. Manifeste public
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
