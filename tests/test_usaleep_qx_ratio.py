"""Tests for the USALEEP qx-ratio adjustment helpers in popfc.data.nchs."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from popfc.data._common import LIFE_TABLE_COLUMNS
from popfc.data.nchs import (
    apply_qx_ratio_to_life_table,
    usaleep_qx_band_ratio,
)

_BAND_STARTS = [0, 1, 5, 15, 25, 35, 45, 55, 65, 75, 85]
_BAND_LABELS = [
    "Under 1", "1-4", "5-14", "15-24", "25-34",
    "35-44", "45-54", "55-64", "65-74", "75-84", "85 and older",
]


def _usaleep_lt(qx_per_band: list[float]) -> pd.DataFrame:
    """Build a tiny USALEEP-shaped life table from per-band qx values."""
    return pd.DataFrame({
        "age": _BAND_STARTS,
        "age_band": _BAND_LABELS,
        "qx": qx_per_band,
    })


def _nvsr_lt(n_ages: int = 101) -> pd.DataFrame:
    """Build a synthetic NVSR-shaped life table — ages 0..n_ages-1, all sexes=All."""
    ages = list(range(n_ages))
    qx = [0.001] * n_ages  # placeholder constant
    qx[-1] = 1.0
    lx = [100_000.0]
    for i in range(n_ages - 1):
        lx.append(lx[-1] * (1.0 - qx[i]))
    Lx = [(lx[i] + lx[i + 1]) / 2 for i in range(n_ages - 1)] + [lx[-1] * 5.0]
    Tx = list(np.cumsum(Lx[::-1])[::-1])
    ex = [Tx[i] / lx[i] if lx[i] > 0 else 0.0 for i in range(n_ages)]
    return pd.DataFrame({
        "geoid": "36000", "geography": "NY", "year_start": 2022, "year_end": 2022,
        "sex": "All", "age": ages,
        "age_band": [f"{a}-{a+1}" if a < n_ages - 1 else f"{a}+" for a in ages],
        "qx": qx, "lx": lx, "Lx": Lx, "ex": ex,
        "source": "nchs_nvsr", "vintage": "nvsr-test", "notes": "",
    })


def test_qx_band_ratio_basic():
    target = _usaleep_lt([0.010, 0.001, 0.001, 0.005, 0.008, 0.012, 0.020, 0.045, 0.110, 0.290, 1.000])
    ref    = _usaleep_lt([0.005, 0.001, 0.001, 0.005, 0.008, 0.012, 0.020, 0.045, 0.110, 0.290, 1.000])
    out = usaleep_qx_band_ratio(target, ref)
    assert list(out.columns) == ["age", "age_band", "qx_ratio"]
    # First band: target / ref = 0.010 / 0.005 = 2.0
    assert out.iloc[0]["qx_ratio"] == pytest.approx(2.0)
    # Bands 5-95 are identical → ratio = 1.0
    closed_bands = out[(out["age"] >= 5) & (out["age"] <= 85)]
    np.testing.assert_allclose(closed_bands["qx_ratio"].astype(float), 1.0)


def test_qx_band_ratio_band_mismatch():
    target = _usaleep_lt([0.01] * 11)
    ref = target.iloc[:5].copy()  # missing bands
    with pytest.raises(ValueError, match="bands don't align"):
        usaleep_qx_band_ratio(target, ref)


def test_apply_ratio_lowers_qx_when_ratio_below_one():
    nvsr = _nvsr_lt(n_ages=11)  # short table for fast test
    # qx_ratio = 0.5 for every band → halve mortality across the board
    ratios = pd.DataFrame({
        "age": _BAND_STARTS, "age_band": _BAND_LABELS, "qx_ratio": [0.5] * 11,
    })
    out = apply_qx_ratio_to_life_table(
        nvsr, ratios, target_geoid="36115", target_geography="Wash",
    )
    assert list(out.columns) == LIFE_TABLE_COLUMNS
    # Adjusted qx should be half the original.
    np.testing.assert_allclose(
        out["qx"].astype(float).to_numpy(),
        nvsr["qx"].astype(float).to_numpy() * 0.5,
        atol=1e-9,
    )
    # e(0) should be higher (lower mortality → longer life).
    assert float(out[out["age"] == 0]["ex"].iloc[0]) >= float(nvsr[nvsr["age"] == 0]["ex"].iloc[0])


def test_apply_ratio_identity_when_all_ones():
    """qx_ratio = 1.0 for every band → output should match input qx exactly."""
    nvsr = _nvsr_lt(n_ages=11)
    ratios = pd.DataFrame({
        "age": _BAND_STARTS, "age_band": _BAND_LABELS, "qx_ratio": [1.0] * 11,
    })
    out = apply_qx_ratio_to_life_table(
        nvsr, ratios, target_geoid="36115", target_geography="Wash",
    )
    np.testing.assert_allclose(
        out["qx"].astype(float).to_numpy(),
        nvsr["qx"].astype(float).to_numpy(),
        atol=1e-9,
    )


def test_apply_ratio_writes_target_geoid_and_geography():
    nvsr = _nvsr_lt(n_ages=11)
    ratios = pd.DataFrame({
        "age": _BAND_STARTS, "age_band": _BAND_LABELS, "qx_ratio": [1.0] * 11,
    })
    out = apply_qx_ratio_to_life_table(
        nvsr, ratios, target_geoid="36115", target_geography="Washington",
    )
    assert (out["geoid"] == "36115").all()
    assert (out["geography"] == "Washington").all()
    # Vintage should carry a _usaleep_adj suffix.
    assert out["vintage"].str.endswith("_usaleep_adj").all()


def test_apply_ratio_caps_qx_at_one():
    """If a ratio would push qx above 1.0, it should clip to 1.0."""
    nvsr = _nvsr_lt(n_ages=11)
    # Push qx in the youngest band way up.
    ratios = pd.DataFrame({
        "age": _BAND_STARTS, "age_band": _BAND_LABELS,
        "qx_ratio": [5000.0] + [1.0] * 10,
    })
    out = apply_qx_ratio_to_life_table(
        nvsr, ratios, target_geoid="X", target_geography="X",
    )
    # The age-0 qx_adj = 0.001 * 5000 = 5.0 → clip to 1.0.
    assert float(out[out["age"] == 0]["qx"].iloc[0]) == pytest.approx(1.0)
