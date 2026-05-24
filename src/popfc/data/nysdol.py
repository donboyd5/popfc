"""New York State Department of Labor — annual population estimates loader.

Source file (already in long format):
    `data_raw/nysdol/Annual_Population_Estimates_for_New_York_State_and_Counties__
     Beginning_1970_<YYYYMMDD>.csv`

Columns in the raw file: `fips_code, geography, year, program_type, population`.

NYSDOL fips_code convention:
    - 36000: New York State
    - 36001-36123 (odd): NY counties

Emits POP_LONG_COLUMNS.
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
from popfc.paths import NYSDOL_DIR

# Default file — update when a newer vintage is dropped in.
DEFAULT_NYSDOL_ANNUAL = (
    NYSDOL_DIR
    / "Annual_Population_Estimates_for_New_York_State_and_Counties__Beginning_1970_20260524.csv"
)

# Map NYSDOL's `program_type` strings to our canonical `kind` values.
# Labels observed in the 2025-04-20 vintage:
#   "Intercensal Population Estimate" (most years)
#   "Postcensal Population Estimate"  (2020+)
#   "Census Base Population"          (decennial years: 1970, 1980, 1990, 2000, 2010, 2020)
# Historical / plural variants are included defensively.
_PROGRAM_KIND: dict[str, str] = {
    "Postcensal Population Estimate": "estimate",
    "Postcensal Population Estimates": "estimate",
    "Intercensal Population Estimate": "intercensal",
    "Intercensal Population Estimates": "intercensal",
    "Census Base Population": "census",
    "Decennial Census": "census",
    "Census": "census",
}


def _derive_vintage(path: Path) -> str:
    """Extract YYYYMMDD from filename and format as 'nysdol_YYYY-MM-DD'."""
    m = re.search(r"(\d{8})", path.stem)
    if m:
        d = m.group(1)
        return f"nysdol_{d[:4]}-{d[4:6]}-{d[6:8]}"
    return "nysdol_unknown"


def load_nysdol_annual(
    path: Path | str | None = None,
    vintage: str | None = None,
) -> pd.DataFrame:
    """Load the NYSDOL annual population estimates series (1970+).

    Parameters
    ----------
    path
        Override the default file. Useful when a newer vintage is dropped in.
    vintage
        Override the auto-derived vintage tag.

    Returns
    -------
    DataFrame with POP_LONG_COLUMNS schema.
    """
    path = Path(path) if path is not None else DEFAULT_NYSDOL_ANNUAL
    vintage = vintage or _derive_vintage(path)

    # String-first read: keeps raw values visible and flags coercion failures
    # explicitly at the conversion step below, rather than letting pandas
    # silently decide column dtypes.
    raw = read_csv_strings(path)
    # Normalize columns defensively. Future vintages may shift capitalization
    # or use spaces instead of underscores — the data.ny.gov direct CSV uses
    # "FIPS Code" / "Program Type", while the older curated CSV used
    # "fips_code" / "program_type".
    raw.columns = [
        c.strip().lower().replace(" ", "_") for c in raw.columns
    ]

    # Coerce fips_code and year to numeric explicitly so non-integer sentinel
    # values would surface as warnings.
    fips = coerce_numeric(raw["fips_code"], label="nysdol/fips_code", dtype="Int64")
    state_int = (fips // 1000).astype("Int64")
    county_int = (fips % 1000).astype("Int64")

    out = pd.DataFrame({
        "state_fips": state_int.map(lambda v: pad_state_fips(int(v))),
        "county_fips": county_int.map(lambda v: pad_county_fips(int(v))),
        "geoid": [
            make_geoid(int(s), int(c))
            for s, c in zip(state_int, county_int, strict=True)
        ],
        "geography": raw["geography"].astype(str),
        "year": coerce_numeric(raw["year"], label="nysdol/year", dtype="Int64").astype(int),
        "kind": raw["program_type"].map(_PROGRAM_KIND).fillna("unknown"),
        "population": coerce_numeric(
            raw["population"], label=f"nysdol/population/{vintage}", dtype="Int64"
        ),
        "source": "nysdol",
        "vintage": vintage,
        "notes": raw["program_type"].astype(str),  # preserve raw label in notes
    })

    return enforce_pop_long_schema(out)
