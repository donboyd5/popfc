"""Decennial census sub-county population (towns + villages), 2000/2010/2020.

The PEP/ACS sub-county series in `town_total_pop_history.parquet` only reaches
back to 2007 (ACS 5-yr midpoints) / 2020 (PEP). That is too short, and too
noisy near the 2019/2020 ACS->PEP seam, to distinguish a genuine multi-decade
decline-then-rebound from an estimation artifact. The decennial census supplies
hard, wall-to-wall population *counts* (not estimates) at two geographies the
project cares about:

- **county subdivisions** (NY towns and cities — MCDs), 10-digit geoid
  `state(2) + county(3) + cousub(5)`, matching `town_total_pop_history`.
- **places** (incorporated villages and cities, plus CDPs), 7-digit geoid
  `state(2) + place(5)`. This is the only village-level history available, since
  the PEP sub-county vintages in-repo cover villages for 2020+ only.

Three decennial vintages are reachable through the Census Data API:

    2000  ->  dec/sf1   variable P001001
    2010  ->  dec/sf1   variable P001001
    2020  ->  dec/dhc   variable P1_001N

1990 and earlier are NOT on the Census API (404); those require an NHGIS extract
and are out of scope here. See `download_decennial_subcounty` for the gap note.

Design (per project conventions):
- `download_decennial_subcounty` is the only networked function. It writes raw
  API responses verbatim to `data_raw/census/decennial/` as CSV, one file per
  (year, geo level), so the raw values are inspectable before any coercion.
- `load_decennial_subcounty` is **pure**: it reads those raw CSVs as strings,
  coerces explicitly, and emits the canonical `POP_LONG_COLUMNS` long format
  (`kind="census"`), plus two extra descriptive columns `geo_level`
  ("cousub" | "place") and `geo_kind` ("town" | "city" | "village" | "cdp").
"""

from __future__ import annotations

import io
import json
import urllib.parse
import urllib.request
import warnings
from pathlib import Path

import pandas as pd

from popfc.data._common import (
    coerce_numeric,
    enforce_pop_long_schema,
    read_csv_strings,
)
from popfc.paths import CENSUS_DIR

DECENNIAL_DIR: Path = CENSUS_DIR / "decennial"

# (year, dataset, pop variable) for each reachable decennial vintage.
_VINTAGES: tuple[tuple[int, str, str], ...] = (
    (2000, "dec/sf1", "P001001"),
    (2010, "dec/sf1", "P001001"),
    (2020, "dec/dhc", "P1_001N"),
)

_API_BASE = "https://api.census.gov/data"


def _raw_path(geo_level: str, year: int) -> Path:
    return DECENNIAL_DIR / f"ny_{geo_level}_{year}.csv"


def _fetch_api(year: int, dataset: str, pop_var: str, geo_level: str,
               state_fips: str, api_key: str | None) -> str:
    """Return the raw API response (a JSON array-of-arrays) as CSV text."""
    if geo_level == "cousub":
        for_clause = "county subdivision:*"
        in_clause = f"state:{state_fips} county:*"
    elif geo_level == "place":
        for_clause = "place:*"
        in_clause = f"state:{state_fips}"
    else:  # pragma: no cover - guarded by caller
        raise ValueError(f"unknown geo_level {geo_level!r}")

    params = {"get": f"NAME,{pop_var}", "for": for_clause, "in": in_clause}
    if api_key:
        params["key"] = api_key
    url = f"{_API_BASE}/{year}/{dataset}?" + urllib.parse.urlencode(params)

    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 (trusted host)
        rows = json.loads(resp.read().decode("utf-8"))

    # rows[0] is the header; normalize the pop variable name to "population".
    header = ["population" if c == pop_var else c for c in rows[0]]
    frame = pd.DataFrame(rows[1:], columns=header)
    return frame.to_csv(index=False)


def download_decennial_subcounty(
    state_fips: str = "36",
    out_dir: Path | str = DECENNIAL_DIR,
    api_key: str | None = None,
    *,
    force: bool = False,
) -> dict[str, Path]:
    """Fetch decennial 2000/2010/2020 town + village counts from the Census API.

    Writes six raw CSVs (3 years x {cousub, place}) under `out_dir`. Existing
    files are kept unless `force=True`. Returns a map of "<geo>_<year>" -> path.

    `api_key` defaults to the `CENSUS_API_KEY` environment variable. A key is
    not strictly required for these query sizes but avoids throttling.

    Note: 1990 and earlier sub-county counts are not served by the Census API;
    obtaining them requires an IPUMS NHGIS extract and is out of scope here.
    """
    import os

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    api_key = api_key or os.environ.get("CENSUS_API_KEY")

    written: dict[str, Path] = {}
    for year, dataset, pop_var in _VINTAGES:
        for geo_level in ("cousub", "place"):
            path = out_dir / f"ny_{geo_level}_{year}.csv"
            key = f"{geo_level}_{year}"
            if path.exists() and not force:
                written[key] = path
                continue
            csv_text = _fetch_api(
                year, dataset, pop_var, geo_level, state_fips, api_key
            )
            path.write_text(csv_text)
            written[key] = path
    return written


# Map the trailing word of the place/MCD name to a coarse geography kind.
_GEO_KIND = {
    "town": "town",
    "city": "city",
    "village": "village",
    "CDP": "cdp",
    "borough": "village",
}


def _parse_geo_kind(name: pd.Series) -> pd.Series:
    """town/city/village/cdp from a census NAME like 'Argyle town, ...'."""
    label = name.str.split(",", n=1).str[0].str.strip().str.rsplit(" ", n=1).str[-1]
    return label.map(_GEO_KIND).fillna("other")


def _load_one(path: Path, geo_level: str, year: int) -> pd.DataFrame:
    raw = read_csv_strings(path)
    out = pd.DataFrame()
    out["state_fips"] = raw["state"].str.zfill(2)
    if geo_level == "cousub":
        out["county_fips"] = raw["county"].str.zfill(3)
        out["geoid"] = (
            out["state_fips"] + out["county_fips"]
            + raw["county subdivision"].str.zfill(5)
        )
    else:  # place: no county nesting (a place may span counties)
        out["county_fips"] = pd.NA
        out["geoid"] = out["state_fips"] + raw["place"].str.zfill(5)
    out["geography"] = raw["NAME"]
    out["year"] = year
    out["kind"] = "census"
    out["population"] = coerce_numeric(
        raw["population"], f"census_decennial/{geo_level}/{year}"
    )
    out["source"] = "census_decennial"
    out["vintage"] = f"dec{year}"
    out["notes"] = f"{geo_level} total-population count, decennial {year}"
    out["geo_level"] = geo_level
    out["geo_kind"] = _parse_geo_kind(raw["NAME"])
    return out


def load_decennial_subcounty(
    raw_dir: Path | str = DECENNIAL_DIR,
) -> pd.DataFrame:
    """Load decennial town + village counts from raw CSVs into long format.

    Pure: reads the six CSVs written by `download_decennial_subcounty`. Emits
    `POP_LONG_COLUMNS` plus `geo_level` and `geo_kind`. Raises if no raw files
    are present (call `download_decennial_subcounty` first).
    """
    raw_dir = Path(raw_dir)
    frames: list[pd.DataFrame] = []
    for year, _dataset, _pop_var in _VINTAGES:
        for geo_level in ("cousub", "place"):
            path = raw_dir / f"ny_{geo_level}_{year}.csv"
            if not path.exists():
                warnings.warn(f"missing raw decennial file: {path}", stacklevel=2)
                continue
            frames.append(_load_one(path, geo_level, year))
    if not frames:
        raise FileNotFoundError(
            f"no decennial raw CSVs found in {raw_dir}; "
            "run download_decennial_subcounty() first"
        )
    out = pd.concat(frames, ignore_index=True)
    extra = ["geo_level", "geo_kind"]
    long = enforce_pop_long_schema(out)
    return pd.concat([long, out[extra]], axis=1)
