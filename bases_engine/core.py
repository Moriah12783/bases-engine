"""
base_des_bases.py — Outil d'étude (lab Radar), PAS du code de production.
=========================================================================

Objet : à partir des 8 chevaux du moteur et de probabilités par partant,
choisir le sous-ensemble de k chevaux (k = 1..4) qui maximise la probabilité
que TOUS finissent dans les m premiers (m = 5 Quinté, m = 4 Quarté), estimer
cette probabilité honnêtement (corrélation négative comprise) et en déduire
une structure de ticket (« échelle des bases »).

Trois briques, indépendantes du moteur de prédiction (module aval) :

  1. Modèle d'ordre d'arrivée à discount (Lo & Bacon-Shone / Henery)
       P(1er = i)          = p_i
       P(2e = j | 1er = i) = w_j^l2 / sum_{k != i} w_k^l2      etc.
     - p  : probabilités de VICTOIRE calibrées (moteur mélangé au marché)
     - w  : « force de placement » (par défaut w = p ; sinon ajustée pour
            reproduire des probabilités de PLACE q issues d'un modèle dédié)
     - l2..lm : coefficients de discount estimés sur l'historique (fit_lambdas)

  2. Sélection d'ensemble : énumération des C(8,k) sous-ensembles,
     probabilité jointe par Monte-Carlo, échelle des bases k = 1..4.

  3. Back-test : taux de réussite réels (3/3, >=2/3), comparaison aux
     baselines (3 premiers du moteur, 3 premiers du marché), et courbe de
     fiabilité de la probabilité jointe annoncée (promesse tenue ?).

Dépendance : numpy uniquement.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np

# ----------------------------------------------------------------------------
# 1. Modèle d'ordre d'arrivée
# ----------------------------------------------------------------------------

# Valeurs de départ raisonnables (littérature : l2 ~ 0.8, l3 ~ 0.65) ; à
# ré-estimer sur VOTRE historique avec fit_lambdas().
DEFAULT_LAMBDAS = (1.0, 0.81, 0.65, 0.55, 0.50)


def _normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    return v / v.sum()


def simulate_top_m(p_win, lambdas=DEFAULT_LAMBDAS, top_m=5, n_sims=20_000,
                   w_place=None, rng=None) -> np.ndarray:
    """Tire n_sims ordres d'arrivée (indices des top_m) sans remise.

    Position 1 : poids p_win. Positions 2..top_m : poids w_place^lambda_k
    (w_place = p_win par défaut). Retourne un tableau (n_sims, top_m).
    """
    rng = rng or np.random.default_rng()
    p = _normalize(p_win)
    w = p if w_place is None else _normalize(w_place)
    n = len(p)
    orders = np.empty((n_sims, top_m), dtype=np.int64)
    alive = np.ones((n_sims, n), dtype=bool)
    for pos in range(top_m):
        base = p if pos == 0 else w
        wt = np.where(alive, base[None, :] ** lambdas[pos], 0.0)
        wt /= wt.sum(axis=1, keepdims=True)
        cum = np.cumsum(wt, axis=1)
        idx = np.minimum((cum < rng.random(n_sims)[:, None]).sum(axis=1), n - 1)
        orders[:, pos] = idx
        alive[np.arange(n_sims), idx] = False
    return orders


def marginal_place_probs(orders: np.ndarray, n_runners: int) -> np.ndarray:
    """P(cheval i dans le top_m) estimée sur les ordres simulés."""
    return np.array([(orders == i).any(axis=1).mean() for i in range(n_runners)])


def fit_place_weights(p_win, q_place, lambdas=DEFAULT_LAMBDAS, top_m=5,
                      n_sims=20_000, n_iter=8, rng=None) -> np.ndarray:
    """Trouve des poids de placement w tels que les marginales simulées
    P(top_m) reproduisent q_place (probabilités de place calibrées d'un
    modèle dédié). Ajustement proportionnel itératif.

    Contraintes imposées : q_i >= p_win_i, somme(q) = top_m.
    """
    rng = rng or np.random.default_rng(0)
    p = _normalize(p_win)
    q = np.maximum(np.asarray(q_place, dtype=float), p + 1e-4)
    for _ in range(6):                      # somme = top_m ET chaque q_i < 1
        q = np.clip(q * (top_m / q.sum()), p + 1e-4, 0.99)
    w = q.copy()
    for _ in range(n_iter):
        orders = simulate_top_m(p, lambdas, top_m, n_sims, w_place=w, rng=rng)
        q_hat = np.clip(marginal_place_probs(orders, len(p)), 1e-4, 1 - 1e-4)
        w = w * (q / q_hat)
        w = _normalize(w)
    return w


def fit_lambdas(races, top_m=5, grid=np.linspace(0.3, 1.2, 19)) -> tuple:
    """Estime l2..lm par maximum de vraisemblance (descente par coordonnées
    sur une grille) à partir de courses historiques.

    races : liste de (p_win: array[n], arrivee: liste des indices des top_m)
    """
    lambdas = list(DEFAULT_LAMBDAS[:top_m])

    def loglik(lams):
        ll = 0.0
        for p, arr in races:
            p = _normalize(p)
            alive = np.ones(len(p), dtype=bool)
            for pos, i in enumerate(arr[:top_m]):
                wt = np.where(alive, p ** lams[pos], 0.0)
                ll += np.log(wt[i] / wt.sum())
                alive[i] = False
        return ll

    for _sweep in range(3):
        for pos in range(1, top_m):
            best = max(grid, key=lambda g: loglik(lambdas[:pos] + [g] + lambdas[pos + 1:]))
            lambdas[pos] = float(best)
    return tuple(lambdas)


# ----------------------------------------------------------------------------
# 2. Sélection d'ensemble et échelle des bases
# ----------------------------------------------------------------------------

@dataclass
class SubsetScore:
    horses: tuple            # indices dans la course
    p_all: float             # P(tous dans le top_m)
    p_all_but_one: float     # P(au moins k-1 dans le top_m)


@dataclass
class BaseLadder:
    """Échelle des bases : pour k = 1..4, meilleur sous-ensemble et sa P jointe."""
    top_m: int
    rungs: dict = field(default_factory=dict)      # k -> SubsetScore
    all_trios: list = field(default_factory=list)  # tous les trios classés

    def recommend(self, thresholds=None) -> tuple:
        """Politique simple : le plus grand k dont P(k/k) >= seuil_k.
        Seuils par défaut volontairement exigeants — à calibrer sur la
        courbe de fiabilité du back-test, pas au doigt mouillé.
        """
        thresholds = thresholds or {4: 0.10, 3: 0.20, 2: 0.40, 1: 0.60}
        for k in (4, 3, 2, 1):
            if k in self.rungs and self.rungs[k].p_all >= thresholds[k]:
                return k, self.rungs[k]
        return 0, None


def score_subsets(orders: np.ndarray, candidates, k: int) -> list[SubsetScore]:
    """Classe tous les sous-ensembles de taille k parmi candidates."""
    hits = {h: (orders == h).any(axis=1) for h in candidates}
    out = []
    for sub in itertools.combinations(candidates, k):
        n_in = sum(hits[h] for h in sub)
        out.append(SubsetScore(tuple(int(h) for h in sub),
                               float((n_in == k).mean()),
                               float((n_in >= k - 1).mean())))
    out.sort(key=lambda s: -s.p_all)
    return out


def base_ladder(p_win, engine8, top_m=5, q_place=None, lambdas=DEFAULT_LAMBDAS,
                n_sims=40_000, rng=None) -> BaseLadder:
    """Calcule l'échelle des bases pour une course.

    p_win    : probabilités de victoire calibrées pour TOUS les partants
    engine8  : indices des 8 chevaux du moteur (l'ordre n'a pas d'importance)
    q_place  : optionnel, probabilités de place (top_m) d'un modèle dédié ;
               si fourni, la force de placement est ajustée dessus.
    """
    rng = rng or np.random.default_rng(0)
    w = None
    if q_place is not None:
        w = fit_place_weights(p_win, q_place, lambdas, top_m,
                              n_sims=min(n_sims, 20_000), rng=rng)
    orders = simulate_top_m(p_win, lambdas, top_m, n_sims, w_place=w, rng=rng)
    ladder = BaseLadder(top_m=top_m)
    for k in (1, 2, 3, 4):
        ranked = score_subsets(orders, list(engine8), k)
        ladder.rungs[k] = ranked[0]
        if k == 3:
            ladder.all_trios = ranked
    return ladder


# ----------------------------------------------------------------------------
# 2 bis. Recalibration post-sélection (malédiction du gagnant)
# ----------------------------------------------------------------------------

class PostSelectionCalibrator:
    """Corrige la probabilité annoncée du sous-ensemble RETENU.

    On choisit le sous-ensemble qui maximise une probabilité estimée, donc la
    valeur affichée est biaisée vers le haut. On apprend, sur l'historique
    (P annoncée -> réussite observée), une courbe monotone par régression
    isotonique (pool-adjacent-violators). Tant que l'historique est trop mince
    (n < min_n), on applique un simple facteur de rétrécissement.
    """

    def __init__(self, shrink: float = 0.85, min_n: int = 150, n_bins: int = 8):
        self.shrink, self.min_n, self.n_bins = shrink, min_n, n_bins
        self.knots_x, self.knots_y, self.n = None, None, 0

    def fit(self, p_announced, hit):
        p = np.asarray(p_announced, dtype=float); h = np.asarray(hit, dtype=float)
        self.n = len(p)
        if self.n < self.min_n:
            self.knots_x = self.knots_y = None
            return self
        order = np.argsort(p); p, h = p[order], h[order]
        # PAV : blocs [somme_y, poids], fusion tant que la monotonie est violée
        blocks = []
        for y in h:
            blocks.append([float(y), 1])
            while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
                a, c = blocks[-2], blocks[-1]
                blocks[-2] = [a[0] + c[0], a[1] + c[1]]
                blocks.pop()
        y_fit = np.concatenate([np.full(w, s / w) for s, w in blocks])   # valeur ajustée par point
        # Noeuds : quantiles de P annoncée, valeur isotonique moyenne dans chaque tranche
        edges = np.quantile(p, np.linspace(0, 1, self.n_bins + 1))
        kx, ky = [], []
        for i, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
            m = (p >= lo) & ((p < hi) if i < self.n_bins - 1 else (p <= hi))
            if m.sum():
                kx.append(float(p[m].mean())); ky.append(float(y_fit[m].mean()))
        self.knots_x, self.knots_y = np.array(kx), np.maximum.accumulate(np.array(ky))
        return self

    def transform(self, p_announced):
        p = np.asarray(p_announced, dtype=float)
        if self.knots_x is None or len(self.knots_x) < 2:
            return np.clip(p * self.shrink, 0.0, 1.0)
        return np.clip(np.interp(p, self.knots_x, self.knots_y), 0.0, 1.0)

    def to_dict(self):
        return {"n": self.n, "shrink": self.shrink,
                "knots_x": None if self.knots_x is None else self.knots_x.tolist(),
                "knots_y": None if self.knots_y is None else self.knots_y.tolist()}


# ----------------------------------------------------------------------------
# 3. Back-test
# ----------------------------------------------------------------------------

def backtest(races, top_m=5, lambdas=DEFAULT_LAMBDAS, n_sims=20_000, seed=0):
    """races : liste de dicts
         p_win   : array[n] probabilités de victoire (moteur mélangé)
         p_market: array[n] probabilités implicites du marché (optionnel)
         engine8 : indices des 8 du moteur DANS L'ORDRE du moteur
         q_place : array[n] probabilités de place d'un modèle dédié (optionnel)
         arrivee : indices des top_m réels
    Retourne un dict de taux de réussite + courbe de fiabilité.
    """
    rng = np.random.default_rng(seed)
    res = {"n": 0, "greedy_engine_3": [], "market_3": [], "joint_3": [],
           "joint_3_2of3": [], "pred_p3": [], "obs_p3": []}
    for r in races:
        arr = set(r["arrivee"][:top_m])
        eng = list(r["engine8"])
        ladder = base_ladder(r["p_win"], eng, top_m, r.get("q_place"), lambdas,
                             n_sims=n_sims, rng=rng)
        trio = ladder.rungs[3]
        hit = lambda s: len(set(s) & arr)
        res["n"] += 1
        res["greedy_engine_3"].append(hit(eng[:3]) == 3)
        if r.get("p_market") is not None:
            res["market_3"].append(hit(np.argsort(-np.asarray(r["p_market"]))[:3]) == 3)
        res["joint_3"].append(hit(trio.horses) == 3)
        res["joint_3_2of3"].append(hit(trio.horses) >= 2)
        res["pred_p3"].append(trio.p_all)
        res["obs_p3"].append(hit(trio.horses) == 3)

    summary = {"n_courses": res["n"],
               "taux_3/3_moteur_3_premiers": float(np.mean(res["greedy_engine_3"])),
               "taux_3/3_trio_joint": float(np.mean(res["joint_3"])),
               "taux_>=2/3_trio_joint": float(np.mean(res["joint_3_2of3"]))}
    if res["market_3"]:
        summary["taux_3/3_marche_3_premiers"] = float(np.mean(res["market_3"]))
    # Courbe de fiabilité : P annoncée vs fréquence observée, par tranche
    pred, obs = np.array(res["pred_p3"]), np.array(res["obs_p3"], dtype=float)
    bins = [0, 0.08, 0.12, 0.16, 0.22, 0.30, 1.0]
    fiab = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (pred >= lo) & (pred < hi)
        if m.sum():
            fiab.append({"tranche": f"[{lo:.2f},{hi:.2f})", "n": int(m.sum()),
                         "p_annoncee": float(pred[m].mean()),
                         "freq_observee": float(obs[m].mean())})
    summary["fiabilite_P(3/3)"] = fiab
    return summary


# ----------------------------------------------------------------------------
# Démonstration synthétique (aucune donnée réelle)
# ----------------------------------------------------------------------------

def _synthetic_races(n_races, n_runners=16, top_m=5, seed=1):
    """Génère des courses où chaque cheval a DEUX dimensions :
    une force de victoire et une régularité (force de placement). Le moteur
    'victoire seule' ne voit que la première ; le modèle de place voit les deux.
    """
    rng = np.random.default_rng(seed)
    races = []
    for _ in range(n_races):
        theta = rng.normal(0, 0.9, n_runners)          # force de victoire
        regul = rng.normal(0, 0.9, n_runners)          # régularité (+ = « toujours à l'arrivée »)
        p_win = _normalize(np.exp(theta))
        w_true = _normalize(np.exp(theta + regul))     # force de placement vraie
        arrivee = simulate_top_m(p_win, DEFAULT_LAMBDAS, top_m, 1, w_place=w_true, rng=rng)[0]
        # Le moteur : estimation bruitée de p_win, 8 premiers par p_win estimée
        p_hat = _normalize(np.exp(np.log(p_win) + rng.normal(0, 0.3, n_runners)))
        engine8 = list(np.argsort(-p_hat)[:8])
        # Modèle de place « dédié » : voit la régularité avec du bruit
        big = simulate_top_m(p_win, DEFAULT_LAMBDAS, top_m, 4000, w_place=w_true, rng=rng)
        q_true = marginal_place_probs(big, n_runners)
        q_hat = np.clip(q_true + rng.normal(0, 0.04, n_runners), 0.01, 0.99)
        races.append({"p_win": p_hat, "p_market": p_win, "engine8": engine8,
                      "q_place": q_hat, "arrivee": list(arrivee)})
    return races


if __name__ == "__main__":
    print("Démo synthétique — 400 Quintés à 16 partants, objectif top 5\n")
    races = _synthetic_races(400)
    sans_place = [dict(r, q_place=None) for r in races]
    print("A) Trio joint sur probabilités de VICTOIRE seules (pas de modèle de place)")
    for k, v in backtest(sans_place, n_sims=8000).items():
        print("  ", k, ":", v if not isinstance(v, list) else "")
    print("\nB) Trio joint avec modèle de PLACE dédié (régularité vue)")
    s = backtest(races, n_sims=8000)
    for k, v in s.items():
        if not isinstance(v, list):
            print("  ", k, ":", v)
    print("   fiabilité P(3/3) annoncée vs observée :")
    for row in s["fiabilite_P(3/3)"]:
        print(f"     {row['tranche']}  n={row['n']:3d}  annoncée={row['p_annoncee']:.3f}  observée={row['freq_observee']:.3f}")

    print("\nExemple d'échelle des bases sur une course :")
    r = races[0]
    lad = base_ladder(r["p_win"], r["engine8"], 5, r["q_place"], n_sims=20000)
    for k in (1, 2, 3, 4):
        sc = lad.rungs[k]
        print(f"   {k} base(s) : chevaux {sc.horses}  P({k}/{k})={sc.p_all:.3f}  P(>= {k-1}/{k})={sc.p_all_but_one:.3f}")
    k, sc = lad.recommend()
    print("   Structure recommandée :", f"{k} base(s) fixes" if k else "abstention / champ total sans base fixe")
