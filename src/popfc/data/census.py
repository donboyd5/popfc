"""Census Bureau Population Estimates Program (PEP) county-level loaders.

Three vintage-layout files currently supported, all in `data_raw/census/`:

- `2000-2010/co-est00int-tot.csv`          — Intercensal 2000-2010 (totals only)
- `2010-2020/co-est2020-alldata.csv`       — Intercensal 2010-2020 (totals + components)
- `2020-plus/co-est2024-alldata.csv`       — Postcensal 2020-2024  (totals + components)

Each file is wide-format (year-by-measure columns). These loaders emit
long-format DataFrames conforming to `POP_LONG_COLUMNS` (for totals) and
`COMPONENTS_LONG_COLUMNS` (for components of change).

Design notes:
- Each function accepts `path` as a parameter with a default pointing into
  `DATA_RAW`, so swapping in a newer vintage is a one-line change.
- `vintage` is auto-derived from the file name if not provided.
- Column name differences between vintages (e.g., `NATURALCHG` vs `NATURALINC`)
  are normalized to `natural_change` in the output.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from popfc.data._common import (
    add_geoid_columns,
    coerce_numeric,
    enforce_agesex_long_schema,
    enforce_components_long_schema,
    enforce_pop_long_schema,
    read_csv_strings,
)
from popfc.paths import CENSUS_DIR

# Default paths — override via function args when loading a newer vintage.
DEFAULT_PEP_2020_PLUS = CENSUS_DIR / "2020-plus" / "co-est2025-alldata.csv"
DEFAULT_PEP_2010_2020 = CENSUS_DIR / "2010-2020" / "co-est2020-alldata.csv"
DEFAULT_PEP_2000_2010 = CENSUS_DIR / "2000-2010" / "co-est00int-tot.csv"
DEFAULT_SYA_2020_PLUS = CENSUS_DIR / "2020-plus" / "cc-est2024-syasex-36.csv"

# Census SUMLEV codes
SUMLEV_STATE = 40
SUMLEV_COUNTY = 50

# Map of component column prefix -> normalized measure name.
# Covers both 2010-2020 (NATURALINC / NPOPCHG_) and 2020-plus (NATURALCHG / NPOPCHG) naming.
#
# COUNT prefixes: integer counts per year (e.g., BIRTHS2020).
_COMPONENT_COUNT_PREFIXES: dict[str, str] = {
    "BIRTHS": "births",
    "DEATHS": "deaths",
    "NATURALINC": "natural_change",
    "NATURALCHG": "natural_change",
    "INTERNATIONALMIG": "international_mig",
    "DOMESTICMIG": "domestic_mig",
    "NETMIG": "net_mig",
    "NPOPCHG": "pop_change",
    "RESIDUAL": "residual",
    "GQESTIMATES": "gq_estimate",
}

# RATE prefixes: per 1,000 of mid-year average population (e.g., RBIRTH2024).
# Used by the "adjusted" method to compute consistent births/deaths near
# decennial census seams (see docs/r_reference/get-components-of-change.qmd).
# NOTE: Census uses "RBIRTH" / "RDEATH" (singular), unlike the count columns
# "BIRTHS" / "DEATHS" (plural).
_COMPONENT_RATE_PREFIXES: dict[str, str] = {
    "RBIRTH": "rate_births",
    "RDEATH": "rate_deaths",
    "RNATURALINC": "rate_natural_change",
    "RNATURALCHG": "rate_natural_change",
    "RINTERNATIONALMIG": "rate_international_mig",
    "RDOMESTICMIG": "rate_domestic_mig",
    "RNETMIG": "rate_net_mig",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _derive_vintage(path: Path, fallback: str) -> str:
    """Infer a vintage tag from the filename, falling back to a sentinel."""
    stem = path.stem.lower()
    # e.g., 'co-est2024-alldata' -> 'v2024'
    for part in stem.split("-"):
        if part.startswith("est") and len(part) >= 6:
            year_part = part[3:7]
            if year_part.isdigit():
                return f"v{year_part}"
    return fallback


def _filter_counties(df: pd.DataFrame, keep_state_rows: bool = True) -> pd.DataFrame:
    """Keep SUMLEV 40 (state) and 50 (county) rows; drop country-total rows.

    Keeps SUMLEV as a string and normalizes leading zeros for the comparison,
    so this works whether the raw file writes "40" or "040". Staying in
    string-space lets the raw values remain visible for inspection.
    """
    keep = {str(SUMLEV_COUNTY)}
    if keep_state_rows:
        keep.add(str(SUMLEV_STATE))
    sumlev_norm = df["SUMLEV"].astype(str).str.lstrip("0").replace("", "0")
    return df[sumlev_norm.isin(keep)].copy()


def _wide_to_long_pop(
    df: pd.DataFrame,
    year_cols: dict[int, str],
    kind: str,
    source: str,
    vintage: str,
) -> pd.DataFrame:
    """Melt a wide population block into POP_LONG_COLUMNS long format.

    Parameters
    ----------
    df
        Wide dataframe that already has `state_fips`, `county_fips`, `geoid`,
        and `geography` columns attached.
    year_cols
        Mapping of {year_int: column_name_in_df}, e.g.
        {2020: 'POPESTIMATE2020', 2021: 'POPESTIMATE2021', ...}.
    kind
        Value for the output `kind` column (e.g., 'estimate', 'estimates_base',
        'census', 'intercensal').
    """
    keep_id = ["state_fips", "county_fips", "geoid", "geography"]
    present = {y: c for y, c in year_cols.items() if c in df.columns}
    if not present:
        return pd.DataFrame(columns=keep_id + ["year", "population"])
    long = df[keep_id + list(present.values())].melt(
        id_vars=keep_id,
        var_name="_col",
        value_name="population",
    )
    col_to_year = {c: y for y, c in present.items()}
    long["year"] = long["_col"].map(col_to_year).astype(int)
    long = long.drop(columns="_col")
    # Coerce population (may arrive as string from string-first read) to
    # nullable Int64, surfacing any non-numeric values via warning.
    long["population"] = coerce_numeric(
        long["population"], label=f"{source}/{kind}/{vintage} population"
    )
    long["kind"] = kind
    long["source"] = source
    long["vintage"] = vintage
    long["notes"] = ""
    return long


def _wide_to_long_components(
    df: pd.DataFrame,
    vintage: str,
    source: str = "census_pep",
) -> pd.DataFrame:
    """Melt component columns (counts + rates) to long form.

    Handles both COUNT columns (e.g., BIRTHS2020) and RATE columns
    (e.g., RBIRTH2020 — per 1,000 mid-year average population). Rate
    measures are emitted with a `rate_` prefix (e.g., "rate_births").

    Returns COMPONENTS_LONG_COLUMNS schema. RATE values are cast to float;
    COUNT values are left as whatever dtype pandas infers (int where clean).
    """
    keep_id = ["state_fips", "county_fips", "geoid", "geography"]
    frames: list[pd.DataFrame] = []

    # Iterate longest prefix first so "RNATURALINC" is tried before "RESIDUAL"
    # etc. — avoids a short prefix swallowing a longer column name. Also
    # ensures rate prefixes are tried before count prefixes that share a
    # stem (none currently overlap, but this is defensive).
    prefix_items = sorted(
        [(p, m, False) for p, m in _COMPONENT_COUNT_PREFIXES.items()]
        + [(p, m, True) for p, m in _COMPONENT_RATE_PREFIXES.items()],
        key=lambda t: -len(t[0]),
    )

    # Track which columns have already been claimed by a (longer) prefix so
    # that, e.g., "RBIRTH2020" isn't re-matched by a later shorter prefix.
    claimed: set[str] = set()

    for prefix, measure, is_rate in prefix_items:
        year_cols: dict[int, str] = {}
        for col in df.columns:
            if col in claimed or not col.startswith(prefix):
                continue
            tail = col[len(prefix):].lstrip("_")
            if tail.isdigit() and len(tail) == 4:
                year_cols[int(tail)] = col
        if not year_cols:
            continue
        claimed.update(year_cols.values())

        sub = df[keep_id + list(year_cols.values())].melt(
            id_vars=keep_id,
            var_name="_col",
            value_name="value",
        )
        sub["year"] = sub["_col"].map({v: k for k, v in year_cols.items()}).astype(int)
        sub = sub.drop(columns="_col")
        sub["measure"] = measure
        # Coerce explicitly so string-first reads are handled uniformly.
        # Rates are per-1000 floats; counts are nullable ints.
        sub["value"] = coerce_numeric(
            sub["value"],
            label=f"{source}/{measure}/{vintage}",
            dtype="Float64" if is_rate else "Int64",
        )
        frames.append(sub)

    if not frames:
        return pd.DataFrame(columns=keep_id + ["year", "measure", "value"])
    out = pd.concat(frames, ignore_index=True)
    out["source"] = source
    out["vintage"] = vintage
    out["notes"] = ""
    return out


def _prepare_frame(df: pd.DataFrame, state_filter: str | None = "36") -> pd.DataFrame:
    """Filter to NY (default), keep state+county rows, attach FIPS columns."""
    df = _filter_counties(df)
    if state_filter is not None:
        df = df[df["STATE"].astype(int) == int(state_filter)].copy()
    df = add_geoid_columns(df, state_col="STATE", county_col="COUNTY")
    df["geography"] = df["CTYNAME"]
    return df


# ---------------------------------------------------------------------------
# Public loaders
# ---------------------------------------------------------------------------

def load_pep_2020_plus(
    path: Path | str | None = None,
    state_filter: str | None = "36",
    vintage: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Load the Census PEP 2020-plus vintage file.

    Returns
    -------
    dict with keys:
        - 'population': long-format DataFrame (POP_LONG_COLUMNS)
        - 'components': long-format DataFrame (COMPONENTS_LONG_COLUMNS)
    """
    path = Path(path) if path is not None else DEFAULT_PEP_2020_PLUS
    vintage = vintage or _derive_vintage(path, fallback="v2020plus")

    raw = read_csv_strings(path)
    df = _prepare_frame(raw, state_filter=state_filter)

    # Years covered: 2020-2025. Columns include ESTIMATESBASE2020 and POPESTIMATE2020..2025.
    year_cols = {y: f"POPESTIMATE{y}" for y in range(2020, 2026)}
    pop_estimates = _wide_to_long_pop(
        df, year_cols, kind="estimate", source="census_pep", vintage=vintage
    )
    pop_base = _wide_to_long_pop(
        df,
        {2020: "ESTIMATESBASE2020"},
        kind="estimates_base",
        source="census_pep",
        vintage=vintage,
    )
    population = pd.concat([pop_base, pop_estimates], ignore_index=True)

    components = _wide_to_long_components(df, vintage=vintage)

    return {
        "population": enforce_pop_long_schema(population),
        "components": enforce_components_long_schema(components),
    }


def load_pep_2010_2020(
    path: Path | str | None = None,
    state_filter: str | None = "36",
    vintage: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Load the Census PEP 2010-2020 intercensal vintage file."""
    path = Path(path) if path is not None else DEFAULT_PEP_2010_2020
    vintage = vintage or _derive_vintage(path, fallback="v2020")

    raw = read_csv_strings(path)
    df = _prepare_frame(raw, state_filter=state_filter)

    year_cols_est = {y: f"POPESTIMATE{y}" for y in range(2010, 2021)}
    pop_estimates = _wide_to_long_pop(
        df, year_cols_est, kind="estimate", source="census_pep", vintage=vintage
    )
    pop_base = _wide_to_long_pop(
        df,
        {2010: "ESTIMATESBASE2010"},
        kind="estimates_base",
        source="census_pep",
        vintage=vintage,
    )
    pop_census = _wide_to_long_pop(
        df,
        {2010: "CENSUS2010POP"},
        kind="census",
        source="census_pep",
        vintage=vintage,
    )
    population = pd.concat([pop_base, pop_census, pop_estimates], ignore_index=True)

    components = _wide_to_long_components(df, vintage=vintage)

    return {
        "population": enforce_pop_long_schema(population),
        "components": enforce_components_long_schema(components),
    }


def load_pep_2000_2010(
    path: Path | str | None = None,
    state_filter: str | None = "36",
    vintage: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Load the Census PEP 2000-2010 intercensal totals file.

    This file has population totals only, no components of change.
    Returns a dict with only a 'population' key for consistency with other loaders.
    """
    path = Path(path) if path is not None else DEFAULT_PEP_2000_2010
    vintage = vintage or _derive_vintage(path, fallback="v2010int")

    raw = read_csv_strings(path)
    df = _prepare_frame(raw, state_filter=state_filter)

    year_cols_est = {y: f"POPESTIMATE{y}" for y in range(2000, 2011)}
    pop_estimates = _wide_to_long_pop(
        df, year_cols_est, kind="intercensal", source="census_pep", vintage=vintage
    )
    pop_base = _wide_to_long_pop(
        df,
        {2000: "ESTIMATESBASE2000"},
        kind="estimates_base",
        source="census_pep",
        vintage=vintage,
    )
    pop_census = _wide_to_long_pop(
        df,
        {2010: "CENSUS2010POP"},
        kind="census",
        source="census_pep",
        vintage=vintage,
    )
    population = pd.concat([pop_base, pop_census, pop_estimates], ignore_index=True)

    # 2000-2010 intercensal file has no component-of-change columns.
    # Return a schema-conformant empty frame (built via the enforcer so it
    # matches dtypes of the populated frames produced by other loaders).
    empty_components = enforce_components_long_schema(
        pd.DataFrame({
            "state_fips": pd.Series(dtype="object"),
            "county_fips": pd.Series(dtype="object"),
            "geoid": pd.Series(dtype="object"),
            "geography": pd.Series(dtype="object"),
            "year": pd.Series(dtype="int64"),
            "measure": pd.Series(dtype="object"),
            "value": pd.Series(dtype="float64"),
            "source": pd.Series(dtype="object"),
            "vintage": pd.Series(dtype="object"),
            "notes": pd.Series(dtype="object"),
        })
    )
    return {
        "population": enforce_pop_long_schema(population),
        "components": empty_components,
    }


def load_all_pep(
    state_filter: str | None = "36",
) -> dict[str, pd.DataFrame]:
    """Load all three available Census PEP vintages and stack.

    Returns
    -------
    dict with keys 'population' and 'components'.
    """
    a = load_pep_2000_2010(state_filter=state_filter)
    b = load_pep_2010_2020(state_filter=state_filter)
    c = load_pep_2020_plus(state_filter=state_filter)
    return {
        "population": pd.concat(
            [a["population"], b["population"], c["population"]], ignore_index=True
        ),
        "components": pd.concat(
            [a["components"], b["components"], c["components"]], ignore_index=True
        ),
    }


# ---------------------------------------------------------------------------
# Single-year-of-age × sex × year loader (post-2020 vintages)
# ---------------------------------------------------------------------------

# YEAR-code mapping for the cc-estYYYY-syasex-36.csv files.
#
# Census documents this mapping in each file's accompanying README. For both
# the V2023 and V2024 releases the codes are:
#
#   1 = 4/1/2020 Estimates Base           (kind='census',   calendar=2020)
#   2 = 7/1/2020 Population Estimate      (kind='estimate', calendar=2020)
#   3 = 7/1/2021 Population Estimate      (kind='estimate', calendar=2021)
#   4 = 7/1/2022 Population Estimate      (kind='estimate', calendar=2022)
#   5 = 7/1/2023 Population Estimate      (kind='estimate', calendar=2023)
#   6 = 7/1/2024 Population Estimate      (kind='estimate', calendar=2024)   [V2024 only]
#
# Code 1 is the demographic-analysis-adjusted 4/1/2020 base used by PEP, which
# is within a few persons of the raw 4/1/2020 census enumeration; we label it
# 'census' for continuity with the rest of the pipeline.
#
# Verification: cross-checks against PEP V2024 county totals match SYA V2024
# at the unit for every code and every NY county. **Always re-verify when a
# newer vintage is dropped in** — Census occasionally shifts the codes (older
# `cc-est20XX` files include both 4/1/2020 Census and 4/1/2020 Estimates Base,
# so the mapping has 6 codes instead of 5).
_SYA_YEAR_MAP_V2023: dict[int, tuple[int, str]] = {
    1: (2020, "census"),
    2: (2020, "estimate"),
    3: (2021, "estimate"),
    4: (2022, "estimate"),
    5: (2023, "estimate"),
}

_SYA_YEAR_MAP_V2024: dict[int, tuple[int, str]] = {
    **_SYA_YEAR_MAP_V2023,
    6: (2024, "estimate"),
}


def load_census_sya(
    path: Path | str | None = None,
    state_filter: str | None = "36",
    year_map: dict[int, tuple[int, str]] | None = None,
    vintage: str | None = None,
) -> pd.DataFrame:
    """Load the Census single-year-of-age × sex county-level file.

    The 2020+ vintage file (`cc-est2023-syasex-36.csv`) carries population by
    SUMLEV × STATE × COUNTY × YEAR-code × AGE, with separate columns for
    TOT_POP, TOT_MALE, and TOT_FEMALE. This loader melts MALE/FEMALE into
    long-format rows with a `sex` column and translates the YEAR code into a
    calendar year + `kind` label (census vs estimate).

    Parameters
    ----------
    path
        Override the default file location.
    state_filter
        Restrict to a state FIPS string (default "36" for NY). Pass None to
        load all states (the file ships per-state, so this is usually
        redundant).
    year_map
        Override the YEAR-code mapping. Defaults to `_SYA_YEAR_MAP_V2024`
        (codes 1-6, covering 4/1/2020 through 7/1/2024). For the older V2023
        vintage file, pass `_SYA_YEAR_MAP_V2023` explicitly. **Always re-verify
        the mapping before upgrading the default to a newer vintage.**
    vintage
        Vintage tag for the output. Default is derived from the filename.

    Returns
    -------
    DataFrame with AGESEX_LONG_COLUMNS schema, one row per
    (geoid, year, kind, sex, age).
    """
    path = Path(path) if path is not None else DEFAULT_SYA_2020_PLUS
    if year_map is None:
        year_map = _SYA_YEAR_MAP_V2024
    if vintage is None:
        vintage = _derive_vintage(path, fallback="syasex_unknown")
        if not vintage.startswith("sya_"):
            vintage = f"sya_{vintage}"

    raw = read_csv_strings(path)
    # Filter to county rows (SUMLEV=050).
    sumlev_norm = raw["SUMLEV"].astype(str).str.lstrip("0").replace("", "0")
    df = raw[sumlev_norm == str(SUMLEV_COUNTY)].copy()
    if state_filter is not None:
        df = df[df["STATE"].astype(int) == int(state_filter)].copy()

    df = add_geoid_columns(df, state_col="STATE", county_col="COUNTY")
    df["geography"] = df["CTYNAME"]

    year_code = coerce_numeric(df["YEAR"], label="census_sya/year_code", dtype="Int64")
    age = coerce_numeric(df["AGE"], label="census_sya/age", dtype="Int64")

    # Map year code → (calendar_year, kind). Drop rows whose code is unmapped
    # (a noisy default avoids silently emitting under-the-wrong-year rows).
    mapped = year_code.map(lambda v: year_map.get(int(v)) if pd.notna(v) else None)
    unmapped = year_code[mapped.isna() & year_code.notna()].unique()
    if len(unmapped) > 0:
        import warnings
        warnings.warn(
            f"census_sya: unmapped YEAR codes {sorted(int(c) for c in unmapped)} — "
            "rows dropped. Update year_map or the SYA YEAR-code documentation.",
            stacklevel=2,
        )
    keep = mapped.notna()
    df = df[keep].copy()
    mapped = mapped[keep]
    age = age[keep]

    calendar_year = mapped.map(lambda t: t[0]).astype(int)
    kind = mapped.map(lambda t: t[1])

    # Melt TOT_MALE and TOT_FEMALE into a long sex/population frame.
    frames = []
    for sex_col, sex_code in (("TOT_MALE", "M"), ("TOT_FEMALE", "F")):
        pop = coerce_numeric(
            df[sex_col],
            label=f"census_sya/{sex_col}/{vintage}",
            dtype="Int64",
        )
        frames.append(pd.DataFrame({
            "state_fips": df["state_fips"].to_numpy(),
            "county_fips": df["county_fips"].to_numpy(),
            "geoid": df["geoid"].to_numpy(),
            "geography": df["geography"].to_numpy(),
            "year": calendar_year.to_numpy(),
            "kind": kind.to_numpy(),
            "sex": sex_code,
            "age": age.astype(int).to_numpy(),
            "age_top_coded": (age.astype(int) == 85).to_numpy(),
            "population": pop.to_numpy(),
            "source": "census_sya",
            "vintage": vintage,
            "notes": "",
        }))
    out = pd.concat(frames, ignore_index=True)
    return enforce_agesex_long_schema(out)
