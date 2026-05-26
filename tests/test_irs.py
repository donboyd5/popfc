"""Tests for popfc.data.irs.load_irs_county_migration."""

from __future__ import annotations

import pandas as pd
import pytest

from popfc.data.irs import (
    DEFAULT_VINTAGE_TAG,
    IRS_MIGRATION_COLUMNS,
    PARTNER_KIND_NON_MIGRANTS,
    PARTNER_KIND_OTHER_DIFFERENT_STATE,
    PARTNER_KIND_OTHER_REGION,
    PARTNER_KIND_OTHER_SAME_STATE,
    PARTNER_KIND_SPECIFIC,
    PARTNER_KIND_TOTAL_DIFFERENT_STATE,
    PARTNER_KIND_TOTAL_SAME_STATE,
    PARTNER_KIND_TOTAL_US,
    PARTNER_KIND_TOTAL_US_AND_FOREIGN,
    _default_inflow_path,
    _default_outflow_path,
    _vintage_from_tag,
    load_irs_county_migration,
)


@pytest.fixture(scope="module")
def irs_ny():
    if not _default_inflow_path(DEFAULT_VINTAGE_TAG).exists():
        pytest.skip(f"IRS inflow file not present at {_default_inflow_path(DEFAULT_VINTAGE_TAG)}")
    if not _default_outflow_path(DEFAULT_VINTAGE_TAG).exists():
        pytest.skip(f"IRS outflow file not present at {_default_outflow_path(DEFAULT_VINTAGE_TAG)}")
    return load_irs_county_migration()


def test_vintage_from_tag():
    y1, y2, label = _vintage_from_tag("2223")
    assert y1 == 2022 and y2 == 2023
    assert label == "irs_soi_2022-2023"


def test_vintage_from_tag_bad():
    with pytest.raises(ValueError):
        _vintage_from_tag("not-a-tag")


def test_schema(irs_ny):
    assert list(irs_ny.columns) == IRS_MIGRATION_COLUMNS


def test_state_filter_default_is_ny(irs_ny):
    # Every row anchored on NY (statefips == 36).
    assert (irs_ny["state_fips"] == "36").all()


def test_both_directions(irs_ny):
    assert set(irs_ny["direction"].unique()) == {"in", "out"}


def test_sentinel_kinds_present(irs_ny):
    # Each NY anchor has one row each of the grand-total sentinels.
    for kind in (
        PARTNER_KIND_TOTAL_US,
        PARTNER_KIND_TOTAL_US_AND_FOREIGN,
        PARTNER_KIND_TOTAL_SAME_STATE,
        PARTNER_KIND_TOTAL_DIFFERENT_STATE,
    ):
        counts = irs_ny[irs_ny["partner_kind"] == kind].groupby("direction").size()
        # 62 NY counties × 2 directions == 124, but every county should have these.
        assert counts.get("in", 0) > 0 and counts.get("out", 0) > 0


def test_specific_county_partner_geoids_are_valid(irs_ny):
    sp = irs_ny[irs_ny["partner_kind"] == PARTNER_KIND_SPECIFIC]
    # Partner geoids should be 5-char strings, all digits.
    assert sp["partner_geoid"].str.len().eq(5).all()
    assert sp["partner_geoid"].str.match(r"^\d{5}$").all()


def test_non_migrants_anchor_eq_partner(irs_ny):
    nm = irs_ny[irs_ny["partner_kind"] == PARTNER_KIND_NON_MIGRANTS]
    # By construction the partner_geoid equals the anchor geoid for non-migrant rows.
    assert (nm["partner_geoid"] == nm["geoid"]).all()


def test_aggregate_kinds_have_no_partner_geoid(irs_ny):
    aggregate_kinds = {
        PARTNER_KIND_TOTAL_US_AND_FOREIGN,
        PARTNER_KIND_TOTAL_US,
        PARTNER_KIND_TOTAL_SAME_STATE,
        PARTNER_KIND_TOTAL_DIFFERENT_STATE,
        PARTNER_KIND_OTHER_SAME_STATE,
        PARTNER_KIND_OTHER_DIFFERENT_STATE,
        PARTNER_KIND_OTHER_REGION,
    }
    agg = irs_ny[irs_ny["partner_kind"].isin(aggregate_kinds)]
    assert agg["partner_geoid"].isna().all()


def test_total_us_consistency(irs_ny):
    # total_us_and_foreign should be >= total_us for each (geoid, direction) —
    # the "and foreign" version aggregates over MORE flows.
    wide = (
        irs_ny[irs_ny["partner_kind"].isin([
            PARTNER_KIND_TOTAL_US, PARTNER_KIND_TOTAL_US_AND_FOREIGN
        ])]
        .pivot_table(
            index=["geoid", "direction"], columns="partner_kind",
            values="exemptions", aggfunc="first",
        )
        .dropna()
    )
    # exemptions are Int64 with possible NA; drop those.
    assert (wide[PARTNER_KIND_TOTAL_US_AND_FOREIGN] >= wide[PARTNER_KIND_TOTAL_US]).all()


def test_direction_only(irs_ny):
    # load_irs_county_migration(direction="in") returns inflow only.
    only_in = load_irs_county_migration(direction="in")
    assert set(only_in["direction"].unique()) == {"in"}
    assert list(only_in.columns) == IRS_MIGRATION_COLUMNS


def test_geoid_format(irs_ny):
    # Anchor geoid is always 5 chars and starts with state_fips.
    assert irs_ny["geoid"].str.len().eq(5).all()
    assert (irs_ny["geoid"].str[:2] == irs_ny["state_fips"]).all()
