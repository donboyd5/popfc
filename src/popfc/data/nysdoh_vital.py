"""NYSDOH vital statistics — births and deaths via the Socrata API.

Closes GitHub issue #2. The existing `popfc.data.nysdoh` module covers the
population CSV; this one adds the vital-events datasets that NYSDOH
publishes only via API.

## Datasets

- **Live Births by Mother's Age and Resident County: Beginning 2008**
  Socrata id ``i7yg-w5rg``. Columns: ``year``, ``county``,
  ``mother_s_age_range`` (``"<15"``, ``"15-17"``, …, ``"45+"``,
  ``"Total"``, ``"Unknown"``), ``value`` (count). Returns ~9k rows
  (62 counties × ~16 years × 11 categories) plus NY-state aggregates.
- **Deaths by Resident County, Region, and Age-Group: Beginning 2003**
  Socrata id ``xit9-mprv``. Columns: ``year``, ``county_name``,
  ``region`` (``"NYC"`` / ``"ROS"``), ``age_group`` (``"<1"``, ``"1-9"``,
  …, ``"85+"``, ``"Total"``, ``"Unknown"``), ``deaths`` (count).
  Returns ~16k rows.

Both datasets include an explicit ``Total`` row per (year, county) — we
use that directly rather than summing the age detail so the function
matches NYSDOH's own published totals exactly.

## Caching

Raw API responses are cached under ``data_raw/nysdoh/api/`` keyed by
dataset id + data-publication date (Socrata ``rowsUpdatedAt``). Cache
hits skip the network entirely; pass ``refresh=True`` to force a
re-pull.

## Vintage

The vintage tag is ``nysdoh_vital_YYYYMMDD`` where YYYYMMDD is the
data-publication date (NOT the retrieval date). This matches the
convention used elsewhere in the project (see `popfc.data.nysdol`).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from pathlib import Path

import pandas as pd
import requests

from popfc.data._common import (
    COMPONENTS_LONG_COLUMNS,
    coerce_numeric,
    pad_state_fips,
)
from popfc.data.nysdoh import NYSDOH_COUNTY_FIPS_MAP
from popfc.paths import NYSDOH_DIR

# ---------------------------------------------------------------------------
# Endpoint constants
# ---------------------------------------------------------------------------

API_HOST = "https://health.data.ny.gov"
DATASET_BIRTHS = "i7yg-w5rg"
DATASET_DEATHS = "xit9-mprv"

ENV_APP_TOKEN_VAR = "NYSDOH_SOCRATA_APP_TOKEN"  # optional; raises rate limit

_API_DIR = NYSDOH_DIR / "api"

# County-name → 3-digit NY FIPS, derived from the existing NYSDOH code map.
# Excludes aggregate-row names so the default loader path can drop them.
NYSDOH_NAME_TO_FIPS: dict[str, str] = {
    name: fips
    for _code, (fips, name) in NYSDOH_COUNTY_FIPS_MAP.items()
    if fips not in {"000", "998", "999"}
}

# Aggregate-row names paired with their sentinel FIPS — used when callers
# pass keep_aggregates=True.
_NYSDOH_AGGREGATE_NAME_TO_FIPS: dict[str, str] = {
    name: fips
    for _code, (fips, name) in NYSDOH_COUNTY_FIPS_MAP.items()
    if fips in {"000", "998", "999"}
}
_NYSDOH_AGGREGATE_NAMES: set[str] = set(_NYSDOH_AGGREGATE_NAME_TO_FIPS.keys())


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

# Detail frame for births: one row per (year, county, mother_s_age_range).
NYSDOH_VITAL_BIRTHS_DETAIL_COLUMNS: list[str] = [
    "state_fips",
    "county_fips",
    "geoid",
    "geography",
    "year",
    "mother_age_range",   # API's mother_s_age_range, including 'Total' and 'Unknown'
    "births",
    "source",
    "vintage",
    "notes",
]

# Detail frame for deaths: one row per (year, county, age_group).
NYSDOH_VITAL_DEATHS_DETAIL_COLUMNS: list[str] = [
    "state_fips",
    "county_fips",
    "geoid",
    "geography",
    "year",
    "region",
    "age_group",
    "deaths",
    "source",
    "vintage",
    "notes",
]


# ---------------------------------------------------------------------------
# Socrata helpers
# ---------------------------------------------------------------------------

def _resolve_app_token(app_token: str | None) -> str | None:
    if app_token:
        return app_token
    val = os.environ.get(ENV_APP_TOKEN_VAR)
    return val if val else None


def _socrata_metadata(dataset_id: str) -> dict:
    """Return Socrata view metadata (incl. rowsUpdatedAt)."""
    r = requests.get(f"{API_HOST}/api/views/{dataset_id}.json", timeout=30)
    r.raise_for_status()
    return r.json()


def _data_publication_date(meta: dict) -> str:
    """Extract YYYYMMDD data-publication date from Socrata metadata.

    `rowsUpdatedAt` is epoch seconds. We use UTC for determinism — a
    locale-dependent vintage tag would jitter the cache filename across
    machines in different time zones.
    """
    t = meta.get("rowsUpdatedAt") or meta.get("dataUpdatedAt") or 0
    try:
        ts = int(t)
    except (TypeError, ValueError):
        return "unknown"
    if ts == 0:
        return "unknown"
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%Y%m%d")


def _cache_path(dataset_id: str, vintage_yyyymmdd: str) -> Path:
    return _API_DIR / f"{dataset_id}_d{vintage_yyyymmdd}.json"


def _fetch_full_dataset(
    dataset_id: str,
    *,
    refresh: bool = False,
    app_token: str | None = None,
    page_size: int = 50_000,
    extra_where: str | None = None,
) -> tuple[list[dict], str]:
    """Fetch all rows of a Socrata dataset, with on-disk caching.

    Returns ``(rows, vintage_tag)`` where vintage_tag is
    ``nysdoh_vital_YYYYMMDD`` keyed on the dataset's data-publication date.
    """
    _API_DIR.mkdir(parents=True, exist_ok=True)
    meta = _socrata_metadata(dataset_id)
    vintage_date = _data_publication_date(meta)
    vintage_tag = f"nysdoh_vital_{vintage_date}"

    cache = _cache_path(dataset_id, vintage_date)
    if cache.exists() and not refresh:
        return json.loads(cache.read_text())["rows"], vintage_tag

    token = _resolve_app_token(app_token)
    headers = {"X-App-Token": token} if token else {}

    params_base: dict[str, str] = {"$limit": str(page_size), "$order": ":id"}
    if extra_where:
        params_base["$where"] = extra_where

    rows: list[dict] = []
    offset = 0
    while True:
        params = dict(params_base, **{"$offset": str(offset)})
        resp = requests.get(
            f"{API_HOST}/resource/{dataset_id}.json",
            params=params, headers=headers, timeout=120,
        )
        resp.raise_for_status()
        batch = resp.json()
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
        # Be polite to the API.
        time.sleep(0.1)

    cache.write_text(json.dumps({
        "rows": rows, "vintage": vintage_tag,
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "dataset_id": dataset_id, "row_count": len(rows),
    }, indent=None))
    return rows, vintage_tag


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _attach_fips(
    df: pd.DataFrame, county_col: str, keep_aggregates: bool,
) -> pd.DataFrame:
    """Map county-name strings to NY FIPS; drop aggregates unless asked."""
    df = df.copy()
    if not keep_aggregates:
        df = df[~df[county_col].isin(_NYSDOH_AGGREGATE_NAMES)].copy()
        name_map = NYSDOH_NAME_TO_FIPS
    else:
        # Honor aggregates by mapping their names to sentinel FIPS codes
        # (000 = state, 998 = NYC, 999 = Rest-of-State).
        name_map = {**NYSDOH_NAME_TO_FIPS, **_NYSDOH_AGGREGATE_NAME_TO_FIPS}
    df["state_fips"] = pad_state_fips(36)
    df["county_fips"] = df[county_col].map(name_map)
    df["geography"] = df[county_col]
    unmapped = df[df["county_fips"].isna()][county_col].unique().tolist()
    if unmapped:
        import warnings
        warnings.warn(
            f"nysdoh_vital: unmapped county names {sorted(unmapped)} — "
            "these rows will have geoid prefix '36' with county_fips missing.",
            stacklevel=3,
        )
    df["geoid"] = (
        df["state_fips"].astype(str) + df["county_fips"].fillna("XXX").astype(str)
    )
    return df


def load_nysdoh_births(
    *,
    refresh: bool = False,
    app_token: str | None = None,
    keep_aggregates: bool = False,
) -> dict[str, pd.DataFrame]:
    """Load NYSDOH live-births by resident county.

    Returns
    -------
    dict with keys:
        - ``'totals'``: county-year total births in
          `COMPONENTS_LONG_COLUMNS` (`measure='births'`). One row per
          (geoid, year). Extracted directly from the API's ``mother_s_age_range == 'Total'``
          rows — exact match to NYSDOH's own published county totals.
        - ``'by_mother_age'``: full detail in
          `NYSDOH_VITAL_BIRTHS_DETAIL_COLUMNS`.

    The ``'Total'`` and ``'Unknown'`` mother-age categories are kept in
    the detail frame; the totals frame uses only the ``'Total'`` row.
    """
    rows, vintage = _fetch_full_dataset(
        DATASET_BIRTHS, refresh=refresh, app_token=app_token,
    )
    raw = pd.DataFrame(rows)
    if raw.empty:
        return {
            "totals": pd.DataFrame(columns=COMPONENTS_LONG_COLUMNS),
            "by_mother_age": pd.DataFrame(columns=NYSDOH_VITAL_BIRTHS_DETAIL_COLUMNS),
        }

    detail = _attach_fips(raw, "county", keep_aggregates=keep_aggregates)
    detail["year"] = coerce_numeric(detail["year"], label="nysdoh_vital/births/year",
                                     dtype="Int64").astype("Int64")
    detail["births"] = coerce_numeric(detail["value"], label="nysdoh_vital/births/value",
                                       dtype="Int64")
    detail["mother_age_range"] = detail["mother_s_age_range"].astype(str)
    detail["source"] = "nysdoh_vital"
    detail["vintage"] = vintage
    detail["notes"] = ""
    detail = detail[NYSDOH_VITAL_BIRTHS_DETAIL_COLUMNS].reset_index(drop=True)

    totals_src = detail[detail["mother_age_range"] == "Total"].copy()
    totals = pd.DataFrame({
        "state_fips": totals_src["state_fips"],
        "county_fips": totals_src["county_fips"],
        "geoid": totals_src["geoid"],
        "geography": totals_src["geography"],
        "year": totals_src["year"].astype("Int64"),
        "measure": "births",
        "value": totals_src["births"],
        "source": "nysdoh_vital",
        "vintage": vintage,
        "notes": "from i7yg-w5rg mother_s_age_range=='Total'",
    }).reset_index(drop=True)
    totals = totals[COMPONENTS_LONG_COLUMNS]

    return {"totals": totals, "by_mother_age": detail}


def load_nysdoh_deaths(
    *,
    refresh: bool = False,
    app_token: str | None = None,
    keep_aggregates: bool = False,
) -> dict[str, pd.DataFrame]:
    """Load NYSDOH deaths by resident county.

    Returns
    -------
    dict with keys:
        - ``'totals'``: county-year total deaths in `COMPONENTS_LONG_COLUMNS`
          (`measure='deaths'`). From the API's ``age_group == 'Total'`` rows.
        - ``'by_age_group'``: full detail in `NYSDOH_VITAL_DEATHS_DETAIL_COLUMNS`.
    """
    rows, vintage = _fetch_full_dataset(
        DATASET_DEATHS, refresh=refresh, app_token=app_token,
    )
    raw = pd.DataFrame(rows)
    if raw.empty:
        return {
            "totals": pd.DataFrame(columns=COMPONENTS_LONG_COLUMNS),
            "by_age_group": pd.DataFrame(columns=NYSDOH_VITAL_DEATHS_DETAIL_COLUMNS),
        }

    detail = _attach_fips(raw, "county_name", keep_aggregates=keep_aggregates)
    detail["year"] = coerce_numeric(detail["year"], label="nysdoh_vital/deaths/year",
                                     dtype="Int64").astype("Int64")
    detail["deaths"] = coerce_numeric(detail["deaths"], label="nysdoh_vital/deaths/value",
                                       dtype="Int64")
    detail["age_group"] = detail["age_group"].astype(str)
    detail["region"] = detail.get("region", pd.Series("", index=detail.index)).astype(str)
    detail["source"] = "nysdoh_vital"
    detail["vintage"] = vintage
    detail["notes"] = ""
    detail = detail[NYSDOH_VITAL_DEATHS_DETAIL_COLUMNS].reset_index(drop=True)

    totals_src = detail[detail["age_group"] == "Total"].copy()
    totals = pd.DataFrame({
        "state_fips": totals_src["state_fips"],
        "county_fips": totals_src["county_fips"],
        "geoid": totals_src["geoid"],
        "geography": totals_src["geography"],
        "year": totals_src["year"].astype("Int64"),
        "measure": "deaths",
        "value": totals_src["deaths"],
        "source": "nysdoh_vital",
        "vintage": vintage,
        "notes": "from xit9-mprv age_group=='Total'",
    }).reset_index(drop=True)
    totals = totals[COMPONENTS_LONG_COLUMNS]

    return {"totals": totals, "by_age_group": detail}
