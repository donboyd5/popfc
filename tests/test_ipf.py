"""Tests for popfc.constrain.ipf.apply_ipf_constraint."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from popfc.constrain.ipf import apply_ipf_constraint


def _make_seed(seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for g in ("A", "B", "C"):
        for sex in ("M", "F"):
            for age in (0, 5, 10, 15):
                rows.append({
                    "geoid": g, "sex": sex, "age_band_start": age,
                    "population": float(rng.integers(50, 200)),
                })
    return pd.DataFrame(rows)


def test_column_only_one_pass_exact():
    """Column-only IPF is a single pass and reaches exact column matches."""
    seed = _make_seed(0)
    col_targets = pd.DataFrame([
        {"sex": s, "age_band_start": a, "population": 300.0}
        for s in ("M", "F") for a in (0, 5, 10, 15)
    ])
    result = apply_ipf_constraint(seed, column_targets=col_targets)
    assert result.converged
    assert result.iterations == 1
    sums = result.adjusted.groupby(["sex", "age_band_start"])["population"].sum()
    assert sums.round(6).eq(300.0).all()


def test_biproportional_matches_both_marginals():
    seed = _make_seed(0)
    col_targets = pd.DataFrame([
        {"sex": s, "age_band_start": a, "population": 300.0}
        for s in ("M", "F") for a in (0, 5, 10, 15)
    ])
    row_targets = pd.DataFrame([
        {"geoid": "A", "population": 900.0},
        {"geoid": "B", "population": 900.0},
        {"geoid": "C", "population": 600.0},
    ])
    result = apply_ipf_constraint(seed, column_targets=col_targets, row_targets=row_targets)
    assert result.converged
    col_sums = result.adjusted.groupby(["sex", "age_band_start"])["population"].sum()
    row_sums = result.adjusted.groupby("geoid")["population"].sum()
    assert col_sums.round(4).eq(300.0).all()
    assert row_sums.loc["A"] == pytest.approx(900.0, abs=1e-3)
    assert row_sums.loc["B"] == pytest.approx(900.0, abs=1e-3)
    assert row_sums.loc["C"] == pytest.approx(600.0, abs=1e-3)


def test_zero_column_passthrough():
    """A column that is all-zero in the seed shouldn't blow up — no division by 0."""
    rows = []
    for g in ("A", "B"):
        for age in (0, 5):
            rows.append({"geoid": g, "sex": "M", "age_band_start": age, "population": 0.0})
        rows.append({"geoid": g, "sex": "F", "age_band_start": 0, "population": 100.0})
        rows.append({"geoid": g, "sex": "F", "age_band_start": 5, "population": 100.0})
    seed = pd.DataFrame(rows)
    col_targets = pd.DataFrame([
        {"sex": s, "age_band_start": a, "population": 100.0}
        for s in ("M", "F") for a in (0, 5)
    ])
    result = apply_ipf_constraint(seed, column_targets=col_targets)
    assert result.converged
    # Female columns reach 100 each; male columns stay 0 (no upward seed value to scale).
    sums = result.adjusted.groupby(["sex", "age_band_start"])["population"].sum()
    assert sums.loc[("F", 0)] == pytest.approx(100.0, abs=1e-6)
    assert sums.loc[("F", 5)] == pytest.approx(100.0, abs=1e-6)
    assert sums.loc[("M", 0)] == 0.0
    assert sums.loc[("M", 5)] == 0.0


def test_max_iter_bounds_terminates():
    """Even with inconsistent targets, IPF must terminate without raising."""
    seed = _make_seed(0)
    col_targets = pd.DataFrame([
        {"sex": s, "age_band_start": a, "population": 100.0}
        for s in ("M", "F") for a in (0, 5, 10, 15)
    ])
    row_targets = pd.DataFrame([
        {"geoid": g, "population": 1000.0}
        for g in ("A", "B", "C")
    ])
    # Sum of column targets = 800; sum of row targets = 3000. Marginals
    # disagree by a factor of ~4 — IPF reaches a stable point that
    # compromises between them. It terminates either by convergence
    # criterion (max abs change < tol) or by hitting max_iter.
    result = apply_ipf_constraint(
        seed, column_targets=col_targets, row_targets=row_targets, max_iter=50,
    )
    assert 1 <= result.iterations <= 50
    assert isinstance(result.converged, bool)
