"""CLI : python -m bases_engine <commande> [options]."""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import date as _date

from . import config, storage
from .fetch import FetchError, get_snapshot
from .notify import alert, step_summary
from .util import iso_utc



def cmd_contract_check(args) -> int:
    from .contract import run_contract_checks
    snap = get_snapshot(args.sha)
    day = args.date or _date.today().isoformat()
    res = run_contract_checks(snap, day, results_client=_results_client(args.no_network), network=not args.no_network)
    head = f"Contract-check — commit {snap.sha[:10]} — date {day}"
    print(head); print(res.summary())
    if not res.ok:
        msg = f"⛔ BASES — arrêt : {res.failed[0][0]} a échoué sur commit {snap.sha[:10]}. Aucune publication. Action requise : Steph."
        print("\n" + msg)
        alert(f"contract-check : {res.failed[0][0]} a échoué sur commit {snap.sha[:10]}", res.summary(), date=day)
        return 2
    tail = "OK — tous les tests de contrat exécutés sont verts." + (" (test réseau sauté)" if res.skipped else "")
    print("\n" + tail)
    step_summary(f"✅ BASES — contract-check {day}", f"{head}\n{res.summary()}\n{tail}")
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
    a5 = bt["par_cible"][5]
    step_summary(f"📊 BASES — backtest {args.horizon} depuis {args.since}",
                 f"commit {snap.sha[:10]} · {bt['n_courses']} courses · {bt['duree_s']} s\n"
                 + (f"top 5 : 1 base {100 * a5['taux_k1']:.1f} % · 2 bases {100 * a5['taux_k2']:.1f} % · 3 bases {100 * a5['taux_k3']:.1f} % · 4 bases {100 * a5['taux_k4']:.1f} % · ≥ 2/3 {100 * a5['taux_2of3']:.1f} %\n" if a5.get("n") else "")
                 + f"rapport : {md_path.relative_to(config.ROOT)}")

    if args.freeze_params:
        version = args.params_version or f"{stamp}.1"
        params = {
            "version": version, "valid_from": stamp, "lambdas": bt["lambdas"],
            "seuils_solidite": {f"top{m}": bt["par_cible"][m]["seuils_solidite"] for m in (4, 5) if bt["par_cible"][m].get("seuils_solidite")},
            "shrink": config.SHRINK, "calibration_paliers": config.CALIB_LEVELS, "n_sims": config.N_SIMS,
            "calibration": {}, "source": {"snapshot_commit": snap.sha, "horizon": args.horizon, "since": args.since, "n_courses": bt["n_courses"]},
            "note": (f"Gelé le {stamp} par `backtest --since {args.since} --horizon {args.horizon}` sur {bt['n_courses']} courses. "
                     "Lambdas = littérature (pas de ré-estimation avant 1 500 courses). Seuils = terciles de P(3/3) recalibrée. "
                     "Recalibration par paliers selon n (fixe 0,85 < 150 ≤ ratio borné [0,60 ; 1,00] < 300 ≤ logit-linéaire < 1000 ≤ isotonique). "
                     "Inchangés jusqu'au verdict du protocole pré-enregistré ; recalibration hebdomadaire = nouvelle version."),
        }
        for m in (4, 5):
            for key, entry in bt["par_cible"][m].get("calibration", {}).items():
                cal = {kk: v for kk, v in entry.items() if kk in ("n", "mode", "facteur", "a", "b", "knots_x", "knots_y")}
                params["calibration"][key] = cal
                storage.insert_calibration(con, iso_utc(), int(key[1]), m, entry["n"], cal, version)
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


def _results_client(no_network: bool):
    from .fetch import ResultsClient
    if no_network:
        local = os.environ.get("BASES_RESULTS_LOCAL_DIR")
        if local:
            return ResultsClient(base_url=f"file://{local}")
    return None


def cmd_matin(args) -> int:
    from datetime import datetime, timezone
    from .pipeline import PipelineStop, run_matin
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")).astimezone(timezone.utc) if args.now else None
    try:
        return run_matin(day=args.date, horizon=args.horizon, dry_run=args.dry_run, sha=args.sha, network=not args.no_network,
                         results_client=_results_client(args.no_network), now=now, db_path=args.db, shadow_token=args.shadow_token,
                         n_sims=args.n_sims, max_wait=0 if args.no_wait else 3)
    except PipelineStop as e:
        print(f"⛔ BASES — arrêt : {e}", file=sys.stderr)
        return e.code


def cmd_soir(args) -> int:
    from .pipeline import PipelineStop, run_soir
    try:
        return run_soir(day=args.date, sha=args.sha, network=not args.no_network, results_client=_results_client(args.no_network),
                        db_path=args.db, shadow_token=args.shadow_token, n_sims=args.n_sims)
    except PipelineStop as e:
        print(f"⛔ BASES — arrêt : {e}", file=sys.stderr)
        return e.code


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

    s = sub.add_parser("matin", help="édition du matin (§4) : contrat, éligibilité, calcul, stockage, site, journal")
    s.add_argument("--date"); s.add_argument("--horizon", default="T_MATIN", choices=list(config.HORIZONS))
    s.add_argument("--dry-run", action="store_true", help="tout sauf la publication (published_at_utc vide, déploiement sauté)")
    s.add_argument("--no-network", action="store_true"); s.add_argument("--shadow-token")
    s.add_argument("--now", help="instant de calcul UTC (tests), ex. 2026-09-21T09:05:00Z")
    s.add_argument("--n-sims", type=int, default=config.N_SIMS)
    s.add_argument("--no-wait", action="store_true", help="ne pas attendre l'instantané du matin (SNAPSHOT_LATE immédiat)")
    s.set_defaults(fn=cmd_matin)

    s = sub.add_parser("soir", help="notation J et J-7..J-1 sur le JSON public, mesure T15, palmarès, site, journal")
    s.add_argument("--date"); s.add_argument("--no-network", action="store_true"); s.add_argument("--shadow-token")
    s.add_argument("--n-sims", type=int, default=config.N_SIMS)
    s.set_defaults(fn=cmd_soir)

    s = sub.add_parser("hebdo", help="lundi : recalibration (k, cible) hors répétitions, rapport hebdomadaire rapports/AAAA-Www.md")
    s.add_argument("--date"); s.add_argument("--sans-recalibration", action="store_true")
    s.set_defaults(fn=lambda a: __import__("bases_engine.hebdo", fromlist=["run_hebdo"]).run_hebdo(day=a.date, sha=a.sha, db_path=a.db, recalibrer=not a.sans_recalibration))

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except FetchError as e:
        alert(f"arrêt : {args.command} — {e}. Aucune publication. Action requise : Steph.", str(e))
        print(f"⛔ BASES — arrêt : {e}. Aucune publication. Action requise : Steph.", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 — filet de sécurité : la cause va toujours dans le résumé de job (§6.2)
        import traceback
        alert(f"échec inattendu de {args.command} : {e!r}", traceback.format_exc())
        raise


if __name__ == "__main__":
    sys.exit(main())
