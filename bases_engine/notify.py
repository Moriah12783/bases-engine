"""Notifications (§6.2) : résumé de job GitHub, journal committé, Telegram inactif tant que non configuré.

`notify(kind, title, body)` diffuse vers les canaux de `NOTIFY_CHANNELS` (`summary,journal` par défaut).
kind ∈ {"matin", "soir", "hebdo", "alerte", "info"}.
"""
from __future__ import annotations

import os
from pathlib import Path

from . import config
from .util import now_utc

JOURNAL_DIR = config.RAPPORTS_DIR / "journal"


def channels() -> list[str]:
    raw = os.environ.get("NOTIFY_CHANNELS", "summary,journal")
    return [c.strip() for c in raw.split(",") if c.strip()]


def _summary(title: str, body: str) -> None:
    text = f"## {title}\n\n```\n{body}\n```\n"
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)


def _journal(kind: str, title: str, body: str, date: str | None) -> Path:
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    stamp = now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    if kind == "alerte":
        path = JOURNAL_DIR / "ALERTES.md"
        if not path.exists():
            path.write_text("# Alertes bases-engine (une ligne par incident)\n\n", encoding="utf-8")
        with path.open("a", encoding="utf-8") as f:
            f.write(f"- {stamp} — {title} — {body.strip().splitlines()[0] if body.strip() else ''}\n")
        return path
    day = date or now_utc().strftime("%Y-%m-%d")
    path = JOURNAL_DIR / f"{day}.md"
    if not path.exists():
        path.write_text(f"# Journal bases-engine — {day}\n\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"## {title}\n\n_{stamp}_\n\n```\n{body}\n```\n\n")
    return path


def _telegram(kind: str, title: str, body: str) -> bool:
    """Prévu, inactif : ne s'active que si NOTIFY_CHANNELS contient `telegram` ET que les secrets existent."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN_BASES")
    mode = os.environ.get("PUBLICATION_MODE", "shadow").upper()
    chat = os.environ.get(f"TELEGRAM_CHAT_ID_{mode}")
    if not token or not chat:
        return False                      # ignoré silencieusement, sans erreur
    try:
        import requests
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": f"{title}\n\n{body}"[:4000]}, timeout=20)
        return True
    except Exception:  # noqa: BLE001 — une panne Telegram ne bloque jamais le pipeline
        return False


def notify(kind: str, title: str, body: str, *, date: str | None = None) -> dict:
    sent = {}
    for ch in channels():
        if ch == "summary":
            _summary(title, body); sent["summary"] = True
        elif ch == "journal":
            sent["journal"] = str(_journal(kind, title, body, date))
        elif ch == "telegram":
            sent["telegram"] = _telegram(kind, title, body)
    return sent


def alert(title: str, body: str, *, date: str | None = None) -> dict:
    return notify("alerte", f"⛔ BASES — {title}", body, date=date)
