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

# Filename conventions for the NYSDOL annual CSV. The download module writes
# files matching the new convention; this loader prefers it but falls back
# to legacy retrieval-only filenames if that's all that's on disk.
#
#   Annual_..._beginning_1970_d<YYYYMMDD>_r<YYYYMMDD>.csv   (new)
#     - d<YYYYMMDD>: dataset publication date (data.ny.gov rowsUpdatedAt)
#     - r<YYYYMMDD>: our retrieval date
#   Annual_..._beginning_1970_<YYYYMMDD>.csv                (legacy)
#     - <YYYYMMDD>: retrieval date only; publication date unknown
_NYSDOL_BASE = "Annual_Population_Estimates_for_New_York_State_and_Counties__Beginning_1970"


def _default_nysdol_path() -> Path:
    """Locate the latest NYSDOL annual CSV on disk; prefer new-format filenames."""
    new_fmt = sorted(NYSDOL_DIR.glob(f"{_NYSDOL_BASE}_d*_r*.csv"))
    if new_fmt:
        return new_fmt[-1]
    legacy = sorted(NYSDOL_DIR.glob(f"{_NYSDOL_BASE}_*.csv"))
    if legacy:
        return legacy[-1]
    # Fall back to a non-existent path so the caller hits a clear FileNotFoundError.
    return NYSDOL_DIR / f"{_NYSDOL_BASE}_NOT_DOWNLOADED.csv"


# Back-compat alias: existing imports of DEFAULT_NYSDOL_ANNUAL still work, but
# they now resolve to whatever file is currently on disk rather than a fixed
# date string baked into source.
def __getattr__(name: str):  # PEP 562 lazy module attribute
    if name == "DEFAULT_NYSDOL_ANNUAL":
        return _default_nysdol_path()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

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
    """Return the dataset's vintage tag.

    Reads the data-publication date (preferred) or the retrieval date (fallback)
    from the filename. Returns:
      - ``nysdol_YYYY-MM-DD`` when the filename carries an explicit ``d<YYYYMMDD>``
        component (data-publication date per data.ny.gov metadata).
      - ``nysdol_retrieved_YYYY-MM-DD`` when only a single date is present in the
        filename (legacy convention; we know when WE downloaded, not when the
        dataset was published).
      - ``nysdol_unknown`` if neither pattern matches.
    """
    m_pub = re.search(r"_d(\d{8})(?:_r\d{8})?", path.stem)
    if m_pub:
        d = m_pub.group(1)
        return f"nysdol_{d[:4]}-{d[4:6]}-{d[6:8]}"
    m_legacy = re.search(r"(\d{8})", path.stem)
    if m_legacy:
        d = m_legacy.group(1)
        return f"nysdol_retrieved_{d[:4]}-{d[4:6]}-{d[6:8]}"
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
    path = Path(path) if path is not None else _default_nysdol_path()
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
