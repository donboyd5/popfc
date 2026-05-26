"""Tests for popfc.data.nchs.usaleep_county_life_table aggregator."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from popfc.data._common import LIFE_TABLE_COLUMNS
from popfc.data.nchs import (
    load_usaleep_life_table,
    usaleep_county_life_table,
)


# Standard USALEEP age band map.
_BANDS = [
    (0, "Under 1"), (1, "1-4"), (5, "5-14"), (15, "15-24"),
    (25, "25-34"), (35, "35-44"), (45, "45-54"), (55, "55-64"),
    (65, "65-74"), (75, "75-84"), (85, "85 and older"),
]


def _synthetic_tracts(tract_ids: list[str], qx_per_tract: dict[str, list[float]]):
    """Build a tract_table-shaped frame from per-tract qx vectors."""
    rows = []
    for tid in tract_ids:
        qx_list = qx_per_tract[tid]
        for (age, band), qx in zip(_BANDS, qx_list):
            rows.append({
                "geoid": tid,
                "geography": f"Tract {tid}",
                "year_start": 2010, "year_end": 2015, "sex": "All",
                "age": age, "age_band": band,
                "qx": qx, "lx": 100_000.0, "Lx": 95_000.0, "ex": 80.0,
                "source": "nchs_usaleep", "vintage": "usaleep_2010_2015",
                "notes": "",
            })
    return pd.DataFrame(rows)


def test_schema_conformance():
    """Aggregator output should conform to LIFE_TABLE_COLUMNS."""
    qx = [0.005, 0.001, 0.001, 0.005, 0.008, 0.012, 0.020, 0.045, 0.110, 0.290, 1.000]
    tracts = _synthetic_tracts(
        ["36115000100", "36115000200", "36115000300"],
        {"36115000100": qx, "36115000200": qx, "36115000300": qx},
    )
    out = usaleep_county_life_table(tracts, county_fips="115")
    assert list(out.columns) == LIFE_TABLE_COLUMNS
    # 11 bands.
    assert len(out) == 11
    # geoid is the 5-digit county.
    assert (out["geoid"] == "36115").all()
    # All bands are tagged USALEEP.
    assert (out["source"] == "nchs_usaleep").all()


def test_identical_tracts_match_input():
    """If every tract is identical, the aggregate qx equals the per-tract qx."""
    qx = [0.005, 0.001, 0.001, 0.005, 0.008, 0.012, 0.020, 0.045, 0.110, 0.290, 1.000]
    tracts = _synthetic_tracts(
        ["36115000100", "36115000200"],
        {"36115000100": qx, "36115000200": qx},
    )
    out = usaleep_county_life_table(tracts, county_fips="115")
    np.testing.assert_allclose(
        out["qx"].astype(float).to_numpy(), qx, atol=1e-9
    )


def test_population_weighting_shifts_qx():
    """Higher-population tract pulls the aggregate qx toward its values."""
    qx_low = [0.005, 0.001, 0.001, 0.005, 0.008, 0.010, 0.015, 0.030, 0.080, 0.220, 1.000]
    qx_high = [0.010, 0.002, 0.002, 0.010, 0.016, 0.020, 0.030, 0.060, 0.140, 0.360, 1.000]
    tracts = _synthetic_tracts(
        ["36115000100", "36115000200"],
        {"36115000100": qx_low, "36115000200": qx_high},
    )

    # Equal weighting → midpoint qx.
    out_equal = usaleep_county_life_table(tracts, county_fips="115")
    midpoint = np.array(qx_low) / 2 + np.array(qx_high) / 2
    np.testing.assert_allclose(
        out_equal["qx"].astype(float).to_numpy(), midpoint, atol=1e-9,
    )

    # Heavily-weight the low-qx tract → aggregate moves toward qx_low.
    weights = pd.Series({"36115000100": 9.0, "36115000200": 1.0})
    out_w = usaleep_county_life_table(tracts, county_fips="115", weights=weights)
    weighted = 0.9 * np.array(qx_low) + 0.1 * np.array(qx_high)
    np.testing.assert_allclose(
        out_w["qx"].astype(float).to_numpy(), weighted, atol=1e-9,
    )
    # Aggregate qx should be closer to qx_low than to the midpoint.
    assert (
        (out_w["qx"].astype(float) - qx_low).abs().sum()
        < (out_equal["qx"].astype(float) - qx_low).abs().sum()
    )


def test_missing_county_raises():
    qx = [0.005] * 11
    tracts = _synthetic_tracts(["36001000100"], {"36001000100": qx})
    with pytest.raises(ValueError, match="no tract rows"):
        usaleep_county_life_table(tracts, county_fips="115")


def test_missing_weights_raises():
    qx = [0.005] * 11
    tracts = _synthetic_tracts(
        ["36115000100", "36115000200"],
        {"36115000100": qx, "36115000200": qx},
    )
    # Weights provided only for one of the two tracts.
    weights = pd.Series({"36115000100": 1.0})
    with pytest.raises(ValueError, match="weights missing values"):
        usaleep_county_life_table(tracts, county_fips="115", weights=weights)


def test_real_washington_data():
    """Sanity check the function against the real Washington NY data."""
    tracts = load_usaleep_life_table(county_fips="115")
    assert tracts["geoid"].nunique() == 17  # known Washington Co tract count
    out = usaleep_county_life_table(tracts, county_fips="115")
    e0 = float(out[out["age"] == 0]["ex"].iloc[0])
    # The empirical aggregate is ~81.4; assert within a generous tolerance
    # so this test isn't brittle to future USALEEP refreshes (USALEEP is static,
    # but the function might change).
    assert 75.0 <= e0 <= 90.0
