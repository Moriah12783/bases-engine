import numpy as np
import pytest

from bases_engine.calibration import LadderCalibrator, fit_logit_linear


def _synthetic(n, seed=0, over=0.8):
    rng = np.random.default_rng(seed)
    p = rng.uniform(0.05, 0.5, n)
    hit = (rng.uniform(size=n) < over * p).astype(float)
    return p, hit


def test_palier_fixe_below_150():
    p, h = _synthetic(120)
    c = LadderCalibrator().fit(p, h)
    assert c.mode == "fixe" and c.transform([0.4])[0] == pytest.approx(0.34)


def test_palier_ratio_between_150_and_300_is_bounded():
    p, h = _synthetic(200, over=0.8)
    c = LadderCalibrator().fit(p, h)
    assert c.mode == "ratio" and 0.6 <= c.facteur <= 1.0
    assert c.facteur == pytest.approx(h.mean() / p.mean(), abs=1e-9)
    p2, h2 = _synthetic(200, over=0.2)            # sur-confiance massive → borne basse
    assert LadderCalibrator().fit(p2, h2).facteur == 0.60
    p3, h3 = _synthetic(200, over=1.5)            # sous-confiance → jamais au-dessus de 1
    assert LadderCalibrator().fit(p3, h3).facteur == 1.00


def test_palier_logit_recovers_known_curve():
    rng = np.random.default_rng(3)
    p = rng.uniform(0.03, 0.6, 5000)
    a, b = -0.4, 0.9
    x = np.log(p / (1 - p))
    hit = (rng.uniform(size=5000) < 1 / (1 + np.exp(-(a + b * x)))).astype(float)
    ah, bh = fit_logit_linear(p, hit)
    assert ah == pytest.approx(a, abs=0.12) and bh == pytest.approx(b, abs=0.1)
    c = LadderCalibrator().fit(p[:600], hit[:600])
    assert c.mode == "logit"
    out = c.transform(np.array([0.1, 0.3, 0.5]))
    assert np.all(np.diff(out) > 0) and 0 < out[0] < out[2] < 1


def test_palier_isotonique_from_1000():
    p, h = _synthetic(1200)
    c = LadderCalibrator().fit(p, h)
    assert c.mode == "isotonique"
    out = c.transform(np.array([0.1, 0.3, 0.45]))
    assert np.all(np.diff(out) >= 0)


def test_roundtrip_serialisation_all_modes():
    for n in (100, 200, 500, 1200):
        p, h = _synthetic(n)
        c = LadderCalibrator().fit(p, h)
        d = c.to_dict()
        c2 = LadderCalibrator.from_dict(d)
        assert c2.mode == c.mode and c2.n == n
        assert np.allclose(c2.transform([0.12, 0.33]), c.transform([0.12, 0.33]))
    assert LadderCalibrator.from_dict(None).mode == "fixe"
