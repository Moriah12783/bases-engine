"""Calcul d'une édition (§4.3) à partir d'une course éligible : échelles m=4 et m=5, solidité, structure."""
from __future__ import annotations

import numpy as np

from . import config
from .core import base_ladder
from .eligibility import EligibleRace
from .params import calibrator_for, solidite, structure_for, trio_seulement
from .util import race_seed


def ladder_for(race: EligibleRace, top_m: int, lambdas, *, n_sims: int = config.N_SIMS, seed: int | None = None) -> dict:
    """Échelle brute k=1..4 pour une cible `top_m` (numéros PMU, pas des indices)."""
    nums = sorted(race.probs)
    idx = {n: i for i, n in enumerate(nums)}
    p = np.array([race.probs[n] for n in nums])
    cand_idx = [idx[n] for n in race.candidates]
    rng = np.random.default_rng(race_seed(race.date, race.race_id) if seed is None else seed)
    lad = base_ladder(p, cand_idx, top_m=top_m, lambdas=tuple(lambdas), n_sims=n_sims, rng=rng)
    rungs = {}
    for k in (1, 2, 3, 4):
        s = lad.rungs.get(k)
        if s is None:
            continue
        rungs[k] = {"chevaux": [nums[i] for i in s.horses], "p_brute": s.p_all, "p_k_moins_1": s.p_all_but_one}
    trios = [{"chevaux": [nums[i] for i in s.horses], "p_brute": s.p_all} for s in lad.all_trios[:5]]
    return {"top_m": top_m, "echelle": rungs, "trios": trios}


def compute_edition(race: EligibleRace, params: dict, *, n_sims: int = config.N_SIMS) -> dict:
    lambdas = params.get("lambdas") or list(config.DEFAULT_LAMBDAS)
    out = {"race_id": race.race_id, "date": race.date, "horizon": race.horizon, "top_m": race.top_m,
           "lambdas": list(lambdas), "params_version": params.get("version"), "flags": list(race.flags),
           "engine8": race.engine8, "candidates": race.candidates, "ladders": {}}
    for m in (4, 5):
        lad = ladder_for(race, m, lambdas, n_sims=n_sims)
        for k, rung in lad["echelle"].items():
            cal = calibrator_for(params, k, m)
            rung["p_calibree"] = float(cal.transform(np.array([rung["p_brute"]]))[0])
        out["ladders"][m] = lad
    if trio_seulement(race.paris_offerts):
        # Trio / Couplé placé seulement : échelle cible top 3, mêmes lambdas, même graine, probabilité brute (non recalibrée).
        # La solidité, le palmarès et le protocole restent calculés sur la cible top 4 / top 5.
        out["ladders"][3] = ladder_for(race, 3, lambdas, n_sims=n_sims)
    target = out["ladders"][race.top_m]
    p3 = target["echelle"][3]["p_calibree"]
    solid = solidite(p3, params, race.top_m)
    out["solidite"] = solid
    out["structure"] = structure_for(solid, race.top_m)
    return out
