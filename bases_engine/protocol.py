"""Protocole pré-enregistré : date de début fixée par la première exécution planifiée."""
from __future__ import annotations

import os
import re
from pathlib import Path

from . import config

PROTOCOL_PATH = config.ROOT / "PROTOCOLE_PREENREGISTRE.md"
PLACEHOLDER = "**Date de début : à renseigner par la première exécution planifiée.**"
PLACEHOLDER_COMMIT = "**Commit du dépôt `bases-engine` à l'activation : à renseigner par la première exécution planifiée.**"


def set_start_date(day: str, run_id: str, path: Path | None = None) -> bool:
    """Remplace le champ « à renseigner » par la date ; ne fait rien si déjà renseigné (jamais réécrit)."""
    path = path or PROTOCOL_PATH
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    if PLACEHOLDER not in text:
        return False
    text = text.replace(PLACEHOLDER, f"**Date de début : {day}** (fixée par le premier `matin` planifié, run `{run_id}`).")
    sha = os.environ.get("GITHUB_SHA") or "inconnu (exécution hors GitHub Actions)"
    text = text.replace(PLACEHOLDER_COMMIT, f"**Commit du dépôt `bases-engine` à l'activation : `{sha}`.**")
    path.write_text(text, encoding="utf-8")
    return True


def start_date_in_file(path: Path | None = None) -> str | None:
    path = path or PROTOCOL_PATH
    if not path.exists():
        return None
    m = re.search(r"\*\*Date de début : (\d{4}-\d{2}-\d{2})\*\*", path.read_text(encoding="utf-8"))
    return m.group(1) if m else None
