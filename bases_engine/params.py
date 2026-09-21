"""`params.json` : export lisible de la version courante des paramètres (gelés jusqu'au verdict)."""
from __future__ import annotations

import json
from pathlib import Path

from . import config
from .calibration import LadderCalibrator


def load_params(path: Path | None = None) -> dict:
    path = path or config.PARAMS_PATH          # résolu à l'appel (surchargeable dans les tests)
    if not path.exists():
        return {"version": "defaut", "valid_from": None, "lambdas": list(config.DEFAULT_LAMBDAS),
                "seuils_solidite": None, "shrink": config.SHRINK, "calibration_paliers": config.CALIB_LEVELS, "calibration": {}, "note": "params.json absent : lambdas littérature, pas de seuils gelés"}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_params(params: dict, path: Path | None = None) -> None:
    path = path or config.PARAMS_PATH
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


def pari_principal(paris: list[str]) -> str | None:
    for code in config.PARIS_UTILES:
        if code in paris:
            return code
    return None


PARIS_A_BASES = ("QUINTE_PLUS", "QUARTE_PLUS", "MULTI", "MINI_MULTI", "DEUX_SUR_QUATRE")


def trio_seulement(paris: list[str]) -> bool:
    """Course sans Quarté+, Multi ni 2sur4 : seuls Trio / Couplé placé (3 premiers) sont offerts."""
    return not any(c in paris for c in PARIS_A_BASES)


def structure_libelle(solid: str, top_m: int, paris: list[str], ladder: dict, ladder_top3: dict | None = None) -> dict:
    """Libellé de la structure recommandée dans le pari réellement offert (décision mentor 21/09, présentation seule ;
    le code stocké ne change pas). Retourne {code, texte, motif, pari, barreau, bases, associes_k}."""
    base = structure_for(solid, top_m)
    principal = pari_principal(paris)
    lib = config.PARIS_LIBELLES.get(principal or "", None)
    quarte_ou_multi = any(c in paris for c in ("QUINTE_PLUS", "QUARTE_PLUS", "MULTI", "MINI_MULTI"))
    if solid == "C":
        return {**base, "texte": "abstention sur bases fixes", "pari": lib, "barreau": None, "bases": []}
    if solid not in ("A", "B"):
        return {**base, "pari": lib, "barreau": None, "bases": []}
    k = 3 if solid == "A" else 2
    if not quarte_ou_multi:                       # règle mentor : barreau 2 ; 2sur4 s'il est offert
        k = 2
        if "DEUX_SUR_QUATRE" in paris:
            lib, texte = "2sur4", "2sur4 avec les 2 bases"
        elif ladder_top3:                         # Trio / Couplé placé seulement : échelle cible top 3, probabilité brute
            r2 = ladder_top3.get("2") or ladder_top3.get(2) or {}
            p2 = r2.get("p_brute")
            lib = "Trio ou Couplé placé"
            texte = (f"Trio ou Couplé placé : 2 bases + X · P(les 2 bases dans les 3 premiers) = "
                     f"{100 * p2:.0f} % (estimation brute, non recalibrée)") if p2 is not None else "Trio ou Couplé placé : 2 bases + X"
            return {**base, "texte": texte, "pari": lib, "barreau": 2, "bases": list(r2.get("chevaux", [])), "cible_affichee": 3, "p_brute_top3": p2}
        else:
            lib, texte = None, "2 bases, aucun pari à bases offert sur cette course"
    elif principal == "QUINTE_PLUS":
        texte = "3 bases + XX avec les associés" if k == 3 else "2 bases + XXX avec les associés"
    elif principal == "QUARTE_PLUS":
        texte = "3 bases + X avec les associés" if k == 3 else "2 bases + XX avec les associés"
    else:  # MULTI / MINI_MULTI
        texte = f"{lib} en 5 ou 6 autour des {k} bases"
    rung = ladder.get(str(k)) or ladder.get(k) or {}
    return {**base, "texte": texte, "pari": lib, "barreau": k, "bases": list(rung.get("chevaux", []))}
