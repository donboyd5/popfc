"""Tests for popfc.models.hamilton_perry."""

from __future__ import annotations

import pandas as pd
import pytest

from popfc.models.hamilton_perry import (
    FIVE_YEAR_BANDS,
    HP_PROJECTION_COLUMNS,
    aggregate_b01001_to_5yr_bands,
    child_woman_ratios,
    cohort_change_ratios,
    project_one_county_hp,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _synthetic_pop(
    geoid: str = "TEST",
    geography: str = "Test",
    year: int = 2017,
    vintage: str = "test",
    base: float = 100.0,
) -> pd.DataFrame:
    rows = []
    for sex in ("M", "F"):
        for start, end in FIVE_YEAR_BANDS:
            rows.append({
                "geoid": geoid, "geography": geography, "year": year,
                "vintage": vintage, "sex": sex,
                "age_band_start": start, "age_band_end": end,
                "population": base,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# ACS aggregation
# ---------------------------------------------------------------------------

class TestAggregateB01001:
    def test_handles_real_acs_frame(self):
        # Build a minimal ACS frame mimicking load_acs5_group output.
        rows = []
        for var_no in range(1, 50):  # 001..049
            var = f"B01001_{var_no:03d}E"
            rows.append({
                "state_fips": "36", "county_fips": "115",
                "mcd_fips": "30037", "geoid": "3611530037",
                "geography_level": "county subdivision",
                "name": "Granville town, Washington County, New York",
                "year": 2024, "vintage": "acs5_2020_2024",
                "variable": var, "label": "x", "concept": "y",
                "value": 100.0, "source": "acs5", "notes": "",
            })
        df = pd.DataFrame(rows)
        out = aggregate_b01001_to_5yr_bands(df)
        # 2 sexes × 18 bands = 36 rows.
        assert len(out) == 36
        # Sum should equal sum of the 46 detail vars (003-025 and 027-049 = 46 rows × 100 = 4600)
        # 002 and 026 are totals; aggregate function drops vars 001-002 (so M side = 003..025 = 23 vars).
        # Female side: 027-049 = 23 vars. Total = 46. We have 4600.
        assert int(out["population"].sum()) == 4600


# ---------------------------------------------------------------------------
# CCR
# ---------------------------------------------------------------------------

class TestCohortChangeRatios:
    def test_closed_band_ccr_is_one_for_stationary_pyramid(self):
        # Under a uniform pyramid (every band = 100) repeated at t0 and t1:
        # - closed CCR = 100/100 = 1.0 for every age band
        # - open CCR = 100/(100+100) = 0.5 (because the pool combines the
        #   last closed band and the open band)
        p = _synthetic_pop()
        ccr = cohort_change_ratios(p, p, cap=None)  # raw, no clipping
        # 17 destination bands (everything except 0-4) × 2 sexes = 34 rows.
        assert len(ccr) == 34
        closed = ccr[ccr["age_band_start"] != 85]
        open_ = ccr[ccr["age_band_start"] == 85]
        assert (closed["ccr"] == 1.0).all()
        assert (open_["ccr"] == 0.5).all()
        # No clipping applied.
        assert (~ccr["clipped"]).all()

    def test_default_cap_clips_extreme_ratios(self):
        # Set up t0 with very small pop and t1 with much larger pop so
        # raw CCRs exceed the default cap upper bound (2.0).
        p0 = _synthetic_pop(base=10.0)
        p1 = _synthetic_pop(base=100.0)
        ccr = cohort_change_ratios(p0, p1)  # default cap (0.5, 2.0)
        # Raw closed CCR would be 10.0; clipped to 2.0.
        closed = ccr[ccr["age_band_start"] != 85]
        assert (closed["ccr"] == 2.0).all()
        assert (closed["ccr_raw"] == 10.0).all()
        assert (closed["clipped"]).all()

    def test_open_band_uses_pool(self):
        # Set 80-84 = 100 and 85+ = 200 at t0; set 85+ = 300 at t1.
        # CCR(85+) = 300 / (100 + 200) = 1.0.
        p0 = _synthetic_pop()
        p1 = _synthetic_pop()
        # Modify only the 85+ at t1.
        mask_t1_open = (p1["age_band_start"] == 85)
        p1.loc[mask_t1_open, "population"] = 300.0
        mask_t0_85 = (p0["age_band_start"] == 85)
        p0.loc[mask_t0_85, "population"] = 200.0
        # p0[80-84] is left at 100.
        ccr = cohort_change_ratios(p0, p1, cap=None)
        open_ccrs = ccr[ccr["age_band_start"] == 85]
        assert all(abs(float(r) - 1.0) < 1e-12 for r in open_ccrs["ccr"])


# ---------------------------------------------------------------------------
# CWR
# ---------------------------------------------------------------------------

class TestChildWomanRatios:
    def test_uniform_pop_gives_known_ratio(self):
        # Every band = 100; women 15-49 = 7 bands × 100 = 700; P(0-4, sex) = 100.
        # CWR = 100 / 700 ≈ 0.1429.
        p = _synthetic_pop()
        cwr = child_woman_ratios(p)
        assert len(cwr) == 2  # M and F
        for _, row in cwr.iterrows():
            assert abs(float(row["cwr"]) - 100.0 / 700.0) < 1e-12


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

class TestProjectOneCountyHp:
    def test_schema(self):
        p = _synthetic_pop(year=2022)
        ccr = cohort_change_ratios(p, p)
        cwr = child_woman_ratios(p)
        out = project_one_county_hp(p, ccr, cwr, base_year=2022, end_year=2032)
        assert list(out.columns) == HP_PROJECTION_COLUMNS
        # 3 years (2022, 2027, 2032) × 2 sexes × 18 bands = 108
        assert len(out) == 3 * 2 * 18

    def test_stationary_pyramid_holds_stationary(self):
        # With CCR=1 everywhere and CWR consistent with the pyramid, the
        # projection should reproduce the input each step.
        p = _synthetic_pop(year=2022)
        ccr = cohort_change_ratios(p, p)
        cwr = child_woman_ratios(p)
        out = project_one_county_hp(p, ccr, cwr, base_year=2022, end_year=2032)
        # Every (year, sex, age_band_start) population should be 100.
        bad = out[(out["population"] - 100.0).abs() > 1e-9]
        assert bad.empty, f"non-stationary rows:\n{bad.head().to_string()}"

    def test_end_minus_base_must_be_multiple_of_step(self):
        p = _synthetic_pop(year=2022)
        ccr = cohort_change_ratios(p, p)
        cwr = child_woman_ratios(p)
        with pytest.raises(ValueError, match="multiple of step_years"):
            project_one_county_hp(p, ccr, cwr, base_year=2022, end_year=2030)
