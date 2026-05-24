"""Tests for popfc.data.census.load_census_sya."""

from __future__ import annotations

import pandas as pd
import pytest

from popfc.data._common import AGESEX_LONG_COLUMNS
from popfc.data.census import DEFAULT_SYA_2020_PLUS, load_census_sya


@pytest.fixture(scope="module")
def sya():
    if not DEFAULT_SYA_2020_PLUS.exists():
        pytest.skip(f"Census SYA file not present at {DEFAULT_SYA_2020_PLUS}")
    return load_census_sya()


def test_schema(sya):
    assert list(sya.columns) == AGESEX_LONG_COLUMNS


def test_row_count(sya):
    # 62 NY counties × 6 YEAR-codes × 86 ages × 2 sex = 63,984
    assert len(sya) == 62 * 6 * 86 * 2


def test_years_and_kinds(sya):
    assert set(sya["year"].unique()) == {2020, 2021, 2022, 2023, 2024}
    assert set(sya["kind"].unique()) == {"census", "estimate"}
    # 2020 has both kinds; 2021-2024 have estimate only.
    yk = sya.groupby("year")["kind"].unique().apply(lambda a: set(a)).to_dict()
    assert yk[2020] == {"census", "estimate"}
    assert yk[2021] == {"estimate"}
    assert yk[2022] == {"estimate"}
    assert yk[2023] == {"estimate"}
    assert yk[2024] == {"estimate"}


def test_age_range(sya):
    assert sya["age"].min() == 0
    assert sya["age"].max() == 85
    # All ages 0..85 present per (county, year, kind, sex) cell
    counts = sya.groupby(["geoid", "year", "kind", "sex"])["age"].nunique()
    assert (counts == 86).all()


def test_washington_totals_match_pep(sya):
    """Verify YEAR-code mapping by checking Washington against expected PEP V2024 totals."""
    wash = sya[sya["geoid"] == "36115"].groupby(["year", "kind"])["population"].sum()
    # Values verified against PEP V2024 (co-est2024-alldata.csv) for Washington Co:
    # ESTIMATESBASE2020=61302, POPESTIMATE2020-2024 = 61106, 60871, 60764, 60032, 59839.
    expected = {
        (2020, "census"):   61302,
        (2020, "estimate"): 61106,
        (2021, "estimate"): 60871,
        (2022, "estimate"): 60764,
        (2023, "estimate"): 60032,
        (2024, "estimate"): 59839,
    }
    for k, v in expected.items():
        assert int(wash.loc[k]) == v, f"mismatch at {k}: got {int(wash.loc[k])}, expected {v}"


def test_sex_split_sums_to_kind_total(sya):
    by_sex = sya.groupby(["geoid", "year", "kind", "sex"])["population"].sum().unstack("sex")
    by_sex["total"] = by_sex["M"] + by_sex["F"]
    # Cross-check that within each (geoid, year, kind), sex totals roll up cleanly.
    # We don't have an independent M+F total in the file beyond TOT_POP, so this
    # is mostly an internal sanity check that nothing got lost in the melt.
    assert by_sex["total"].notna().all()
    assert (by_sex["total"] > 0).all()
