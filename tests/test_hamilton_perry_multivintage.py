"""Tests for the multi-vintage CCR averaging in popfc.models.hamilton_perry."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from popfc.models.hamilton_perry import (
    cohort_change_ratios_multi_vintage,
)


def _make_history(n_vintages=4, geoid="A", base_pop=1000):
    """Build a tiny synthetic agesex history with vintages 5 years apart."""
    rows = []
    rng = np.random.default_rng(0)
    # Vintage midpoint years: 2005, 2010, 2015, 2020.
    midpoints = [2005 + 5 * i for i in range(n_vintages)]
    for m in midpoints:
        for sex in ("M", "F"):
            for start in (0, 5, 10, 15, 20):  # 5 closed bands
                end = start + 4
                pop = float(base_pop + rng.integers(-100, 100))
                rows.append({
                    "geoid": geoid, "geography": "Test",
                    "sex": sex, "age_band_start": start, "age_band_end": end,
                    "population": pop,
                    "vintage_midpoint_year": m,
                    "vintage_year_start": m - 2, "vintage_year_end": m + 2,
                    "vintage_label": f"acs5_{m-2}_{m+2}",
                })
    return pd.DataFrame(rows)


def test_pair_counting():
    """N vintages spaced 5 years apart → N-1 5-year pairs per cohort cell."""
    h = _make_history(n_vintages=4)
    out = cohort_change_ratios_multi_vintage(h, cap=None)
    # 5 source bands × 2 sexes = 10 cells (4 closed dest bands 5,10,15,20 plus
    # the open-band aggregation at 25/sentinel for the youngest open-source
    # cohort). Each cell averages over n_vintages - 1 = 3 pairs.
    assert (out["n_pairs"] == 3).all()
    # The function emits per-cell rows for every (sex × dest_band) it can compute.
    # Lower bound: at least the 4 closed dest bands × 2 sexes = 8.
    assert len(out) >= 8


def test_cap_clips_per_pair():
    """The per-pair cap should propagate to ccr values (averaged after clip)."""
    h = _make_history(n_vintages=3)
    out_no_cap = cohort_change_ratios_multi_vintage(h, cap=None)
    out_tight = cohort_change_ratios_multi_vintage(h, cap=(0.95, 1.05))
    assert (out_tight["ccr"] >= 0.95).all()
    assert (out_tight["ccr"] <= 1.05).all()
    # Tight cap should clip more pairs than no cap.
    assert out_tight["n_pairs_clipped"].sum() > out_no_cap["n_pairs_clipped"].sum()


def test_requires_5yr_pairs():
    """Vintages at midpoints 2 years apart don't form 5-year pairs."""
    rows = []
    for m in (2010, 2012, 2014):
        for sex in ("M", "F"):
            for start in (0, 5, 10):
                rows.append({
                    "geoid": "A", "geography": "Test",
                    "sex": sex, "age_band_start": start, "age_band_end": start+4,
                    "population": 1000.0,
                    "vintage_midpoint_year": m,
                    "vintage_year_start": m-2, "vintage_year_end": m+2,
                    "vintage_label": f"v{m}",
                })
    h = pd.DataFrame(rows)
    with pytest.raises(ValueError, match="No vintage-pair separations of 5 years"):
        cohort_change_ratios_multi_vintage(h)


def test_missing_columns():
    h = pd.DataFrame({"geoid": ["A"], "sex": ["M"]})  # missing required cols
    with pytest.raises(ValueError, match="missing required columns"):
        cohort_change_ratios_multi_vintage(h)
