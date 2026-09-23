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
    (2, """
    -- Sprint 2 : lien édition ↔ notation, suivi des empreintes du manifeste public, journal de déploiement.
    ALTER TABLE bases_results ADD COLUMN edition_id TEXT;
    ALTER TABLE bases_results ADD COLUMN hits_json TEXT;
    ALTER TABLE bases_results ADD COLUMN solidite TEXT;
    ALTER TABLE bases_results ADD COLUMN p_calibree_k3 REAL;
    ALTER TABLE bases_results ADD COLUMN horizon TEXT NOT NULL DEFAULT 'T_MATIN';
    ALTER TABLE bases_results ADD COLUMN statut TEXT;
    CREATE TABLE IF NOT EXISTS results_manifest (
        date TEXT PRIMARY KEY, empreinte_sha256 TEXT NOT NULL, nb_courses INTEGER,
        fetched_at_utc TEXT NOT NULL, scored_at_utc TEXT);
    CREATE TABLE IF NOT EXISTS abstentions (
        date TEXT NOT NULL, race_id TEXT NOT NULL, horizon TEXT NOT NULL, snapshot_commit TEXT NOT NULL,
        motif TEXT NOT NULL, recorded_at_utc TEXT NOT NULL,
        PRIMARY KEY (date, race_id, horizon, snapshot_commit));
    CREATE TABLE IF NOT EXISTS journal_days (
        date TEXT NOT NULL, horizon TEXT NOT NULL, snapshot_commit TEXT NOT NULL, run_id TEXT NOT NULL,
        published_at_utc TEXT, mode TEXT NOT NULL, status TEXT NOT NULL,
        PRIMARY KEY (date, horizon, snapshot_commit));
    """),
    (3, """
    -- Décisions mentor 21/09 : répétitions (exécutions manuelles avant le début du protocole) hors palmarès et verdict ;
    -- date de début du protocole fixée par le premier `matin` planifié (clé meta `protocole_debut`).
    ALTER TABLE bases_editions ADD COLUMN repetition INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE bases_results ADD COLUMN repetition INTEGER NOT NULL DEFAULT 0;
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT, set_at_utc TEXT NOT NULL);
    """),
    (4, """
    -- Clé de bases_results étendue à l'horizon : une même course est notée pour l'édition publiée (T_MATIN)
    -- et pour l'édition de mesure (T15) sans que l'une écrase l'autre.
    CREATE TABLE bases_results_v4 (
        race_id TEXT NOT NULL, result_version INTEGER NOT NULL, arrivee_json TEXT NOT NULL,
        top_m INTEGER NOT NULL, hit_k1 INTEGER, hit_k2 INTEGER, hit_k3 INTEGER, hit_k4 INTEGER,
        hit_2of3 INTEGER, scored_at_utc TEXT NOT NULL, source TEXT NOT NULL,
        checked_against_sqlite INTEGER NOT NULL DEFAULT 0,
        edition_id TEXT, hits_json TEXT, solidite TEXT, p_calibree_k3 REAL,
        horizon TEXT NOT NULL DEFAULT 'T_MATIN', statut TEXT, repetition INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (race_id, result_version, top_m, horizon));
    INSERT INTO bases_results_v4 SELECT race_id, result_version, arrivee_json, top_m, hit_k1, hit_k2, hit_k3, hit_k4,
        hit_2of3, scored_at_utc, source, checked_against_sqlite, edition_id, hits_json, solidite, p_calibree_k3,
        horizon, statut, repetition FROM bases_results;
    DROP TABLE bases_results;
    ALTER TABLE bases_results_v4 RENAME TO bases_results;
    """),
    (5, """
    -- Mesure intrajournée (T90/T30/T15) : non-partants au résultat pour compter les bases du matin devenues NP.
    ALTER TABLE bases_results ADD COLUMN non_partants_json TEXT;
    """),
    (6, """
    -- Sprint 4 : statut de chaque course du JSON public (pour l'affichage : en attente / provisoire / définitive / annulée)
    -- et finalité des notations (le palmarès ne compte que DEFINITIVE + VERIFIEE_PMU).
    ALTER TABLE bases_results ADD COLUMN finalite TEXT;
    CREATE TABLE IF NOT EXISTS course_statuts (
        race_id TEXT PRIMARY KEY, date TEXT NOT NULL, statut TEXT NOT NULL, finalite TEXT, annulee INTEGER NOT NULL DEFAULT 0,
        pmu_statut TEXT, version INTEGER, arrivee_json TEXT, non_partants_json TEXT, updated_at_utc TEXT NOT NULL);
    """),
    (7, """
    -- Métronome : déclencheur (manuel | cron | metronome) et journée visée, sur les runs, les éditions et le journal.
    ALTER TABLE runs ADD COLUMN declencheur TEXT;
    ALTER TABLE runs ADD COLUMN day TEXT;
    ALTER TABLE bases_editions ADD COLUMN declencheur TEXT;
    ALTER TABLE journal_days ADD COLUMN declencheur TEXT;
    """),
    (8, """
    -- Incidents d'exploitation comptés dans le rapport hebdomadaire (écart d'empreinte persistant, …) et
    -- compteur d'écarts consécutifs manifeste ↔ journée par date.
    CREATE TABLE IF NOT EXISTS incidents (
        id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, date TEXT NOT NULL, at_utc TEXT NOT NULL, detail TEXT);
    CREATE TABLE IF NOT EXISTS ecarts_empreinte (
        date TEXT PRIMARY KEY, consecutifs INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
        premier_at_utc TEXT, dernier_at_utc TEXT);
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

PLANIFIES = ("cron", "metronome")


def start_run(con, run_id: str, command: str, snapshot_commit: str | None, mode: str, *, declencheur: str = "manuel", day: str | None = None) -> None:
    from .util import iso_utc
    con.execute("""insert or replace into runs(run_id, started_at_utc, command, snapshot_commit, mode, status, declencheur, day)
                   values (?, ?, ?, ?, ?, 'RUNNING', ?, ?)""", (run_id, iso_utc(), command, snapshot_commit, mode, declencheur, day))
    con.commit()


def served_run(con, command: str, day: str, *, planned_only: bool) -> dict | None:
    """Run OK de la même commande pour la même journée (planifié seulement, ou n'importe quel déclencheur)."""
    q = "select run_id, declencheur, started_at_utc from runs where command=? and day=? and status='OK' and mode <> 'repetition' and mode <> 'dry-run'"
    if planned_only:
        q += " and declencheur in ('cron','metronome')"
    r = con.execute(q + " order by started_at_utc limit 1", (command, day)).fetchone()
    return dict(r) if r else None


def metronome_counter(con, until: str, days: int = 7) -> dict:
    """Sur les `days` derniers jours (matin) : servis par le métronome, par le filet GitHub (cron), manqués."""
    from datetime import datetime, timedelta
    d0 = datetime.strptime(until, "%Y-%m-%d")
    out = {"metronome": 0, "filet": 0, "manques": 0, "jours": []}
    for i in range(days):
        d = (d0 - timedelta(days=i)).strftime("%Y-%m-%d")
        decl = {r[0] for r in con.execute("select declencheur from runs where command='matin' and day=? and status='OK' and mode not in ('repetition','dry-run')", (d,))}
        if "metronome" in decl:
            out["metronome"] += 1; out["jours"].append((d, "metronome"))
        elif "cron" in decl:
            out["filet"] += 1; out["jours"].append((d, "filet"))
        else:
            out["manques"] += 1; out["jours"].append((d, "manque"))
    return out



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


# --- éditions -----------------------------------------------------------------------------

def edition_id(date: str, race_id: str, horizon: str, snapshot_commit: str) -> str:
    from .util import race_slug
    return f"{race_slug(race_id)}_{horizon}_{snapshot_commit[:10]}"


def editions_for_day(con, date: str, horizon: str, *, current_only: bool = True) -> list[dict]:
    q = "select * from bases_editions where date = ? and horizon = ?"
    if current_only:
        q += " and superseded_by is null"
    return [dict(r) for r in con.execute(q + " order by race_id", (date, horizon))]


def editions_exist(con, date: str, horizon: str, snapshot_commit: str) -> bool:
    return con.execute("select 1 from bases_editions where date=? and horizon=? and snapshot_commit=? limit 1",
                       (date, horizon, snapshot_commit)).fetchone() is not None


def supersede(con, date: str, horizon: str, new_commit: str) -> int:
    """Marque les éditions courantes d'un autre commit comme remplacées (nouvelle version du matin)."""
    n = 0
    for r in con.execute("select edition_id, race_id from bases_editions where date=? and horizon=? and snapshot_commit<>? and superseded_by is null",
                         (date, horizon, new_commit)):
        new_id = edition_id(date, r["race_id"], horizon, new_commit)
        if con.execute("select 1 from bases_editions where edition_id=?", (new_id,)).fetchone():
            con.execute("update bases_editions set superseded_by=? where edition_id=?", (new_id, r["edition_id"]))
            n += 1
    con.commit()
    return n


def insert_edition(con, row: dict) -> None:
    cols = ",".join(row.keys())
    con.execute(f"insert or ignore into bases_editions ({cols}) values ({','.join('?' * len(row))})", list(row.values()))


def current_edition_for_race(con, race_id: str, horizon: str) -> dict | None:
    r = con.execute("select * from bases_editions where race_id=? and horizon=? and superseded_by is null order by computed_at_utc desc limit 1",
                    (race_id, horizon)).fetchone()
    return dict(r) if r else None


# --- résultats ----------------------------------------------------------------------------

def result_already_scored(con, race_id: str, result_version: int, top_m: int, horizon: str) -> bool:
    return con.execute("select 1 from bases_results where race_id=? and result_version=? and top_m=? and horizon=?",
                       (race_id, result_version, top_m, horizon)).fetchone() is not None


def latest_results(con, horizon: str = "T_MATIN") -> list[dict]:
    """Dernière version notée de chaque course (par top_m), jointe à son édition."""
    rows = con.execute("""
        select r.*, e.date, e.solidite as ed_solidite, e.ladder_json, e.top_m as ed_top_m, e.mode as ed_mode,
               e.engine8_json, e.repetition as ed_repetition
        from bases_results r join bases_editions e on e.edition_id = r.edition_id
        where r.horizon = ? and r.statut = 'DEFINITIVE' and r.finalite = 'VERIFIEE_PMU' and r.result_version = (
            select max(result_version) from bases_results r2 where r2.race_id = r.race_id and r2.top_m = r.top_m and r2.horizon = r.horizon)
        order by e.date, r.race_id""", (horizon,))
    return [dict(r) for r in rows]


def upsert_course_statut(con, course: dict, date: str) -> None:
    from .util import iso_utc
    st = course.get("statut") or {}
    nps = [int(x["num"]) for x in course.get("non_partants") or []]
    con.execute("""insert or replace into course_statuts(race_id, date, statut, finalite, annulee, pmu_statut, version, arrivee_json, non_partants_json, updated_at_utc)
                   values (?,?,?,?,?,?,?,?,?,?)""",
                (course.get("course_id"), date, st.get("code") or "EN_ATTENTE", st.get("finalite"), 1 if st.get("annulee") else 0, st.get("pmu_statut"),
                 int((course.get("correction") or {}).get("version") or 0), json.dumps(course.get("arrivee") or []), json.dumps(nps), iso_utc()))


def course_statuts_for_day(con, date: str) -> dict[str, dict]:
    return {r["race_id"]: dict(r) for r in con.execute("select * from course_statuts where date=?", (date,))}


def unchecked_days(con) -> set[str]:
    """Journées ayant des notations non contrôlées avec SQLite (passe horaire) : le soir les relit même à empreinte inchangée."""
    return {r[0] for r in con.execute("""select distinct e.date from bases_results r join bases_editions e on e.edition_id=r.edition_id
                                          where r.checked_against_sqlite=0""")}


def manifest_fingerprint(con, date: str) -> str | None:
    r = con.execute("select empreinte_sha256 from results_manifest where date=?", (date,)).fetchone()
    return r[0] if r else None


def set_manifest_fingerprint(con, date: str, fp: str, nb: int | None, fetched_at: str, scored_at: str | None) -> None:
    con.execute("insert or replace into results_manifest(date, empreinte_sha256, nb_courses, fetched_at_utc, scored_at_utc) values (?,?,?,?,?)",
                (date, fp, nb, fetched_at, scored_at))
    con.commit()


def get_meta(con, key: str) -> str | None:
    r = con.execute("select value from meta where key=?", (key,)).fetchone()
    return r[0] if r else None


def set_meta(con, key: str, value: str) -> None:
    from .util import iso_utc
    con.execute("insert or replace into meta(key, value, set_at_utc) values (?,?,?)", (key, value, iso_utc()))
    con.commit()


def protocol_start_date(con) -> str | None:
    """Date de début du protocole : fixée par le premier `matin` planifié (cron). None tant qu'il n'a pas eu lieu."""
    return get_meta(con, "protocole_debut")


def shadow_start_date(con) -> str | None:
    return protocol_start_date(con)


def is_repetition(con, day: str) -> bool:
    """Toute exécution portant sur un jour antérieur au début du protocole (ou avant qu'il soit fixé) est une répétition."""
    start = protocol_start_date(con)
    return start is None or day < start


def display_results_for_day(con, date: str, horizon: str = "T_MATIN") -> dict[str, dict]:
    """Dernière notation (définitive ou provisoire) de chaque course de la journée, pour l'affichage."""
    rows = con.execute("""
        select r.*, e.top_m as ed_top_m from bases_results r join bases_editions e on e.edition_id = r.edition_id
        where e.date = ? and r.horizon = ? and e.superseded_by is null and r.top_m = e.top_m
          and r.result_version = (select max(result_version) from bases_results r2 where r2.race_id = r.race_id and r2.top_m = r.top_m and r2.horizon = r.horizon)""",
        (date, horizon))
    return {r["race_id"]: dict(r) for r in rows}


def day_has_editions(con, date: str, horizon: str = "T_MATIN") -> bool:
    return con.execute("select 1 from bases_editions where date=? and horizon=? limit 1", (date, horizon)).fetchone() is not None


def day_scored_at(con, date: str) -> str | None:
    r = con.execute("select scored_at_utc from results_manifest where date=?", (date,)).fetchone()
    return r[0] if r else None


def unchecked_count(con, date: str) -> int:
    return con.execute("""select count(*) from bases_results r join bases_editions e on e.edition_id=r.edition_id
                          where e.date=? and r.checked_against_sqlite=0""", (date,)).fetchone()[0]


def results_count(con, date: str) -> int:
    return con.execute("""select count(*) from bases_results r join bases_editions e on e.edition_id=r.edition_id where e.date=?""", (date,)).fetchone()[0]


# --- incidents / écarts d'empreinte ------------------------------------------------------------

def add_incident(con, kind: str, date: str, detail: str) -> None:
    from .util import iso_utc
    con.execute("insert into incidents(kind, date, at_utc, detail) values (?,?,?,?)", (kind, date, iso_utc(), detail))
    con.commit()


def incidents_count(con, kind: str, until: str, days: int = 7) -> int:
    from datetime import datetime, timedelta
    since = (datetime.strptime(until, "%Y-%m-%d") - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    return con.execute("select count(*) from incidents where kind=? and date between ? and ?", (kind, since, until)).fetchone()[0]


def ecart_empreinte_note(con, date: str) -> int:
    """Un écart de plus pour cette date ; retourne le nombre d'écarts consécutifs."""
    from .util import iso_utc
    r = con.execute("select consecutifs, total, premier_at_utc from ecarts_empreinte where date=?", (date,)).fetchone()
    now = iso_utc()
    if r is None:
        con.execute("insert into ecarts_empreinte(date, consecutifs, total, premier_at_utc, dernier_at_utc) values (?,1,1,?,?)", (date, now, now))
        n = 1
    else:
        n = r[0] + 1
        con.execute("update ecarts_empreinte set consecutifs=?, total=?, dernier_at_utc=? where date=?", (n, r[1] + 1, now, date))
    con.commit()
    return n


def ecart_empreinte_reset(con, date: str) -> None:
    con.execute("update ecarts_empreinte set consecutifs=0 where date=?", (date,))
    con.commit()


def ecart_empreinte_consecutifs(con, date: str) -> int:
    r = con.execute("select consecutifs from ecarts_empreinte where date=?", (date,)).fetchone()
    return r[0] if r else 0
