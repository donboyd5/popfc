"""Tests for popfc.constrain.prorata."""

from __future__ import annotations

import pandas as pd
import pytest

from popfc.constrain.prorata import apply_prorata_constraint


def _sub_pop():
    # Two towns, two years, two age × sex cells per (town, year).
    rows = []
    for geoid in ("A", "B"):
        for year in (2025, 2030):
            for age in (10, 20):
                for sex in ("M", "F"):
                    rows.append({
                        "geoid": geoid, "year": year, "sex": sex,
                        "age": age, "population": 100.0,
                    })
    return pd.DataFrame(rows)


def _county_targets():
    return pd.DataFrame([
        {"year": 2025, "population": 1000.0},
        {"year": 2030, "population": 600.0},
    ])


class TestProrata:
    def test_identity_when_already_matches(self):
        sub = _sub_pop()
        # Each year has 2 towns × 2 ages × 2 sexes × 100 = 800.
        target = pd.DataFrame([
            {"year": 2025, "population": 800.0},
            {"year": 2030, "population": 800.0},
        ])
        out = apply_prorata_constraint(sub, target)
        assert (out["population"] == 100.0).all()
        assert (out["constraint_factor"] == 1.0).all()

    def test_scaling_matches_target(self):
        sub = _sub_pop()
        target = _county_targets()
        out = apply_prorata_constraint(sub, target)
        # Per-year sums must equal targets.
        per_year = out.groupby("year")["population"].sum()
        assert abs(float(per_year[2025]) - 1000.0) < 1e-9
        assert abs(float(per_year[2030]) - 600.0) < 1e-9
        # Constraint factor consistency.
        f_2025 = float(out[out["year"] == 2025]["constraint_factor"].iloc[0])
        assert abs(f_2025 - 1000.0 / 800.0) < 1e-12

    def test_missing_target_raises(self):
        sub = _sub_pop()
        target = pd.DataFrame([{"year": 2025, "population": 1000.0}])  # missing 2030
        with pytest.raises(ValueError, match="missing parent targets"):
            apply_prorata_constraint(sub, target)

    def test_preserves_age_sex_structure(self):
        sub = _sub_pop()
        target = _county_targets()
        out = apply_prorata_constraint(sub, target)
        # Within each year, all cells should be scaled by the same factor.
        for year in (2025, 2030):
            year_out = out[out["year"] == year]
            year_in = sub[sub["year"] == year]
            ratios = year_out["population"].astype(float).to_numpy() / year_in["population"].astype(float).to_numpy()
            assert all(abs(r - ratios[0]) < 1e-12 for r in ratios)
