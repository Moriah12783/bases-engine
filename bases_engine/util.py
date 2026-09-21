"""Petits utilitaires partagés (slug, graine, horodatage)."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone

_RACE_ID_RE = re.compile(r"^R(\d+)C(\d+)_(\d{2})(\d{2})(\d{4})_(.+)$")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime | None = None) -> str:
    dt = dt or now_utc()
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_race_id(race_id: str) -> dict:
    """`R1C1_21092026_LA CAPELLE` -> {reunion, course, date, hippodrome}."""
    m = _RACE_ID_RE.match(race_id)
    if not m:
        raise ValueError(f"race_id inattendu : {race_id!r}")
    r, c, dd, mm, yyyy, hippo = m.groups()
    return {"reunion": int(r), "course": int(c), "date": f"{yyyy}-{mm}-{dd}", "hippodrome": hippo}


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text


def race_slug(race_id: str) -> str:
    """`R1C1_21092026_LA CAPELLE` -> `2026-09-21_r1c1_la-capelle` (jamais d'espace)."""
    p = parse_race_id(race_id)
    return f"{p['date']}_r{p['reunion']}c{p['course']}_{slugify(p['hippodrome'])}"


def race_label(race_id: str) -> str:
    p = parse_race_id(race_id)
    return f"{p['hippodrome']} - R{p['reunion']}C{p['course']}"


def race_seed(date: str, race_id: str) -> int:
    """Graine déterministe par (date, race_id) : un recalcul donne le même résultat."""
    h = hashlib.sha256(f"{date}|{race_id}".encode("utf-8")).hexdigest()
    return int(h[:16], 16)


def sha256_json_compact(obj) -> str:
    import json
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
