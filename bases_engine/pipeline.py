"""Pipeline quotidien (§4, §7, §8) : `matin` et `soir`. `hebdo` arrive au sprint 3."""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import date as _date, datetime, timedelta, timezone

from . import config, storage
from .compute import compute_edition
from .contract import run_contract_checks
from .eligibility import Abstention, EligibleRace, evaluate_race
from .fetch import FetchError, ResultsClient, Snapshot, get_snapshot, ls_remote
from .notify import alert, notify
from .params import load_params
from .protocol import set_start_date
from .publish import build_day_contract, palmares_and_fiabilite
from .site import build_site
from .scoring import arrival_top, course_is_scorable, cross_check_sqlite, placed_from_course_json, score_edition
from .util import iso_utc, now_utc, race_label, race_slug


class PipelineStop(RuntimeError):
    """Arrêt bruyant : la cause a déjà été notifiée."""
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code


def is_scheduled() -> bool:
    """Exécution planifiée (cron GitHub) — seule habilitée à fixer la date de début du protocole."""
    return os.environ.get("GITHUB_EVENT_NAME") == "schedule"


def _mode() -> str:
    m = os.environ.get("PUBLICATION_MODE", "shadow").lower()
    return m if m in ("shadow", "live") else "shadow"


# ----------------------------------------------------------------------------
# MATIN
# ----------------------------------------------------------------------------

def _snapshot_for_day(day: str, sha: str | None, *, wait_s: float, max_wait: int, sleep=time.sleep) -> tuple[Snapshot | None, str]:
    """Instantané contenant la date J ; attend (5 min × 3 max) si le commit du matin n'est pas encore là."""
    tried = 0
    while True:
        snap = get_snapshot(sha)
        if any(h.get("date") == day for h in snap.historical_logs()):
            return snap, "OK"
        tried += 1
        if sha or tried > max_wait:
            return snap, "SNAPSHOT_LATE"
        sleep(wait_s)
        sha_new = ls_remote()
        if sha_new == snap.sha:
            continue
        sha = None          # nouveau commit : on le lit au prochain tour (ls-remote dans get_snapshot)


def run_matin(*, day: str | None = None, horizon: str = "T_MATIN", dry_run: bool = False, sha: str | None = None,
              network: bool = True, results_client: ResultsClient | None = None, now: datetime | None = None,
              db_path=config.DB_PATH, shadow_token: str | None = None, wait_s: float = 300.0, max_wait: int = 3,
              sleep=time.sleep, n_sims: int = config.N_SIMS, scheduled: bool | None = None,
              protocol_path=None) -> int:
    day = day or _date.today().isoformat()
    now = now or now_utc()
    mode = "dry-run" if dry_run else _mode()
    scheduled = is_scheduled() if scheduled is None else scheduled
    run_id = f"matin-{day}-{uuid.uuid4().hex[:6]}"
    t0 = time.time()
    con = storage.connect(db_path)
    storage.start_run(con, run_id, "matin", None, mode)
    try:
        # 1. Instantané
        try:
            snap, state = _snapshot_for_day(day, sha, wait_s=wait_s, max_wait=max_wait, sleep=sleep)
        except FetchError as e:
            alert("arrêt : téléchargement de l'instantané", str(e), date=day)
            raise PipelineStop(2, str(e))
        con.execute("update runs set snapshot_commit=? where run_id=?", (snap.sha, run_id))
        if state == "SNAPSHOT_LATE":
            body = f"Le commit {snap.sha[:10]} ne contient pas la date {day} (instantané du matin en retard). Aucune base ce tour ; le rattrapage prendra le relais."
            notify("alerte", f"⚠️ BASES — {day} — SNAPSHOT_LATE", body, date=day)
            storage.finish_run(con, run_id, "SNAPSHOT_LATE", races_seen=0, races_published=0, duration_s=round(time.time() - t0, 1))
            return 0

        # 2. Tests de contrat (bloquants)
        res = run_contract_checks(snap, day, results_client=results_client, network=network or results_client is not None)
        if not res.ok:
            name = res.failed[0][0]
            alert(f"arrêt : {name} a échoué sur commit {snap.sha[:10]}. Aucune publication. Action requise : Steph.",
                  res.summary(), date=day)
            storage.finish_run(con, run_id, "CONTRACT_FAILED", error=name, duration_s=round(time.time() - t0, 1))
            raise PipelineStop(2, f"test de contrat en échec : {name}")

        # 3. Début du protocole (premier matin planifié) et statut de répétition
        if scheduled and not dry_run and storage.protocol_start_date(con) is None:
            storage.set_meta(con, "protocole_debut", day)
            storage.set_meta(con, "protocole_debut_run", run_id)
            set_start_date(day, run_id, protocol_path)
            notify("info", f"📌 BASES — début du protocole pré-enregistré fixé au {day}", f"Premier matin planifié (run {run_id}). Fin : 28 jours ou 800 courses notées.", date=day)
        repetition = dry_run or storage.is_repetition(con, day)

        # Idempotence : (date, horizon, snapshot_commit)
        replay = storage.editions_exist(con, day, horizon, snap.sha)
        params = load_params()
        logs = snap.logs_by_race()
        scon = snap.connect()
        editions, abstentions = [], []
        try:
            race_ids = [r[0] for r in scon.execute("select race_id from races where date=? order by meeting_number, race_number", (day,))]
            for race_id in race_ids:
                ev = evaluate_race(scon, race_id, horizon, logs.get(race_id), mode="matin", now=now)
                if isinstance(ev, Abstention):
                    abstentions.append(ev)
                    con.execute("insert or ignore into abstentions(date, race_id, horizon, snapshot_commit, motif, recorded_at_utc) values (?,?,?,?,?,?)",
                                (day, race_id, horizon, snap.sha, ev.motif, iso_utc()))
                    continue
                eid = storage.edition_id(day, race_id, horizon, snap.sha)
                existing = con.execute("select * from bases_editions where edition_id=?", (eid,)).fetchone()
                if existing:
                    editions.append((ev, json.loads(existing["ladder_json"]), dict(existing)))
                    continue
                ed = compute_edition(ev, params, n_sims=n_sims)
                row = _edition_row(eid, ev, ed, snap.sha, mode if mode != "dry-run" else _mode(), params)
                row["repetition"] = int(repetition)
                storage.insert_edition(con, row)
                editions.append((ev, ed["ladders"], row))
            con.commit()
        finally:
            scon.close()
        n_sup = storage.supersede(con, day, horizon, snap.sha)

        # 4. Publication (JSON contrat, site, palmarès) — le déploiement est l'affaire du workflow
        published_at = None if dry_run else iso_utc()
        if published_at:
            con.execute("update bases_editions set published_at_utc=coalesce(published_at_utc, ?) where date=? and horizon=? and snapshot_commit=?",
                        (published_at, day, horizon, snap.sha))
            con.commit()
        contract = build_day_contract(con, day, horizon, snap.sha, params, mode=_mode())
        site_info = build_site(con, day, params, mode=_mode(), shadow_token=shadow_token or os.environ.get("SHADOW_TOKEN"), dry_run=dry_run)
        con.execute("insert or replace into journal_days(date, horizon, snapshot_commit, run_id, published_at_utc, mode, status) values (?,?,?,?,?,?,?)",
                    (day, horizon, snap.sha, run_id, published_at, mode, "DRY_RUN" if dry_run else "OK"))
        con.commit()

        # 5. Notification (annexe E)
        body = matin_message(day, snap.sha, contract, len(race_ids), abstentions, mode, replay=replay, superseded=n_sup, site_info=site_info, repetition=repetition)
        notify("matin", f"🏇 BASES — {day} — édition du matin ({mode})" + (" · RÉPÉTITION, hors palmarès et verdict" if repetition else ""), body, date=day)
        storage.finish_run(con, run_id, "OK", races_seen=len(race_ids), races_published=len(editions), duration_s=round(time.time() - t0, 1))
        return 0
    except PipelineStop:
        raise
    except Exception as e:  # noqa: BLE001
        storage.finish_run(con, run_id, "FAILED", error=repr(e), duration_s=round(time.time() - t0, 1))
        alert("arrêt : erreur inattendue dans matin", repr(e), date=day)
        raise
    finally:
        con.close()


def _edition_row(eid: str, ev: EligibleRace, ed: dict, sha: str, mode: str, params: dict) -> dict:
    ladders = {str(m): {str(k): v for k, v in lad["echelle"].items()} for m, lad in ed["ladders"].items()}
    target = ladders[str(ev.top_m)]
    ladder_json = {"cible": target, "top4": ladders["4"], "top5": ladders["5"]}
    if "3" in ladders:
        ladder_json["top3"] = {k: {"chevaux": v["chevaux"], "p_brute": v["p_brute"], "p_k_moins_1": v["p_k_moins_1"]} for k, v in ladders["3"].items()}
    return {
        "edition_id": eid, "date": ev.date, "race_id": ev.race_id, "race_slug": race_slug(ev.race_id),
        "horizon": ev.horizon, "top_m": ev.top_m, "computed_at_utc": iso_utc(), "snapshot_commit": sha,
        "prediction_hash": ev.prediction_hash, "lock_time_utc": ev.lock_time_utc,
        "engine8_json": json.dumps(ev.engine8), "candidates_json": json.dumps(ev.candidates),
        "lambdas_json": json.dumps(ed["lambdas"]),
        "ladder_json": json.dumps(ladder_json),
        "trios_json": json.dumps(ed["ladders"][ev.top_m]["trios"]),
        "solidite": ed["solidite"], "structure_code": ed["structure"]["code"],
        "flags_json": json.dumps(ed["flags"] + [f"pari_cible:{ev.pari_cible}", f"paris:{'|'.join(ev.paris_offerts)}", f"partants:{ev.active_runners}",
                                                f"etoiles:{ev.confidence_stars}", f"depart:{ev.scheduled_start_time}",
                                                f"depart_utc:{ev.start_time_utc}", f"discipline:{ev.discipline}"]),
        "params_version": params.get("version"), "mode": mode, "published_at_utc": None, "superseded_by": None,
    }


def matin_message(day: str, sha: str, contract: dict, n_seen: int, abstentions, mode: str, *, replay=False, superseded=0, site_info=None, repetition=False) -> str:
    d = datetime.strptime(day, "%Y-%m-%d")
    L = [f"🏇 BASES — {d:%d/%m} — édition du matin ({mode})" + (" · RÉPÉTITION (repetition = 1) : hors palmarès et hors verdict" if repetition else ""),
         f"Source moteur commit {sha[:7]} · {n_seen} courses lues · {len(contract['courses'])} éligibles · {len(contract['abstentions'])} abstentions"
         + (" · rejeu idempotent (aucun doublon)" if replay else "") + (f" · {superseded} édition(s) remplacée(s)" if superseded else ""), ""]
    from .publish import sort_courses          # même ordre que la page : Quinté+ épinglé, puis A, B, C, puis heure
    for c in sort_courses(contract["courses"]):
        e = c["echelle"]; b = c["base_des_bases"]
        L.append(f"{c['libelle']} · {c['depart_affiche']} · {c['paris_libelle']} · {c['partants']} partants")
        L.append(f"Base des bases : {' - '.join(map(str, b['chevaux']))} · solidité {b['solidite']} · P(3/3) {100 * b['p_calibree_3sur3']:.0f} % · P(2/3) {100 * b['p_calibree_2sur3']:.0f} %")
        L.append("Tous à l'arrivée : " + " · ".join(f"{100 * e[k]['p_calibree']:.0f} % ({k} sur {k})" for k in ("1", "2", "3", "4")))
        L.append("Tous sauf un : — · " + " · ".join(f"{100 * e[k]['p_k_moins_1']:.0f} % ({int(k) - 1} sur {k})" for k in ("2", "3", "4")))
        L.append(f"Structure : {c['structure_recommandee']['texte']}")
        L.append("")
    if contract["abstentions"]:
        L.append("Abstentions : " + ", ".join(f"{race_label(a['course_id']).split(' - ')[1]} {race_label(a['course_id']).split(' - ')[0]} ({a['motif_libelle']})" for a in contract["abstentions"]))
    if site_info:
        L.append(f"Site : {site_info}")
    return "\n".join(L)


# ----------------------------------------------------------------------------
# SOIR
# ----------------------------------------------------------------------------

def run_soir(*, day: str | None = None, sha: str | None = None, network: bool = True, results_client: ResultsClient | None = None,
             db_path=config.DB_PATH, shadow_token: str | None = None, lookback: int = 7, n_sims: int = config.N_SIMS,
             mesure_horizons: tuple[str, ...] = ("T90", "T30", "T15")) -> int:
    day = day or _date.today().isoformat()
    
    run_id = f"soir-{day}-{uuid.uuid4().hex[:6]}"
    t0 = time.time()
    con = storage.connect(db_path)
    storage.start_run(con, run_id, "soir", None, _mode())
    client = results_client or ResultsClient()
    try:
        try:
            snap = get_snapshot(sha)
        except FetchError as e:
            alert("arrêt : téléchargement de l'instantané (soir)", str(e), date=day)
            raise PipelineStop(2, str(e))
        con.execute("update runs set snapshot_commit=? where run_id=?", (snap.sha, run_id))
        res = run_contract_checks(snap, day, results_client=client, network=network or results_client is not None)
        # le soir, l'absence de la date J dans historical_logs n'est pas bloquante (journée sans réunion) : on ne bloque que sur le reste
        blocking = [(n, d) for n, d in res.failed if n != "historical_logs contient la date J"]
        if blocking:
            alert(f"arrêt : {blocking[0][0]} a échoué sur commit {snap.sha[:10]}. Aucune publication. Action requise : Steph.", res.summary(), date=day)
            storage.finish_run(con, run_id, "CONTRACT_FAILED", error=blocking[0][0], duration_s=round(time.time() - t0, 1))
            raise PipelineStop(2, f"test de contrat en échec : {blocking[0][0]}")

        # 1 + 2. Auto-rattrapage (complément mentor 22/09) : J puis J-1..J-7, de façon idempotente —
        #   mesure intrajournée T90/T30/T15 absente, notation non faite, contrôle croisé absent, empreinte modifiée.
        stats = {"jours_relus": [], "notees": 0, "renotees": 0, "ignorees": {}, "divergences": [], "corrections": 0, "rattrapage": {}}
        try:
            manifest = client.manifest()
        except FetchError as e:
            alert("arrêt : manifeste des résultats injoignable (soir)", str(e), date=day)
            storage.finish_run(con, run_id, "MANIFEST_FAILED", error=str(e), duration_s=round(time.time() - t0, 1))
            raise PipelineStop(2, str(e))
        journees = manifest.get("journees") or {}
        n_mesure = 0
        scon = snap.connect()
        try:
            for back in range(0, lookback + 1):
                d = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=back)).strftime("%Y-%m-%d")
                done: list[str] = []
                # mesure intrajournée : toujours pour J ; pour J-1..J-7 seulement si une édition du matin existe (comparaison matin ↔ horizon)
                if back == 0 or storage.day_has_editions(con, d, "T_MATIN"):
                    rep_d = storage.is_repetition(con, d)
                    n_new = sum(_mesure_horizon(con, snap, d, h, n_sims, repetition=rep_d) for h in mesure_horizons)
                    n_mesure += n_new
                    if n_new:
                        done.append(f"mesure intrajournée complétée ({n_new} édition(s) T90/T30/T15)")
                entry = journees.get(d)
                if entry:
                    fp = entry.get("empreinte_sha256")
                    never_scored = storage.day_scored_at(con, d) is None and (entry.get("compte_par_statut") or {}).get("DEFINITIVE", 0) > 0
                    unchecked = storage.unchecked_count(con, d)
                    changed = not (fp and fp == storage.manifest_fingerprint(con, d))
                    has_eds = con.execute("select 1 from bases_editions where date=? limit 1", (d,)).fetchone() is not None
                    if has_eds and (changed or never_scored or unchecked):
                        before = storage.results_count(con, d)
                        data = client.day(d, expected_fingerprint=fp)
                        stats["jours_relus"].append(d)
                        for course in data.get("courses") or []:
                            storage.upsert_course_statut(con, course, d)
                            _score_course(con, scon, course, stats)
                        storage.set_manifest_fingerprint(con, d, fp or data.get("empreinte_sha256") or "", data.get("nb_courses"), iso_utc(), iso_utc())
                        con.commit()
                        added = storage.results_count(con, d) - before
                        why = "notation non faite" if never_scored else ("contrôle croisé absent" if unchecked else "empreinte modifiée")
                        done.append(f"notation complétée ({why} : {added} notation(s) ajoutée(s), {unchecked} contrôlée(s) avec SQLite)")
                    elif not has_eds and changed:
                        storage.set_manifest_fingerprint(con, d, fp or "", entry.get("nb_courses"), iso_utc(), None)   # aucune édition : rien à noter
                if done and back > 0:
                    stats["rattrapage"][d] = done
        finally:
            scon.close()

        # 3. Palmarès, fiabilité, site (la page d'accueil reste sur la dernière édition publiée)
        params = load_params()
        pal, _ = palmares_and_fiabilite(con)
        last = con.execute("select max(date) from journal_days where horizon='T_MATIN' and status='OK'").fetchone()[0] or day
        site_info = build_site(con, last, params, mode=_mode(), shadow_token=shadow_token or os.environ.get("SHADOW_TOKEN"), dry_run=False)
        repetition = storage.is_repetition(con, day)
        body = soir_message(day, stats, pal, n_mesure, site_info, repetition=repetition)
        notify("soir", f"🌙 BASES — bilan du {datetime.strptime(day, '%Y-%m-%d'):%d/%m}" + (" · RÉPÉTITION, hors palmarès et verdict" if repetition else ""), body, date=day)
        if stats["divergences"]:
            alert("divergence JSON public ↔ SQLite (courses non notées)", "\n".join(stats["divergences"]), date=day)
        storage.finish_run(con, run_id, "OK", races_seen=stats["notees"] + stats["renotees"], races_published=n_mesure, duration_s=round(time.time() - t0, 1))
        return 0
    except PipelineStop:
        raise
    except Exception as e:  # noqa: BLE001
        storage.finish_run(con, run_id, "FAILED", error=repr(e), duration_s=round(time.time() - t0, 1))
        alert("arrêt : erreur inattendue dans soir", repr(e), date=day)
        raise
    finally:
        con.close()


def _mesure_horizon(con, snap: Snapshot, day: str, horizon: str, n_sims: int, *, repetition: bool = False) -> int:
    """Éditions rétrospectives à l'horizon de mesure (T15) pour la journée J : stockées (mode `mesure`), jamais publiées."""
    params = load_params()
    logs = snap.logs_by_race()
    scon = snap.connect()
    n = 0
    try:
        for (race_id,) in scon.execute("select race_id from races where date=? order by meeting_number, race_number", (day,)):
            eid = storage.edition_id(day, race_id, horizon, snap.sha)
            if con.execute("select 1 from bases_editions where edition_id=?", (eid,)).fetchone():
                continue
            ev = evaluate_race(scon, race_id, horizon, logs.get(race_id), mode="backtest")
            if isinstance(ev, Abstention):
                con.execute("insert or ignore into abstentions(date, race_id, horizon, snapshot_commit, motif, recorded_at_utc) values (?,?,?,?,?,?)",
                            (day, race_id, horizon, snap.sha, ev.motif, iso_utc()))
                continue
            ed = compute_edition(ev, params, n_sims=n_sims)
            row = _edition_row(eid, ev, ed, snap.sha, "mesure", params)
            row["repetition"] = int(repetition)
            storage.insert_edition(con, row)
            n += 1
        con.commit()
    finally:
        scon.close()
    return n


def _score_course(con, scon, course: dict, stats: dict, *, allow_provisoire: bool = False) -> None:
    race_id = course.get("course_id")
    eds = [dict(r) for r in con.execute("select * from bases_editions where race_id=? and superseded_by is null", (race_id,))]
    if not eds:
        return
    ok, why = course_is_scorable(course, allow_provisoire=allow_provisoire)
    if not ok:
        stats["ignorees"][why] = stats["ignorees"].get(why, 0) + 1
        return
    version = int((course.get("correction") or {}).get("version") or 1)
    nb_corr = int((course.get("correction") or {}).get("nb_corrections") or 0)
    for ed in eds:
        ladders = json.loads(ed["ladder_json"])
        for m in (4, 5):
            prev = con.execute("select statut, checked_against_sqlite from bases_results where race_id=? and result_version=? and top_m=? and horizon=?",
                               (race_id, version, m, ed["horizon"])).fetchone()
            if prev and prev["statut"] == (course.get("statut") or {}).get("code") and (prev["checked_against_sqlite"] or scon is None):
                continue                                       # déjà notée à l'identique
            placed, arrivee = placed_from_course_json(course, m)
            check, detail = cross_check_sqlite(scon, race_id, arrivee, m) if scon is not None else (None, "PASSE_HORAIRE")
            if check is False:
                stats["divergences"].append(f"{race_id} (m={m}) : {detail}")
                continue
            hits = score_edition(ladders[f"top{m}"], placed)
            k3 = ladders[f"top{m}"]["3"]
            prior = con.execute("select 1 from bases_results where race_id=? and top_m=? and horizon=?", (race_id, m, ed["horizon"])).fetchone()
            rep = int(bool(ed.get("repetition")) or storage.is_repetition(con, ed["date"]))
            nps = sorted(int(x["num"]) for x in course.get("non_partants") or [])
            con.execute("""insert or replace into bases_results(race_id, result_version, arrivee_json, top_m, hit_k1, hit_k2, hit_k3, hit_k4, hit_2of3,
                           scored_at_utc, source, checked_against_sqlite, edition_id, hits_json, solidite, p_calibree_k3, horizon, statut, repetition, non_partants_json, finalite)
                           values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (race_id, version, json.dumps(arrivee), m, hits["hit_k1"], hits["hit_k2"], hits["hit_k3"], hits["hit_k4"], hits["hit_2of3"],
                         iso_utc(), "RESULTATS_JSON", 1 if check else 0, ed["edition_id"], json.dumps(hits),
                         ed["solidite"] if m == ed["top_m"] else None, k3.get("p_calibree"), ed["horizon"],
                         (course.get("statut") or {}).get("code"), rep, json.dumps(nps), (course.get("statut") or {}).get("finalite")))
            if m == ed["top_m"] and ed["horizon"] == "T_MATIN":
                if prior:
                    stats["renotees"] += 1
                    if nb_corr:
                        stats["corrections"] += 1
                else:
                    stats["notees"] += 1


def soir_message(day: str, stats: dict, pal: dict, n_mesure: int, site_info=None, repetition=False) -> str:
    d = datetime.strptime(day, "%Y-%m-%d")
    today = pal.get("par_jour", {}).get(day, {})
    L = [f"🌙 BASES — bilan du {d:%d/%m}" + (" · RÉPÉTITION (repetition = 1) : hors palmarès et hors verdict" if repetition else "") + f" : {today.get('n', 0)} courses notées"
         + (f" · 3/3 : {today.get('k3', 0)} ({100 * today.get('taux_k3', 0):.0f} %) · 2/3 : {today.get('k2of3', 0)} ({100 * today.get('taux_2of3', 0):.0f} %)" if today.get("n") else "")
         + f" · corrections : {stats['corrections']}"]
    if today.get("par_solidite"):
        L.append("Solidité : " + " · ".join(f"{s} {v['k3']}/{v['n']}" for s, v in today["par_solidite"].items() if v["n"]))
    g = pal.get("global", {})
    if g.get("n"):
        L.append(f"Palmarès depuis le {pal.get('depuis')} ({g['n']} courses) : 1 base {100 * g['taux_k1']:.0f} % · 2 bases {100 * g['taux_k2']:.0f} % · 3 bases {100 * g['taux_k3']:.0f} % · 4 bases {100 * g['taux_k4']:.0f} % · ≥ 2/3 {100 * g['taux_2of3']:.0f} % · abstentions {pal.get('abstentions', 0)}")
    L.append(f"Journées relues : {', '.join(stats['jours_relus']) or 'aucune (empreintes inchangées)'} · notées {stats['notees']} · re-notées {stats['renotees']} · mesure intrajournée T90/T30/T15 : {n_mesure} édition(s), jamais publiées")
    if stats.get("rattrapage"):
        for d2, done in sorted(stats["rattrapage"].items(), reverse=True):
            L.append(f"Rattrapage — journée du {datetime.strptime(d2, '%Y-%m-%d'):%d/%m} : " + " ; ".join(done))
    else:
        L.append("Rattrapage : rien à compléter sur J-1..J-7")
    if stats["ignorees"]:
        L.append("Non notées : " + ", ".join(f"{k} = {v}" for k, v in stats["ignorees"].items()))
    if stats["divergences"]:
        L.append("⚠️ Divergences JSON ↔ SQLite : " + " ; ".join(stats["divergences"]))
    if site_info:
        L.append(f"Site : {site_info}")
    return "\n".join(L)


# ----------------------------------------------------------------------------
# RESULTATS (passe horaire, sprint 4)
# ----------------------------------------------------------------------------

def run_resultats(*, day: str | None = None, network: bool = True, results_client: ResultsClient | None = None, db_path=config.DB_PATH,
                  shadow_token: str | None = None) -> int:
    """Lit index.json ; relit la journée seulement si l'empreinte a changé ; note DEFINITIVE et PROVISOIRE (statut affiché tel quel,
    palmarès inchangé : DEFINITIVE + VERIFIEE_PMU seulement) ; régénère la page du jour. Aucun instantané moteur téléchargé
    (budget), donc pas de contrôle croisé : `soir` relira et contrôlera ces journées."""
    day = day or _date.today().isoformat()
    run_id = f"resultats-{day}-{uuid.uuid4().hex[:6]}"
    t0 = time.time()
    con = storage.connect(db_path)
    storage.start_run(con, run_id, "resultats", None, _mode())
    client = results_client or ResultsClient()
    try:
        try:
            manifest = client.manifest()
        except FetchError as e:
            alert("arrêt : manifeste des résultats injoignable (resultats)", str(e), date=day)
            storage.finish_run(con, run_id, "MANIFEST_FAILED", error=str(e), duration_s=round(time.time() - t0, 1))
            raise PipelineStop(2, str(e))
        entry = (manifest.get("journees") or {}).get(day)
        stats = {"jours_relus": [], "notees": 0, "renotees": 0, "ignorees": {}, "divergences": [], "corrections": 0}
        relu = False
        if entry:
            fp = entry.get("empreinte_sha256")
            if not (fp and fp == storage.manifest_fingerprint(con, day)):
                data = client.day(day, expected_fingerprint=fp)
                relu = True
                for course in data.get("courses") or []:
                    storage.upsert_course_statut(con, course, day)
                    _score_course(con, None, course, stats, allow_provisoire=True)
                storage.set_manifest_fingerprint(con, day, fp or data.get("empreinte_sha256") or "", data.get("nb_courses"), iso_utc(), iso_utc())
                con.commit()
        params = load_params()
        last = con.execute("select max(date) from journal_days where horizon='T_MATIN' and status='OK'").fetchone()[0] or day
        site_info = build_site(con, last, params, mode=_mode(), shadow_token=shadow_token or os.environ.get("SHADOW_TOKEN"), dry_run=False)
        res = storage.display_results_for_day(con, day)
        n_def = sum(1 for r in res.values() if r.get("statut") == "DEFINITIVE")
        n_prov = sum(1 for r in res.values() if r.get("statut") == "PROVISOIRE")
        n3 = sum(1 for r in res.values() if r.get("hit_k3"))
        body = (f"⏱ BASES — {datetime.strptime(day, '%Y-%m-%d'):%d/%m} — passe horaire : "
                + ("journée relue (empreinte modifiée)" if relu else ("journée absente du manifeste" if not entry else "empreinte inchangée, rien à relire"))
                + f" · notées {n_def} définitives + {n_prov} provisoires · 3/3 : {n3}"
                + (" · " + ", ".join(f"{k} = {v}" for k, v in stats["ignorees"].items()) if stats["ignorees"] else "")
                + f"\nSite : {site_info}")
        notify("resultats", f"⏱ BASES — {day} — passe horaire résultats", body, date=day)
        storage.finish_run(con, run_id, "OK", races_seen=len(res), races_published=0, duration_s=round(time.time() - t0, 1))
        return 0
    except PipelineStop:
        raise
    except Exception as e:  # noqa: BLE001
        storage.finish_run(con, run_id, "FAILED", error=repr(e), duration_s=round(time.time() - t0, 1))
        alert("arrêt : erreur inattendue dans resultats", repr(e), date=day)
        raise
    finally:
        con.close()
