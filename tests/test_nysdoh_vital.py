"""Tests for popfc.data.nysdoh_vital — Socrata fetching + parsing.

Network calls are mocked via monkeypatch on ``requests.get`` so the suite
runs offline. A separate integration check (`test_live_pull_smoke`) hits
the real API if the cache is present from a prior development run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from popfc.data import nysdoh_vital as nv
from popfc.data._common import COMPONENTS_LONG_COLUMNS


# ---------------------------------------------------------------------------
# Synthetic Socrata responses
# ---------------------------------------------------------------------------

_FAKE_BIRTHS_ROWS = [
    # Real county — Albany
    {"year": "2022", "county": "Albany", "mother_s_age_range": "20-24", "value": "100"},
    {"year": "2022", "county": "Albany", "mother_s_age_range": "25-29", "value": "200"},
    {"year": "2022", "county": "Albany", "mother_s_age_range": "Total",  "value": "300"},
    # Aggregate row — should be dropped by default
    {"year": "2022", "county": "New York State", "mother_s_age_range": "Total", "value": "20000"},
    # Different year for Albany
    {"year": "2023", "county": "Albany", "mother_s_age_range": "Total", "value": "310"},
]

_FAKE_DEATHS_ROWS = [
    {"year": "2021", "county_name": "Albany", "region": "ROS", "age_group": "65-74", "deaths": "120"},
    {"year": "2021", "county_name": "Albany", "region": "ROS", "age_group": "85+",   "deaths": "200"},
    {"year": "2021", "county_name": "Albany", "region": "ROS", "age_group": "Total", "deaths": "320"},
    {"year": "2021", "county_name": "New York State", "region": "NYS", "age_group": "Total", "deaths": "150000"},
]

_FAKE_META = {"rowsUpdatedAt": 1735689600}  # 2025-01-01 UTC


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload)
    def json(self):
        return self._payload
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _make_fake_requests_get(meta_payload, data_rows):
    """Return a fake `requests.get` that mimics Socrata responses."""
    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        if "/api/views/" in url:
            return _FakeResp(meta_payload)
        # /resource/<id>.json — return all rows in one page (smaller than page_size).
        return _FakeResp(data_rows)
    return fake_get


@pytest.fixture
def _isolated_cache(monkeypatch, tmp_path):
    """Redirect the cache dir to a tmp path so tests don't pollute real cache."""
    monkeypatch.setattr(nv, "_API_DIR", tmp_path / "api")
    yield tmp_path / "api"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestSocrataMetadata:
    def test_data_publication_date_from_epoch(self):
        # 2025-01-01 00:00 UTC = epoch 1735689600
        assert nv._data_publication_date({"rowsUpdatedAt": 1735689600}) == "20250101"

    def test_data_publication_date_unknown(self):
        assert nv._data_publication_date({}) == "unknown"
        assert nv._data_publication_date({"rowsUpdatedAt": None}) == "unknown"
        assert nv._data_publication_date({"rowsUpdatedAt": "garbage"}) == "unknown"


class TestNameToFIPS:
    def test_covers_all_62_counties(self):
        # 62 counties + Washington should be present; aggregates excluded.
        assert "Washington" in nv.NYSDOH_NAME_TO_FIPS
        assert nv.NYSDOH_NAME_TO_FIPS["Washington"] == "115"
        # Aggregates excluded
        assert "New York State" not in nv.NYSDOH_NAME_TO_FIPS
        assert "New York City" not in nv.NYSDOH_NAME_TO_FIPS
        # 62 counties total
        assert len(nv.NYSDOH_NAME_TO_FIPS) == 62


# ---------------------------------------------------------------------------
# Loaders (mocked Socrata)
# ---------------------------------------------------------------------------

class TestLoadBirths:
    def test_schema_and_totals(self, monkeypatch, _isolated_cache):
        monkeypatch.setattr(nv.requests, "get",
                            _make_fake_requests_get(_FAKE_META, _FAKE_BIRTHS_ROWS))
        out = nv.load_nysdoh_births()
        assert set(out.keys()) == {"totals", "by_mother_age"}
        # Schemas conform
        assert list(out["totals"].columns) == COMPONENTS_LONG_COLUMNS
        # Aggregates dropped by default → no "New York State" row
        assert "New York State" not in out["totals"]["geography"].tolist()
        # Albany 2022 total = 300 (from the explicit 'Total' row, not summed)
        albany_2022 = out["totals"][
            (out["totals"]["geoid"] == "36001") & (out["totals"]["year"] == 2022)
        ]
        assert int(albany_2022["value"].iloc[0]) == 300
        # measure column
        assert (out["totals"]["measure"] == "births").all()

    def test_keep_aggregates_keeps_state_row(self, monkeypatch, _isolated_cache):
        monkeypatch.setattr(nv.requests, "get",
                            _make_fake_requests_get(_FAKE_META, _FAKE_BIRTHS_ROWS))
        out = nv.load_nysdoh_births(keep_aggregates=True)
        # State aggregate present, with sentinel county_fips '000' and 5-char geoid '36000'
        nys = out["totals"][out["totals"]["geography"] == "New York State"]
        assert len(nys) == 1
        assert nys["geoid"].iloc[0] == "36000"
        assert int(nys["value"].iloc[0]) == 20000

    def test_cache_round_trip(self, monkeypatch, _isolated_cache):
        calls = {"n": 0}
        base = _make_fake_requests_get(_FAKE_META, _FAKE_BIRTHS_ROWS)
        def counting_get(*a, **kw):
            calls["n"] += 1
            return base(*a, **kw)
        monkeypatch.setattr(nv.requests, "get", counting_get)

        out1 = nv.load_nysdoh_births()
        calls_after_first = calls["n"]
        out2 = nv.load_nysdoh_births()  # should be cache hit (no new fetches)
        # The metadata endpoint is hit each call (we always re-check
        # publication date), but the rows endpoint is only hit on miss.
        # Allow at most one extra meta hit per call.
        assert calls["n"] - calls_after_first <= 1
        # Frames are equal.
        pd.testing.assert_frame_equal(out1["totals"], out2["totals"])

    def test_vintage_format(self, monkeypatch, _isolated_cache):
        monkeypatch.setattr(nv.requests, "get",
                            _make_fake_requests_get(_FAKE_META, _FAKE_BIRTHS_ROWS))
        out = nv.load_nysdoh_births()
        v = out["totals"]["vintage"].iloc[0]
        assert v == "nysdoh_vital_20250101", f"got {v!r}"


class TestLoadDeaths:
    def test_schema_and_totals(self, monkeypatch, _isolated_cache):
        monkeypatch.setattr(nv.requests, "get",
                            _make_fake_requests_get(_FAKE_META, _FAKE_DEATHS_ROWS))
        out = nv.load_nysdoh_deaths()
        assert list(out["totals"].columns) == COMPONENTS_LONG_COLUMNS
        albany_2021 = out["totals"][
            (out["totals"]["geoid"] == "36001") & (out["totals"]["year"] == 2021)
        ]
        assert int(albany_2021["value"].iloc[0]) == 320
        assert (out["totals"]["measure"] == "deaths").all()
        # Detail frame has region column
        assert "region" in out["by_age_group"].columns


# ---------------------------------------------------------------------------
# Live-pull smoke check (skipped unless cache is present)
# ---------------------------------------------------------------------------

class TestLivePull:
    def test_cached_response_parses(self):
        """If a prior dev run cached the live response, confirm it parses cleanly."""
        from popfc.paths import NYSDOH_DIR
        cache_dir = NYSDOH_DIR / "api"
        if not cache_dir.exists() or not any(cache_dir.glob("i7yg-w5rg_d*.json")):
            pytest.skip("no cached NYSDOH births API response — run loader once to populate")
        # Use the actual loader against the actual cache (no network, since cache exists).
        out = nv.load_nysdoh_births()
        assert len(out["totals"]) > 0
        assert out["totals"]["geoid"].nunique() == 62
        # Washington must be present at a recent year.
        wash = out["totals"][out["totals"]["geoid"] == "36115"]
        assert len(wash) > 0
        assert wash["year"].max() >= 2020
