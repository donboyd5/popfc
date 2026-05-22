"""American Community Survey (ACS) 5-year loader via the Census Data API.

Currently latest 5-year release: **ACS 2020-2024** (`year=2024`), released
December 2025. Update `LATEST_ACS5_YEAR` here when the next release ships.

## API key

Real data pulls **require a Census API key** as of 2025 — anonymous
requests return an HTML "Missing Key" page (HTTP 200, not 403, so callers
must inspect the body). Sign up at
https://api.census.gov/data/key_signup.html and export the key as

    export CENSUS_API_KEY=<your-key>

The variables-metadata endpoint (`variables.json`) is still anonymous-
accessible, so `get_acs_variables()` works without a key.

## Caching

Every fetched response is cached on disk under
`data_raw/acs/<year>/<filename>.json` (raw API response) and surfaced as a
parsed pandas DataFrame. Subsequent calls hit the cache; pass
`refresh=True` to force a re-pull.

## Statewide-by-default

Per project rules, loaders are statewide by default. For ACS at the
county-subdivision level the API requires a parent county, so MCD pulls
do take a `county_fips` parameter.
"""

from __future__ import annotations

import json
import os
import re
import warnings
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from popfc.paths import ACS_DIR

# ---------------------------------------------------------------------------
# Vintage / endpoint configuration
# ---------------------------------------------------------------------------

# Latest published ACS 5-year vintage. Update this single constant when the
# Census releases a newer 5-year endpoint (typically December each year).
LATEST_ACS5_YEAR: int = 2024

API_ROOT = "https://api.census.gov/data"
ENV_KEY_VAR = "CENSUS_API_KEY"

# Census API geography names. Public callers should use these constants
# rather than passing strings, so renames stay in one place.
GEO_COUNTY = "county"
GEO_COUNTY_SUBDIVISION = "county subdivision"
GEO_TRACT = "tract"

_SUPPORTED_GEOGRAPHIES = {GEO_COUNTY, GEO_COUNTY_SUBDIVISION, GEO_TRACT}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class CensusApiError(RuntimeError):
    """Raised when the Census Data API returns an error or unparseable body."""


def _resolve_api_key(api_key: str | None) -> str | None:
    """Return the API key from the explicit arg, env var, or None."""
    if api_key:
        return api_key
    val = os.environ.get(ENV_KEY_VAR)
    return val if val else None


def _build_url(
    year: int,
    dataset: str = "acs/acs5",
    *,
    get: str,
    geography: str,
    geo_filter: dict[str, str] | None = None,
) -> str:
    """Construct an ACS API URL (without the key — added at request time)."""
    base = f"{API_ROOT}/{year}/{dataset}"
    # The Census API URL-encodes spaces in geography names as "%20"; requests
    # handles encoding for us via params, but the `for`/`in` clauses are
    # idiomatic to keep in the query string.
    parts: list[str] = [f"get={get}"]
    parts.append(f"for={geography.replace(' ', '%20')}:*")
    if geo_filter:
        in_clause = "+".join(f"{k}:{v}" for k, v in geo_filter.items())
        parts.append(f"in={in_clause}")
    return base + "?" + "&".join(parts)


def _is_html_error(text: str) -> bool:
    """Census returns HTML rather than JSON for errors. Detect that case."""
    head = text.lstrip()[:64].lower()
    return head.startswith("<html") or head.startswith("<!doctype html")


def _cache_path(year: int, name: str) -> Path:
    out = ACS_DIR / str(year) / name
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def _fetch_json(
    url: str,
    cache_file: Path,
    *,
    api_key: str | None,
    refresh: bool,
    timeout: int = 60,
    require_key: bool = True,
) -> Any:
    """Fetch a Census API URL with on-disk caching.

    The cache file stores the raw JSON response body. Cache hits skip the
    network entirely. On error (missing key, HTML body, non-200), raises
    `CensusApiError` with the response text.

    `require_key=False` is used for the public variables endpoint, which the
    API serves without authentication.
    """
    if cache_file.exists() and not refresh:
        return json.loads(cache_file.read_text())

    if require_key and api_key is None:
        warnings.warn(
            f"{ENV_KEY_VAR} is not set — the Census API requires a key for "
            "data requests. Sign up at "
            "https://api.census.gov/data/key_signup.html",
            stacklevel=3,
        )

    params: dict[str, str] = {}
    if api_key:
        params["key"] = api_key

    resp = requests.get(url, params=params or None, timeout=timeout)
    text = resp.text
    if resp.status_code != 200 or _is_html_error(text):
        snippet = text[:400].replace("\n", " ")
        raise CensusApiError(
            f"Census API returned status {resp.status_code} from {url} "
            f"(key={'set' if api_key else 'UNSET — set CENSUS_API_KEY env var'}). "
            f"Body starts: {snippet!r}"
        )
    try:
        data = resp.json()
    except json.JSONDecodeError as e:
        snippet = text[:400].replace("\n", " ")
        raise CensusApiError(
            f"Could not parse JSON from {url}: {e}. Body starts: {snippet!r}"
        ) from e
    cache_file.write_text(text)
    return data


# ---------------------------------------------------------------------------
# Variable metadata
# ---------------------------------------------------------------------------

def get_acs_variables(
    year: int = LATEST_ACS5_YEAR,
    *,
    refresh: bool = False,
) -> dict[str, dict[str, Any]]:
    """Return the full variable metadata dict for an ACS 5-year vintage.

    This endpoint is anonymous-accessible (no key required). Cached to
    `data_raw/acs/<year>/_variables.json` after first call.
    """
    cache_file = _cache_path(year, "_variables.json")
    url = f"{API_ROOT}/{year}/acs/acs5/variables.json"
    payload = _fetch_json(url, cache_file, api_key=None, refresh=refresh,
                          require_key=False)
    return payload.get("variables", {})


def filter_variables_in_group(
    variables: dict[str, dict[str, Any]],
    group: str,
) -> dict[str, dict[str, Any]]:
    """Return only the variables belonging to a particular table group.

    ACS variable names look like ``B01001_001E`` (group=B01001, line=001,
    type=E for estimate or M for margin of error). This helper filters the
    full variables dict down to one group.
    """
    return {
        name: meta
        for name, meta in variables.items()
        if name.startswith(f"{group}_") and name.endswith("E")
    }


# ---------------------------------------------------------------------------
# Data pull
# ---------------------------------------------------------------------------

def load_acs5_group(
    group: str,
    *,
    year: int = LATEST_ACS5_YEAR,
    geography: str = GEO_COUNTY,
    state_fips: str = "36",
    county_fips: str | None = None,
    api_key: str | None = None,
    refresh: bool = False,
) -> pd.DataFrame:
    """Fetch every estimate variable in an ACS table group for a geography.

    Parameters
    ----------
    group
        ACS table group name, e.g., "B01001" (sex by age), "B07001"
        (geographic mobility), "B06001" (place of birth).
    year
        ACS 5-year vintage (default: `LATEST_ACS5_YEAR`).
    geography
        One of `GEO_COUNTY`, `GEO_COUNTY_SUBDIVISION`, `GEO_TRACT`.
    state_fips
        State FIPS as string (default "36" for NY).
    county_fips
        Required when geography is `GEO_COUNTY_SUBDIVISION` or `GEO_TRACT`;
        ignored for `GEO_COUNTY`.
    api_key
        Override the env var. None falls back to `CENSUS_API_KEY`.
    refresh
        Force re-pull and overwrite the cache.

    Returns
    -------
    Long-format DataFrame:
        state_fips | county_fips | (mcd_fips) | geoid | geography | year |
        variable | label | concept | value | source | vintage | notes
    """
    if geography not in _SUPPORTED_GEOGRAPHIES:
        raise ValueError(f"Unsupported geography {geography!r}; "
                         f"choose from {sorted(_SUPPORTED_GEOGRAPHIES)}")
    if geography in (GEO_COUNTY_SUBDIVISION, GEO_TRACT) and county_fips is None:
        # Default to statewide — Census API supports "county:*" as a wildcard
        # within a state for sub-county geographies. This honors the
        # statewide-by-default project rule (see CLAUDE.md).
        county_fips = "*"

    key = _resolve_api_key(api_key)

    geo_filter: dict[str, str] = {"state": state_fips}
    if geography == GEO_COUNTY_SUBDIVISION:
        geo_filter["county"] = county_fips  # type: ignore[assignment]
    elif geography == GEO_TRACT:
        geo_filter["county"] = county_fips  # type: ignore[assignment]

    url = _build_url(
        year,
        get=f"NAME,group({group})",
        geography=geography,
        geo_filter=geo_filter,
    )
    geo_tag = geography.replace(" ", "_")
    # Sanitize wildcard county for filename ("*" → "all").
    cnty_tag = (county_fips or "").replace("*", "all")
    parent_tag = f"_in_county_{cnty_tag}" if county_fips else ""
    cache_file = _cache_path(year, f"{group}_state{state_fips}{parent_tag}_{geo_tag}.json")
    raw = _fetch_json(url, cache_file, api_key=key, refresh=refresh)

    if not raw or len(raw) < 2:
        return pd.DataFrame()

    headers, *rows = raw
    # The group() query returns the NAME column twice (once at the beginning,
    # once near the geography keys at the end) plus a GEO_ID column. Drop
    # duplicates and the GEO_ID by keeping only the columns we care about,
    # selecting by position to dodge the duplicate-label problem.
    seen: set[str] = set()
    keep_idx: list[int] = []
    keep_names: list[str] = []
    for i, h in enumerate(headers):
        # Strip per-variable annotation/margin-of-error variants. Keep only
        # estimate ("E") variables for the requested group, plus identifier
        # columns (NAME, state, county, county subdivision, tract).
        keep = (
            h in {"NAME", "state", "county", "county subdivision", "tract"}
            or re.match(rf"^{group}_\d+E$", h) is not None
        )
        if keep and h not in seen:
            seen.add(h)
            keep_idx.append(i)
            keep_names.append(h)
    rows_kept = [[r[i] for i in keep_idx] for r in rows]
    df = pd.DataFrame(rows_kept, columns=keep_names)

    id_cols_present = [
        c for c in ("NAME", "state", "county", "county subdivision", "tract")
        if c in df.columns
    ]
    var_cols = [c for c in df.columns if c not in id_cols_present]

    long = df.melt(
        id_vars=id_cols_present,
        value_vars=var_cols,
        var_name="variable",
        value_name="value_raw",
    )
    long["value"] = pd.to_numeric(long["value_raw"], errors="coerce")

    # Attach human-readable labels from the variables metadata.
    var_meta = get_acs_variables(year=year)
    long["label"] = long["variable"].map(lambda v: var_meta.get(v, {}).get("label", ""))
    long["concept"] = long["variable"].map(lambda v: var_meta.get(v, {}).get("concept", ""))

    long["state_fips"] = long["state"].astype(str).str.zfill(2)
    if "county" in long.columns:
        long["county_fips"] = long["county"].astype(str).str.zfill(3)
    else:
        long["county_fips"] = pd.NA
    long["geography_level"] = geography

    if geography == GEO_COUNTY:
        long["geoid"] = long["state_fips"] + long["county_fips"]
        long["mcd_fips"] = pd.NA
    elif geography == GEO_COUNTY_SUBDIVISION:
        long["mcd_fips"] = long["county subdivision"].astype(str).str.zfill(5)
        long["geoid"] = (
            long["state_fips"] + long["county_fips"] + long["mcd_fips"]
        )
    elif geography == GEO_TRACT:
        long["mcd_fips"] = pd.NA
        long["geoid"] = (
            long["state_fips"]
            + long["county_fips"]
            + long["tract"].astype(str).str.zfill(6)
        )

    long["year"] = year
    long["source"] = "acs5"
    long["vintage"] = f"acs5_{year - 4}_{year}"  # e.g., "acs5_2020_2024"
    long["notes"] = ""
    long = long.rename(columns={"NAME": "name"})

    columns = [
        "state_fips", "county_fips", "mcd_fips", "geoid",
        "geography_level", "name", "year",
        "variable", "label", "concept",
        "value", "source", "vintage", "notes",
    ]
    columns = [c for c in columns if c in long.columns]
    return long[columns].reset_index(drop=True)
