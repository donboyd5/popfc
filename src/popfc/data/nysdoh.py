"""New York State Department of Health — population loader.

Source file in `data_raw/nysdoh/`:

- `New_York_State_Population_Data__Beginning_2003_<YYYYMMDD>.csv`
  Population by year × NYSDOH county code × age group × gender × race/ethnicity,
  2003 to most-recent vintage year. Columns: `Year, Age Group Code, Age Group
  Description, Gender Code, Gender Description, Race Ethnicity Code,
  Race/Ethnicity Description, County Code, County Name, Population`.

NYSDOH `County Code` is **not** the FIPS county code — it's a NYSDOH-specific
1-65 enumeration with NYC aggregates (1=NYS, 2=NYC, 3-7=NYC boroughs,
8=Rest-of-State, 9-65=upstate counties alphabetically). This loader maps it
to standard county FIPS via `NYSDOH_COUNTY_FIPS_MAP`.

Age, gender, and race/ethnicity *Code* values are integer keys for the
underlying category (descriptions in the file vary between vintages — e.g.,
"01-09" vs "1 to 9" for age-group code 2). The loader keeps the codes and
the latest description observed for each code.

Vital statistics (births, deaths) are **not** in this file — they require
separate API pulls from health.data.ny.gov; that is deferred.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from popfc.data._common import (
    coerce_numeric,
    enforce_pop_long_schema,
    make_geoid,
    pad_county_fips,
    pad_state_fips,
    read_csv_strings,
)
from popfc.paths import NYSDOH_DIR

DEFAULT_NYSDOH_POP = (
    NYSDOH_DIR / "New_York_State_Population_Data__Beginning_2003_20250419.csv"
)

# NYSDOH "County Code" → standard 3-digit NY county FIPS. Codes 1, 2, and 8
# are aggregates (state total, NYC total, Rest-of-State); we keep them with
# county_fips='000' or sentinel codes so analysts can filter them out.
#
# Standard county FIPS lookup table for the 57 non-NYC + 5 NYC counties.
NYSDOH_COUNTY_FIPS_MAP: dict[int, tuple[str, str]] = {
    # NYSDOH_code: (county_fips, canonical_name)
    1:  ("000", "New York State"),       # aggregate
    2:  ("998", "New York City"),        # aggregate (5 boroughs)
    3:  ("005", "Bronx"),
    4:  ("047", "Kings"),
    5:  ("061", "New York"),
    6:  ("081", "Queens"),
    7:  ("085", "Richmond"),
    8:  ("999", "Rest of State"),        # aggregate
    9:  ("001", "Albany"),
    10: ("003", "Allegany"),
    11: ("007", "Broome"),
    12: ("009", "Cattaraugus"),
    13: ("011", "Cayuga"),
    14: ("013", "Chautauqua"),
    15: ("015", "Chemung"),
    16: ("017", "Chenango"),
    17: ("019", "Clinton"),
    18: ("021", "Columbia"),
    19: ("023", "Cortland"),
    20: ("025", "Delaware"),
    21: ("027", "Dutchess"),
    22: ("029", "Erie"),
    23: ("031", "Essex"),
    24: ("033", "Franklin"),
    25: ("035", "Fulton"),
    26: ("037", "Genesee"),
    27: ("039", "Greene"),
    28: ("041", "Hamilton"),
    29: ("043", "Herkimer"),
    30: ("045", "Jefferson"),
    31: ("049", "Lewis"),
    32: ("051", "Livingston"),
    33: ("053", "Madison"),
    34: ("055", "Monroe"),
    35: ("057", "Montgomery"),
    36: ("059", "Nassau"),
    37: ("063", "Niagara"),
    38: ("065", "Oneida"),
    39: ("067", "Onondaga"),
    40: ("069", "Ontario"),
    41: ("071", "Orange"),
    42: ("073", "Orleans"),
    43: ("075", "Oswego"),
    44: ("077", "Otsego"),
    45: ("079", "Putnam"),
    46: ("083", "Rensselaer"),
    47: ("087", "Rockland"),
    48: ("089", "St Lawrence"),
    49: ("091", "Saratoga"),
    50: ("093", "Schenectady"),
    51: ("095", "Schoharie"),
    52: ("097", "Schuyler"),
    53: ("099", "Seneca"),
    54: ("101", "Steuben"),
    55: ("103", "Suffolk"),
    56: ("105", "Sullivan"),
    57: ("107", "Tioga"),
    58: ("109", "Tompkins"),
    59: ("111", "Ulster"),
    60: ("113", "Warren"),
    61: ("115", "Washington"),
    62: ("117", "Wayne"),
    63: ("119", "Westchester"),
    64: ("121", "Wyoming"),
    65: ("123", "Yates"),
}

# Schema for the full breakdown frame.
NYSDOH_POP_DETAIL_COLUMNS: list[str] = [
    "state_fips",
    "county_fips",
    "geoid",
    "geography",
    "year",
    "age_group_code",        # int, 0=Total, 1=<1, 2=1-9, 3=10-19, ..., 11=85+
    "age_group_description", # latest observed description for this code
    "sex_code",              # int, 0=Total, 1=Male, 2=Female
    "race_code",             # int, 0=Total, 1=WNH, 2=BNH, 3=ONH, 5=Hispanic
    "population",
    "source",
    "vintage",
    "notes",
]


def _derive_vintage(path: Path) -> str:
    m = re.search(r"(\d{8})", path.stem)
    if m:
        d = m.group(1)
        return f"nysdoh_{d[:4]}-{d[4:6]}-{d[6:8]}"
    return "nysdoh_unknown"


def load_nysdoh_population(
    path: Path | str | None = None,
    vintage: str | None = None,
    keep_aggregates: bool = False,
) -> dict[str, pd.DataFrame]:
    """Load the NYSDOH population breakdown file (2003+).

    Parameters
    ----------
    path
        Override the default file.
    vintage
        Override the auto-derived vintage tag.
    keep_aggregates
        If False (default), rows for the state total (code 1), NYC aggregate
        (code 2), and Rest-of-State (code 8) are dropped. If True they are
        retained — useful for cross-checking that detail sums to aggregates.

    Returns
    -------
    dict with keys:
        - 'detail': full long-format frame (NYSDOH_POP_DETAIL_COLUMNS) — one
          row per (county, year, age_group, sex, race), including the
          all-category-totals rows (code 0 in each dimension).
        - 'totals': county-year total population only (POP_LONG_COLUMNS),
          extracted directly from the file's all-totals rows
          (age_group_code=0, sex_code=0, race_code=0).
    """
    path = Path(path) if path is not None else DEFAULT_NYSDOH_POP
    vintage = vintage or _derive_vintage(path)

    raw = read_csv_strings(path)
    raw.columns = [c.strip() for c in raw.columns]

    nysdoh_code = coerce_numeric(
        raw["County Code"], label="nysdoh/county_code", dtype="Int64"
    )
    age_code = coerce_numeric(
        raw["Age Group Code"], label="nysdoh/age_code", dtype="Int64"
    )
    sex_code = coerce_numeric(
        raw["Gender Code"], label="nysdoh/sex_code", dtype="Int64"
    )
    race_code = coerce_numeric(
        raw["Race Ethnicity Code"], label="nysdoh/race_code", dtype="Int64"
    )
    year = coerce_numeric(raw["Year"], label="nysdoh/year", dtype="Int64").astype(int)
    pop = coerce_numeric(
        raw["Population"], label=f"nysdoh/population/{vintage}", dtype="Int64"
    )

    # Map NYSDOH county code → (county_fips, canonical_name)
    fips_map = nysdoh_code.map(lambda v: NYSDOH_COUNTY_FIPS_MAP.get(int(v)) if pd.notna(v) else None)
    county_fips = fips_map.map(lambda t: t[0] if t else None)
    canonical_name = fips_map.map(lambda t: t[1] if t else None)
    # Surface any code we didn't map (would indicate the upstream file added
    # a category we don't know about).
    unmapped = nysdoh_code[county_fips.isna() & nysdoh_code.notna()].unique()
    if len(unmapped) > 0:
        import warnings
        warnings.warn(
            f"nysdoh: unmapped NYSDOH county codes {sorted(int(c) for c in unmapped)}",
            stacklevel=2,
        )

    state_fips = pad_state_fips(36)
    geoid = state_fips + county_fips.fillna("XXX")

    detail = pd.DataFrame({
        "state_fips": state_fips,
        "county_fips": county_fips,
        "geoid": geoid,
        "geography": canonical_name,
        "year": year,
        "age_group_code": age_code,
        "age_group_description": raw["Age Group Description"].astype(str),
        "sex_code": sex_code,
        "race_code": race_code,
        "population": pop,
        "source": "nysdoh",
        "vintage": vintage,
        "notes": "",
    })

    if not keep_aggregates:
        # Drop state and NYC/RoS aggregates; keep all 62 actual counties.
        aggregate_codes = {1, 2, 8}
        keep_mask = ~nysdoh_code.isin(aggregate_codes)
        detail = detail[keep_mask].reset_index(drop=True)

    detail = detail[NYSDOH_POP_DETAIL_COLUMNS]

    # Build totals frame: all-categories-total rows.
    totals_mask = (
        (detail["age_group_code"] == 0)
        & (detail["sex_code"] == 0)
        & (detail["race_code"] == 0)
    )
    totals_raw = detail[totals_mask].copy()
    totals = pd.DataFrame({
        "state_fips": totals_raw["state_fips"],
        "county_fips": totals_raw["county_fips"],
        "geoid": totals_raw["geoid"],
        "geography": totals_raw["geography"],
        "year": totals_raw["year"],
        "kind": "estimate",
        "population": totals_raw["population"],
        "source": "nysdoh",
        "vintage": vintage,
        "notes": "nysdoh_all_categories_total",
    }).reset_index(drop=True)

    return {
        "detail": detail,
        "totals": enforce_pop_long_schema(totals),
    }
