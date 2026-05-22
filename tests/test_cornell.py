"""Tests for popfc.data.cornell."""

from __future__ import annotations

import pandas as pd
import pytest

from popfc.data._common import POP_LONG_COLUMNS
from popfc.data.cdc import AGESEX_LONG_COLUMNS
from popfc.data.cornell import DEFAULT_CORNELL_XLS, load_cornell_pad


@pytest.fixture(scope="module")
def pad():
    if not DEFAULT_CORNELL_XLS.exists():
        pytest.skip(f"Cornell PAD file not present at {DEFAULT_CORNELL_XLS}")
    return load_cornell_pad()


def test_returns_three_frames(pad):
    assert set(pad.keys()) == {"totals", "by_sex", "agesex"}


def test_totals_schema(pad):
    assert list(pad["totals"].columns) == POP_LONG_COLUMNS


def test_agesex_schema(pad):
    assert list(pad["agesex"].columns) == AGESEX_LONG_COLUMNS


def test_year_horizon(pad):
    yrs = pad["totals"]["year"]
    assert yrs.min() == 2015
    assert yrs.max() == 2040
    assert len(yrs) == 26


def test_male_plus_female_equals_all(pad):
    bs = pad["by_sex"].pivot_table(
        index="year", columns="sex", values="population", aggfunc="sum"
    )
    diff = (bs["All"].astype("Int64") - (bs["M"] + bs["F"]).astype("Int64")).abs().max()
    assert int(diff) == 0


def test_agesex_sums_to_by_sex(pad):
    agesex_sum = (
        pad["agesex"].groupby(["year", "sex"])["population"].sum().unstack("sex")
    )
    bs = pad["by_sex"].pivot_table(
        index="year", columns="sex", values="population", aggfunc="sum"
    )
    for s in ("M", "F"):
        diff = (bs[s].astype("Int64") - agesex_sum[s].astype("Int64")).abs().max()
        assert int(diff) == 0


def test_geoid_is_washington(pad):
    assert (pad["totals"]["geoid"] == "36115").all()


def test_no_median_rows_in_agesex(pad):
    # AGEGRPCODE 999 ("Median") must not survive into the age detail.
    assert (pad["agesex"]["age"] <= 85).all()
    assert (pad["agesex"]["age"] >= 0).all()
