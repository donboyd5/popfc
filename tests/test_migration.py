"""Tests for popfc.models.migration."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from popfc.models.migration import (
    NET_MIGRATION_RATES_COLUMNS,
    REFERENCE_PERIOD_COLUMNS,
    _residual_one_pair,
    build_net_migration_rates,
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
