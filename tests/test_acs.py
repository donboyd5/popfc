"""Tests for popfc.data.acs.

Live API tests are gated on the CENSUS_API_KEY env var being set; offline
tests cover URL building, error detection, key resolution, and parsing of
cached responses (skipped if the cache isn't populated).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pytest

from popfc.data import acs
from popfc.data.acs import (
    GEO_COUNTY,
    GEO_COUNTY_SUBDIVISION,
    LATEST_ACS5_YEAR,
    CensusApiError,
    _build_url,
    _is_html_error,
    _resolve_api_key,
    filter_variables_in_group,
    load_acs5_group,
)
from popfc.paths import ACS_DIR


# ---------------------------------------------------------------------------
# Offline tests
# ---------------------------------------------------------------------------

class TestUrlBuilding:
    def test_county_url_no_filter(self):
        url = _build_url(2024, get="NAME,B01001_001E", geography=GEO_COUNTY,
                         geo_filter={"state": "36"})
        assert url == (
            "https://api.census.gov/data/2024/acs/acs5"
            "?get=NAME,B01001_001E&for=county:*&in=state:36"
        )

    def test_mcd_url_with_parent_county(self):
        url = _build_url(2024, get="group(B01001)", geography=GEO_COUNTY_SUBDIVISION,
                         geo_filter={"state": "36", "county": "115"})
        assert "for=county%20subdivision:*" in url
        assert "in=state:36+county:115" in url

    def test_mcd_url_with_wildcard_county(self):
        url = _build_url(2024, get="group(B01001)", geography=GEO_COUNTY_SUBDIVISION,
                         geo_filter={"state": "36", "county": "*"})
        assert "in=state:36+county:*" in url


class TestErrorDetection:
    def test_detects_html_body(self):
        assert _is_html_error('<html><head><title>Missing Key</title>')
        assert _is_html_error('   <!DOCTYPE html><html>')
        assert _is_html_error('<HTML>')

    def test_passes_through_json(self):
        assert not _is_html_error('[["NAME","B01001_001E"],...]')
        assert not _is_html_error('{"variables": {...}}')


class TestKeyResolution:
    def test_explicit_arg_wins(self, monkeypatch):
        monkeypatch.setenv(acs.ENV_KEY_VAR, "from-env")
        assert _resolve_api_key("from-arg") == "from-arg"

    def test_env_var_when_no_arg(self, monkeypatch):
        monkeypatch.setenv(acs.ENV_KEY_VAR, "from-env")
        assert _resolve_api_key(None) == "from-env"

    def test_none_when_neither(self, monkeypatch):
        monkeypatch.delenv(acs.ENV_KEY_VAR, raising=False)
        assert _resolve_api_key(None) is None

    def test_unsupported_geography_raises(self):
        with pytest.raises(ValueError, match="Unsupported geography"):
            load_acs5_group("B01001", geography="bogus")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Cache-based tests (skip if not populated)
# ---------------------------------------------------------------------------

CACHE_DIR = ACS_DIR / str(LATEST_ACS5_YEAR)
B01001_COUNTY_CACHE = CACHE_DIR / "B01001_state36_county.json"


def _cache_present():
    return B01001_COUNTY_CACHE.exists() and (CACHE_DIR / "_variables.json").exists()


@pytest.mark.skipif(not _cache_present(),
                    reason="ACS cache not populated; run a live pull first")
class TestParseCachedResponse:
    def test_load_county_from_cache(self):
        df = load_acs5_group("B01001", year=LATEST_ACS5_YEAR,
                             geography=GEO_COUNTY, state_fips="36")
        assert df["geoid"].nunique() == 62
        # 49 estimate vars in B01001 × 62 counties
        assert len(df) == 49 * 62

    def test_known_value_present(self):
        df = load_acs5_group("B01001", year=LATEST_ACS5_YEAR,
                             geography=GEO_COUNTY, state_fips="36")
        wash_total = df[(df["geoid"] == "36115")
                        & (df["variable"] == "B01001_001E")]["value"].iloc[0]
        # ACS 2020-2024 5-yr Washington total population (verified at pull time).
        assert int(wash_total) == 60522

    def test_columns_include_provenance(self):
        df = load_acs5_group("B01001", year=LATEST_ACS5_YEAR,
                             geography=GEO_COUNTY, state_fips="36")
        for col in ("source", "vintage", "label", "concept", "geoid"):
            assert col in df.columns
        assert (df["source"] == "acs5").all()
        assert (df["vintage"] == f"acs5_{LATEST_ACS5_YEAR - 4}_{LATEST_ACS5_YEAR}").all()


# ---------------------------------------------------------------------------
# Variables-metadata tests (anonymous-accessible endpoint, but skip if no cache
# AND no network — keep tests deterministic by only relying on the cache).
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not (CACHE_DIR / "_variables.json").exists(),
                    reason="variables.json cache not populated")
def test_filter_variables_in_group():
    variables = json.loads((CACHE_DIR / "_variables.json").read_text())["variables"]
    b01001 = filter_variables_in_group(variables, "B01001")
    # 49 estimate variables in the B01001 group.
    assert len(b01001) == 49
    assert "B01001_001E" in b01001
    assert "B01001_001M" not in b01001  # margin of error not included
