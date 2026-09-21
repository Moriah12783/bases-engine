"""`params.json` : export lisible de la version courante des paramètres (gelés jusqu'au verdict)."""
from __future__ import annotations

import json
from pathlib import Path

from . import config
from .calibration import LadderCalibrator


def load_params(path: Path = config.PARAMS_PATH) -> dict:
    if not path.exists():
        return {"version": "defaut", "valid_from": None, "lambdas": list(config.DEFAULT_LAMBDAS),
                "seuils_solidite": None, "shrink": config.SHRINK, "calibration_paliers": config.CALIB_LEVELS, "calibration": {}, "note": "params.json absent : lambdas littérature, pas de seuils gelés"}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_params(params: dict, path: Path = config.PARAMS_PATH) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False, indent=2)
        f.write("\n")


def calibrator_for(params: dict, k: int, top_m: int) -> LadderCalibrator:
    """Calibrateur (k, top_m) reconstruit depuis params.json (palier choisi selon n à l'ajustement) ;
    repli palier « fixe » (facteur 0,85) si aucune entrée."""
    levels = params.get("calibration_paliers") or config.CALIB_LEVELS
    entry = (params.get("calibration") or {}).get(f"k{k}_m{top_m}")
    return LadderCalibrator.from_dict(entry, levels)


def solidite(p_calibree_k3: float, params: dict, top_m: int) -> str:
    seuils = (params.get("seuils_solidite") or {}).get(f"top{top_m}")
    if not seuils:
        return "?"           # seuils non gelés : pas d'indice (jamais inventé)
    if p_calibree_k3 >= seuils["A"]:
        return "A"
    if p_calibree_k3 >= seuils["B"]:
        return "B"
    return "C"


def structure_for(solid: str, top_m: int) -> dict:
    if solid == "A":
        return {"code": "3B_XX" if top_m == 5 else "3B_X", "texte": "3 bases + XX" if top_m == 5 else "3 bases + X", "motif": "solidité A"}
    if solid == "B":
        return {"code": "2B_XXX" if top_m == 5 else "2B_XX", "texte": "2 bases + XXX" if top_m == 5 else "2 bases + XX", "motif": "solidité B"}
    if solid == "C":
        return {"code": "ABSTENTION", "texte": "abstention sur bases fixes", "motif": "solidité C"}
    return {"code": "NON_QUALIFIE", "texte": "échelle seule (seuils non gelés)", "motif": "pas d'indice de solidité"}
