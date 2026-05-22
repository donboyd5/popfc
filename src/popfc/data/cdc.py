"""CDC WONDER Bridged-Race Population Estimates loader.

Source files in `data_raw/cdc/`:

- `Bridged-Race Population Estimates 1990-2020 _WashingtonCounty.txt`
  Single county (Washington), full year × sex × single-year-of-age, 1990-2020.
  Schema: Notes | Yearly July 1st Estimates | ...Code | Sex | Sex Code |
          Age | Age Code | Population
- `Bridged-Race Population Estimates 1990-2020_SaratogaWashington.txt`
  Two counties, collapsed over year and sex (auxiliary; not parsed here).

WONDER export quirks:

- Tab-delimited with quoted strings and CRLF line endings.
- The first column "Notes" is a flag: empty for detail rows, "Total" for
  subtotal rows aggregated over one or more grouping variables.
- The file ends with a literal `"---"` line followed by query metadata,
  citation, footnotes, and caveats — we slice the file at the first such
  delimiter.
- Age "< 1 year" → 0, "1 year" → 1, …, "85+ years" → 85 (top-coded).
- Geography is **not** carried in the per-county WONDER export file — the
  loader takes it as a parameter (defaulting to Washington County).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from popfc.data._common import (
    POP_LONG_COLUMNS,
    coerce_numeric,
    enforce_pop_long_schema,
    make_geoid,
    pad_county_fips,
    pad_state_fips,
)
from popfc.paths import CDC_DIR

DEFAULT_CDC_WASHINGTON = (
    CDC_DIR / "Bridged-Race Population Estimates 1990-2020 _WashingtonCounty.txt"
)

# Schema of the age/sex/year long-format frame this loader emits in addition to
# the POP_LONG_COLUMNS totals frame. Sex-by-age frames are needed for cohort-
# component base years.
AGESEX_LONG_COLUMNS: list[str] = [
    "state_fips",
    "county_fips",
    "geoid",
    "geography",
    "year",
    "sex",       # "F" | "M"
    "age",       # int 0..85 (85 is top-coded "85+ years")
    "age_top_coded",  # bool — True only for age==85
    "population",
    "source",
    "vintage",
    "notes",
]


def _read_wonder_tsv(path: Path) -> pd.DataFrame:
    """Read a CDC WONDER export, dropping the trailing metadata block.

    Returns a string-typed DataFrame of just the data section (header + rows),
    with `"---"` and everything after it removed.
    """
    # WONDER files mix tabs (data) and quoted-string metadata after a `---`
    # sentinel line. pd.read_csv can't reliably parse the metadata as TSV, so
    # we slice the bytes first.
    raw = path.read_bytes().decode("utf-8", errors="replace")
    # Normalize line endings.
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    # Cut at the first '---' delimiter line; if absent, keep the whole file.
    sentinel = '\n"---"'
    cut = raw.find(sentinel)
    if cut != -1:
        raw = raw[:cut]
    from io import StringIO
    df = pd.read_csv(
        StringIO(raw),
        sep="\t",
        dtype=str,
        keep_default_na=False,  # don't turn "" into NaN — we want to see it
    )
    return df


def _parse_age(code: str) -> int | None:
    """Map an Age Code value to an integer age (top-coded at 85)."""
    s = str(code).strip()
    if s == "" or s.lower() == "nan":
        return None
    # WONDER's "Age Code" column already encodes ages numerically:
    # "0", "1", ..., "84", "85" (where 85 = "85+ years").
    if s.isdigit():
        return int(s)
    # Defensive: handle string forms like "< 1 year" or "85+ years" if they
    # ever appear in the Age (not Age Code) column.
    if s.startswith("<"):
        return 0
    if "+" in s:
        return int(s.split("+", 1)[0].strip())
    head = s.split(" ", 1)[0]
    return int(head) if head.isdigit() else None


def load_cdc_bridged_race(
    path: Path | str | None = None,
    state_fips: str = "36",
    county_fips: str = "115",
    geography: str = "Washington County",
    vintage: str = "wonder_bridged_race_v2020",
) -> dict[str, pd.DataFrame]:
    """Load a CDC WONDER bridged-race single-county export.

    The WONDER per-county export does not carry county identifiers in the
    file body, so the caller passes them explicitly. Defaults are Washington
    County, NY.

    Returns
    -------
    dict with keys:
        - 'agesex': long-format DataFrame with AGESEX_LONG_COLUMNS schema
          (one row per year × sex × single-year-of-age)
        - 'totals': long-format DataFrame with POP_LONG_COLUMNS schema
          (one row per year — total population)
    """
    path = Path(path) if path is not None else DEFAULT_CDC_WASHINGTON

    raw = _read_wonder_tsv(path)
    # Normalize column names (defensive against vintage changes).
    raw.columns = [c.strip() for c in raw.columns]

    # Split detail rows (Notes == "") from subtotal rows (Notes == "Total").
    # The "Total" block contains:
    #   - per-year × sex subtotals (Sex Code in {F, M}, year code populated)
    #   - per-year all-sex subtotals (Sex Code empty, year code populated)
    #   - one grand-total across all years (year code empty) — dropped here.
    notes_col = raw["Notes"].astype(str).str.strip()
    year_code = raw["Yearly July 1st Estimates Code"].astype(str).str.strip()
    sex_code = raw["Sex Code"].astype(str).str.strip()
    detail = raw[notes_col == ""].copy()
    totals_year = raw[
        (notes_col == "Total") & (sex_code == "") & year_code.str.fullmatch(r"\d{4}")
    ].copy()

    # --- Build agesex frame ----------------------------------------------------
    year_col = "Yearly July 1st Estimates Code"
    age = detail["Age Code"].map(_parse_age).astype("Int64")
    agesex = pd.DataFrame({
        "state_fips": pad_state_fips(int(state_fips)),
        "county_fips": pad_county_fips(int(county_fips)),
        "geoid": make_geoid(int(state_fips), int(county_fips)),
        "geography": geography,
        "year": coerce_numeric(detail[year_col], label="cdc/year", dtype="Int64").astype(int),
        "sex": detail["Sex Code"].astype(str).str.strip(),
        "age": age.astype(int),
        "age_top_coded": age.astype(int) == 85,
        "population": coerce_numeric(
            detail["Population"], label=f"cdc/agesex/{vintage}", dtype="Int64"
        ),
        "source": "cdc_bridged",
        "vintage": vintage,
        "notes": "",
    })
    agesex = agesex[AGESEX_LONG_COLUMNS].reset_index(drop=True)

    # --- Build totals frame (one row per year, summed over sex × age) ---------
    # Prefer the WONDER-supplied "Total" rows where Sex Code is empty (totals
    # across both sexes); fall back to summing the detail if those are absent.
    if not totals_year.empty:
        totals = pd.DataFrame({
            "state_fips": pad_state_fips(int(state_fips)),
            "county_fips": pad_county_fips(int(county_fips)),
            "geoid": make_geoid(int(state_fips), int(county_fips)),
            "geography": geography,
            "year": coerce_numeric(
                totals_year[year_col], label="cdc/year", dtype="Int64"
            ).astype(int),
            "kind": "estimate",
            "population": coerce_numeric(
                totals_year["Population"], label=f"cdc/total/{vintage}", dtype="Int64"
            ),
            "source": "cdc_bridged",
            "vintage": vintage,
            "notes": "wonder_total",
        })
    else:
        totals = (
            agesex.groupby(["year"], as_index=False)["population"]
            .sum(min_count=1)
            .assign(
                state_fips=pad_state_fips(int(state_fips)),
                county_fips=pad_county_fips(int(county_fips)),
                geoid=make_geoid(int(state_fips), int(county_fips)),
                geography=geography,
                kind="estimate",
                source="cdc_bridged",
                vintage=vintage,
                notes="summed_from_agesex",
            )
        )

    return {
        "agesex": agesex,
        "totals": enforce_pop_long_schema(totals),
    }
