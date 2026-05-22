"""NCHS life-table loaders.

Three sources:

1. **NCHS US Life Tables** — single-year national period life tables, published
   annually as NVSR reports. We use the 2023 vintage (NVSR Vol 74, No 6).
   Files: `us_2023_Table01.xlsx` (total), `Table02.xlsx` (male),
   `Table03.xlsx` (female). Schema: ages 0–100+, columns qx, lx, dx, Lx, Tx,
   ex.

2. **NCHS State Life Tables** — single-year state period life tables, less
   frequent (latest: 2022, NVSR Vol 74, No 12). Files: `ny_2022_NY1.xlsx`
   (total), `NY2` (male), `NY3` (female), `NY4` (standard errors).

3. **NCHS USALEEP** — small-area life expectancy by 2010 Census tract, period
   2010–2015. Two files per state: `<ST>_A.csv` (life expectancy at birth
   only) and `<ST>_B.csv` (full abridged life table in 5-year age bands).

All loaders emit the `LIFE_TABLE_COLUMNS` schema (see `_common.py`). USALEEP
abridged tables use age bands (`0-1`, `1-5`, ..., `85+`); national / state
tables use single-year bands (`0-1`, `1-2`, ..., `100+`).
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Literal

import pandas as pd

from popfc.data._common import (
    enforce_life_table_schema,
    pad_county_fips,
    pad_state_fips,
)
from popfc.paths import NCHS_DIR

# ---------------------------------------------------------------------------
# Default file paths
# ---------------------------------------------------------------------------

LIFE_TABLES_DIR = NCHS_DIR / "life_tables"
USALEEP_DIR = NCHS_DIR / "usaleep"

# National (NVSR 74-06, 2023 data)
DEFAULT_US_LIFE_TABLE_TOTAL = LIFE_TABLES_DIR / "us_2023_Table01.xlsx"
DEFAULT_US_LIFE_TABLE_MALE = LIFE_TABLES_DIR / "us_2023_Table02.xlsx"
DEFAULT_US_LIFE_TABLE_FEMALE = LIFE_TABLES_DIR / "us_2023_Table03.xlsx"
DEFAULT_US_LIFE_TABLE_YEAR = 2023
DEFAULT_US_LIFE_TABLE_VINTAGE = "nvsr74-06"

# State, NY (NVSR 74-12, 2022 data)
DEFAULT_NY_LIFE_TABLE_TOTAL = LIFE_TABLES_DIR / "ny_2022_NY1.xlsx"
DEFAULT_NY_LIFE_TABLE_MALE = LIFE_TABLES_DIR / "ny_2022_NY2.xlsx"
DEFAULT_NY_LIFE_TABLE_FEMALE = LIFE_TABLES_DIR / "ny_2022_NY3.xlsx"
DEFAULT_NY_LIFE_TABLE_YEAR = 2022
DEFAULT_NY_LIFE_TABLE_VINTAGE = "nvsr74-12"

# USALEEP (2010-2015)
DEFAULT_USALEEP_NY_A = USALEEP_DIR / "NY_A.csv"
DEFAULT_USALEEP_NY_B = USALEEP_DIR / "NY_B.csv"


# ---------------------------------------------------------------------------
# NVSR single-year life table loader
# ---------------------------------------------------------------------------

# Column order in NVSR XLSX files after the multi-row header:
#   Age | qx | lx | dx | Lx | Tx | ex
_NVSR_COLS = ["age_band", "qx", "lx", "dx", "Lx", "Tx", "ex"]


def _parse_age_band(band: str) -> tuple[int, str] | None:
    """Return (start_age, normalized_band) or None for unparseable strings.

    Handles NVSR conventions: en-dash ranges ("0–1"), ASCII hyphens ("0-1"),
    and top-coded forms ("100 and over", "100 and older", "85+").
    Returns None for footer rows like "SOURCE: ..." so the caller can drop them.
    """
    s = str(band).strip()
    lower = s.lower()
    if "and over" in lower or "and older" in lower or s.endswith("+"):
        head = (lower
                .replace("and over", "")
                .replace("and older", "")
                .replace("+", "")
                .strip())
        try:
            start = int(head)
        except ValueError:
            return None
        return start, f"{start}+"
    # Ranges with en-dash or hyphen.
    for sep in ("–", "-"):
        if sep in s:
            lo, hi = s.split(sep, 1)
            try:
                start = int(lo.strip())
                end = int(hi.strip())
                return start, f"{start}-{end}"
            except ValueError:
                continue
    # Single integer (rare for life tables, but defensive).
    try:
        return int(s), s
    except ValueError:
        return None


def _load_nvsr_life_table_file(
    path: Path,
    *,
    sex: Literal["All", "M", "F"],
    geography: str,
    geoid: str,
    year_start: int,
    year_end: int,
    vintage: str,
) -> pd.DataFrame:
    """Load one NVSR XLSX life-table file into LIFE_TABLE_COLUMNS."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Workbook contains no default style",
            category=UserWarning,
        )
        # Skip the title row + two header rows; the remaining rows are data.
        raw = pd.read_excel(path, sheet_name=0, header=None, skiprows=3)
    # Truncate any trailing all-NaN rows from the XLSX export.
    raw = raw.dropna(how="all").reset_index(drop=True)
    # First seven columns are age | qx | lx | dx | Lx | Tx | ex.
    raw = raw.iloc[:, :7]
    raw.columns = _NVSR_COLS

    # Drop trailing footer/source rows (e.g., "SOURCE: NCHS...") whose age
    # column is unparseable.
    ages_parsed = raw["age_band"].map(_parse_age_band)
    keep = ages_parsed.notna()
    raw = raw[keep].reset_index(drop=True)
    ages_parsed = ages_parsed[keep].reset_index(drop=True)
    starts = ages_parsed.map(lambda t: t[0])
    bands = ages_parsed.map(lambda t: t[1])

    out = pd.DataFrame({
        "geoid": geoid,
        "geography": geography,
        "year_start": year_start,
        "year_end": year_end,
        "sex": sex,
        "age": starts.astype(int),
        "age_band": bands,
        "qx": pd.to_numeric(raw["qx"], errors="coerce").astype("Float64"),
        "lx": pd.to_numeric(raw["lx"], errors="coerce").astype("Float64"),
        "Lx": pd.to_numeric(raw["Lx"], errors="coerce").astype("Float64"),
        "ex": pd.to_numeric(raw["ex"], errors="coerce").astype("Float64"),
        "source": "nchs_nvsr",
        "vintage": vintage,
        "notes": "",
    })
    return enforce_life_table_schema(out)


def load_nchs_us_life_table(
    *,
    sex: Literal["All", "M", "F"] = "All",
    path: Path | str | None = None,
    year: int = DEFAULT_US_LIFE_TABLE_YEAR,
    vintage: str = DEFAULT_US_LIFE_TABLE_VINTAGE,
) -> pd.DataFrame:
    """Load a national NCHS life table (single sex)."""
    if path is None:
        path = {
            "All": DEFAULT_US_LIFE_TABLE_TOTAL,
            "M": DEFAULT_US_LIFE_TABLE_MALE,
            "F": DEFAULT_US_LIFE_TABLE_FEMALE,
        }[sex]
    return _load_nvsr_life_table_file(
        Path(path),
        sex=sex,
        geography="United States",
        geoid="US",
        year_start=year,
        year_end=year,
        vintage=vintage,
    )


def load_nchs_us_life_tables_all_sexes(
    *,
    year: int = DEFAULT_US_LIFE_TABLE_YEAR,
    vintage: str = DEFAULT_US_LIFE_TABLE_VINTAGE,
) -> pd.DataFrame:
    """Load and stack all three (total / male / female) national life tables."""
    return pd.concat(
        [
            load_nchs_us_life_table(sex="All", year=year, vintage=vintage),
            load_nchs_us_life_table(sex="M", year=year, vintage=vintage),
            load_nchs_us_life_table(sex="F", year=year, vintage=vintage),
        ],
        ignore_index=True,
    )


def load_nchs_state_life_table(
    *,
    state_fips: str = "36",
    state_abbr: str = "NY",
    state_name: str = "New York",
    sex: Literal["All", "M", "F"] = "All",
    path: Path | str | None = None,
    year: int = DEFAULT_NY_LIFE_TABLE_YEAR,
    vintage: str = DEFAULT_NY_LIFE_TABLE_VINTAGE,
) -> pd.DataFrame:
    """Load a state-level NCHS life table (single sex).

    Defaults are NY 2022. The file naming convention from NCHS is
    `{ABBR}1.xlsx` (total), `{ABBR}2.xlsx` (male), `{ABBR}3.xlsx` (female).
    """
    if path is None:
        if state_abbr != "NY":
            raise ValueError(
                f"No default path configured for state_abbr={state_abbr!r}. "
                "Pass `path` explicitly."
            )
        path = {
            "All": DEFAULT_NY_LIFE_TABLE_TOTAL,
            "M": DEFAULT_NY_LIFE_TABLE_MALE,
            "F": DEFAULT_NY_LIFE_TABLE_FEMALE,
        }[sex]
    return _load_nvsr_life_table_file(
        Path(path),
        sex=sex,
        geography=state_name,
        geoid=pad_state_fips(int(state_fips)) + "000",
        year_start=year,
        year_end=year,
        vintage=vintage,
    )


def load_nchs_state_life_tables_all_sexes(
    *,
    state_fips: str = "36",
    state_abbr: str = "NY",
    state_name: str = "New York",
    year: int = DEFAULT_NY_LIFE_TABLE_YEAR,
    vintage: str = DEFAULT_NY_LIFE_TABLE_VINTAGE,
) -> pd.DataFrame:
    """Load and stack all three (total / male / female) state life tables."""
    return pd.concat(
        [
            load_nchs_state_life_table(
                state_fips=state_fips, state_abbr=state_abbr,
                state_name=state_name, sex=s, year=year, vintage=vintage,
            )
            for s in ("All", "M", "F")
        ],
        ignore_index=True,
    )


# ---------------------------------------------------------------------------
# USALEEP loader
# ---------------------------------------------------------------------------

# USALEEP age-band coding (from NCHS docs):
#   "Under 1"       → age 0
#   "1-4"           → age 1
#   "5-14"          → age 5
#   "15-24"         → age 15
#   "25-34"         → age 25
#   ...
#   "85+"           → age 85
_USALEEP_AGE_MAP: dict[str, int] = {
    "Under 1": 0,
    "1-4": 1,
    "5-14": 5,
    "15-24": 15,
    "25-34": 25,
    "35-44": 35,
    "45-54": 45,
    "55-64": 55,
    "65-74": 65,
    "75-84": 75,
    "85+": 85,
    "85 and older": 85,  # observed top-coded label in NY File B
}


def load_usaleep_life_expectancy(
    path: Path | str | None = None,
    *,
    state_fips: str = "36",
    state_name: str = "New York",
) -> pd.DataFrame:
    """Load the USALEEP File A: life expectancy at birth by census tract.

    Returns one row per tract, with `geoid` as the 11-digit tract ID,
    `ex` (life expectancy at birth), and standard error in the `notes`
    column. Sex = 'All', age = 0, age_band = '0+'.
    """
    path = Path(path) if path is not None else DEFAULT_USALEEP_NY_A
    raw = pd.read_csv(path, dtype=str)
    # Header is: Tract ID, STATE2KX, CNTY2KX, TRACT2KX, e(0), se(e(0)), flag
    out = pd.DataFrame({
        "geoid": raw["Tract ID"].astype(str),
        "geography": "Tract " + raw["TRACT2KX"].astype(str)
                     + ", County " + raw["CNTY2KX"].astype(str)
                     + ", " + state_name,
        "year_start": 2010,
        "year_end": 2015,
        "sex": "All",
        "age": 0,
        "age_band": "0+",
        "qx": pd.NA,
        "lx": pd.NA,
        "Lx": pd.NA,
        "ex": pd.to_numeric(raw["e(0)"], errors="coerce").astype("Float64"),
        "source": "nchs_usaleep",
        "vintage": "usaleep_2010_2015",
        "notes": "se(e(0))=" + raw["se(e(0))"].astype(str),
    })
    return enforce_life_table_schema(out)


def load_usaleep_life_table(
    path: Path | str | None = None,
    *,
    state_fips: str = "36",
    state_name: str = "New York",
    county_fips: str | None = None,
) -> pd.DataFrame:
    """Load USALEEP File B: full abridged life table by census tract.

    Returns one row per tract × age-band, conforming to LIFE_TABLE_COLUMNS.
    Pass `county_fips` (3-digit) to subset to a single county at load time
    (much cheaper than filtering downstream — File B is ~25k rows
    statewide).
    """
    path = Path(path) if path is not None else DEFAULT_USALEEP_NY_B
    raw = pd.read_csv(path, dtype=str)

    if county_fips is not None:
        county_fips = pad_county_fips(int(county_fips))
        raw = raw[raw["CNTY2KX"].astype(str).str.zfill(3) == county_fips].copy()

    ages = raw["Age Group"].map(_USALEEP_AGE_MAP).astype("Int64")
    if ages.isna().any():
        unknown = raw.loc[ages.isna(), "Age Group"].unique().tolist()
        warnings.warn(
            f"usaleep: unmapped age-band values dropped: {unknown}",
            stacklevel=2,
        )
        keep = ages.notna()
        raw = raw[keep].copy()
        ages = ages[keep]

    out = pd.DataFrame({
        "geoid": raw["Tract ID"].astype(str),
        "geography": "Tract " + raw["TRACT2KX"].astype(str)
                     + ", County " + raw["CNTY2KX"].astype(str)
                     + ", " + state_name,
        "year_start": 2010,
        "year_end": 2015,
        "sex": "All",
        "age": ages.astype(int),
        "age_band": raw["Age Group"].astype(str),
        "qx": pd.to_numeric(raw["nq(x)"], errors="coerce").astype("Float64"),
        "lx": pd.to_numeric(raw["l(x)"], errors="coerce").astype("Float64"),
        "Lx": pd.to_numeric(raw["nL(x)"], errors="coerce").astype("Float64"),
        "ex": pd.to_numeric(raw["e(x)"], errors="coerce").astype("Float64"),
        "source": "nchs_usaleep",
        "vintage": "usaleep_2010_2015",
        "notes": "",
    })
    return enforce_life_table_schema(out)
