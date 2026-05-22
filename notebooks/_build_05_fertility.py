"""Generator for notebooks/05_fertility.ipynb."""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf

NOTEBOOK_PATH = Path(__file__).parent / "05_fertility.ipynb"


def md(s: str) -> nbf.NotebookNode:
    return nbf.v4.new_markdown_cell(s.strip("\n"))


def code(s: str) -> nbf.NotebookNode:
    return nbf.v4.new_code_cell(s.strip("\n"))


CELLS = [
    md("""
# 05 — Fertility (Phase 3 prep)

**Goal.** Produce age-specific fertility rates (ASFR) per county-year for
all 62 NY counties (2021-2023) plus Washington 2011-2019 — i.e., every
year for which we have both a fully-observed birth count and a single-
year-of-age female-population frame.

## Method (small-area "scaled national schedule")

1. **Reference schedule**: NCHS 2023 US ASFR by 5-year age band
   (NVSR 74-1 Table 2), expanded to a single-year-of-age step
   function. Implemented in `popfc.models.fertility`.
2. For each county-year, compute a single multiplicative scaling factor
   `k` so that the scaled schedule × the county's female-pop-by-age sums
   to the observed total births. This pins the **level** to local data
   while borrowing the **age pattern** from the national reference.
3. The resulting county TFR is just `sum(scaled_ASFR) / 1000`. By
   construction, county TFR = (national 2023 TFR) × k.

This is standard small-area demographic practice: single-year county ASFRs
are too noisy to estimate directly, but the national age pattern is stable
and the scaling target (total births) is observed cleanly.

## Annual births: rate-based, not raw count

Census PEP publishes both `births` (count) and `rate_births` (births per
1,000 mid-year average population, annualized). For decennial-seam years
(2010, 2020) the raw count is partial-year (Apr-Jul only — ~3 months),
which would make ASFRs implausibly low for those years.

We instead compute annual births as
`rate_births × mid_year_pop / 1000`, which Census annualizes correctly
for every year (including 2020). Year 2010 has no published rate so
that year is dropped — Washington loses one historical observation.

## Output

`data_interim/asfr.parquet` — one row per (geoid, year, age) for ages
10-49, with the scaled ASFR plus provenance (scaling_factor, implied_tfr,
observed_births).
"""),
    # ---------------------------------------------------------------
    code("""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from popfc.models.fertility import (
    ASFR_LONG_COLUMNS,
    NCHS_ASFR_2023_TFR,
    REPRO_AGE_MAX,
    REPRO_AGE_MIN,
    SEX_RATIO_AT_BIRTH,
    SHARE_MALE_AT_BIRTH,
    build_county_year_asfr,
    reference_asfr_schedule,
    reference_tfr,
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
## 1. Reference ASFR schedule (NCHS 2023 US, all races)
"""),
    code("""
ref = reference_asfr_schedule()
print(f"reference ages: {ref['age'].min()}-{ref['age'].max()}  ({len(ref)} ages)")
print(f"implied TFR:    {reference_tfr(ref):.4f}  (NCHS published: {NCHS_ASFR_2023_TFR})")
print(f"share male at birth: {SHARE_MALE_AT_BIRTH:.5f}  (SRB = {SEX_RATIO_AT_BIRTH:g})")
print()
# Plot the single-year ASFR step function.
fig, ax = plt.subplots(figsize=(9, 4))
ax.step(ref["age"], ref["asfr_per_1000"], where="mid", linewidth=1.6)
ax.set_xlabel("mother's age")
ax.set_ylabel("ASFR (births per 1,000 women per year)")
ax.set_title("Reference ASFR — NCHS NVSR 74-1, 2023, US all races/origins")
ax.grid(True, alpha=0.3)
fig.tight_layout()
plt.show()
"""),
    # ---------------------------------------------------------------
    md("""
## 2. Build annual births from rate_births × population

PEP publishes both counts and rates. We use the rate to annualize the
decennial-year values (2020 raw count is a 3-month partial; the rate is
annualized). Years without a published rate (e.g., 2010 in the v2020
vintage) are dropped.
"""),
    code("""
comp = pd.read_parquet(DATA_INTERIM / "county_components.parquet")
pop = pd.read_parquet(DATA_INTERIM / "population_reconciled.parquet")

# Pivot components to wide so rate_births and births sit side by side.
comp_wide = comp.pivot_table(
    index=["geoid", "year"],
    columns="measure",
    values="value",
    aggfunc="first",
).reset_index()

# Mid-year population (use reconciled — annual, no gaps).
pop_year = pop[["geoid", "year", "population"]].copy()
# Mid-year average ≈ (Pop(t-1) + Pop(t)) / 2.
pop_year_sorted = pop_year.sort_values(["geoid", "year"]).copy()
pop_year_sorted["pop_prev"] = pop_year_sorted.groupby("geoid")["population"].shift(1)
pop_year_sorted["mid_year_pop"] = (
    pop_year_sorted["population"].astype("Float64")
    + pop_year_sorted["pop_prev"].astype("Float64")
) / 2

births_annual = comp_wide.merge(
    pop_year_sorted[["geoid", "year", "mid_year_pop"]], on=["geoid", "year"], how="inner"
)
births_annual["annual_births"] = (
    births_annual["rate_births"].astype("Float64")
    * births_annual["mid_year_pop"].astype("Float64")
    / 1000.0
)
births_annual = births_annual[births_annual["annual_births"].notna()].copy()

print(f"births_annual rows after dropping years w/o rate_births: {len(births_annual):,}")
print(f"  year range: {births_annual['year'].min()}-{births_annual['year'].max()}")
print()
# Washington spot-check.
w = births_annual[births_annual["geoid"] == WASHINGTON][["year", "annual_births", "births", "rate_births"]]
w["raw_vs_ann"] = (w["births"].astype("Float64") / w["annual_births"].astype("Float64"))
print("Washington — annual births (from rate × mid-year pop) vs raw count:")
print(w.to_string(index=False, float_format=lambda x: f'{x:.3f}'))
"""),
    # ---------------------------------------------------------------
    md("""
Note how `births / annual_births` is ~0.26 for 2020 (about 3 months of
12) — confirming the raw count is a partial-year value. Using the
rate-based annual births fixes this without losing the year.
"""),
    # ---------------------------------------------------------------
    md("""
## 3. Female population by single year of age

From `data_interim/county_agesex_1990_2023.parquet`. Two sources stitched
together:

- **CDC bridged-race** (Washington only, 1990-2020, single-year ages)
- **Census SYA** (all 62 NY counties, 2020-2023, single-year ages)

We use Census SYA for all year ≥ 2020 (consistent statewide), and CDC
bridged for Washington's pre-2020 history.
"""),
    code("""
agesex = pd.read_parquet(DATA_INTERIM / "county_agesex_1990_2023.parquet")
# Take Census SYA `kind=='estimate'` for 2020+ (annual July-1 estimates),
# and CDC bridged for pre-2020 Washington.
sya_est = agesex[(agesex["source"] == "census_sya") & (agesex["kind"] == "estimate")]
cdc_pre2020 = agesex[(agesex["source"] == "cdc_bridged") & (agesex["year"] < 2020)]
female_pop = pd.concat([sya_est, cdc_pre2020], ignore_index=True)
female_pop = female_pop[female_pop["sex"] == "F"].copy()

print("female_pop rows:", len(female_pop))
print(female_pop.groupby(["source"])["year"].agg(["min", "max", "nunique"]).to_string())
"""),
    # ---------------------------------------------------------------
    md("""
## 4. Build scaled ASFR per (county, year)
"""),
    code("""
births_for_builder = births_annual[["geoid", "year", "annual_births"]].rename(
    columns={"annual_births": "value"}
)
asfr = build_county_year_asfr(female_pop, births_for_builder)
print(f"asfr rows: {len(asfr):,}  ({asfr['geoid'].nunique()} counties × "
      f"{asfr['year'].nunique()} years × {asfr['age'].nunique()} ages)")
print(f"year coverage: {asfr['year'].min()}-{asfr['year'].max()}")
print()
# Coverage detail by source.
cov = asfr.groupby("year")["geoid"].nunique().rename("n_counties")
print("counties per year:")
print(cov.to_string())
"""),
    # ---------------------------------------------------------------
    md("""
## 5. Diagnostic — Washington historical TFR
"""),
    code("""
wash_tfr = (
    asfr[asfr["geoid"] == WASHINGTON]
    .groupby("year").agg(
        tfr=("implied_tfr", "first"),
        k=("scaling_factor", "first"),
        births=("observed_births", "first"),
    ).reset_index()
)
print("Washington TFR by year (scaled from 2023 US ALL):")
print(wash_tfr.to_string(index=False, float_format=lambda x: f'{x:.4f}'))

fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(wash_tfr["year"], wash_tfr["tfr"], marker="o", linewidth=1.4)
ax.axhline(NCHS_ASFR_2023_TFR, color="grey", linestyle="--", label=f"US 2023 TFR = {NCHS_ASFR_2023_TFR}")
ax.axhline(2.1, color="C3", linestyle=":", alpha=0.6, label="replacement (2.1)")
ax.set_xlabel("year")
ax.set_ylabel("TFR (implied from scaling)")
ax.set_title(f"Washington County TFR — {wash_tfr['year'].min()} to {wash_tfr['year'].max()}")
ax.grid(True, alpha=0.3)
ax.legend()
fig.tight_layout()
plt.show()
"""),
    # ---------------------------------------------------------------
    md("""
## 6. Cohort comparison — 2023 TFR distribution across NY counties
"""),
    code("""
y_latest = int(asfr["year"].max())
tfr_by_county = (
    asfr[asfr["year"] == y_latest]
    .groupby("geoid").agg(
        geography=("geography", "first"),
        tfr=("implied_tfr", "first"),
        births=("observed_births", "first"),
    ).reset_index()
)

print(f"{y_latest} TFR distribution (NY counties):")
print(tfr_by_county["tfr"].describe().to_string())
print()
print(f"Cohort counties ({y_latest}):")
sub = tfr_by_county[tfr_by_county["geoid"].isin(COHORT)].copy()
sub["county"] = sub["geoid"].map(COHORT)
print(sub[["county", "tfr", "births"]]
      .sort_values("tfr").to_string(index=False, float_format=lambda x: f'{x:.4f}'))
"""),
    # ---------------------------------------------------------------
    md("""
## 7. QA assertions
"""),
    code("""
def qa(asfr: pd.DataFrame) -> None:
    assert list(asfr.columns) == ASFR_LONG_COLUMNS
    # Repro age range.
    assert asfr["age"].min() >= REPRO_AGE_MIN
    assert asfr["age"].max() <= REPRO_AGE_MAX
    # ASFR non-negative.
    assert (asfr["asfr_per_1000"].astype("Float64") >= 0).all()
    # Sex is always female (ASFR are defined for women).
    assert (asfr["sex"] == "F").all()
    # implied_tfr same as sum(asfr_per_1000)/1000 per slice.
    grouped = asfr.groupby(["geoid", "year"]).agg(
        recomputed=("asfr_per_1000", lambda s: float(s.sum()) / 1000.0),
        stored=("implied_tfr", "first"),
    )
    diff = (grouped["recomputed"] - grouped["stored"]).abs().max()
    assert diff < 1e-9, f"TFR consistency: max diff {diff}"
    print("OK — all QA checks pass.")

qa(asfr)
"""),
    # ---------------------------------------------------------------
    md("""
## 8. Save asfr.parquet
"""),
    code("""
out_path = DATA_INTERIM / "asfr.parquet"
asfr.to_parquet(out_path, index=False)
print(f"wrote {out_path}  ({len(asfr):,} rows)")
"""),
    # ---------------------------------------------------------------
    md("""
## Next steps

- **Notebook 07 — migration prep**: net migration rates by age/sex.
- **`src/popfc/models/cohort_component.py`** — the projection engine.
- **Optional refinement**: when NYSDOH vital-stats API pulls land
  (issue #2), replace the national reference schedule with NYSDOH
  county-specific births-by-mother's-age so the county age pattern
  reflects local data, not just the level.
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
