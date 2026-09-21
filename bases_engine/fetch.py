"""Lecture des sources (§3) : dépôt public du moteur au SHA détecté, résultats publics.

Règles : jamais `main` flottant ; au plus 4 téléchargements par jour et par fichier ;
cache `.cache/<sha>/` ; résultats publics à ≤ 1 requête par minute ; aucun HTML.
"""
from __future__ import annotations

import gzip
import json
import shutil
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from . import config
from .util import now_utc, sha256_json_compact


class FetchError(RuntimeError):
    pass


# ----------------------------------------------------------------------------
# Dépôt du moteur
# ----------------------------------------------------------------------------

def ls_remote(git_url: str = config.ENGINE_GIT_URL, branch: str = config.ENGINE_BRANCH) -> str:
    """SHA courant de `refs/heads/<branch>` (pas d'API GitHub, pas de quota)."""
    try:
        out = subprocess.run(["git", "ls-remote", git_url, f"refs/heads/{branch}"],
                             check=True, capture_output=True, text=True, timeout=60).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        raise FetchError(f"git ls-remote a échoué : {e}") from e
    for line in out.splitlines():
        sha, ref = line.split("\t", 1)
        if ref.strip() == f"refs/heads/{branch}":
            return sha.strip()
    raise FetchError(f"branche {branch} introuvable dans {git_url}")


def _budget_path(cache_dir: Path) -> Path:
    return cache_dir / "downloads.log"


def _downloads_today(cache_dir: Path, filename: str) -> int:
    p = _budget_path(cache_dir)
    if not p.exists():
        return 0
    today = now_utc().strftime("%Y-%m-%d")
    return sum(1 for line in p.read_text().splitlines()
               if line.startswith(today) and line.rstrip().endswith(" " + filename))


def _record_download(cache_dir: Path, filename: str, sha: str) -> None:
    with _budget_path(cache_dir).open("a") as f:
        f.write(f"{now_utc().strftime('%Y-%m-%dT%H:%M:%SZ')} {sha} {filename}\n")


def download_raw(sha: str, filename: str, dest: Path, *, cache_dir: Path = config.CACHE_DIR,
                 base_url: str = config.SOURCE_BASE_URL, session: requests.Session | None = None) -> Path:
    """Télécharge `<base_url>/<sha>/<filename>` vers `dest` (budget quotidien respecté).

    Un fichier `.gz` est décompressé vers `dest` sans le suffixe (source alternative §12).
    """
    if _downloads_today(cache_dir, filename) >= config.DOWNLOAD_BUDGET_PER_DAY:
        raise FetchError(f"budget de téléchargement épuisé aujourd'hui pour {filename} "
                         f"({config.DOWNLOAD_BUDGET_PER_DAY}/jour)")
    url = f"{base_url}/{sha}/{filename}"
    s = session or requests.Session()
    tmp = dest.with_suffix(dest.suffix + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with s.get(url, stream=True, timeout=(15, 300)) as r:
            if r.status_code != 200:
                raise FetchError(f"HTTP {r.status_code} sur {url}")
            with tmp.open("wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
    except requests.RequestException as e:
        tmp.unlink(missing_ok=True)
        raise FetchError(f"téléchargement impossible : {url} ({e})") from e
    _record_download(cache_dir, filename, sha)
    if filename.endswith(".gz"):
        with gzip.open(tmp, "rb") as src, dest.open("wb") as out:
            shutil.copyfileobj(src, out)
        tmp.unlink()
    else:
        tmp.replace(dest)
    return dest


@dataclass
class Snapshot:
    """Instantané figé du moteur (un SHA = une journée reproductible)."""
    sha: str
    dir: Path
    db_path: Path
    report_path: Path
    _logs: list | None = None

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con

    def historical_logs(self) -> list[dict]:
        if self._logs is None:
            with self.report_path.open(encoding="utf-8") as f:
                self._logs = json.load(f).get("historical_logs") or []
        return self._logs

    def logs_by_race(self) -> dict[str, dict]:
        return {h["race_id"]: h for h in self.historical_logs() if "race_id" in h}


def get_snapshot(sha: str | None = None, *, cache_dir: Path = config.CACHE_DIR,
                 local_dir: str | Path | None = config.LOCAL_SNAPSHOT_DIR) -> Snapshot:
    """Retourne l'instantané au SHA (téléchargé si absent du cache).

    `local_dir` (ou BASES_LOCAL_SNAPSHOT_DIR) : répertoire déjà rempli (tests, hors-ligne) ;
    le SHA est alors lu dans `<local_dir>/SHA` s'il existe, sinon `local`.
    """
    if local_dir:
        d = Path(local_dir)
        sha_file = d / "SHA"
        sha = sha or (sha_file.read_text().strip() if sha_file.exists() else "local")
        db = d / config.DB_FILENAME.removesuffix(".gz")
        rep = d / config.REPORT_FILENAME
        if not db.exists() or not rep.exists():
            raise FetchError(f"instantané local incomplet dans {d}")
        return Snapshot(sha, d, db, rep)
    sha = sha or ls_remote()
    d = cache_dir / sha
    db = d / config.DB_FILENAME.removesuffix(".gz")
    rep = d / config.REPORT_FILENAME
    if not db.exists():
        download_raw(sha, config.DB_FILENAME, db, cache_dir=cache_dir)
    if not rep.exists():
        download_raw(sha, config.REPORT_FILENAME, rep, cache_dir=cache_dir)
    (d / "SHA").write_text(sha + "\n")
    return Snapshot(sha, d, db, rep)


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
