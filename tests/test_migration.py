"""Tests for popfc.models.migration."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from popfc.models.migration import (
    AGE_COMPONENT_SHAPE_COLUMNS,
    B07001_AGE_BANDS,
    NET_MIGRATION_COMPONENTS_COLUMNS,
    NET_MIGRATION_RATES_COLUMNS,
    REFERENCE_PERIOD_COLUMNS,
    _residual_one_pair,
    b07001_age_component_shape,
    build_net_migration_rates,
    decompose_net_migration,
    expand_age_shape_to_single_year,
    historical_reference_periods,
)
from popfc.models.mortality import SURVIVAL_RATES_COLUMNS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stationary_survival(top_code_age: int = 4) -> pd.DataFrame:
    """Build a minimal survival frame for ages 0..ω with all S=1 (no deaths).

    The resulting frame conforms to SURVIVAL_RATES_COLUMNS and has one
    boundary row at age=top_code_age with S=1.
    """
    rows = []
    for x in range(0, top_code_age - 1):
        rows.append({"geoid": "TEST", "geography": "Test", "year_start": 2020,
                     "year_end": 2020, "sex": "All", "band_type": "closed",
                     "age": x, "Sx": 1.0, "source": "test", "vintage": "test", "notes": ""})
    rows.append({"geoid": "TEST", "geography": "Test", "year_start": 2020,
                 "year_end": 2020, "sex": "All", "band_type": "boundary",
                 "age": top_code_age, "Sx": 1.0, "source": "test", "vintage": "test", "notes": ""})
    rows.append({"geoid": "TEST", "geography": "Test", "year_start": 2020,
                 "year_end": 2020, "sex": "All", "band_type": "birth",
                 "age": -1, "Sx": 1.0, "source": "test", "vintage": "test", "notes": ""})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Single-pair helper
# ---------------------------------------------------------------------------

class TestResidualOnePair:
    def test_no_migration_no_deaths_no_residual(self):
        # If P_tp1 = expected (P_t shifted by 1 with S=1), all m_rate = 0.
        P_t = pd.Series([100, 100, 100, 100, 100], index=[0, 1, 2, 3, 4])
        P_tp1 = pd.Series([100, 100, 100, 100, 200], index=[0, 1, 2, 3, 4])
        # Note: open at age 4. After 1 year with S=1, P_tp1[4] = P_t[3] + P_t[4] = 200.
        S_closed = pd.Series([1.0, 1.0, 1.0], index=[0, 1, 2])
        out = _residual_one_pair(P_t, P_tp1, S_closed, 1.0, top_code_age=4)
        # All m_rate should be 0 (within float tolerance).
        assert (out["m_rate"].abs() < 1e-12).all()

    def test_in_migration_at_age_1(self):
        # Insert 10 net in-migrants into age 1.
        P_t = pd.Series([100, 100, 100, 100, 100], index=[0, 1, 2, 3, 4])
        P_tp1 = pd.Series([100, 110, 100, 100, 200], index=[0, 1, 2, 3, 4])
        S_closed = pd.Series([1.0, 1.0, 1.0], index=[0, 1, 2])
        out = _residual_one_pair(P_t, P_tp1, S_closed, 1.0, top_code_age=4)
        # Closed age=1 row (source_age=0) has m_rate = (110 - 100) / 100 = 0.10.
        row = out[(out["band_type"] == "closed") & (out["age"] == 1)].iloc[0]
        assert abs(float(row["m_rate"]) - 0.10) < 1e-12

    def test_with_mortality(self):
        # S=0.9 across the board. P_tp1 = expected (no migration).
        P_t = pd.Series([100, 100, 100, 100, 100], index=[0, 1, 2, 3, 4])
        # Expected new pop: age 0 same (birth handled elsewhere), age 1 = 100*0.9, ...
        # age 4 (open) = (P_t[3] + P_t[4]) * 0.9 = 180.
        P_tp1 = pd.Series([100, 90, 90, 90, 180], index=[0, 1, 2, 3, 4])
        S_closed = pd.Series([0.9, 0.9, 0.9], index=[0, 1, 2])
        out = _residual_one_pair(P_t, P_tp1, S_closed, 0.9, top_code_age=4)
        assert (out["m_rate"].abs() < 1e-12).all()


# ---------------------------------------------------------------------------
# Frame builder
# ---------------------------------------------------------------------------

class TestBuildNetMigrationRates:
    def _synthetic_pop(self):
        """One county, two sexes, 4 years, stationary pop with no migration."""
        rows = []
        for year in range(2020, 2024):
            for sex in ("F", "M"):
                for age in range(0, 5):  # top code 4 (open)
                    rows.append({
                        "geoid": "TEST", "geography": "Test",
                        "year": year, "sex": sex, "age": age,
                        "population": 100.0 if age < 4 else 100.0 * (year - 2019),
                        # Open band grows by 100 each year (no deaths, all flow in).
                    })
        return pd.DataFrame(rows)

    def test_schema(self):
        pop = self._synthetic_pop()
        # Need survival frame whose geoid matches state_geoid arg.
        surv = _stationary_survival(top_code_age=4)
        surv = surv.assign(geoid="36000")  # match default state_geoid
        # Need both sexes — duplicate.
        surv_f = surv.copy(); surv_f["sex"] = "F"
        surv_m = surv.copy(); surv_m["sex"] = "M"
        out = build_net_migration_rates(
            pop, pd.concat([surv_f, surv_m], ignore_index=True),
            top_code_age=4, state_geoid="36000",
        )
        assert list(out.columns) == NET_MIGRATION_RATES_COLUMNS

    def test_zero_migration_for_stationary_input(self):
        # Stationary pop (no births shown here but all closed transitions
        # match S=1 stationary projection) should give zero m_rate.
        pop = self._synthetic_pop()
        # Set boundary growth equal to (P[ω-1] + P[ω]) under S=1 (which is fine
        # since open band keeps growing): each year, new_P[4] = old_P[3] + old_P[4].
        # synth pop already does this so the residual should be zero.
        surv = _stationary_survival(top_code_age=4)
        surv = surv.assign(geoid="36000")
        surv_f = surv.copy(); surv_f["sex"] = "F"
        surv_m = surv.copy(); surv_m["sex"] = "M"
        out = build_net_migration_rates(
            pop, pd.concat([surv_f, surv_m], ignore_index=True),
            top_code_age=4, state_geoid="36000",
        )
        assert (out["m_rate"].abs() < 1e-12).all()

    def test_requires_consecutive_years(self):
        # Pop with a year gap (skip 2021) should still produce something
        # from the 2022-2023 pair only.
        pop = self._synthetic_pop()
        pop = pop[pop["year"] != 2021].copy()
        surv = _stationary_survival(top_code_age=4)
        surv = surv.assign(geoid="36000")
        surv_f = surv.copy(); surv_f["sex"] = "F"
        surv_m = surv.copy(); surv_m["sex"] = "M"
        out = build_net_migration_rates(
            pop, pd.concat([surv_f, surv_m], ignore_index=True),
            top_code_age=4, state_geoid="36000",
        )
        # Only 2022-2023 is a consecutive pair, so n_year_pairs == 1 everywhere.
        assert (out["n_year_pairs"] == 1).all()


# ---------------------------------------------------------------------------
# Historical reference periods
# ---------------------------------------------------------------------------

class TestHistoricalReferencePeriods:
    def _synthetic(self, years=range(2010, 2025),
                   net_mig_series=None, pop_series=None):
        if net_mig_series is None:
            # Simple alternating positive/negative pattern that makes
            # best/worst windows easy to compute by hand.
            net_mig_series = [+100 if (y % 2 == 0) else -100 for y in years]
        if pop_series is None:
            pop_series = [10000] * len(list(years))
        comp_rows = []
        pop_rows = []
        for y, nm, pp in zip(years, net_mig_series, pop_series):
            comp_rows.append({
                "state_fips": "36", "county_fips": "001",
                "geoid": "36001", "geography": "Test",
                "year": y, "measure": "net_mig", "value": float(nm),
                "source": "test", "vintage": "vt", "notes": "",
            })
            pop_rows.append({
                "state_fips": "36", "county_fips": "001",
                "geoid": "36001", "geography": "Test",
                "year": y, "kind": "estimate", "population": int(pp),
                "source": "test", "vintage": "vt", "notes": "",
            })
        return pd.DataFrame(comp_rows), pd.DataFrame(pop_rows)

    def test_schema(self):
        comp, pop = self._synthetic()
        out = historical_reference_periods(comp, pop, window_years=5, start_year=2010)
        assert list(out.columns) == REFERENCE_PERIOD_COLUMNS

    def test_three_rows_per_county(self):
        comp, pop = self._synthetic()
        out = historical_reference_periods(comp, pop, window_years=5, start_year=2010)
        # Expect exactly three rows (current, best, worst) for one county.
        assert len(out) == 3
        assert set(out["window_kind"].unique()) == {"current", "best", "worst"}

    def test_best_vs_worst_ordering(self):
        # Three regimes — moderate-out early, positive middle, heavy-out late.
        # Forces best, worst, and current to be three distinct windows.
        years = list(range(2010, 2025))
        nm = ([-100] * 5) + ([+500] * 5) + ([-500] * 5)
        comp, pop = self._synthetic(years=years, net_mig_series=nm)
        out = historical_reference_periods(comp, pop, window_years=5, start_year=2010)
        best = out[out["window_kind"] == "best"].iloc[0]
        worst = out[out["window_kind"] == "worst"].iloc[0]
        current = out[out["window_kind"] == "current"].iloc[0]
        # Best is the middle window 2015-2019 (everything is +500).
        assert int(best["year_start"]) == 2015 and int(best["year_end"]) == 2019
        # Worst is the latest window 2020-2024 (heavy out).
        assert int(worst["year_start"]) == 2020 and int(worst["year_end"]) == 2024
        # Current is the latest window — in this case current == worst.
        assert int(current["year_end"]) == 2024
        # Invariant: best is at least as good as current, worst at least as bad.
        assert best["avg_rate"] > current["avg_rate"]
        assert worst["avg_rate"] <= current["avg_rate"]

    def test_insufficient_data_skips_county(self):
        # Only 3 years of data: too few for a 5-year window.
        years = list(range(2010, 2013))
        nm = [+100, -100, +50]
        comp, pop = self._synthetic(years=years, net_mig_series=nm,
                                    pop_series=[10000] * 3)
        out = historical_reference_periods(comp, pop, window_years=5, start_year=2010)
        assert out.empty
        assert list(out.columns) == REFERENCE_PERIOD_COLUMNS

    def test_average_rate_arithmetic(self):
        # Net mig = 200 every year against pop = 10,000 means rate = 0.02 every
        # year (mid-pop = 10,000 too, since pop is constant). Average over any
        # 5-year window = 0.02 exactly.
        years = list(range(2010, 2020))
        nm = [200] * 10
        comp, pop = self._synthetic(years=years, net_mig_series=nm,
                                    pop_series=[10000] * 10)
        out = historical_reference_periods(comp, pop, window_years=5, start_year=2010)
        for _, row in out.iterrows():
            assert abs(float(row["avg_rate"]) - 0.02) < 1e-9


# ---------------------------------------------------------------------------
# B07001 age × component shape (Batch 4b)
# ---------------------------------------------------------------------------

def _synth_b07001_long() -> pd.DataFrame:
    """Build a tiny synthetic B07001-shape long frame for one state, two bands.

    Two age bands ("1 to 4 years", "20 to 24 years") × four components.
    Counts chosen so domestic / international ratios differ between bands.
    """
    rows = []
    cells = [
        # band, component, value
        ("1 to 4 years", "Moved within same county",                   500),
        ("1 to 4 years", "Moved from different county within same state",  100),
        ("1 to 4 years", "Moved from different state",                  50),
        ("1 to 4 years", "Moved from abroad",                          150),  # international-heavy
        ("20 to 24 years", "Moved within same county",                 1000),
        ("20 to 24 years", "Moved from different county within same state", 800),
        ("20 to 24 years", "Moved from different state",                400),
        ("20 to 24 years", "Moved from abroad",                         200),  # domestic-heavy
    ]
    for age_band, comp, val in cells:
        rows.append({
            "state_fips": "36",
            "geoid": "36000",
            "label": f"Estimate!!Total:!!{comp}:!!{age_band}",
            "value": float(val),
        })
    # Add a header / non-cell row to make sure parser ignores it
    rows.append({"state_fips": "36", "geoid": "36000",
                 "label": "Estimate!!Total:", "value": 99999.0})
    return pd.DataFrame(rows)


class TestB07001AgeComponentShape:
    def test_schema(self):
        out = b07001_age_component_shape(_synth_b07001_long(), state_filter="36")
        assert list(out.columns) == AGE_COMPONENT_SHAPE_COLUMNS

    def test_domestic_excludes_intra_county(self):
        out = b07001_age_component_shape(_synth_b07001_long(), state_filter="36")
        # 1-to-4 band: domestic = 100 + 50 = 150 (excluding intra-county 500)
        r = out[out["age_band"] == "1 to 4 years"].iloc[0]
        assert float(r["domestic"]) == 150.0
        assert float(r["international"]) == 150.0
        assert abs(float(r["f_dom"]) - 0.5) < 1e-9

    def test_f_dom_differs_across_bands(self):
        out = b07001_age_component_shape(_synth_b07001_long(), state_filter="36")
        # 20-24 band: domestic = 800 + 400 = 1200; international = 200; f_dom = 1200/1400
        r = out[out["age_band"] == "20 to 24 years"].iloc[0]
        assert abs(float(r["f_dom"]) - (1200.0 / 1400.0)) < 1e-9

    def test_state_filter_drops_other_states(self):
        df = _synth_b07001_long()
        df_other = df.copy()
        df_other["state_fips"] = "06"  # California
        df_other["value"] = df_other["value"].astype(float) * 100  # very different
        combined = pd.concat([df, df_other], ignore_index=True)
        out = b07001_age_component_shape(combined, state_filter="36")
        # Result should be the same as the NY-only run.
        r = out[out["age_band"] == "1 to 4 years"].iloc[0]
        assert float(r["domestic"]) == 150.0


class TestExpandAgeShape:
    def test_single_year_grid(self):
        band = pd.DataFrame({
            "age_lower": [1, 5, 75],
            "age_upper": [4, 17, pd.NA],
            "age_band": ["1 to 4 years", "5 to 17 years", "75 years and over"],
            "f_dom": [0.50, 0.70, 0.80],
        })
        out = expand_age_shape_to_single_year(band, top_code_age=85)
        # 0..85 inclusive = 86 rows
        assert len(out) == 86
        # Age 0 (below the youngest band) takes the 1-4 value.
        assert float(out[out["age"] == 0]["f_dom"].iloc[0]) == 0.50
        # Ages 1-4 take the 1-4 value.
        for a in range(1, 5):
            assert float(out[out["age"] == a]["f_dom"].iloc[0]) == 0.50
        # Ages 5-17 take the 5-17 value.
        for a in range(5, 18):
            assert float(out[out["age"] == a]["f_dom"].iloc[0]) == 0.70
        # Ages 75..85 take the open-top value.
        for a in range(75, 86):
            assert float(out[out["age"] == a]["f_dom"].iloc[0]) == 0.80


# ---------------------------------------------------------------------------
# decompose_net_migration (Tier 1 + Tier 3)
# ---------------------------------------------------------------------------

def _synth_net_mig(geoid: str = "36001", geography: str = "Test County",
                   m_rate: float = 0.02) -> pd.DataFrame:
    """Build a minimal net_mig frame: one county, both sexes, ages 1..5 closed + 5 boundary."""
    rows = []
    for sex in ("M", "F"):
        for source_age in range(0, 4):  # destination 1..4
            rows.append({
                "geoid": geoid, "geography": geography, "year_basis": "test",
                "sex": sex, "band_type": "closed",
                "age": source_age + 1, "source_age": source_age,
                "m_rate": m_rate, "n_year_pairs": 1, "notes": "",
            })
        rows.append({
            "geoid": geoid, "geography": geography, "year_basis": "test",
            "sex": sex, "band_type": "boundary",
            "age": 5, "source_age": 4, "m_rate": m_rate, "n_year_pairs": 1, "notes": "",
        })
    return pd.DataFrame(rows)


def _synth_components(geoid: str = "36001", geography: str = "Test County",
                      dom_per_year: float = +80.0,
                      int_per_year: float = +20.0,
                      years=range(2019, 2025)) -> pd.DataFrame:
    rows = []
    for y in years:
        rows.append({"geoid": geoid, "geography": geography,
                     "year": y, "measure": "domestic_mig", "value": dom_per_year,
                     "source": "test", "vintage": "test", "notes": ""})
        rows.append({"geoid": geoid, "geography": geography,
                     "year": y, "measure": "international_mig", "value": int_per_year,
                     "source": "test", "vintage": "test", "notes": ""})
    return pd.DataFrame(rows)


class TestDecomposeNetMigration:
    def test_schema(self):
        out = decompose_net_migration(_synth_net_mig(), _synth_components(),
                                      share_years=(2019, 2024))
        assert list(out.columns) == NET_MIGRATION_COMPONENTS_COLUMNS

    def test_cell_sum_identity(self):
        # m_dom + m_int must equal m_total for every cell, regardless of inputs.
        out = decompose_net_migration(_synth_net_mig(m_rate=0.05),
                                      _synth_components(dom_per_year=+50, int_per_year=+10))
        err = (out["m_dom_rate"].astype(float)
               + out["m_int_rate"].astype(float)
               - out["m_total_rate"].astype(float)).abs().max()
        assert err < 1e-12

    def test_tier1_share_matches_pep(self):
        # No age shape → p_dom = dom_sum / (dom_sum + int_sum).
        out = decompose_net_migration(_synth_net_mig(),
                                      _synth_components(dom_per_year=+80, int_per_year=+20))
        p = float(out["p_dom_county"].iloc[0])
        assert abs(p - 0.8) < 1e-9
        # m_dom should be 80% of m_total when age_shape is None.
        ratio = float(out["m_dom_rate"].iloc[0]) / float(out["m_total_rate"].iloc[0])
        assert abs(ratio - 0.8) < 1e-9

    def test_opposite_sign_components_yield_signed_p_dom(self):
        # Domestic net = -135, international net = +51 → p_dom = -135 / -84 = 1.607
        out = decompose_net_migration(_synth_net_mig(m_rate=-0.001),
                                      _synth_components(dom_per_year=-135, int_per_year=+51))
        p = float(out["p_dom_county"].iloc[0])
        assert abs(p - (-135.0 / -84.0)) < 1e-9
        # |p_dom| > 1 — instability flag should NOT fire at default threshold 5.
        assert (out["notes"] == "").all()

    def test_instability_flag(self):
        # Net = -7, components -98 and +91 → p_dom = -98/-7 = 14.0 → flagged.
        out = decompose_net_migration(_synth_net_mig(),
                                      _synth_components(dom_per_year=-98, int_per_year=+91))
        assert (out["notes"].str.startswith("p_dom_unstable")).all()

    def test_age_tilt_zero_factor_matches_tier1(self):
        # With age_tilt_factor = 0, the age shape should have no effect.
        shape_band = pd.DataFrame({
            "age_lower": [1], "age_upper": [pd.NA], "age_band": ["1 to 4 years"],
            "f_dom": [0.5],
        })
        shape_single = expand_age_shape_to_single_year(shape_band, top_code_age=5)
        # Build matching net_mig with same age range as shape coverage.
        nm = _synth_net_mig()
        out_no_shape = decompose_net_migration(nm, _synth_components(),
                                               age_shape_single_year=None)
        out_zero_tilt = decompose_net_migration(nm, _synth_components(),
                                                age_shape_single_year=shape_single,
                                                age_tilt_factor=0.0)
        # Both should produce identical m_dom_rate per cell.
        merged = out_no_shape.merge(
            out_zero_tilt, on=["geoid", "sex", "age", "source_age", "band_type"],
            suffixes=("_a", "_b"),
        )
        diff = (merged["m_dom_rate_a"].astype(float)
                - merged["m_dom_rate_b"].astype(float)).abs().max()
        assert diff < 1e-12
