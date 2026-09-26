"""CLI : python -m bases_engine <commande> [options]."""
from __future__ import annotations

import argparse
from pathlib import Path
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
    from datetime import datetime, timezone
    from .pipeline import source_freshness
    snap = get_snapshot()
    day = args.date or _date.today().isoformat()
    res = run_contract_checks(snap, day, results_client=_results_client(args.no_network), network=not args.no_network)
    ok_f, motif_f, warns_f = source_freshness(snap, day, datetime.now(timezone.utc))
    fraicheur = ("✅ garde de fraîcheur : T_MATIN du jour présents, poussée postérieure au verrou" if ok_f else f"⚠️ garde de fraîcheur : {motif_f}") + \
                "".join(f"\n⚠️ {w}" for w in warns_f)
    head = f"Contract-check — {snap.header()} — date {day}\n✅ empreinte sha256 = métadonnée · PRAGMA integrity_check = ok"
    print(head); print(res.summary()); print(fraicheur)
    if not res.ok:
        msg = f"⛔ BASES — arrêt : {res.failed[0][0]} a échoué sur la base {snap.sha[:12]}. Aucune publication. Action requise : Steph."
        print("\n" + msg)
        alert(f"contract-check : {res.failed[0][0]} a échoué sur la base {snap.sha[:12]}", f"{head}\n{res.summary()}\n{fraicheur}", date=day)
        return 2
    tail = "OK — tous les tests de contrat exécutés sont verts." + (f" · {len(res.warnings)} avertissement(s) non bloquant(s)" if res.warnings else "") + (" (test réseau sauté)" if res.skipped else "")
    print("\n" + tail)
    step_summary(f"✅ BASES — contract-check {day}", f"{head}\n{res.summary()}\n{fraicheur}\n{tail}")
    return 0


def cmd_backtest(args) -> int:
    from .report import backtest_markdown
    from .scoring import backtest
    from .params import load_params, save_params
    snap = get_snapshot()
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


def cmd_parite_porte(args) -> int:
    """Test de parité de la porte sur la base R2 (lancé à chaque modification du code de la porte et avec l'hebdo)."""
    from .notify import step_summary as _summary
    from .porte import parite
    snap = get_snapshot()
    con = snap.connect()
    try:
        ok, lignes, _ = parite(con)
    finally:
        con.close()
    corps = "\n".join([snap.header(), *lignes])
    print(corps)
    if not ok:
        print(f"::error title=Parité de porte::{lignes[1]}")
    _summary(f"{'✅' if ok else '⛔'} BASES — parité de la porte", corps)
    return 0 if ok else 1


def cmd_annexe_empreintes(args) -> int:
    """Annexe factuelle (décision du mentor du 25/09/2026, §3) : compare les prediction_hash des T_MATIN de la journée entre
    la copie Git figée (référence extraite avant la vérification) et la base R2. Règle fixée avant la vérification : une course
    dont l'empreinte diffère est retirée du palmarès, les autres comptent."""
    import json as _json
    from .notify import step_summary as _summary
    day = args.date
    ref_path = Path(args.reference) if args.reference else config.RAPPORTS_DIR / "annexe" / f"{day}_empreintes_copie_git.json"
    ref = _json.loads(ref_path.read_text(encoding="utf-8"))
    snap = get_snapshot()
    scon = snap.connect()
    r2 = {r["race_id"]: r["prediction_hash"] for r in scon.execute(
        """select p.race_id, p.prediction_hash from predictions p join races r using(race_id)
           where r.date=? and p.engine_name=? and p.horizon='T_MATIN'""", (day, config.ENGINE_NAME))}
    scon.close()
    con = storage.connect(args.db)
    lignes, diff = [], []
    for race_id, h_git in sorted(ref["empreintes"].items()):
        h_r2 = r2.get(race_id)
        ok = h_r2 == h_git
        lignes.append(f"| {race_id} | {h_git[:16]}… | {(h_r2 or 'absente')[:16]}{'…' if h_r2 else ''} | {'identique' if ok else 'DIFFÉRENTE'} |")
        if not ok:
            diff.append(race_id)
            storage.exclure_du_palmares(con, race_id, day, "empreinte T_MATIN R2 ≠ copie Git (annexe du protocole)")
    ed = con.execute("""select count(*) n, min(computed_at_utc) c0, max(computed_at_utc) c1, min(published_at_utc) p0, max(published_at_utc) p1,
                               count(distinct snapshot_commit) nsc, max(snapshot_commit) sc
                        from bases_editions where date=? and horizon='T_MATIN' and superseded_by is null""", (day,)).fetchone()
    con.close()
    corps = [f"# Annexe — empreintes des T_MATIN du {day} : copie Git figée vs base R2", "",
             f"- Référence : `{ref_path.name}` ({len(ref['empreintes'])} lignes, {ref.get('source', 'copie Git')}).",
             f"- Base R2 lue : {snap.header()}.",
             f"- Résultat : {len(ref['empreintes']) - len(diff)} identique(s), {len(diff)} différente(s)" + (f" : {', '.join(diff)} retirée(s) du palmarès." if diff else "."),
             f"- Éditions du {day} (non remplacées) : {ed['n']}, calculées entre {ed['c0']} et {ed['c1']}, publiées entre {ed['p0']} et {ed['p1']}, "
             f"sur {ed['nsc']} instantané(s) ({str(ed['sc'])[:10]}). Aucune n'a été recalculée ; les pages régénérées ensuite ne font que les réafficher.",
             "", "| Course | Copie Git | R2 | Verdict |", "|---|---|---|---|", *lignes]
    out = config.RAPPORTS_DIR / "annexe" / f"{day}_verification_empreintes.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(corps) + "\n", encoding="utf-8")
    print("\n".join(corps))
    _summary(f"{'✅' if not diff else '⚠️'} BASES — annexe : empreintes T_MATIN du {day}", "\n".join(corps[2:6]))
    return 0


def cmd_show(args) -> int:
    """Calcule et affiche l'édition (sans stockage ni publication) pour la date J de l'instantané."""
    from .compute import compute_edition
    from .eligibility import Abstention, evaluate_race
    from .params import load_params
    snap = get_snapshot()
    day = args.date or _date.today().isoformat()
    params = load_params()
    con = snap.connect()
    mode = "backtest" if args.retro else "matin"
    n_ok = 0
    print(f"🏇 BASES — {day} — édition {args.horizon} (aperçu, {snap.header()}, params {params.get('version')})")
    for (race_id,) in con.execute("select race_id from races where date = ? order by meeting_number, race_number", (day,)):
        ev = evaluate_race(con, race_id, args.horizon, mode=mode)
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
        return run_matin(day=args.date, horizon=args.horizon, dry_run=args.dry_run, network=not args.no_network,
                         results_client=_results_client(args.no_network), now=now, db_path=args.db, shadow_token=args.shadow_token,
                         n_sims=args.n_sims, declencheur=args.declencheur)
    except PipelineStop as e:
        print(f"⛔ BASES — arrêt : {e}", file=sys.stderr)
        return e.code


def cmd_soir(args) -> int:
    from .pipeline import PipelineStop, run_soir
    try:
        return run_soir(day=args.date, network=not args.no_network, results_client=_results_client(args.no_network),
                        db_path=args.db, shadow_token=args.shadow_token, n_sims=args.n_sims, declencheur=args.declencheur)
    except PipelineStop as e:
        print(f"⛔ BASES — arrêt : {e}", file=sys.stderr)
        return e.code


def cmd_resultats(args) -> int:
    from .pipeline import PipelineStop, run_resultats
    try:
        return run_resultats(day=args.date, network=not args.no_network, results_client=_results_client(args.no_network),
                             db_path=args.db, shadow_token=args.shadow_token, declencheur=args.declencheur)
    except PipelineStop as e:
        print(f"⛔ BASES — arrêt : {e}", file=sys.stderr)
        return e.code


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="bases_engine", description="Service Bases Elite Turf (lecture seule du moteur).")
    p.add_argument("--db", default=str(config.DB_PATH), help="chemin de bases.db")
    p.add_argument("--declencheur", choices=["manuel", "cron", "metronome"], default=None,
                   help="origine de la passe (défaut : cron si GITHUB_EVENT_NAME=schedule, sinon manuel) ; cron et metronome = passe planifiée")
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
    s.set_defaults(fn=cmd_matin)

    s = sub.add_parser("soir", help="notation J et J-7..J-1 sur le JSON public, mesure T15, palmarès, site, journal")
    s.add_argument("--date"); s.add_argument("--no-network", action="store_true"); s.add_argument("--shadow-token")
    s.add_argument("--n-sims", type=int, default=config.N_SIMS)
    s.set_defaults(fn=cmd_soir)

    s = sub.add_parser("resultats", help="passe horaire : relit la journée si l'empreinte a changé, note définitives et provisoires, régénère la page")
    s.add_argument("--date"); s.add_argument("--no-network", action="store_true"); s.add_argument("--shadow-token")
    s.set_defaults(fn=cmd_resultats)

    s = sub.add_parser("hebdo", help="lundi : recalibration (k, cible) hors répétitions, rapport hebdomadaire rapports/AAAA-Www.md")
    s.add_argument("--date"); s.add_argument("--sans-recalibration", action="store_true")
    s.set_defaults(fn=lambda a: __import__("bases_engine.hebdo", fromlist=["run_hebdo"]).run_hebdo(day=a.date, db_path=a.db, recalibrer=not a.sans_recalibration, declencheur=a.declencheur))

    s = sub.add_parser("parite-porte", help="parité de la porte sur la base R2 : 21/09/2026 rejoué course par course (20 éligibles, 12 abstentions)")
    s.set_defaults(fn=cmd_parite_porte)

    s = sub.add_parser("annexe-empreintes", help="annexe du protocole : prediction_hash des T_MATIN d'une journée, copie Git (référence figée) vs base R2")
    s.add_argument("--date", default="2026-09-24")
    s.add_argument("--reference", default=None, help="JSON de référence (défaut : rapports/annexe/<date>_empreintes_copie_git.json)")
    s.set_defaults(fn=cmd_annexe_empreintes)

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
