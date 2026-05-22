"""Shared utilities and schema constants for data loaders.

All population-series loaders in this package emit a **long-format** DataFrame
with the `POP_LONG_COLUMNS` schema below. All components-of-change loaders emit
the `COMPONENTS_LONG_COLUMNS` schema.

This keeps downstream reconciliation code source-agnostic.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Canonical long-format schemas
# ---------------------------------------------------------------------------

POP_LONG_COLUMNS: list[str] = [
    "state_fips",   # "36"  (zero-padded 2-digit)
    "county_fips",  # "115" (zero-padded 3-digit; "000" for state totals)
    "geoid",        # "36115" (state_fips + county_fips)
    "geography",    # "Washington County"
    "year",         # int, e.g., 2020
    "kind",         # "estimate" | "estimates_base" | "census" | "projection" | "intercensal"
    "population",   # int64 (nullable)
    "source",       # "census_pep" | "nysdol" | "cdc_bridged" | "nysdoh" | "cornell_pad"
    "vintage",      # file vintage tag, e.g., "v2024" or "2020-2024"
    "notes",        # free-form string (may be empty)
]

COMPONENTS_LONG_COLUMNS: list[str] = [
    "state_fips",
    "county_fips",
    "geoid",
    "geography",
    "year",
    "measure",      # "births" | "deaths" | "natural_change" | "international_mig" |
                    # "domestic_mig" | "net_mig" | "residual" | "gq_estimate"
    "value",        # int64 (nullable); some residuals can be negative
    "source",
    "vintage",
    "notes",
]

AGESEX_LONG_COLUMNS: list[str] = [
    "state_fips",
    "county_fips",
    "geoid",
    "geography",
    "year",
    "kind",         # "estimate" | "census" | "estimates_base" | "projection"
    "sex",          # "F" | "M"
    "age",          # int 0..85 (85 is typically top-coded)
    "age_top_coded",  # bool
    "population",
    "source",
    "vintage",
    "notes",
]

LIFE_TABLE_COLUMNS: list[str] = [
    "geoid",         # "US" | "36000" (state) | full 11-digit tract id
    "geography",     # "United States" | "New York" | "Tract 100, Albany County"
    "year_start",    # int — first year of period
    "year_end",      # int — last year of period (== year_start for single-year tables)
    "sex",           # "All" | "M" | "F"
    "age",           # int — starting age of the band (0, 1, 5, 10, ...)
    "age_band",      # string — "0-1", "1-5", "85+", "100+", "Under 1"
    "qx",            # nullable Float64 — probability of dying between x and x+n
    "lx",            # nullable Float64 — number surviving to age x (radix 100,000)
    "Lx",            # nullable Float64 — person-years lived between x and x+n
    "ex",            # nullable Float64 — expectation of life at age x (years)
    "source",        # "nchs_nvsr" | "nchs_usaleep"
    "vintage",       # publication tag, e.g., "nvsr74-06" or "usaleep_2010_2015"
    "notes",
]


# ---------------------------------------------------------------------------
# FIPS helpers
# ---------------------------------------------------------------------------

def pad_state_fips(state: int | str) -> str:
    """Return zero-padded 2-digit state FIPS as a string ('36', '01', ...)."""
    return f"{int(state):02d}"


def pad_county_fips(county: int | str) -> str:
    """Return zero-padded 3-digit county FIPS as a string ('115', '001', ...)."""
    return f"{int(county):03d}"


def make_geoid(state: int | str, county: int | str) -> str:
    """Return 5-char GEOID (state_fips + county_fips): '36115', '36000', ..."""
    return pad_state_fips(state) + pad_county_fips(county)


def add_geoid_columns(
    df: pd.DataFrame,
    state_col: str = "STATE",
    county_col: str = "COUNTY",
) -> pd.DataFrame:
    """Add standardized `state_fips`, `county_fips`, `geoid` columns from int cols.

    Does not drop the original columns. Returns a copy.
    """
    out = df.copy()
    out["state_fips"] = out[state_col].astype(int).map(pad_state_fips)
    out["county_fips"] = out[county_col].astype(int).map(pad_county_fips)
    out["geoid"] = out["state_fips"] + out["county_fips"]
    return out


# ---------------------------------------------------------------------------
# Schema enforcement
# ---------------------------------------------------------------------------

def enforce_pop_long_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Reorder/subset to POP_LONG_COLUMNS, filling missing columns with None.

    Use as the final step of every population loader so downstream code can
    rely on exact column names and order.
    """
    return _enforce_schema(df, POP_LONG_COLUMNS)


def enforce_components_long_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Reorder/subset to COMPONENTS_LONG_COLUMNS, filling missing with None."""
    return _enforce_schema(df, COMPONENTS_LONG_COLUMNS)


def enforce_agesex_long_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Reorder/subset to AGESEX_LONG_COLUMNS, filling missing with None."""
    return _enforce_schema(df, AGESEX_LONG_COLUMNS)


def enforce_life_table_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Reorder/subset to LIFE_TABLE_COLUMNS, filling missing with None."""
    return _enforce_schema(df, LIFE_TABLE_COLUMNS)


def _enforce_schema(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col not in out.columns:
            out[col] = None
    return out[columns]


# ---------------------------------------------------------------------------
# String-first ingestion helpers
#
# Our loaders read raw CSVs with `dtype=str` so we can see the raw values as
# written by the upstream agency before any pandas auto-inference happens.
# This surfaces problems that would otherwise be silently masked (mixed int /
# string columns becoming object-dtype, sentinel values, lost leading zeros
# on FIPS codes, etc.). Explicit coercion with `errors="coerce"` at the melt
# step, with a count of non-numeric values logged as a warning, keeps data
# issues visible.
# ---------------------------------------------------------------------------

def read_csv_strings(path: Path | str, **kwargs) -> pd.DataFrame:
    """Read a CSV with every column forced to string dtype.

    Thin wrapper around `pd.read_csv` with `dtype=str` and
    `encoding_errors="replace"` defaults. Extra kwargs are forwarded.
    """
    kwargs.setdefault("encoding_errors", "replace")
    return pd.read_csv(path, dtype=str, **kwargs)


def coerce_numeric(
    series: pd.Series,
    label: str,
    dtype: str = "Int64",
) -> pd.Series:
    """Coerce a (likely string) series to numeric; warn on non-numeric values.

    Parameters
    ----------
    series
        Values as strings (or already numeric — the call is safe).
    label
        Human-readable label used in the warning message when values are
        coerced to NaN (e.g., "census_pep/births/v2024").
    dtype
        Output dtype — "Int64" (nullable int) for counts, "Float64" for rates.

    Any non-parseable value becomes NaN in the output AND triggers a
    `UserWarning` counting how many were lost. This keeps data-quality
    problems visible instead of silently masked.
    """
    numeric = pd.to_numeric(series, errors="coerce")
    # Treat empty strings as already-null input (pandas does this, but be
    # explicit for clarity).
    was_present = series.notna() & (series.astype(str).str.strip() != "")
    lost = int((was_present & numeric.isna()).sum())
    if lost > 0:
        warnings.warn(
            f"{label}: coerced {lost:,} non-numeric value(s) to NaN",
            stacklevel=3,
        )
    if dtype in {"Int64", "Int32"}:
        # Counts: round any stray floats, then cast to nullable int.
        numeric = numeric.astype("Float64").round().astype(dtype)
    else:
        numeric = numeric.astype(dtype)
    return numeric
