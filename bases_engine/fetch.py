"""Lecture des sources : base vivante du moteur sur R2 (lecture seule) et JSON publics de résultats.

Contrat de lecture (décision du mentor du 25/09/2026) : l'objet `turf_bench.db` du bucket `turf-engine-data`
uniquement, empreinte sha256 vérifiée contre la métadonnée posée par le moteur, `PRAGMA integrity_check`
avant tout calcul ; aucun repli sur la copie Git, aucune lecture du dépôt turf-engine. Au plus 4
téléchargements par jour. Métadonnées et contenu lus dans la même réponse GET ; écart d'empreinte : jusqu'à
3 nouvelles lectures à 30 s, puis job rouge.
Résultats publics à ≤ 1 requête par minute ; aucun HTML.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from . import config
from .util import now_utc, sha256_json_compact


class FetchError(RuntimeError):
    pass


# ----------------------------------------------------------------------------
# Base vivante du moteur (R2)
# ----------------------------------------------------------------------------

def _budget_path(cache_dir: Path) -> Path:
    return cache_dir / "downloads.log"


def _downloads_today(cache_dir: Path, filename: str) -> int:
    p = _budget_path(cache_dir)
    if not p.exists():
        return 0
    today = now_utc().strftime("%Y-%m-%d")
    return sum(1 for line in p.read_text().splitlines()
               if line.startswith(today) and line.rstrip().endswith(" " + filename))


def _record_download(cache_dir: Path, filename: str, ident: str) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    with _budget_path(cache_dir).open("a") as f:
        f.write(f"{now_utc().strftime('%Y-%m-%dT%H:%M:%SZ')} {ident} {filename}\n")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def integrity_check(db_path: Path) -> str:
    """`PRAGMA integrity_check` en lecture seule : « ok » ou le premier message d'erreur."""
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            return str(con.execute("pragma integrity_check").fetchone()[0])
        finally:
            con.close()
    except sqlite3.DatabaseError as e:
        return f"base illisible : {e}"


def _norm_meta(meta: dict | None) -> dict:
    """Métadonnées posées par le moteur (sha256, counts, pushed-at, run-id, commit), tolérantes aux absences."""
    m = {str(k).lower().removeprefix("x-amz-meta-"): v for k, v in (meta or {}).items()}
    return {"sha256": (m.get("sha256") or "").strip().lower() or None, "pushed_at": m.get("pushed-at") or m.get("pushed_at"),
            "run_id": m.get("run-id") or m.get("run_id"), "commit": m.get("commit"), "counts": m.get("counts")}


@dataclass
class Snapshot:
    """Base du moteur lue pour une passe : identifiée par son empreinte sha256, jamais modifiée."""
    sha: str                      # sha256 de la base lue (identifiant d'instantané, stocké dans snapshot_commit)
    dir: Path
    db_path: Path
    source: dict = field(default_factory=dict)   # origine, sha256, pushed_at, run_id, commit, counts

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con

    def header(self) -> str:
        return source_header(self.source)


def source_header(source: dict | None) -> str:
    """« Source moteur R2 · sha256 <12 car.> · poussée <pushed-at> · run <run-id> · commit <commit> » (champs absents omis)."""
    s = source or {}
    if s.get("origine") == "git":                                   # éditions antérieures à la bascule R2
        return f"Source moteur copie Git · commit {str(s.get('commit') or '?')[:10]}"
    parts = [f"Source moteur {'R2' if s.get('origine') == 'r2' else 'locale'}", f"sha256 {str(s.get('sha256') or '?')[:12]}"]
    for label, key in (("poussée", "pushed_at"), ("run", "run_id"), ("commit", "commit")):
        if s.get(key):
            parts.append(f"{label} {s[key]}")
    return " · ".join(parts)


def _verify(db: Path, expected_sha: str | None, *, where: str) -> str:
    actual = sha256_file(db)
    if not expected_sha:
        raise FetchError(f"{where} : métadonnée sha256 absente, empreinte invérifiable — aucune édition")
    if actual != expected_sha:
        raise FetchError(f"{where} : empreinte {actual[:12]}… ≠ métadonnée {expected_sha[:12]}… — aucune édition")
    ic = integrity_check(db)
    if ic != "ok":
        raise FetchError(f"{where} : PRAGMA integrity_check = {ic!r} — aucune édition")
    return actual


def r2_client():
    """Client S3 du point d'accès R2 du compte (secrets lus dans l'environnement du job, jamais dans la session)."""
    account, key_id, secret = (os.environ.get(v) for v in (config.R2_ACCOUNT_ENV, config.R2_KEY_ID_ENV, config.R2_SECRET_ENV))
    missing = [n for n, v in ((config.R2_ACCOUNT_ENV, account), (config.R2_KEY_ID_ENV, key_id), (config.R2_SECRET_ENV, secret)) if not v]
    if missing:
        raise FetchError(f"secrets R2 absents : {', '.join(missing)}")
    import boto3                                   # import tardif : les tests utilisent un faux client
    from botocore.config import Config
    return boto3.client("s3", endpoint_url=f"https://{account}.r2.cloudflarestorage.com", aws_access_key_id=key_id,
                        aws_secret_access_key=secret, region_name="auto",
                        config=Config(retries={"max_attempts": 3, "mode": "standard"}, connect_timeout=15, read_timeout=300))


def get_snapshot(*, client=None, cache_dir: Path | None = None, local_dir: str | Path | None = None, sleep=time.sleep) -> Snapshot:
    """Base vivante du moteur (R2), vérifiée ; ou répertoire local (`local_dir` / BASES_LOCAL_SNAPSHOT_DIR : tests, hors-ligne).

    Un répertoire local contient `turf_bench.db` et `source.json` (mêmes clés que les métadonnées R2) ; la même
    vérification d'empreinte et d'intégrité s'applique.
    """
    cache_dir = Path(cache_dir or config.CACHE_DIR)
    local_dir = local_dir if local_dir is not None else config.LOCAL_SNAPSHOT_DIR
    if local_dir:
        d = Path(local_dir)
        db = d / config.DB_FILENAME
        src = d / "source.json"
        if not db.exists() or not src.exists():
            raise FetchError(f"instantané local incomplet dans {d} (turf_bench.db + source.json)")
        meta = _norm_meta(json.loads(src.read_text(encoding="utf-8")))
        sha = _verify(db, meta["sha256"], where="base locale")
        return Snapshot(sha, d, db, {"origine": "local", **meta, "sha256": sha})
    client = client or r2_client()
    label = f"r2:{config.R2_OBJECT}"
    tmp = cache_dir / "r2" / (config.DB_FILENAME + ".part")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tentative = 0
    while True:
        # Métadonnées et contenu dans la même réponse GET (jamais HEAD puis GET : un push entre les deux créerait un faux écart).
        if _downloads_today(cache_dir, label) >= config.DOWNLOAD_BUDGET_PER_DAY:
            raise FetchError(f"budget de téléchargement épuisé aujourd'hui pour {label} ({config.DOWNLOAD_BUDGET_PER_DAY}/jour)")
        try:
            obj = client.get_object(Bucket=config.R2_BUCKET, Key=config.R2_OBJECT)
            meta = _norm_meta(obj.get("Metadata"))
            body = obj["Body"]
            with tmp.open("wb") as f:
                for chunk in iter(lambda: body.read(1 << 20), b""):
                    f.write(chunk)
        except Exception as e:  # noqa: BLE001 — NoSuchKey (clé renommée), accès refusé, réseau : job rouge, message sans secret
            tmp.unlink(missing_ok=True)
            raise FetchError(f"lecture R2 impossible ({config.R2_BUCKET}/{config.R2_OBJECT}) : {type(e).__name__}: {e}") from e
        _record_download(cache_dir, label, meta["sha256"] or "sans-empreinte")
        if not meta["sha256"]:
            tmp.unlink(missing_ok=True)
            raise FetchError("base R2 : métadonnée sha256 absente, empreinte invérifiable — aucune édition")
        if sha256_file(tmp) == meta["sha256"] or tentative >= config.R2_MAX_RETRIES:
            break
        tentative += 1                                              # base remplacée pendant la lecture : nouvelle lecture
        sleep(config.R2_RETRY_DELAY_S)
    try:
        sha = _verify(tmp, meta["sha256"], where=f"base R2 (après {tentative + 1} lecture(s))")
    except FetchError:
        tmp.unlink(missing_ok=True)
        raise
    dest = cache_dir / "r2" / sha / config.DB_FILENAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp.replace(dest)
    (dest.parent / "source.json").write_text(json.dumps({"sha256": sha, "pushed-at": meta["pushed_at"], "run-id": meta["run_id"],
                                                          "commit": meta["commit"], "counts": meta["counts"]}, ensure_ascii=False), encoding="utf-8")
    return Snapshot(sha, dest.parent, dest, {"origine": "r2", **meta, "sha256": sha})


# ----------------------------------------------------------------------------
# Résultats publics (JSON documentés par RESULTATS_JSON.md)
# ----------------------------------------------------------------------------

class ResultsClient:
    """Client des JSON `/resultats/` : ≤ 1 requête par minute, empreinte vérifiée."""

    def __init__(self, base_url: str = config.RESULTS_BASE_URL, min_interval_s: float = config.RESULTS_MIN_INTERVAL_S,
                 session: requests.Session | None = None, sleep=time.sleep, clock=time.monotonic):
        self.base_url = base_url.rstrip("/")
        self.min_interval_s = min_interval_s
        self.session = session or requests.Session()
        self._sleep, self._clock = sleep, clock
        self._last: float | None = None
        self.requests_made = 0

    def _throttle(self) -> None:
        if self._last is not None:
            wait = self.min_interval_s - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()

    def get_json(self, name: str) -> dict:
        if self.base_url.startswith("file://"):            # fixture locale : format de production identique
            path = Path(self.base_url[len("file://"):]) / name
            if not path.exists():
                raise FetchError(f"résultats locaux : {path} absent")
            self.requests_made += 1
            with path.open(encoding="utf-8") as f:
                return json.load(f)
        self._throttle()
        url = f"{self.base_url}/{name}"
        try:
            r = self.session.get(url, timeout=(15, 60), headers={"Accept": "application/json"})
        except requests.RequestException as e:
            raise FetchError(f"résultats publics injoignables : {url} ({e})") from e
        self.requests_made += 1
        if r.status_code != 200:
            raise FetchError(f"HTTP {r.status_code} sur {url}")
        try:
            return r.json()
        except ValueError as e:
            raise FetchError(f"JSON invalide : {url}") from e

    def manifest(self) -> dict:
        return self.get_json("index.json")

    def day(self, date: str, *, expected_fingerprint: str | None = None) -> dict:
        data = self.get_json(f"{date}.json")
        fp = sha256_json_compact(data.get("courses", []))
        declared = data.get("empreinte_sha256")
        if declared and fp != declared:
            raise FetchError(f"empreinte {date}.json incohérente (déclarée {declared[:12]}…, calculée {fp[:12]}…)")
        if expected_fingerprint and declared and declared != expected_fingerprint:
            raise FetchError(f"empreinte {date}.json ≠ manifeste")
        return data

    def corrections(self) -> dict:
        return self.get_json("corrections.json")
