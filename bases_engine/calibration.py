"""Recalibration post-sélection : échelle d'estimateurs choisie selon n (décision mentor du 21/09/2026).

Palier (n = courses notées pour la cible (k, top_m)) :
  n < 150            : facteur fixe 0,85                                  (`fixe`)
  150 ≤ n < 300      : facteur = observé/annoncé global, borné [0,60 ; 1,00] (`ratio`)
  300 ≤ n < 1000     : logit-linéaire à deux paramètres a + b·logit(P)     (`logit`)
  n ≥ 1000           : régression isotonique (PostSelectionCalibrator)     (`isotonique`)

La probabilité publiée est toujours la valeur recalibrée ; la brute est stockée.
"""
from __future__ import annotations

import numpy as np

from . import config
from .core import PostSelectionCalibrator

EPS = 1e-4


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def fit_logit_linear(p, hit, *, ridge: float = 1e-3, n_iter: int = 50) -> tuple[float, float]:
    """Maximum de vraisemblance de P(hit) = σ(a + b·logit p) par Newton-Raphson (2 paramètres)."""
    x = _logit(p)
    y = np.asarray(hit, dtype=float)
    X = np.column_stack([np.ones_like(x), x])
    beta = np.array([0.0, 1.0])                       # départ : identité
    for _ in range(n_iter):
        mu = _sigmoid(X @ beta)
        w = mu * (1 - mu)
        grad = X.T @ (y - mu) - ridge * (beta - np.array([0.0, 1.0]))
        hess = (X * w[:, None]).T @ X + ridge * np.eye(2)
        step = np.linalg.solve(hess, grad)
        beta = beta + step
        if np.max(np.abs(step)) < 1e-8:
            break
    return float(beta[0]), float(beta[1])


class LadderCalibrator:
    """Calibrateur à paliers. `levels` = dict des seuils (voir config.CALIB_LEVELS)."""

    def __init__(self, levels: dict | None = None):
        self.levels = levels or config.CALIB_LEVELS
        self.n = 0
        self.mode = "fixe"
        self.facteur: float | None = float(self.levels["fixe"]["facteur"])
        self.a: float | None = None
        self.b: float | None = None
        self.iso: PostSelectionCalibrator | None = None

    # -- ajustement -------------------------------------------------------------------------
    def fit(self, p_announced, hit) -> "LadderCalibrator":
        p = np.asarray(p_announced, dtype=float)
        h = np.asarray(hit, dtype=float)
        self.n = int(len(p))
        lv = self.levels
        self.facteur = self.a = self.b = None
        self.iso = None
        if self.n < lv["ratio"]["n_min"]:
            self.mode, self.facteur = "fixe", float(lv["fixe"]["facteur"])
        elif self.n < lv["logit"]["n_min"]:
            lo, hi = lv["ratio"]["bornes"]
            ratio = float(h.mean() / p.mean()) if p.mean() > 0 else 1.0
            self.mode, self.facteur = "ratio", float(np.clip(ratio, lo, hi))
        elif self.n < lv["isotonique"]["n_min"]:
            self.mode = "logit"
            self.a, self.b = fit_logit_linear(p, h)
        else:
            self.mode = "isotonique"
            self.iso = PostSelectionCalibrator(shrink=float(lv["fixe"]["facteur"]), min_n=1).fit(p, h)
        return self

    # -- application --------------------------------------------------------------------------
    def transform(self, p_announced):
        p = np.asarray(p_announced, dtype=float)
        if self.mode in ("fixe", "ratio"):
            return np.clip(p * self.facteur, 0.0, 1.0)
        if self.mode == "logit":
            return np.clip(_sigmoid(self.a + self.b * _logit(p)), 0.0, 1.0)
        return self.iso.transform(p)

    # -- sérialisation ------------------------------------------------------------------------
    def to_dict(self) -> dict:
        d = {"n": self.n, "mode": self.mode}
        if self.mode in ("fixe", "ratio"):
            d["facteur"] = self.facteur
        elif self.mode == "logit":
            d["a"], d["b"] = self.a, self.b
        else:
            d["knots_x"], d["knots_y"] = self.iso.knots_x.tolist(), self.iso.knots_y.tolist()
        return d

    @classmethod
    def from_dict(cls, d: dict | None, levels: dict | None = None) -> "LadderCalibrator":
        c = cls(levels)
        if not d:
            return c
        c.n, c.mode = int(d.get("n", 0)), d.get("mode", "fixe")
        if c.mode in ("fixe", "ratio"):
            c.facteur = float(d.get("facteur", c.levels["fixe"]["facteur"]))
        elif c.mode == "logit":
            c.a, c.b = float(d["a"]), float(d["b"])
        elif c.mode == "isotonique":
            c.iso = PostSelectionCalibrator(shrink=float(c.levels["fixe"]["facteur"]), min_n=1)
            c.iso.n = c.n
            c.iso.knots_x, c.iso.knots_y = np.array(d["knots_x"]), np.array(d["knots_y"])
        else:
            raise ValueError(f"mode de calibration inconnu : {c.mode}")
        return c
