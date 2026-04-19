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
    enforce_components_long_schema,
    enforce_pop_long_schema,
    read_csv_strings,
)
from popfc.paths import CENSUS_DIR

# Default paths — override via function args when loading a newer vintage.
DEFAULT_PEP_2020_PLUS = CENSUS_DIR / "2020-plus" / "co-est2024-alldata.csv"
DEFAULT_PEP_2010_2020 = CENSUS_DIR / "2010-2020" / "co-est2020-alldata.csv"
DEFAULT_PEP_2000_2010 = CENSUS_DIR / "2000-2010" / "co-est00int-tot.csv"

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

    # Years covered: 2020-2024. Columns include ESTIMATESBASE2020 and POPESTIMATE2020..2024.
    year_cols = {y: f"POPESTIMATE{y}" for y in range(2020, 2025)}
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
