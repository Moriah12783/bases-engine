"""`bases.db` : persistance définitive (schéma §5, migrations numérotées)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import config

MIGRATIONS: list[tuple[int, str]] = [
    (1, """
    CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at_utc TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY, started_at_utc TEXT NOT NULL, command TEXT NOT NULL,
        snapshot_commit TEXT, mode TEXT, races_seen INTEGER, races_published INTEGER,
        status TEXT NOT NULL, error TEXT, duration_s REAL);
    CREATE TABLE IF NOT EXISTS bases_editions (
        edition_id TEXT PRIMARY KEY, date TEXT NOT NULL, race_id TEXT NOT NULL, race_slug TEXT NOT NULL,
        horizon TEXT NOT NULL, top_m INTEGER NOT NULL, computed_at_utc TEXT NOT NULL,
        snapshot_commit TEXT NOT NULL, prediction_hash TEXT, lock_time_utc TEXT,
        engine8_json TEXT NOT NULL, candidates_json TEXT NOT NULL, lambdas_json TEXT NOT NULL,
        ladder_json TEXT NOT NULL, trios_json TEXT NOT NULL, solidite TEXT, structure_code TEXT,
        flags_json TEXT NOT NULL DEFAULT '[]', params_version TEXT NOT NULL, mode TEXT NOT NULL,
        published_at_utc TEXT, superseded_by TEXT,
        UNIQUE(date, race_id, horizon, top_m, snapshot_commit));
    CREATE TABLE IF NOT EXISTS bases_results (
        race_id TEXT NOT NULL, result_version INTEGER NOT NULL, arrivee_json TEXT NOT NULL,
        top_m INTEGER NOT NULL, hit_k1 INTEGER, hit_k2 INTEGER, hit_k3 INTEGER, hit_k4 INTEGER,
        hit_2of3 INTEGER, scored_at_utc TEXT NOT NULL, source TEXT NOT NULL,
        checked_against_sqlite INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (race_id, result_version, top_m));
    CREATE TABLE IF NOT EXISTS calibration (
        computed_at_utc TEXT NOT NULL, k INTEGER NOT NULL, top_m INTEGER NOT NULL, n INTEGER NOT NULL,
        knots_json TEXT NOT NULL, params_version TEXT NOT NULL,
        PRIMARY KEY (params_version, k, top_m));
    CREATE TABLE IF NOT EXISTS params (
        version TEXT PRIMARY KEY, valid_from TEXT NOT NULL, lambdas_json TEXT NOT NULL,
        seuils_json TEXT NOT NULL, shrink REAL NOT NULL, note TEXT);
    """),
]


def connect(path: Path | str = config.DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.execute("pragma journal_mode=DELETE")
    migrate(con)
    return con


def migrate(con: sqlite3.Connection) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at_utc TEXT NOT NULL)")
    done = {r[0] for r in con.execute("select version from schema_version")}
    from .util import iso_utc
    for version, sql in MIGRATIONS:
        if version in done:
            continue
        con.executescript(sql)
        con.execute("insert into schema_version(version, applied_at_utc) values (?, ?)", (version, iso_utc()))
        con.commit()


# --- runs -------------------------------------------------------------------------------------

def start_run(con, run_id: str, command: str, snapshot_commit: str | None, mode: str) -> None:
    from .util import iso_utc
    con.execute("""insert or replace into runs(run_id, started_at_utc, command, snapshot_commit, mode, status)
                   values (?, ?, ?, ?, ?, 'RUNNING')""", (run_id, iso_utc(), command, snapshot_commit, mode))
    con.commit()


def finish_run(con, run_id: str, status: str, *, races_seen=None, races_published=None, error=None, duration_s=None):
    con.execute("""update runs set status=?, races_seen=?, races_published=?, error=?, duration_s=? where run_id=?""",
                (status, races_seen, races_published, error, duration_s, run_id))
    con.commit()


# --- params -----------------------------------------------------------------------------------

def current_params(con) -> dict | None:
    row = con.execute("select * from params order by valid_from desc, version desc limit 1").fetchone()
    return dict(row) if row else None


def insert_params(con, version: str, valid_from: str, lambdas: list, seuils: dict, shrink: float, note: str) -> None:
    con.execute("insert into params(version, valid_from, lambdas_json, seuils_json, shrink, note) values (?,?,?,?,?,?)",
                (version, valid_from, json.dumps(list(lambdas)), json.dumps(seuils, ensure_ascii=False), shrink, note))
    con.commit()


def insert_calibration(con, computed_at_utc: str, k: int, top_m: int, n: int, knots: dict, params_version: str) -> None:
    con.execute("insert or replace into calibration(computed_at_utc, k, top_m, n, knots_json, params_version) values (?,?,?,?,?,?)",
                (computed_at_utc, k, top_m, n, json.dumps(knots), params_version))
    con.commit()


def load_calibrations(con, params_version: str) -> dict[tuple[int, int], dict]:
    return {(r["k"], r["top_m"]): json.loads(r["knots_json"])
            for r in con.execute("select * from calibration where params_version = ?", (params_version,))}
