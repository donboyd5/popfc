"""Cornell Program on Applied Demographics (PAD) projection loader.

Source files in `data_raw/cornell/`:

- `padprojections115.xls` — Cornell PAD projection for Washington County
  (county code 115), wide-format age × sex × year. Despite the .xls
  extension this is actually an .xlsx (Microsoft Excel 2007+) file.
- `washington-county.csv` — small CSV with the same Total series; redundant
  with the XLS once it's parsed.
- `Washington.pdf` — methodology document (not parsed here).

The XLS schema:

    COUNTY | COUNTY_DESCR | SEXCODE | SEX_DESCR | AGEGRPCODE | AGEGRP_DESCR
          | RACECODE | RACE_DESCR | YR_2015 | YR_2016 | ... | YR_2040

`AGEGRPCODE` is a single-year-of-age (1..84), with sentinel codes:

- -999 = Total (sum over all ages)
- 0    = Newborn (age 0)
- 85   = "85+" (top-coded)
- 999  = Median age (statistic, not a population)

`SEX_DESCR` ∈ {All, Male, Female}; `RACE_DESCR` is always "All" in this file.

The vintage of the projection is not encoded in the filename. We default the
`vintage` tag to "pad_h2015_2040" (the projection horizon visible in the
column headers); callers can override.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from popfc.data._common import (
    coerce_numeric,
    enforce_pop_long_schema,
    make_geoid,
    pad_county_fips,
    pad_state_fips,
)
from popfc.data.cdc import AGESEX_LONG_COLUMNS
from popfc.paths import CORNELL_DIR

DEFAULT_CORNELL_XLS = CORNELL_DIR / "padprojections115.xls"

_SEX_CODE_MAP = {"Male": "M", "Female": "F"}


def _melt_year_cols(df: pd.DataFrame, id_cols: list[str]) -> pd.DataFrame:
    """Melt YR_2015..YR_2040 wide columns to long, with `year` int and `value`."""
    year_cols = [c for c in df.columns if isinstance(c, str) and c.startswith("YR_")]
    long = df[id_cols + year_cols].melt(
        id_vars=id_cols, var_name="_col", value_name="value"
    )
    long["year"] = long["_col"].str.slice(3).astype(int)
    return long.drop(columns="_col")


def load_cornell_pad(
    path: Path | str | None = None,
    state_fips: str = "36",
    vintage: str = "pad_h2015_2040",
) -> dict[str, pd.DataFrame]:
    """Load the Cornell PAD projection workbook.

    Parameters
    ----------
    path
        Override the default workbook location.
    state_fips
        State FIPS for the county codes in the file. The PAD workbook
        carries 3-digit county FIPS only (no state); we default to "36".
    vintage
        Tag describing this projection vintage. The workbook does not
        encode a release date; the default reflects the projection
        horizon visible in the column headers.

    Returns
    -------
    dict with keys:
        - 'totals': long-format POP_LONG_COLUMNS, one row per
          (geoid, year), with `kind='projection'`.
        - 'by_sex': long-format with an extra `sex` column ('M', 'F',
          'All'), `kind='projection'`. Useful for sex-disaggregated
          benchmarking.
        - 'agesex': single-year-of-age × sex × year detail conforming
          to AGESEX_LONG_COLUMNS. Median-age rows and sex='All' rows
          are excluded (the consumer wants per-sex single-age cells).
    """
    path = Path(path) if path is not None else DEFAULT_CORNELL_XLS

    with warnings.catch_warnings():
        # openpyxl complains about missing default styles in old workbooks
        # — harmless, suppress to keep loader output clean.
        warnings.filterwarnings(
            "ignore",
            message="Workbook contains no default style",
            category=UserWarning,
        )
        raw = pd.read_excel(path, sheet_name="Projections", dtype={"COUNTY": str})

    id_cols = ["COUNTY", "COUNTY_DESCR", "SEXCODE", "SEX_DESCR",
               "AGEGRPCODE", "AGEGRP_DESCR", "RACECODE", "RACE_DESCR"]
    long = _melt_year_cols(raw, id_cols)

    # County FIPS arrives as either str or int depending on the cell type; the
    # dtype hint above keeps it as str for the COUNTY column at least, so
    # pad it to 3 digits.
    county_fips = long["COUNTY"].astype(str).map(lambda v: pad_county_fips(int(float(v))))
    long["state_fips"] = pad_state_fips(int(state_fips))
    long["county_fips"] = county_fips
    long["geoid"] = long["state_fips"] + long["county_fips"]
    long["geography"] = long["COUNTY_DESCR"].astype(str) + " County"
    long["population_or_median"] = coerce_numeric(
        long["value"].astype(str), label=f"cornell_pad/{vintage}", dtype="Int64"
    )

    # Split out the three views.
    is_total_age = long["AGEGRPCODE"] == -999
    is_median = long["AGEGRPCODE"] == 999
    is_single_year_age = (
        (long["AGEGRPCODE"] >= 0) & (long["AGEGRPCODE"] <= 85)
    )

    # --- by_sex (totals across all ages, per sex) ---------------------------
    by_sex_rows = long[is_total_age].copy()
    by_sex = pd.DataFrame({
        "state_fips": by_sex_rows["state_fips"],
        "county_fips": by_sex_rows["county_fips"],
        "geoid": by_sex_rows["geoid"],
        "geography": by_sex_rows["geography"],
        "year": by_sex_rows["year"].astype(int),
        "kind": "projection",
        "sex": by_sex_rows["SEX_DESCR"].map(lambda s: _SEX_CODE_MAP.get(s, s)),
        "population": by_sex_rows["population_or_median"],
        "source": "cornell_pad",
        "vintage": vintage,
        "notes": "",
    }).reset_index(drop=True)

    # --- totals (collapse to SEX='All') -------------------------------------
    totals_rows = by_sex[by_sex["sex"] == "All"].drop(columns="sex").copy()
    totals = enforce_pop_long_schema(totals_rows)

    # --- agesex (single-year-of-age × sex, exclude SEX='All' & Median) ------
    agesex_rows = long[is_single_year_age & (long["SEX_DESCR"] != "All")].copy()
    age = agesex_rows["AGEGRPCODE"].astype(int)
    agesex = pd.DataFrame({
        "state_fips": agesex_rows["state_fips"],
        "county_fips": agesex_rows["county_fips"],
        "geoid": agesex_rows["geoid"],
        "geography": agesex_rows["geography"],
        "year": agesex_rows["year"].astype(int),
        "sex": agesex_rows["SEX_DESCR"].map(lambda s: _SEX_CODE_MAP.get(s, s)),
        "age": age,
        "age_top_coded": age == 85,
        "population": agesex_rows["population_or_median"],
        "source": "cornell_pad",
        "vintage": vintage,
        "notes": "",
    }).reset_index(drop=True)[AGESEX_LONG_COLUMNS]

    _ = is_median  # explicitly dropped; reference quiets linters

    return {"totals": totals, "by_sex": by_sex, "agesex": agesex}
