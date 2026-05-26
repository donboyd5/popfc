"""Tests for popfc.models.mortality."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from popfc.models.mortality import (
    DEFAULT_RADIX,
    SURVIVAL_RATES_COLUMNS,
    birth_survival_factor,
    boundary_survival_factor,
    closed_band_survival,
    reconstruct_Lx_from_closed_survival,
    survival_rates_from_life_table,
)


# ---------------------------------------------------------------------------
# Scalar building blocks
# ---------------------------------------------------------------------------

class TestBoundarySurvivalFactor:
    def test_typical_value(self):
        # NCHS US 2023 total: L(99) ≈ 2,442; L(100+) ≈ 4,393.
        # Combined boundary survival ≈ 4393 / (2442 + 4393) ≈ 0.643.
        s = boundary_survival_factor(L_last_closed=2442, L_open=4393)
        assert 0.640 < s < 0.645

    def test_always_in_unit_interval(self):
        # Whatever positive inputs are, result is in (0, 1).
        for Lm, Lo in [(1.0, 1.0), (5.0, 0.001), (0.001, 5.0), (100, 50)]:
            s = boundary_survival_factor(Lm, Lo)
            assert 0.0 < s < 1.0

    def test_raises_on_nonpositive_sum(self):
        with pytest.raises(ValueError):
            boundary_survival_factor(0.0, 0.0)

    def test_raises_on_non_finite(self):
        with pytest.raises(ValueError):
            boundary_survival_factor(float("nan"), 1.0)


class TestBirthSurvivalFactor:
    def test_standard_radix(self):
        # US 2023: L(0) = 99,515 → ~0.99515.
        assert math.isclose(birth_survival_factor(99515), 0.99515, abs_tol=1e-5)

    def test_radix_override(self):
        # If L0 == radix, survival is 1.
        assert birth_survival_factor(50000, radix=50000) == 1.0

    def test_raises_on_invalid(self):
        with pytest.raises(ValueError):
            birth_survival_factor(0.0)
        with pytest.raises(ValueError):
            birth_survival_factor(100.0, radix=0.0)


class TestClosedBandSurvival:
    def test_constant_lx_yields_ones(self):
        out = closed_band_survival([100, 100, 100])
        assert np.allclose(out, 1.0)

    def test_strictly_decreasing(self):
        out = closed_band_survival([100, 90, 70])
        assert np.allclose(out, [0.9, 70 / 90])

    def test_raises_on_nonpositive(self):
        with pytest.raises(ValueError):
            closed_band_survival([100, 0, 50])


# ---------------------------------------------------------------------------
# Frame-level
# ---------------------------------------------------------------------------

LIFE_TABLES_PARQUET = pytest.importorskip("pyarrow")  # noqa: F841


@pytest.fixture(scope="module")
def life_tables():
    from popfc.paths import DATA_INTERIM
    p = DATA_INTERIM / "life_tables.parquet"
    if not p.exists():
        pytest.skip("life_tables.parquet not present (run Notebook 04 first)")
    return pd.read_parquet(p)


@pytest.fixture(scope="module")
def nvsr_survival(life_tables):
    nvsr = life_tables[life_tables["source"] == "nchs_nvsr"]
    return survival_rates_from_life_table(nvsr)


class TestSurvivalRatesFromLifeTable:
    def test_schema(self, nvsr_survival):
        assert list(nvsr_survival.columns) == SURVIVAL_RATES_COLUMNS

    def test_row_count(self, nvsr_survival):
        # Per slice: 1 birth + 99 closed + 1 boundary = 101.
        # Default geos: US + NY-state (36000); Washington qx-ratio-adjusted
        # (36115) is added when the post-Batch-7 qx-ratio branch lands.
        # Tolerate both shapes — 2 or 3 geos × 3 sexes × 101 rates.
        n_slices = nvsr_survival.groupby(["geoid", "year_start", "sex"]).ngroups
        assert len(nvsr_survival) == n_slices * 101
        assert n_slices in (6, 9)  # 2 or 3 geos × 3 sexes

    def test_band_type_counts(self, nvsr_survival):
        counts = nvsr_survival["band_type"].value_counts().to_dict()
        n_slices = nvsr_survival.groupby(["geoid", "year_start", "sex"]).ngroups
        assert counts["birth"] == n_slices
        assert counts["closed"] == n_slices * 99
        assert counts["boundary"] == n_slices

    def test_all_Sx_in_unit_interval(self, nvsr_survival):
        Sx = nvsr_survival["Sx"].astype(float)
        assert (Sx > 0).all()
        assert (Sx <= 1).all()

    def test_closed_age_range(self, nvsr_survival):
        # Closed-band ages must be exactly 0..98 (since ω=100 here).
        for (geoid, year, sex), sub in nvsr_survival.groupby(
            ["geoid", "year_start", "sex"]
        ):
            closed = sub[sub["band_type"] == "closed"]["age"]
            assert closed.min() == 0
            assert closed.max() == 98

    def test_boundary_age_equals_omega(self, nvsr_survival):
        # Boundary rows have age = 100 (the open-band start).
        boundaries = nvsr_survival[nvsr_survival["band_type"] == "boundary"]
        assert (boundaries["age"] == 100).all()

    def test_birth_age_is_negative_one(self, nvsr_survival):
        births = nvsr_survival[nvsr_survival["band_type"] == "birth"]
        assert (births["age"] == -1).all()

    def test_skips_abridged_tables(self, life_tables):
        # USALEEP tables (~11 rows per tract) must be skipped by the default
        # min_rows_per_slice threshold.
        usaleep = life_tables[life_tables["source"] == "nchs_usaleep"]
        out = survival_rates_from_life_table(usaleep)
        assert out.empty


class TestRoundTrip:
    def test_Lx_reconstruction_exact(self, life_tables, nvsr_survival):
        """Closed survival rates + L(0) reproduce the original Lx exactly."""
        nvsr = life_tables[life_tables["source"] == "nchs_nvsr"]
        recon = reconstruct_Lx_from_closed_survival(nvsr_survival)
        joined = recon.merge(
            nvsr[["geoid", "year_start", "sex", "age", "Lx"]],
            on=["geoid", "year_start", "sex", "age"],
            how="inner",
        )
        joined["ratio"] = joined["Lx_recon"].astype(float) / joined["Lx"].astype(float)
        # Floating-point round-trip should be perfect (or within 1e-12).
        assert (joined["ratio"] - 1.0).abs().max() < 1e-10

    def test_implied_e0_matches_table(self, life_tables, nvsr_survival):
        """Sum of L over all ages divided by radix recovers e(0) from the table."""
        nvsr = life_tables[life_tables["source"] == "nchs_nvsr"]
        recon = reconstruct_Lx_from_closed_survival(nvsr_survival)
        for (geoid, year, sex), sub in nvsr.groupby(["geoid", "year_start", "sex"]):
            # Total person-years = sum of reconstructed Lx (ages 0..ω-1) + L(ω+).
            r = recon[(recon["geoid"] == geoid)
                      & (recon["year_start"] == year)
                      & (recon["sex"] == sex)].set_index("age")["Lx_recon"]
            omega_lx = float(sub[sub["age_band"].str.endswith("+")]["Lx"].iloc[0])
            T0 = float(r.sum()) + omega_lx
            e0_implied = T0 / DEFAULT_RADIX
            e0_table = float(sub[sub["age"] == 0]["ex"].iloc[0])
            assert abs(e0_implied - e0_table) < 1e-4, \
                f"{(geoid, year, sex)}: implied={e0_implied} table={e0_table}"
