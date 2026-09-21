"""CLI : python -m bases_engine <commande> [options]."""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import date as _date

from . import config, storage
from .fetch import FetchError, get_snapshot
from .util import iso_utc

SPRINT2 = {"matin", "soir", "hebdo"}


def cmd_contract_check(args) -> int:
    from .contract import run_contract_checks
    snap = get_snapshot(args.sha)
    day = args.date or _date.today().isoformat()
    res = run_contract_checks(snap, day, network=not args.no_network)
    print(f"Contract-check — commit {snap.sha[:10]} — date {day}")
    print(res.summary())
    if not res.ok:
        print(f"\n⛔ BASES — arrêt : {res.failed[0][0]} a échoué sur commit {snap.sha[:10]}. Aucune publication. Action requise : Steph.")
        return 2
    print("\nOK — tous les tests de contrat exécutés sont verts." + (" (test réseau sauté)" if res.skipped else ""))
    return 0


def cmd_backtest(args) -> int:
    from .report import backtest_markdown
    from .scoring import backtest
    from .params import load_params, save_params
    snap = get_snapshot(args.sha)
    run_id = f"backtest-{iso_utc()}-{uuid.uuid4().hex[:6]}"
    con = storage.connect(args.db)
    storage.start_run(con, run_id, "backtest", snap.sha, "backtest")
    try:
        bt = backtest(snap, since=args.since, until=args.until, horizon=args.horizon, n_sims=args.n_sims)
    except Exception as e:  # noqa: BLE001
        storage.finish_run(con, run_id, "FAILED", error=repr(e))
        raise
    md = backtest_markdown(bt)
    out_dir = config.RAPPORTS_DIR / "backtest"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _date.today().isoformat()
    md_path = out_dir / f"{stamp}_{args.horizon}_since-{args.since}.md"
    md_path.write_text(md, encoding="utf-8")
    (out_dir / f"{stamp}_{args.horizon}_since-{args.since}.json").write_text(json.dumps(bt, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(md)
    print(f"→ rapport : {md_path}")

    if args.freeze_params:
        version = args.params_version or f"{stamp}.1"
        params = {
            "version": version, "valid_from": stamp, "lambdas": bt["lambdas"],
            "seuils_solidite": {f"top{m}": bt["par_cible"][m]["seuils_solidite"] for m in (4, 5) if bt["par_cible"][m].get("seuils_solidite")},
            "shrink": config.SHRINK, "calib_min_n": config.CALIB_MIN_N, "n_sims": config.N_SIMS,
            "calibration": {}, "source": {"snapshot_commit": snap.sha, "horizon": args.horizon, "since": args.since, "n_courses": bt["n_courses"]},
            "note": (f"Gelé le {stamp} par `backtest --since {args.since} --horizon {args.horizon}` sur {bt['n_courses']} courses. "
                     "Lambdas = littérature (pas de ré-estimation avant 1 500 courses). Seuils = terciles de P(3/3) recalibrée. "
                     "Inchangés jusqu'au verdict du protocole pré-enregistré ; recalibration hebdomadaire = nouvelle version."),
        }
        for m in (4, 5):
            for key, entry in bt["par_cible"][m].get("calibration", {}).items():
                params["calibration"][key] = {"n": entry["n"], "mode": entry["mode"], "shrink": config.SHRINK,
                                              "knots_x": entry.get("knots_x"), "knots_y": entry.get("knots_y")}
                k = int(key[1])
                storage.insert_calibration(con, iso_utc(), k, m, entry["n"], {"knots_x": entry.get("knots_x"), "knots_y": entry.get("knots_y")}, version)
        existing = load_params()
        if existing.get("version") == version and not args.force:
            print(f"params.json version {version} existe déjà — non réécrit (utiliser --force).")
        else:
            save_params(params)
            if con.execute("select 1 from params where version = ?", (version,)).fetchone() is None:
                storage.insert_params(con, version, stamp, params["lambdas"], params["seuils_solidite"], config.SHRINK, params["note"])
            print(f"→ params.json gelé : version {version}, seuils {params['seuils_solidite']}")
    storage.finish_run(con, run_id, "OK", races_seen=bt["n_courses"] + sum(bt["abstentions"].values()),
                       races_published=0, duration_s=bt["duree_s"])
    con.close()
    return 0


def cmd_show(args) -> int:
    """Calcule et affiche l'édition (sans stockage ni publication) pour la date J de l'instantané."""
    from .compute import compute_edition
    from .eligibility import Abstention, evaluate_race
    from .params import load_params
    snap = get_snapshot(args.sha)
    day = args.date or _date.today().isoformat()
    params = load_params()
    con = snap.connect()
    logs = snap.logs_by_race()
    mode = "backtest" if args.retro else "matin"
    n_ok = 0
    print(f"🏇 BASES — {day} — édition {args.horizon} (aperçu, commit {snap.sha[:7]}, params {params.get('version')})")
    for (race_id,) in con.execute("select race_id from races where date = ? order by meeting_number, race_number", (day,)):
        ev = evaluate_race(con, race_id, args.horizon, logs.get(race_id), mode=mode)
        if isinstance(ev, Abstention):
            print(f"  ✗ {race_id} — {ev.motif}")
            continue
        ed = compute_edition(ev, params, n_sims=args.n_sims)
        lad = ed["ladders"][ev.top_m]["echelle"]
        n_ok += 1
        print(f"\n{race_id} · {ev.scheduled_start_time} · {ev.pari_cible} (top {ev.top_m}) · {ev.active_runners} partants · {ev.confidence_stars or '?'}★")
        print(f"  Base des bases : {' - '.join(map(str, lad[3]['chevaux']))} · solidité {ed['solidite']} · P(3/3) {100 * lad[3]['p_calibree']:.0f} % · P(2/3) {100 * lad[3]['p_k_moins_1']:.0f} %")
        print("  Échelle : " + " · ".join(f"{k} base{'s' if k > 1 else ''} {100 * lad[k]['p_calibree']:.0f} %" for k in (1, 2, 3, 4)))
        print(f"  Structure : {ed['structure']['texte']}" + (f" · drapeaux {ed['flags']}" if ed["flags"] else ""))
    print(f"\n{n_ok} course(s) éligible(s).")
    con.close()
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="bases_engine", description="Service Bases Elite Turf (lecture seule du moteur).")
    p.add_argument("--sha", help="commit turf-engine à utiliser (défaut : ls-remote main)")
    p.add_argument("--db", default=str(config.DB_PATH), help="chemin de bases.db")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("contract-check", help="tests de contrat §4.4")
    s.add_argument("--date"); s.add_argument("--no-network", action="store_true", help="saute le test du manifeste public (dev hors-ligne)")
    s.set_defaults(fn=cmd_contract_check)

    s = sub.add_parser("backtest", help="rejoue l'échelle sur l'historique de l'instantané")
    s.add_argument("--since", required=True); s.add_argument("--until")
    s.add_argument("--horizon", default="T15", choices=list(config.HORIZONS))
    s.add_argument("--n-sims", type=int, default=config.N_SIMS)
    s.add_argument("--freeze-params", action="store_true", help="écrit params.json (seuils de solidité, calibrateurs)")
    s.add_argument("--params-version"); s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_backtest)

    s = sub.add_parser("show", help="affiche l'édition calculée pour une date (aperçu console)")
    s.add_argument("--date"); s.add_argument("--horizon", default="T_MATIN", choices=list(config.HORIZONS))
    s.add_argument("--n-sims", type=int, default=config.N_SIMS)
    s.add_argument("--retro", action="store_true", help="mode rétrospectif (ignore la porte publishable et l'heure)")
    s.set_defaults(fn=cmd_show)

    for name in sorted(SPRINT2):
        s = sub.add_parser(name, help="sprint 2 — non implémenté")
        s.add_argument("--date"); s.add_argument("--dry-run", action="store_true")
        s.set_defaults(fn=lambda a, n=name: (print(f"{n} : sprint 2, non implémenté (aucune publication possible).") or 3))

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except FetchError as e:
        print(f"⛔ BASES — arrêt : {e}. Aucune publication. Action requise : Steph.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
