"""Tests for the v3 input-quality refinements in popfc.models.hamilton_perry.

Covers the Notebook-12 audit follow-ups:
- rescale_base_to_target (PEP base-year rescaling)
- aggregate_history_to_parent (county-reference history)
- population_shrinkage_weights (w = P / (P + k))
- shrink_ccrs_toward_reference / shrink_cwr_toward_reference
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from popfc.models.hamilton_perry import (
    aggregate_history_to_parent,
    population_shrinkage_weights,
    rescale_base_to_target,
    shrink_ccrs_toward_reference,
    shrink_cwr_toward_reference,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_base(geoid="A", per_cell=100.0) -> pd.DataFrame:
    """5-yr-band base pop: 2 sexes × 3 bands, uniform `per_cell`."""
    rows = []
    for sex in ("M", "F"):
        for start in (0, 5, 10):
            rows.append({
                "geoid": geoid, "geography": "Town A", "sex": sex,
                "age_band_start": start, "age_band_end": start + 4,
                "population": per_cell,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# rescale_base_to_target
# ---------------------------------------------------------------------------

class TestRescaleBaseToTarget:
    def test_scales_to_target_total(self):
        base = _make_base(per_cell=100.0)  # total = 600
        out = rescale_base_to_target(base, {"A": 900.0})
        assert abs(out["population"].sum() - 900.0) < 1e-9
        # Factor 1.5 applied uniformly.
        assert (out["rescale_factor"] == 1.5).all()
        # Shape preserved — all cells still equal.
        assert out["population"].nunique() == 1

    def test_shape_preserved(self):
        # Non-uniform base — proportions must survive rescaling.
        base = _make_base(per_cell=100.0)
        base.loc[0, "population"] = 300.0  # one cell heavier
        total_before = base["population"].sum()
        shares_before = base["population"] / total_before
        out = rescale_base_to_target(base, {"A": total_before * 2})
        shares_after = out["population"] / out["population"].sum()
        np.testing.assert_allclose(shares_before.to_numpy(),
                                   shares_after.to_numpy(), atol=1e-12)

    def test_missing_target_passes_through(self):
        base = _make_base(geoid="Z")
        out = rescale_base_to_target(base, {"A": 900.0})  # Z not in targets
        assert (out["rescale_factor"] == 1.0).all()
        assert abs(out["population"].sum() - base["population"].sum()) < 1e-9

    def test_factor_clipped_and_warns(self):
        base = _make_base(per_cell=100.0)  # total 600
        # Target 6000 → factor 10 → clipped to max_factor=2.0, with a warning.
        with pytest.warns(UserWarning, match="rescale factor outside"):
            out = rescale_base_to_target(base, {"A": 6000.0}, max_factor=2.0)
        assert (out["rescale_factor"] == 2.0).all()

    def test_accepts_dataframe_target(self):
        base = _make_base(per_cell=100.0)
        tgt = pd.DataFrame({"geoid": ["A"], "population": [1200.0]})
        out = rescale_base_to_target(base, tgt)
        assert abs(out["population"].sum() - 1200.0) < 1e-9


# ---------------------------------------------------------------------------
# aggregate_history_to_parent
# ---------------------------------------------------------------------------

class TestAggregateHistoryToParent:
    def _make_history(self):
        rows = []
        for geoid in ("A", "B"):
            for m in (2010, 2015):
                for sex in ("M", "F"):
                    for start in (0, 5):
                        rows.append({
                            "geoid": geoid, "geography": geoid, "sex": sex,
                            "age_band_start": start, "age_band_end": start + 4,
                            "population": 100.0 if geoid == "A" else 50.0,
                            "vintage_midpoint_year": m,
                        })
        return pd.DataFrame(rows)

    def test_sums_across_geographies(self):
        hist = self._make_history()
        agg = aggregate_history_to_parent(hist, parent_geoid="PARENT")
        # One parent geoid, summed populations (100 + 50 = 150 per cell).
        assert (agg["geoid"] == "PARENT").all()
        assert (agg["population"] == 150.0).all()
        # 2 vintages × 2 sexes × 2 bands = 8 rows.
        assert len(agg) == 8

    def test_missing_columns_raise(self):
        bad = pd.DataFrame({"geoid": ["A"], "population": [1.0]})
        with pytest.raises(ValueError, match="missing columns"):
            aggregate_history_to_parent(bad, parent_geoid="P")


# ---------------------------------------------------------------------------
# population_shrinkage_weights
# ---------------------------------------------------------------------------

class TestShrinkageWeights:
    def test_formula(self):
        base = pd.concat([
            _make_base(geoid="small", per_cell=100.0),     # total 600
            _make_base(geoid="big", per_cell=1000.0),       # total 6000
        ], ignore_index=True)
        w = population_shrinkage_weights(base, k=2000.0)
        # small: 600 / 2600 ≈ 0.2308; big: 6000 / 8000 = 0.75
        assert abs(w["small"] - 600 / 2600) < 1e-9
        assert abs(w["big"] - 0.75) < 1e-9

    def test_weights_in_unit_interval(self):
        base = _make_base(per_cell=100.0)
        w = population_shrinkage_weights(base, k=2000.0)
        assert (w > 0).all() and (w < 1).all()

    def test_k_at_pop_gives_half(self):
        base = _make_base(per_cell=100.0)  # total 600
        w = population_shrinkage_weights(base, k=600.0)
        assert abs(w["A"] - 0.5) < 1e-9


# ---------------------------------------------------------------------------
# shrink_ccrs_toward_reference
# ---------------------------------------------------------------------------

class TestShrinkCCRs:
    def _town_ccr(self, geoid="A", ccr=1.30):
        rows = []
        for sex in ("M", "F"):
            for start in (5, 10):
                rows.append({"geoid": geoid, "sex": sex,
                             "age_band_start": start, "ccr": ccr})
        return pd.DataFrame(rows)

    def _ref_ccr(self, ccr=1.00):
        rows = []
        for sex in ("M", "F"):
            for start in (5, 10):
                rows.append({"sex": sex, "age_band_start": start, "ccr": ccr})
        return pd.DataFrame(rows)

    def test_weight_one_keeps_town(self):
        out = shrink_ccrs_toward_reference(
            self._town_ccr(ccr=1.30), self._ref_ccr(ccr=1.00),
            town_weights={"A": 1.0},
        )
        np.testing.assert_allclose(out["ccr"].to_numpy(), 1.30)

    def test_weight_zero_takes_reference(self):
        out = shrink_ccrs_toward_reference(
            self._town_ccr(ccr=1.30), self._ref_ccr(ccr=1.00),
            town_weights={"A": 0.0},
        )
        np.testing.assert_allclose(out["ccr"].to_numpy(), 1.00)

    def test_half_weight_blends(self):
        out = shrink_ccrs_toward_reference(
            self._town_ccr(ccr=1.30), self._ref_ccr(ccr=1.00),
            town_weights={"A": 0.5},
        )
        # 0.5 * 1.30 + 0.5 * 1.00 = 1.15
        np.testing.assert_allclose(out["ccr"].to_numpy(), 1.15)
        # Bookkeeping columns present.
        assert {"ccr_town", "ccr_reference", "shrink_weight"} <= set(out.columns)

    def test_missing_reference_keeps_town(self):
        town = self._town_ccr(ccr=1.30)
        ref = self._ref_ccr(ccr=1.00).iloc[:1]  # only one (sex, band) cell
        out = shrink_ccrs_toward_reference(town, ref, town_weights={"A": 0.0})
        # Cells without a reference must keep the town value even at w=0.
        no_ref = out[out["ccr_reference"].isna()]
        np.testing.assert_allclose(no_ref["ccr"].to_numpy(),
                                   no_ref["ccr_town"].to_numpy())


# ---------------------------------------------------------------------------
# shrink_cwr_toward_reference
# ---------------------------------------------------------------------------

class TestShrinkCWR:
    def test_half_weight_blends(self):
        town = pd.DataFrame({"geoid": ["A", "A"], "sex": ["M", "F"],
                             "cwr": [0.42, 0.42]})
        ref = pd.DataFrame({"sex": ["M", "F"], "cwr": [0.24, 0.24]})
        out = shrink_cwr_toward_reference(town, ref, town_weights={"A": 0.5})
        # 0.5 * 0.42 + 0.5 * 0.24 = 0.33
        np.testing.assert_allclose(out["cwr"].to_numpy(), 0.33)

    def test_small_town_pulled_harder(self):
        town = pd.DataFrame({"geoid": ["small", "big"], "sex": ["F", "F"],
                             "cwr": [0.42, 0.42]})
        ref = pd.DataFrame({"sex": ["F"], "cwr": [0.24]})
        out = shrink_cwr_toward_reference(
            town, ref, town_weights={"small": 0.2, "big": 0.8},
        )
        small = float(out[out["geoid"] == "small"]["cwr"].iloc[0])
        big = float(out[out["geoid"] == "big"]["cwr"].iloc[0])
        # Small town pulled closer to the reference 0.24 than the big town.
        assert abs(small - 0.24) < abs(big - 0.24)
