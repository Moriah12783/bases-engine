"""Tests unitaires du cœur fourni (cas calculables à la main)."""
import itertools

import numpy as np
import pytest

from bases_engine import core


def exact_top_m_set_probs(p, lambdas, top_m):
    """Énumération exacte des permutations (petit n) : P(chaque cheval dans le top_m)."""
    n = len(p)
    p = np.asarray(p, float) / sum(p)
    marg = np.zeros(n)
    for perm in itertools.permutations(range(n), top_m):
        prob, alive = 1.0, set(range(n))
        for pos, i in enumerate(perm):
            w = {j: p[j] ** lambdas[pos] for j in alive}
            prob *= w[i] / sum(w.values())
            alive.remove(i)
        for i in perm:
            marg[i] += prob
    return marg


def test_harville_3_partants_p_top2_0_8393():
    """Harville (lambdas = 1) : p = (0.5, 0.3, 0.2), P(cheval 1 dans les 2 premiers)
    = 0.5 + 0.3·0.5/0.7 + 0.2·0.5/0.8 = 0.8393 (calcul à la main)."""
    p = [0.5, 0.3, 0.2]
    exact = exact_top_m_set_probs(p, (1.0, 1.0), 2)
    assert exact[0] == pytest.approx(0.8393, abs=5e-4)
    orders = core.simulate_top_m(p, (1.0, 1.0), top_m=2, n_sims=200_000, rng=np.random.default_rng(0))
    sim = core.marginal_place_probs(orders, 3)
    assert sim[0] == pytest.approx(0.8393, abs=0.005)
    assert sim.sum() == pytest.approx(2.0, abs=1e-9)


def test_discount_reduces_favourite_place_prob_vs_harville():
    p = [0.5, 0.3, 0.2]
    harville = exact_top_m_set_probs(p, (1.0, 1.0), 2)[0]
    discount = exact_top_m_set_probs(p, (1.0, 0.5), 2)[0]
    assert discount < harville


def test_simulation_matches_exact_with_discount():
    p = [0.35, 0.25, 0.2, 0.12, 0.08]
    lam = (1.0, 0.81, 0.65)
    exact = exact_top_m_set_probs(p, lam, 3)
    orders = core.simulate_top_m(p, lam, top_m=3, n_sims=200_000, rng=np.random.default_rng(1))
    sim = core.marginal_place_probs(orders, 5)
    assert np.allclose(sim, exact, atol=0.006)


def test_base_ladder_is_deterministic_and_monotone():
    p = np.array([0.30, 0.20, 0.15, 0.10, 0.08, 0.07, 0.05, 0.03, 0.02])
    eng = list(range(8))
    a = core.base_ladder(p, eng, top_m=5, n_sims=20_000, rng=np.random.default_rng(42))
    b = core.base_ladder(p, eng, top_m=5, n_sims=20_000, rng=np.random.default_rng(42))
    for k in (1, 2, 3, 4):
        assert a.rungs[k].horses == b.rungs[k].horses
        assert a.rungs[k].p_all == b.rungs[k].p_all
        assert 0.0 <= a.rungs[k].p_all <= a.rungs[k].p_all_but_one <= 1.0
    assert a.rungs[1].p_all > a.rungs[2].p_all > a.rungs[3].p_all > a.rungs[4].p_all
    assert set(a.rungs[1].horses) <= {0, 1, 2}
    assert len(a.all_trios) == 56


def test_score_subsets_exact_on_tiny_case():
    orders = np.array([[0, 1], [0, 2], [1, 2], [0, 1]])
    ranked = core.score_subsets(orders, [0, 1, 2], 2)
    best = ranked[0]
    assert best.horses == (0, 1) and best.p_all == pytest.approx(0.5)
    assert best.p_all_but_one == pytest.approx(1.0)


def test_calibrator_shrink_then_isotonic():
    cal = core.PostSelectionCalibrator(shrink=0.85, min_n=150)
    cal.fit([0.2] * 10, [1] * 10)
    assert cal.transform([0.4])[0] == pytest.approx(0.34)
    rng = np.random.default_rng(0)
    p = rng.uniform(0.05, 0.5, 400)
    hit = (rng.uniform(size=400) < 0.8 * p).astype(float)     # sur-confiance de 20 %
    cal.fit(p, hit)
    assert cal.knots_x is not None
    out = cal.transform(np.array([0.1, 0.3, 0.45]))
    assert np.all(np.diff(out) >= 0)
    assert out[1] < 0.3
