"""Generator for notebooks/04_external_data.ipynb.

Run from project root (with venv active):
    python notebooks/_build_04_external_data.py
"""
from __future__ import annotations

from pathlib import Path

import nbformat as nbf

NOTEBOOK_PATH = Path(__file__).parent / "04_external_data.ipynb"


def md(s: str) -> nbf.NotebookNode:
    return nbf.v4.new_markdown_cell(s.strip("\n"))


def code(s: str) -> nbf.NotebookNode:
    return nbf.v4.new_code_cell(s.strip("\n"))


CELLS = [
    md("""
# 04 — External Data Quick-Look

**Goal.** Audit the Phase-2 external data we'll lean on for the
cohort-component forecast and town-level work: the ACS 5-year estimates
(B01001 sex by age, B07001 mobility by age, B06001 place of birth by
age) and the NCHS life tables (national 2023 + NY state 2022 +
USALEEP tract-level 2010–2015).

Two things this notebook produces:

- A **sanity check**: do ACS county totals line up with our reconciled
  Census PEP series at the ACS 5-year midpoint?
- A **single canonical life-table parquet** at
  `data_interim/life_tables.parquet`, stacking US national, NY state,
  and USALEEP tract-level tables so downstream code has one source.
"""),
    # ---------------------------------------------------------------
    code("""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from popfc.data.acs import LATEST_ACS5_YEAR, load_acs5_group, GEO_COUNTY, GEO_COUNTY_SUBDIVISION
from popfc.data.nchs import (
    load_nchs_state_life_tables_all_sexes,
    load_nchs_us_life_tables_all_sexes,
    load_usaleep_life_expectancy,
    load_usaleep_life_table,
)
from popfc.paths import DATA_INTERIM, FULL_FIPS

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 40)

WASHINGTON = FULL_FIPS  # '36115'
COHORT = {
    WASHINGTON: "Washington",
    "36091": "Saratoga",
    "36113": "Warren",
    "36083": "Rensselaer",
    "36031": "Essex",
    "36021": "Columbia",
}
"""),
    # ---------------------------------------------------------------
    md("""
## 1. Load ACS B01001 (sex by age) — counties and Washington MCDs
"""),
    code("""
b01001_county = load_acs5_group("B01001", geography=GEO_COUNTY, state_fips="36")
b01001_mcd = load_acs5_group(
    "B01001", geography=GEO_COUNTY_SUBDIVISION, state_fips="36"
)

acs_total_var = "B01001_001E"
print(f"ACS B01001 vintage: acs5_{LATEST_ACS5_YEAR-4}_{LATEST_ACS5_YEAR}")
print(f"  county-level: {len(b01001_county):,} rows, {b01001_county['geoid'].nunique()} counties")
print(f"  MCD-level (statewide): {len(b01001_mcd):,} rows, {b01001_mcd['geoid'].nunique()} MCDs")
"""),
    # ---------------------------------------------------------------
    md("""
## 2. ACS county totals vs reconciled PEP

The ACS 5-year estimate is centered on the **midpoint year** of the
5-year window. For the 2020–2024 ACS, the midpoint is 2022. We compare
ACS county totals against reconciled PEP estimates for 2022.
"""),
    code("""
acs_totals = (
    b01001_county[b01001_county["variable"] == acs_total_var]
    [["geoid", "name", "value"]]
    .rename(columns={"value": "acs_5yr_pop", "name": "geography"})
)

reconciled = pd.read_parquet(DATA_INTERIM / "population_reconciled.parquet")
pep_midpoint = (
    reconciled[reconciled["year"] == 2022][["geoid", "population"]]
    .rename(columns={"population": "pep_2022"})
)

compare = acs_totals.merge(pep_midpoint, on="geoid", how="inner")
compare["diff"] = compare["acs_5yr_pop"].astype("Int64") - compare["pep_2022"].astype("Int64")
compare["pct_diff"] = (
    100.0 * compare["diff"].astype("Float64") / compare["pep_2022"].astype("Float64")
)

print("ACS 2020-2024 vs reconciled PEP 2022 — cohort counties:")
sub = compare[compare["geoid"].isin(COHORT)].copy()
sub["county"] = sub["geoid"].map(COHORT)
print(sub[["county", "acs_5yr_pop", "pep_2022", "diff", "pct_diff"]]
      .to_string(index=False, float_format=lambda x: f'{x:+.2f}'))
print()
print("Across all 62 NY counties:")
print(compare["pct_diff"].describe().to_string())
"""),
    # ---------------------------------------------------------------
    md("""
ACS 5-year estimates are typically within a percent or two of PEP
totals — they're a smoothed 5-year average, not a single-year estimate,
so small differences are expected and not a data-quality concern.

**Why we deliberately don't rake ACS to PEP totals.** ACS measures a
different estimand than PEP: ACS is a rolling 5-year survey average,
while PEP is a point-in-time July 1 estimate. Forcing ACS to match a
PEP level would corrupt the survey-based value with point-estimate
information and remove the very signal that makes ACS useful as an
independent series. Where ACS-derived population *levels* DO get
constrained in this pipeline: notebook 09 applies a pro-rata constraint
to scale Washington's town-level Hamilton-Perry forecasts so they sum
to the controlled county forecast totals at every forecast year — i.e.,
ACS towns get level-corrected at *projection time*, not at load time.
The parallel decision for the CDC bridged-race and Census SYA age × sex
frame is tracked in issue #6 (those sources *do* warrant controlling
because they estimate the same quantity as PEP and differ only in
level).
"""),
    # ---------------------------------------------------------------
    md("""
## 3. ACS age structure (B01001) — Washington vs cohort

B01001 reports sex × age-group (5-year and broader bins). Construct an
age pyramid for each cohort county to confirm shape is sensible.
"""),
    code("""
# Map B01001 variable names to age-band metadata.
# Variables 002 (Male) and 026 (Female) are the per-sex totals;
# the per-age cells are 003-025 (Male) and 027-049 (Female).
def b01001_age_lookup() -> pd.DataFrame:
    # Use the label column on the loaded frame — it already came from
    # the ACS variables endpoint.
    base = b01001_county.drop_duplicates("variable")[["variable", "label"]].copy()
    base["sex"] = base["label"].str.contains("Male").map({True: "M", False: "F"})
    # Anything with 'Female' overrides
    base.loc[base["label"].str.contains("Female"), "sex"] = "F"
    # Strip the prefix to get the age-band text
    base["age_band"] = (
        base["label"]
        .str.replace("Estimate!!Total:", "", regex=False)
        .str.replace("!!Male:", "", regex=False)
        .str.replace("!!Female:", "", regex=False)
        .str.strip("!:")
        .str.strip()
    )
    return base

age_lookup = b01001_age_lookup()
# Drop the aggregate cells (Total, Male:, Female:) — keep only age cells.
age_cells = age_lookup[age_lookup["age_band"].str.contains("years|Under", na=False)].copy()

def county_age_dist(geoid: str) -> pd.DataFrame:
    sub = b01001_county[b01001_county["geoid"] == geoid].merge(
        age_cells[["variable", "sex", "age_band"]], on="variable", how="inner"
    )
    return sub[["sex", "age_band", "value"]].sort_values(["sex", "age_band"])

print("Washington age structure (first 8 rows):")
print(county_age_dist(WASHINGTON).head(8).to_string(index=False))
"""),
    # ---------------------------------------------------------------
    md("""
## 4. Foreign-born share by age (B06001)
"""),
    code("""
b06001 = load_acs5_group("B06001", geography=GEO_COUNTY, state_fips="36")

# B06001_001E is total; B06001_049E is "Born outside US"... varies by table.
# Use the label column to find foreign-born indicators.
totals = b06001[b06001["variable"] == "B06001_001E"][["geoid", "value"]].rename(
    columns={"value": "total"}
)
# Foreign-born: NCHS table B06001 has "Place of birth ... Foreign born" lines.
# Look for any row whose label contains "Foreign born" without further sub-strata.
fb_label_mask = b06001["label"].str.contains("Foreign born", case=False, na=False)
# Filter to top-level totals only (avoid age-band sub-rows).
fb_top = b06001[fb_label_mask & (b06001["label"].str.count("!!") <= 3)]
fb_total_per_county = (
    fb_top.groupby("geoid")["value"].sum().rename("foreign_born").reset_index()
)

share = totals.merge(fb_total_per_county, on="geoid", how="left")
share["foreign_born_share_pct"] = (
    100.0 * share["foreign_born"].astype("Float64") / share["total"].astype("Float64")
)

print("Foreign-born share (B06001) — cohort counties:")
sub = share[share["geoid"].isin(COHORT)].copy()
sub["county"] = sub["geoid"].map(COHORT)
print(sub[["county", "total", "foreign_born", "foreign_born_share_pct"]]
      .to_string(index=False, float_format=lambda x: f'{x:.1f}'))
"""),
    # ---------------------------------------------------------------
    md("""
## 5. Geographic mobility by age (B07001)

B07001 is "Geographical Mobility in the Past Year by Age." We use it to
get a rough sense of who moves and at what rate — the cohort-component
model will refine this in Phase 3.
"""),
    code("""
b07001 = load_acs5_group("B07001", geography=GEO_COUNTY, state_fips="36")

# Variable 001 is total; 017 is "Same house" (didn't move); 033 / 049 / 065
# / 081 are sub-categories of movers. For a quick look, compute mover share
# = 1 - same_house_share.
totals = b07001[b07001["variable"] == "B07001_001E"][["geoid", "value"]].rename(
    columns={"value": "total"}
)
same_house = b07001[b07001["variable"] == "B07001_017E"][["geoid", "value"]].rename(
    columns={"value": "same_house"}
)

mob = totals.merge(same_house, on="geoid", how="inner")
mob["mover_share_pct"] = (
    100.0 * (1 - mob["same_house"].astype("Float64") / mob["total"].astype("Float64"))
)

print("Annual mover share (B07001) — cohort counties:")
sub = mob[mob["geoid"].isin(COHORT)].copy()
sub["county"] = sub["geoid"].map(COHORT)
print(sub[["county", "total", "same_house", "mover_share_pct"]]
      .to_string(index=False, float_format=lambda x: f'{x:.1f}'))
"""),
    # ---------------------------------------------------------------
    md("""
## 6. Life tables — national, state, and USALEEP

Build a single stacked life-table frame at `data_interim/life_tables.parquet`.
"""),
    code("""
us_lt = load_nchs_us_life_tables_all_sexes()
ny_lt = load_nchs_state_life_tables_all_sexes()
usaleep_b = load_usaleep_life_table(county_fips="115")
usaleep_a = load_usaleep_life_expectancy()

stacked = pd.concat([us_lt, ny_lt, usaleep_b], ignore_index=True)
print(f"Stacked life tables: {len(stacked):,} rows")
print(f"  Source counts:")
print(stacked["source"].value_counts().to_string())
print(f"\\n  e(0) summary:")
e0 = stacked[stacked["age"] == 0][["geoid", "geography", "sex", "ex", "source", "vintage"]]
print(e0.groupby(["source", "vintage", "sex"])["ex"]
      .describe()[["count", "mean", "min", "max"]].to_string())
"""),
    # ---------------------------------------------------------------
    md("""
### Washington County tract-level life expectancy (USALEEP)
"""),
    code("""
wash_tracts = usaleep_a[usaleep_a["geoid"].str.startswith("36115")].copy()
print(f"Washington tracts (USALEEP File A): {len(wash_tracts)}")
print(f"  e(0) range: {wash_tracts['ex'].min():.1f} – {wash_tracts['ex'].max():.1f}")
print(f"  e(0) median: {wash_tracts['ex'].median():.1f}")
print()
print("Per-tract e(0):")
print(wash_tracts[["geoid", "ex"]].sort_values("ex").to_string(index=False))
"""),
    # ---------------------------------------------------------------
    md("""
## 7. QA assertions
"""),
    code("""
def qa_acs(df: pd.DataFrame, name: str) -> None:
    assert df["geoid"].notna().all(), f"{name}: null geoid rows"
    assert df["variable"].notna().all(), f"{name}: null variable rows"
    # Population variables should be non-negative.
    pop_vals = df[df["variable"].str.endswith("E")]["value"].astype("Float64").dropna()
    bad_neg = int((pop_vals < 0).sum())
    assert bad_neg == 0, f"{name}: {bad_neg} negative value rows"
    print(f"OK — {name}")

qa_acs(b01001_county, "B01001 county")
qa_acs(b01001_mcd, "B01001 MCD")
qa_acs(b07001, "B07001 county")
qa_acs(b06001, "B06001 county")

# Life-table monotonicity
for src, lbl in [(us_lt, "US NVSR"), (ny_lt, "NY NVSR")]:
    for sex in ("All", "M", "F"):
        lx = src[src["sex"] == sex].sort_values("age")["lx"].astype(float).to_numpy()
        assert (lx[1:] - lx[:-1] <= 0).all(), f"{lbl} {sex}: lx not monotone"
print("OK — all life tables: lx monotone non-increasing")
"""),
    # ---------------------------------------------------------------
    md("""
## 8. Save interim parquet
"""),
    code("""
DATA_INTERIM.mkdir(parents=True, exist_ok=True)
lt_path = DATA_INTERIM / "life_tables.parquet"
stacked.to_parquet(lt_path, index=False)
print(f"wrote {lt_path}  ({len(stacked):,} rows)")
"""),
    # ---------------------------------------------------------------
    md("""
## Next steps

- **Notebook 05 — fertility prep** (Phase 3): age-specific fertility
  rates from NYSDOH births (deferred to API pull, issue #2) or from the
  Census PEP rate columns (already in `county_components.parquet`).
- **Notebook 06 — mortality prep** (Phase 3): turn the NY state 2022
  life table into survival rates `Sx = Lx(t+1) / Lx(t)`, with optional
  USALEEP tract-level adjustment for Washington's small-area detail.
- **Cohort-component engine** (Phase 3): `src/popfc/models/cohort_component.py`.
"""),
]


def main() -> None:
    nb = nbf.v4.new_notebook()
    nb["cells"] = CELLS
    nb["metadata"] = {
        "kernelspec": {
            "display_name": "Python 3 (popfc)",
            "language": "python",
            "name": "popfc",
        },
        "language_info": {"name": "python"},
    }
    nbf.write(nb, NOTEBOOK_PATH)
    print(f"wrote {NOTEBOOK_PATH}")


if __name__ == "__main__":
    main()
