"""Generator for notebooks/09_town_forecast.ipynb."""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf

NOTEBOOK_PATH = Path(__file__).parent / "09_town_forecast.ipynb"


def md(s: str) -> nbf.NotebookNode:
    return nbf.v4.new_markdown_cell(s.strip("\n"))


def code(s: str) -> nbf.NotebookNode:
    return nbf.v4.new_code_cell(s.strip("\n"))


CELLS = [
    md("""
# 09 — Town Forecast (Phase 4 deliverable)

**Goal.** Project each of Washington County's 17 towns (MCDs) forward
to 2047 via Hamilton-Perry, then constrain town totals to the county
forecast from Notebook 08 — for each of the three scenarios (low,
baseline, high).

## Method: Hamilton-Perry + pro-rata constraint

1. **Cohort change ratios** (CCRs) computed per town from two ACS
   5-year vintages 5 years apart: 2015-2019 (midpoint ~2017) and
   2020-2024 (midpoint ~2022).
2. **Child-to-woman ratios** (CWRs) at the 2022 midpoint, held
   constant.
3. **Project** each town in 5-year steps: 2022 → 2027 → 2032 → ... →
   2047.
4. **Pro-rata constraint**: at each forecast year, sum the
   unconstrained town projections and scale each by
   `(county forecast total) / (sum of town projections)` so the
   towns add up to the parent county under each scenario.

The constraint is applied uniformly across all age × sex cells in each
town — it preserves the within-town age structure (which is the
informative part of Hamilton-Perry) and only adjusts the level.

## Why Hamilton-Perry vs full cohort-component?

For small areas (Washington's smallest town is Putnam at 540 people),
single-year age-specific fertility/mortality/migration rates from
county-level data are extremely noisy when applied. Hamilton-Perry
sidesteps that by using empirical cohort change ratios that bake in
everything — births, deaths, AND migration. The constraint to the
county forecast ensures consistency.

Move to a town-level cohort-component model later if specific
analytical questions (e.g., "decompose Putnam's growth into
natural-increase vs migration") require the components separately.

## Output

`data_interim/town_forecasts.parquet` — one row per
(geoid, year, sex, age_band, scenario). Years are the town projection
steps (2022, 2027, 2032, 2037, 2042, 2047). Pre- and post-constraint
populations are both included via a `constraint_applied` boolean column.
"""),
    # ---------------------------------------------------------------
    code("""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from popfc.constrain.prorata import apply_prorata_constraint
from popfc.data.acs import GEO_COUNTY_SUBDIVISION, load_acs5_group
from popfc.models.hamilton_perry import (
    HP_PROJECTION_COLUMNS,
    aggregate_b01001_to_5yr_bands,
    child_woman_ratios,
    cohort_change_ratios,
    project_one_county_hp,
)
from popfc.paths import DATA_INTERIM, FULL_FIPS

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 40)

WASHINGTON = FULL_FIPS
BASE_YEAR_TOWN = 2022     # ACS 2020-2024 midpoint
END_YEAR_TOWN = 2047
PRIOR_VINTAGE_YEAR = 2019  # ACS 2015-2019 → midpoint 2017 (5 yrs before 2022)
LATEST_VINTAGE_YEAR = 2024 # ACS 2020-2024 → midpoint 2022

SCENARIOS = ("baseline", "low", "high")
"""),
    # ---------------------------------------------------------------
    md("""
## 1. Load two ACS vintages for Washington MCDs
"""),
    code("""
acs_prior = load_acs5_group(
    "B01001", year=PRIOR_VINTAGE_YEAR,
    geography=GEO_COUNTY_SUBDIVISION,
    state_fips="36", county_fips="115",
)
acs_latest = load_acs5_group(
    "B01001", year=LATEST_VINTAGE_YEAR,
    geography=GEO_COUNTY_SUBDIVISION,
    state_fips="36", county_fips="115",
)

pop_prior  = aggregate_b01001_to_5yr_bands(acs_prior)
pop_latest = aggregate_b01001_to_5yr_bands(acs_latest)

print(f"ACS {PRIOR_VINTAGE_YEAR-4}-{PRIOR_VINTAGE_YEAR}: {len(pop_prior):,} rows  "
      f"(midpoint ~{PRIOR_VINTAGE_YEAR-2})")
print(f"ACS {LATEST_VINTAGE_YEAR-4}-{LATEST_VINTAGE_YEAR}: {len(pop_latest):,} rows "
      f"(midpoint ~{LATEST_VINTAGE_YEAR-2})")
print(f"  17 MCDs × 2 sexes × 18 bands = {17*2*18} expected for each")
print()
# Sanity: per-town totals at the two time points.
totals_compare = (
    pop_latest.groupby("geoid")["population"].sum().rename(f"y{LATEST_VINTAGE_YEAR-2}")
    .to_frame()
    .join(pop_prior.groupby("geoid")["population"].sum().rename(f"y{PRIOR_VINTAGE_YEAR-2}"))
)
totals_compare["pct_change"] = 100 * (
    totals_compare[f"y{LATEST_VINTAGE_YEAR-2}"] / totals_compare[f"y{PRIOR_VINTAGE_YEAR-2}"] - 1
)
# Attach town names.
names = pop_latest[["geoid", "geography"]].drop_duplicates().set_index("geoid")
totals_compare = totals_compare.join(names)
totals_compare["town"] = totals_compare["geography"].str.split(",").str[0]
print("Town population change, ACS 2017 → ACS 2022 (midpoints):")
print(totals_compare[["town", f"y{PRIOR_VINTAGE_YEAR-2}", f"y{LATEST_VINTAGE_YEAR-2}", "pct_change"]]
      .sort_values("pct_change")
      .to_string(index=False, float_format=lambda x: f"{x:.1f}"))
"""),
    # ---------------------------------------------------------------
    md("""
## 2. Compute CCRs and CWRs
"""),
    code("""
ccr = cohort_change_ratios(pop_prior, pop_latest)
cwr = child_woman_ratios(pop_latest)
print(f"CCR rows: {len(ccr):,}  (~17 towns × 2 sex × 17 dest bands = {17*2*17})")
print(f"CWR rows: {len(cwr):,}  (17 towns × 2 sex = {17*2})")
print()
print("CCR summary (closed bands only, all towns/sex/age):")
print(ccr[ccr["age_band_start"] != 85]["ccr"].describe().to_string())
print()
print("CWR summary:")
print(cwr["cwr"].describe().to_string())
"""),
    # ---------------------------------------------------------------
    md("""
## 3. Project each town to 2047 (unconstrained)
"""),
    code("""
proj_list = []
for geoid, name in names["geography"].items():
    town_pop = pop_latest[pop_latest["geoid"] == geoid]
    if town_pop.empty:
        continue
    try:
        sub = project_one_county_hp(
            town_pop, ccr, cwr,
            base_year=BASE_YEAR_TOWN, end_year=END_YEAR_TOWN,
            geoid=geoid, geography=name.split(",")[0],
            scenario="unconstrained",
            projection_vintage="hp_v1_acs2017_to_2022",
        )
        proj_list.append(sub)
    except ValueError as e:
        print(f"WARN: {name}: {e}")

unconstrained = pd.concat(proj_list, ignore_index=True)
print(f"unconstrained rows: {len(unconstrained):,}")
print(f"  towns: {unconstrained['geoid'].nunique()}; years: {sorted(unconstrained['year'].unique())}")
"""),
    # ---------------------------------------------------------------
    md("""
### Unconstrained town total trajectories
"""),
    code("""
unc_totals = (
    unconstrained.groupby(["geoid", "geography", "year"])["population"].sum().reset_index()
)
# County sum check.
county_sum_by_year = unc_totals.groupby("year")["population"].sum()
print("Sum of unconstrained town projections, by year:")
print(county_sum_by_year.astype(int).to_string())
"""),
    # ---------------------------------------------------------------
    md("""
## 4. Apply pro-rata constraint per scenario

The county forecast from Notebook 08 covers 2023-2050 annually. Match
to the town projection years (2027, 2032, 2037, 2042, 2047). For the
base year 2022, the ACS town totals already equal the ACS county total
by construction — no constraint applied.
"""),
    code("""
county_forecasts = pd.read_parquet(DATA_INTERIM / "county_forecasts.parquet")
wash_county = (
    county_forecasts[county_forecasts["geoid"] == WASHINGTON]
    .groupby(["year", "scenario"])["population"].sum().reset_index()
)
constraint_years = [y for y in unconstrained["year"].unique() if y > BASE_YEAR_TOWN]

constrained_frames: list[pd.DataFrame] = []
for scen in SCENARIOS:
    # County target at each constraint year for this scenario.
    target = wash_county[wash_county["scenario"] == scen][["year", "population"]].copy()
    target = target[target["year"].isin(constraint_years)]
    # Town projection at constraint years (drop the base year — no constraint).
    sub = unconstrained[unconstrained["year"].isin(constraint_years)].copy()
    sub_scaled = apply_prorata_constraint(sub, target)
    sub_scaled["scenario"] = scen
    sub_scaled["constraint_applied"] = True
    constrained_frames.append(sub_scaled)

# Base year (2022) — leave as ACS, but emit once per scenario for cleanliness.
base = unconstrained[unconstrained["year"] == BASE_YEAR_TOWN].copy()
base["constraint_factor"] = 1.0
base["constraint_applied"] = False
for scen in SCENARIOS:
    b = base.copy()
    b["scenario"] = scen
    constrained_frames.append(b)

town_forecasts = pd.concat(constrained_frames, ignore_index=True)
print(f"town_forecasts rows: {len(town_forecasts):,}")
print(f"  scenarios: {sorted(town_forecasts['scenario'].unique())}")
print(f"  years: {sorted(town_forecasts['year'].unique())}")
"""),
    # ---------------------------------------------------------------
    md("""
### Verify constraint identity
"""),
    code("""
chk = (
    town_forecasts.groupby(["year", "scenario"])["population"]
    .sum().reset_index()
    .pivot_table(index="year", columns="scenario", values="population")
)
print("Sum of constrained town pops (by year × scenario):")
print(chk.round(0).astype(int).to_string())
print()
# Compare to county forecast totals.
county_pv = wash_county.pivot_table(index="year", columns="scenario", values="population")
print("County forecast totals (Notebook 08) at the same years:")
print(county_pv.loc[constraint_years].round(0).astype(int).to_string())
"""),
    # ---------------------------------------------------------------
    md("""
## 5. Town trajectories — baseline scenario
"""),
    code("""
fig, ax = plt.subplots(figsize=(12, 6))
baseline = town_forecasts[town_forecasts["scenario"] == "baseline"]
totals_baseline = baseline.groupby(["geoid", "geography", "year"])["population"].sum().reset_index()
for geoid, g in totals_baseline.groupby("geoid"):
    g = g.sort_values("year")
    ax.plot(g["year"], g["population"], marker="o", markersize=3, linewidth=1.2,
            label=g["geography"].iloc[0])
ax.set_xlabel("year")
ax.set_ylabel("population")
ax.set_title("Washington County towns — Hamilton-Perry projection (baseline scenario)")
ax.grid(True, alpha=0.3)
ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=8)
fig.tight_layout()
plt.show()
"""),
    # ---------------------------------------------------------------
    md("""
## 6. Per-town summary: 2022 → 2047 baseline
"""),
    code("""
y_base = BASE_YEAR_TOWN
y_end  = END_YEAR_TOWN
summary = totals_baseline.pivot_table(index=["geoid", "geography"], columns="year", values="population")
summary["pct_change"] = 100 * (summary[y_end] / summary[y_base] - 1)
summary = summary[[y_base, y_end, "pct_change"]].sort_values("pct_change")
print(f"Town summary {y_base} → {y_end} (baseline scenario):")
print(summary.to_string(float_format=lambda x: f'{x:.1f}'))
"""),
    # ---------------------------------------------------------------
    md("""
## 7. Scenario spread — top 5 and bottom 5 towns
"""),
    code("""
scen_2047 = (
    town_forecasts[town_forecasts["year"] == END_YEAR_TOWN]
    .groupby(["geoid", "geography", "scenario"])["population"].sum().reset_index()
)
spread = scen_2047.pivot_table(index=["geoid", "geography"], columns="scenario", values="population")
spread["range_pct"] = 100 * (spread["high"] - spread["low"]) / spread["baseline"]
print(f"{END_YEAR_TOWN} populations by scenario, per town:")
print(spread.sort_values("baseline", ascending=False)
      .round(0).astype(int, errors="ignore")
      .to_string(float_format=lambda x: f'{x:.0f}'))
"""),
    # ---------------------------------------------------------------
    md("""
## 8. QA assertions
"""),
    code("""
def qa(town_forecasts: pd.DataFrame, county_targets: pd.DataFrame) -> None:
    # All 17 towns × 3 scenarios × 6 years × 2 sexes × 18 bands = 11,016
    assert len(town_forecasts) == 17 * 3 * 6 * 2 * 18, \
        f"unexpected size {len(town_forecasts)}"
    # Towns covered.
    assert town_forecasts["geoid"].nunique() == 17
    # Constrained-year sums match county forecast targets (within float
    # tolerance) — but constrained_year rows are those with
    # constraint_applied=True.
    for scen in SCENARIOS:
        for year in constraint_years:
            town_sum = float(
                town_forecasts[
                    (town_forecasts["scenario"] == scen)
                    & (town_forecasts["year"] == year)
                    & (town_forecasts["constraint_applied"])
                ]["population"].sum()
            )
            target = float(
                county_targets[
                    (county_targets["scenario"] == scen)
                    & (county_targets["year"] == year)
                ]["population"].iloc[0]
            )
            assert abs(town_sum - target) / target < 1e-9, \
                f"constraint violated for {scen}/{year}: {town_sum} vs {target}"
    print("OK — all QA checks pass.")

qa(town_forecasts, wash_county)
"""),
    # ---------------------------------------------------------------
    md("""
## 9. Save
"""),
    code("""
out_path = DATA_INTERIM / "town_forecasts.parquet"
town_forecasts.to_parquet(out_path, index=False)
print(f"wrote {out_path}  ({len(town_forecasts):,} rows)")
"""),
    # ---------------------------------------------------------------
    md("""
## Notes and caveats

- **5-year cadence** is built into Hamilton-Perry — town projections only
  exist at 2022, 2027, 2032, ... The county forecast (annual) is sampled
  at those years for the constraint. Annual town projections would
  require either interpolation post-hoc or a different method.
- **Constant CCRs** assume the 2017→2022 cohort dynamics persist through
  2047. For some towns this carries pandemic-era shocks forward. Could
  use a longer baseline (multiple ACS vintages) if Phase 2 history is
  needed.
- **Pro-rata only adjusts level**, not age × sex structure. If a town's
  pyramid is unusual relative to the county and the county forecast
  expects different aging dynamics, the town's structure won't shift
  to match. IPF would handle that; not built in v1.
- **CWR is held constant** — same fertility schedule throughout the
  projection horizon. Scenario knobs from Notebook 08 do not propagate
  to town-level CWR; only via the pro-rata level adjustment.

## Next steps

- **Phase 5** — reporting: charts, tables, data dictionary, exports.
- **Refinement** (later): IPF to match county age × sex marginals as
  well as totals; town-level cohort-component for towns where local
  components data exists (e.g., NYSDOH births by sub-county place).
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
