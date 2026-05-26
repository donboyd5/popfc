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


def usaleep_county_life_table(
    tract_table: pd.DataFrame,
    *,
    state_fips: str = "36",
    county_fips: str,
    state_name: str = "New York",
    county_name: str | None = None,
    weights: pd.Series | None = None,
) -> pd.DataFrame:
    """Aggregate USALEEP tract life tables into a county-level abridged table.

    Combines tract-level life tables (one row per (tract, age band)) into
    a single set of county-level abridged life-table values. The
    aggregation weights tracts in one of two ways:

    - ``weights=None`` (default): equal weight per tract. Defensible when
      tracts in the county are similar in population size; explicitly a
      first-pass approximation.
    - ``weights=<Series indexed by tract geoid>``: population-weighted
      aggregation. The weight should represent each tract's *population*
      (typically from the 2010 decennial or contemporaneous ACS).

    Per-band aggregation. **The USALEEP tract life tables are all scaled
    to a radix of 100,000**, so both qx and Lx are *per-100,000-person*
    rates within a tract. To aggregate without double-counting we take
    weighted *means* of both, not sums:

    - ``qx``: weighted mean of the tract qx values across tracts.
    - ``Lx``: weighted mean of the tract Lx values across tracts (since
      each tract's Lx is already normalized to a 100k radix, summing
      would multiply person-years by the tract count).
    - ``lx``: reconstructed from a 100,000 radix and the cumulative
      survival implied by the aggregated qx.
    - ``ex``: re-derived as ``T(x) / l(x)`` from the aggregated L and lx.

    Parameters
    ----------
    tract_table
        Output of ``load_usaleep_life_table`` — long-format, one row per
        (tract geoid, age band).
    state_fips, county_fips
        FIPS codes for the target county. ``county_fips`` should be the
        3-digit string (e.g., ``"115"`` for Washington).
    state_name, county_name
        Used to build the human-readable ``geography`` column.
    weights
        Optional pandas Series indexed by tract geoid (11-digit) giving
        each tract's population weight. If omitted, all tracts in the
        county get equal weight.

    Returns
    -------
    DataFrame conforming to LIFE_TABLE_COLUMNS, with one row per age
    band (11 rows: Under 1, 1-4, 5-14, ..., 85+). Geoid is the 5-digit
    county FIPS; vintage is ``usaleep_2010_2015``.
    """
    county_fips = pad_county_fips(int(county_fips))
    state_fips = pad_state_fips(int(state_fips))
    county_geoid = f"{state_fips}{county_fips}"

    # Subset to county tracts.
    sub = tract_table[tract_table["geoid"].str.startswith(county_geoid)].copy()
    if sub.empty:
        raise ValueError(
            f"usaleep_county_life_table: no tract rows for county_fips={county_fips!r} "
            f"in the supplied tract_table (geoid prefix {county_geoid!r})"
        )

    # Build per-tract weights aligned to the tracts present.
    tract_ids = sub["geoid"].drop_duplicates().tolist()
    if weights is None:
        w = pd.Series(1.0, index=tract_ids)
    else:
        w = weights.reindex(tract_ids).astype(float)
        if w.isna().any():
            missing = w[w.isna()].index.tolist()
            raise ValueError(
                f"usaleep_county_life_table: weights missing values for "
                f"tracts {missing!r}"
            )
    w_total = float(w.sum())
    if w_total <= 0:
        raise ValueError("usaleep_county_life_table: sum of weights must be positive")

    # Aggregate per age band.
    rows: list[dict] = []
    for age in sorted(sub["age"].unique()):
        band_rows = sub[sub["age"] == age].set_index("geoid")
        # Align tracts to weight order (they should all be present, but be defensive).
        common = [t for t in tract_ids if t in band_rows.index]
        qx_vals = band_rows.loc[common, "qx"].astype(float).to_numpy()
        Lx_vals = band_rows.loc[common, "Lx"].astype(float).to_numpy()
        w_vals = w.loc[common].to_numpy()

        qx_county = float((qx_vals * w_vals).sum() / w_vals.sum())
        Lx_county = float((Lx_vals * w_vals).sum() / w_vals.sum())
        rows.append({
            "age": int(age),
            "age_band": band_rows["age_band"].iloc[0],
            "qx": qx_county,
            "Lx": Lx_county,
        })

    df = pd.DataFrame(rows).sort_values("age").reset_index(drop=True)

    # Reconstruct l(x) from the aggregated qx, using a 100,000 radix.
    # l(0) = 100,000; l(x+n) = l(x) * (1 - q(x)).
    lx_series = []
    lx_curr = 100_000.0
    for i in range(len(df)):
        lx_series.append(lx_curr)
        lx_curr = lx_curr * (1.0 - df.iloc[i]["qx"])
    df["lx"] = lx_series

    # T(x) = sum of L(x+) downward; e(x) = T(x) / l(x).
    df["Tx"] = df["Lx"][::-1].cumsum()[::-1]
    df["ex"] = df["Tx"].astype(float) / df["lx"].astype(float)

    geog = county_name or f"County {county_fips}, {state_name}"
    out = pd.DataFrame({
        "geoid": county_geoid,
        "geography": geog,
        "year_start": 2010,
        "year_end": 2015,
        "sex": "All",
        "age": df["age"].astype(int),
        "age_band": df["age_band"].astype(str),
        "qx": df["qx"].astype("Float64"),
        "lx": df["lx"].astype("Float64"),
        "Lx": df["Lx"].astype("Float64"),
        "ex": df["ex"].astype("Float64"),
        "source": "nchs_usaleep",
        "vintage": "usaleep_2010_2015",
        "notes": (
            "county-aggregate from USALEEP tract life tables; "
            f"n_tracts={len(tract_ids)}; "
            f"weighting={'population' if weights is not None else 'equal'}"
        ),
    })
    return enforce_life_table_schema(out)


# ---------------------------------------------------------------------------
# USALEEP qx-ratio adjustment — apply tract-level mortality differential
# to a single-year national/state life table
# ---------------------------------------------------------------------------

# USALEEP age-band boundaries (closed start, inclusive end). The open band
# starts at 85 and has no upper bound.
_USALEEP_BAND_BOUNDS: list[tuple[int, int]] = [
    (0, 0),    # Under 1
    (1, 4),    # 1-4
    (5, 14),   # 5-14
    (15, 24),  # 15-24
    (25, 34),  # 25-34
    (35, 44),  # 35-44
    (45, 54),  # 45-54
    (55, 64),  # 55-64
    (65, 74),  # 65-74
    (75, 84),  # 75-84
    (85, 999), # 85 and older
]


def _usaleep_band_for_age(age: int) -> int:
    """Return the USALEEP band-start age (0, 1, 5, 15, …, 85) for a single year of age."""
    for start, end in _USALEEP_BAND_BOUNDS:
        if start <= age <= end:
            return start
    raise ValueError(f"_usaleep_band_for_age: age {age} doesn't fit any band")


def usaleep_qx_band_ratio(
    target: pd.DataFrame,
    reference: pd.DataFrame,
) -> pd.DataFrame:
    """Compute per-band qx ratios between two USALEEP-aggregate life tables.

    Used to derive a multiplicative adjustment that captures a county's
    mortality differential vs a reference geography (typically the state
    aggregate). The intended use is to apply the ratio to NVSR state-level
    single-year qx values, producing a county-specific single-year life
    table that **preserves the state's period (e.g., 2022)** while
    applying the **county's USALEEP-derived mortality differential**.

    Parameters
    ----------
    target, reference
        USALEEP-aggregate life tables (output of ``usaleep_county_life_table``).
        Both must have the same set of bands.

    Returns
    -------
    DataFrame with columns ``age`` (band-start), ``age_band``, ``qx_ratio``
    where ``qx_ratio = target.qx / reference.qx`` per band. Ratios <1
    indicate the target has *lower* mortality than the reference (better
    survival); >1 indicates higher mortality.
    """
    cols = ["age", "age_band", "qx"]
    missing = [c for c in cols if c not in target.columns or c not in reference.columns]
    if missing:
        raise ValueError(
            f"usaleep_qx_band_ratio: both inputs must have columns {cols}; "
            f"missing: {missing}"
        )
    t = target[cols].rename(columns={"qx": "qx_target"})
    r = reference[cols].rename(columns={"qx": "qx_ref"})
    merged = t.merge(r, on=["age", "age_band"], how="inner")
    if len(merged) != len(t) or len(merged) != len(r):
        raise ValueError(
            f"usaleep_qx_band_ratio: target and reference bands don't align; "
            f"target n={len(t)}, ref n={len(r)}, joined n={len(merged)}"
        )
    merged["qx_ratio"] = merged["qx_target"].astype(float) / merged["qx_ref"].astype(float)
    return merged[["age", "age_band", "qx_ratio"]].reset_index(drop=True)


def apply_qx_ratio_to_life_table(
    life_table: pd.DataFrame,
    qx_ratios: pd.DataFrame,
    *,
    target_geoid: str,
    target_geography: str,
    radix: float = 100_000.0,
) -> pd.DataFrame:
    """Adjust an NVSR single-year life table by per-band qx ratios.

    Rebuilds the life table with adjusted single-year qx values, then
    recomputes lx via cumulative survival from the radix, Lx via the
    standard linear approximation ``(lx + lx_next)/2`` for closed bands,
    Tx via reverse cumulative Lx sum, and ex as ``Tx / lx``.

    Vintage is carried from the source life table (so the *period* is
    NVSR-current — e.g., 2022 — even though the *differential* came from
    USALEEP 2010-2015).

    Parameters
    ----------
    life_table
        NVSR-style single-year life table (one row per single age) for
        the reference geo, conforming to LIFE_TABLE_COLUMNS. Typically the
        NY state NVSR 2022 table loaded via ``load_nchs_state_life_table``.
    qx_ratios
        Output of ``usaleep_qx_band_ratio`` — per-band multiplicative
        adjustments.
    target_geoid, target_geography
        Identifiers stamped onto the output rows.
    radix
        Starting lx(0). Default 100,000 to match NVSR convention.

    Returns
    -------
    DataFrame conforming to LIFE_TABLE_COLUMNS, one row per single age,
    same set of ages as the input life table. Source remains
    ``nchs_nvsr`` (period match preserved); vintage gains an ``_usaleep_adj``
    suffix so downstream code can identify it.
    """
    band_map = qx_ratios.set_index("age")["qx_ratio"].astype(float).to_dict()

    out_rows: list[pd.DataFrame] = []
    for (sex,), sub in life_table.groupby(["sex"], dropna=False, sort=False):
        sub_sorted = sub.sort_values("age").reset_index(drop=True).copy()
        # Adjusted qx per single year.
        bands = sub_sorted["age"].astype(int).map(_usaleep_band_for_age)
        ratios = bands.map(band_map)
        if ratios.isna().any():
            missing_ages = sub_sorted.loc[ratios.isna(), "age"].tolist()
            raise ValueError(
                f"apply_qx_ratio_to_life_table: no qx_ratio for ages {missing_ages}"
            )
        sub_sorted["qx_adj"] = (
            sub_sorted["qx"].astype(float) * ratios.astype(float)
        ).clip(upper=1.0)

        # Rebuild lx via cumulative survival from radix.
        lx = [float(radix)]
        for i in range(len(sub_sorted) - 1):
            lx.append(lx[-1] * (1.0 - sub_sorted.iloc[i]["qx_adj"]))
        # The last band closes out (qx_adj should be ~1.0 at the top); ensure
        # lx for the very last age is correctly computed.
        sub_sorted["lx_new"] = lx

        # Lx via (lx + lx_next)/2 for closed bands; open band uses Lx = lx_top.
        # For the engine's purpose (S(x) = L(x+1)/L(x)), this approximation is
        # fine for closed bands. The open band's Sx is computed separately
        # via Preston's formula by the engine, so its Lx is best computed as
        # the integral of survivors above the boundary — we approximate by
        # carrying the original NVSR ratio (Lx_old / lx_old) and scaling.
        Lx_new = []
        for i in range(len(sub_sorted) - 1):
            Lx_new.append(
                0.5 * (float(sub_sorted.iloc[i]["lx_new"])
                       + float(sub_sorted.iloc[i + 1]["lx_new"]))
            )
        # Open-band Lx: scale by the same lx-ratio as the source.
        last_row = sub_sorted.iloc[-1]
        old_Lx_ratio = float(last_row["Lx"]) / float(last_row["lx"]) if float(last_row["lx"]) > 0 else 0.0
        Lx_new.append(old_Lx_ratio * float(last_row["lx_new"]))
        sub_sorted["Lx_new"] = Lx_new

        # Tx and ex.
        sub_sorted["Tx_new"] = sub_sorted["Lx_new"][::-1].cumsum()[::-1]
        sub_sorted["ex_new"] = sub_sorted["Tx_new"].astype(float) / sub_sorted["lx_new"].astype(float)

        old_vintage = sub_sorted["vintage"].iloc[0]
        new_vintage = f"{old_vintage}_usaleep_adj"
        out_one = pd.DataFrame({
            "geoid": target_geoid,
            "geography": target_geography,
            "year_start": sub_sorted["year_start"],
            "year_end": sub_sorted["year_end"],
            "sex": sex,
            "age": sub_sorted["age"].astype(int),
            "age_band": sub_sorted["age_band"],
            "qx": sub_sorted["qx_adj"].astype("Float64"),
            "lx": sub_sorted["lx_new"].astype("Float64"),
            "Lx": sub_sorted["Lx_new"].astype("Float64"),
            "ex": sub_sorted["ex_new"].astype("Float64"),
            "source": sub_sorted["source"],
            "vintage": new_vintage,
            "notes": (
                "USALEEP qx-ratio-adjusted from "
                + sub_sorted["geoid"].astype(str)
                + "; period preserved from source"
            ),
        })
        out_rows.append(out_one)

    return enforce_life_table_schema(pd.concat(out_rows, ignore_index=True))
