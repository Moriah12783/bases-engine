"""Construit fixtures/snapshot/ : extrait figé (≤ 2 Mo) de turf_bench.db + historical_logs.

Usage : python scripts/make_fixture.py <dossier .cache/<sha>> [--dates 2026-09-19,2026-09-20,2026-09-21]
Lecture seule de l'instantané source ; aucun réseau.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

TABLES = ["races", "runners", "predictions", "race_results", "rapports"]   # tables volumineuses non lues laissées vides (schéma conservé)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--dates", default="2026-09-20,2026-09-21")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "fixtures" / "snapshot"))
    a = ap.parse_args()
    src = Path(a.source)
    dates = a.dates.split(",")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    db_out = out / "turf_bench.db"
    db_out.unlink(missing_ok=True)
    s = sqlite3.connect(f"file:{src / 'turf_bench.db'}?mode=ro", uri=True)
    d = sqlite3.connect(db_out)
    for (name, sql) in s.execute("select name, sql from sqlite_master where type='table' and name != 'sqlite_sequence'"):
        d.execute(sql)
    race_ids = [r[0] for r in s.execute(f"select race_id from races where date in ({','.join('?' * len(dates))})", dates)]
    ph = ",".join("?" * len(race_ids))
    for t in TABLES:
        cols = [c[1] for c in s.execute(f"pragma table_info('{t}')")]
        extra = " and engine_name in ('NEW_VALUE_ENGINE','MARKET_BASELINE')" if t == "predictions" else ""
        rows = s.execute(f"select * from '{t}' where race_id in ({ph}){extra}", race_ids).fetchall()
        d.executemany(f"insert into '{t}' ({','.join(cols)}) values ({','.join('?' * len(cols))})", rows)
    d.commit(); d.execute("vacuum"); d.close()
    rep = json.load((src / "benchmark_report.json").open(encoding="utf-8"))
    logs = [h for h in rep["historical_logs"] if h.get("date") in dates]
    for h in logs:                       # on allège les clés volumineuses non lues par le service
        h.pop("runners", None)
    small = {"engines_evaluated": rep.get("engines_evaluated"), "horizon_bench_start_date": rep.get("horizon_bench_start_date"),
             "fixture_note": f"extrait figé de historical_logs pour {dates} (clé runners retirée)", "historical_logs": logs}
    (out / "benchmark_report.json").write_text(json.dumps(small, ensure_ascii=False), encoding="utf-8")
    sha_file = src / "SHA"
    (out / "SHA").write_text((sha_file.read_text().strip() if sha_file.exists() else src.name) + "\n")
    print("races:", len(race_ids), "logs:", len(logs), "db bytes:", db_out.stat().st_size, "report bytes:", (out / "benchmark_report.json").stat().st_size)


if __name__ == "__main__":
    main()
