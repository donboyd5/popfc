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

# CCR cap — per-step clipping bounds on the cohort change ratio.
# - PRODUCTION (0.85, 1.20): allows ±15-20% change per 5-year step, compounding
#   to roughly (0.44, 2.49) over the 5-step horizon. Conservative enough that
#   small-sample ACS noise can't drive runaway projections, wide enough to
#   capture real demographic divergence between WashCo's southern and
#   northern towns.
# - LEGACY (0.5, 2.0): the library default and the original Phase-4 choice.
#   Allows halving or doubling per step, compounding up to 32x over the
#   horizon — too wide for stable-population rural counties, especially when
#   the 2020-2024 ACS vintage captures COVID-era rural in-migration that
#   the method then extrapolates as a permanent trend.
# We compute both in this notebook so you can see the sensitivity; only the
# PRODUCTION version is saved to data_interim/town_forecasts.parquet.
CCR_CAP_PRODUCTION = (0.85, 1.20)
CCR_CAP_LEGACY = (0.5, 2.0)
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

We compute two versions of the CCRs — the **production** version uses a
tight cap of (0.85, 1.20) per 5-year step; the **legacy** version uses
the library default (0.5, 2.0). The two are compared at the end of this
notebook so the cap choice is transparent. Only the production version
flows into `data_interim/town_forecasts.parquet` and downstream.
"""),
    code("""
ccr = cohort_change_ratios(pop_prior, pop_latest, cap=CCR_CAP_PRODUCTION)
ccr_legacy = cohort_change_ratios(pop_prior, pop_latest, cap=CCR_CAP_LEGACY)
cwr = child_woman_ratios(pop_latest)

print(f"CCR rows: {len(ccr):,}  (~17 towns × 2 sex × 17 dest bands = {17*2*17})")
print(f"CWR rows: {len(cwr):,}  (17 towns × 2 sex = {17*2})")
print()
print(f"Production cap {CCR_CAP_PRODUCTION}:")
print(f"  clipped CCRs (closed bands): "
      f"{int(ccr[ccr['age_band_start'] != 85]['clipped'].sum())}"
      f" of {len(ccr[ccr['age_band_start'] != 85])}")
print(f"  CCR summary (closed bands):")
print(ccr[ccr["age_band_start"] != 85]["ccr"].describe().round(3).to_string())
print()
print(f"Legacy cap {CCR_CAP_LEGACY}:")
print(f"  clipped CCRs (closed bands): "
      f"{int(ccr_legacy[ccr_legacy['age_band_start'] != 85]['clipped'].sum())}"
      f" of {len(ccr_legacy[ccr_legacy['age_band_start'] != 85])}")
print(f"  CCR summary (closed bands):")
print(ccr_legacy[ccr_legacy["age_band_start"] != 85]["ccr"].describe().round(3).to_string())
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
### 5b. Indexed comparison — selected towns, annual interpolation

Compare growth trajectories across a subset of towns on a single chart by
indexing each town's population to its 2022 value = 100. Indexing removes
the size-difference distortion (Kingsbury at ~12k would otherwise dominate
Jackson at ~1.7k) and lets us read shape directly.

**Selected towns**:
- *Southern* — Cambridge, White Creek, Jackson, Salem, Greenwich
- *Northern* — Granville, Kingsbury (the largest town in the county, picked
  for the size-and-trend contrast against the smaller southern towns)

**Interpolation method**. The Hamilton-Perry projector emits 5-year endpoints
(2022, 2027, 2032, 2037, 2042, 2047), and notebook 08's county forecast emits
annual values. We linearly interpolate each town's population between its
5-year endpoints to get annual values 2022→2047, then rescale every year so
the annual town totals sum exactly to the annual county forecast. The
rescaling factor at each year is `county_annual_target / sum_of_interpolated_towns`,
applied uniformly to all 17 towns at that year — so within-year town shares
are preserved while the annual sum hits the county target on the nose.

For 2022, the county "target" is the sum of the ACS-based town totals (no
external county anchor since 2022 predates the cohort-component forecast).
For 2023–2047, the target is the county forecast at the corresponding year.
"""),
    code("""
SELECTED_SOUTHERN = ["Cambridge town", "White Creek town", "Jackson town",
                     "Salem town", "Greenwich town"]
SELECTED_NORTHERN = ["Granville town", "Kingsbury town"]
SELECTED_TOWNS = SELECTED_SOUTHERN + SELECTED_NORTHERN
ANNUAL_YEARS = list(range(BASE_YEAR_TOWN, END_YEAR_TOWN + 1))

# Baseline town endpoints (sum across sex × age band).
tf_base_totals = (
    town_forecasts[town_forecasts["scenario"] == "baseline"]
    .groupby(["geography", "year"])["population"].sum()
    .reset_index()
)
town_wide = tf_base_totals.pivot(index="geography", columns="year", values="population")

# Linear interpolation between 5-year endpoints, annual.
town_annual = town_wide.reindex(columns=ANNUAL_YEARS).astype(float).interpolate(
    method="linear", axis=1, limit_area="inside"
)

# County annual targets.
county_baseline_annual = (
    wash_county[wash_county["scenario"] == "baseline"]
    .set_index("year")["population"].astype(float)
)
county_target = pd.Series(index=ANNUAL_YEARS, dtype=float)
county_target.loc[BASE_YEAR_TOWN] = float(town_annual[BASE_YEAR_TOWN].sum())
for y in ANNUAL_YEARS:
    if y == BASE_YEAR_TOWN:
        continue
    if y in county_baseline_annual.index:
        county_target.loc[y] = float(county_baseline_annual.loc[y])

# Rescale so interpolated town sums hit the county target exactly.
town_sums_annual = town_annual.sum(axis=0)
rescale = county_target / town_sums_annual
town_constrained = town_annual.multiply(rescale, axis=1)

# Verify
check = pd.DataFrame({
    "town_sum_after_rescale": town_constrained.sum(axis=0).round(1),
    "county_target": county_target.round(1),
    "diff": (town_constrained.sum(axis=0) - county_target).round(6),
})
print("Constraint check — annual town sums vs county target (should match exactly):")
print(check.loc[[BASE_YEAR_TOWN, BASE_YEAR_TOWN + 1, BASE_YEAR_TOWN + 5, BASE_YEAR_TOWN + 10,
                 BASE_YEAR_TOWN + 15, END_YEAR_TOWN]].to_string())

# Index to 2022 = 100.
town_indexed = town_constrained.div(town_constrained[BASE_YEAR_TOWN], axis=0) * 100.0
county_indexed = county_target / county_target.loc[BASE_YEAR_TOWN] * 100.0
"""),
    code("""
fig, ax = plt.subplots(figsize=(12, 6.5))
southern_colors = plt.cm.Blues(np.linspace(0.45, 0.95, len(SELECTED_SOUTHERN)))
northern_colors = plt.cm.Reds(np.linspace(0.55, 0.90, len(SELECTED_NORTHERN)))

for town, color in zip(SELECTED_SOUTHERN, southern_colors):
    line = town_indexed.loc[town]
    ax.plot(line.index, line.values, color=color, linewidth=1.8, marker="o", markersize=2.5,
            label=f"S: {town.replace(' town','')}")

for town, color in zip(SELECTED_NORTHERN, northern_colors):
    line = town_indexed.loc[town]
    ax.plot(line.index, line.values, color=color, linewidth=1.8, marker="o", markersize=2.5,
            label=f"N: {town.replace(' town','')}")

ax.plot(county_indexed.index, county_indexed.values, color="black", linewidth=1.4,
        linestyle="--", alpha=0.7, label="WashCo county (reference)")

ax.axhline(100, color="grey", linewidth=0.5)
# Mark the 5-year forecast endpoints on the x-axis.
for y in sorted(town_wide.columns):
    ax.axvline(y, color="grey", linewidth=0.3, alpha=0.4)
ax.set_xlabel("year")
ax.set_ylabel("indexed population (2022 = 100)")
ax.set_title("Selected Washington County towns — indexed population trajectories, baseline scenario\\n"
             "(linear interpolation between 5-year endpoints, rescaled annually to county total)")
ax.grid(True, alpha=0.3, axis="y")
ax.legend(loc="best", fontsize=9, ncol=2)
fig.tight_layout()
plt.show()

# Tabular summary at endpoint years.
print()
print("Indexed values at 5-year endpoints (2022 = 100):")
endpoint_yrs = sorted(town_wide.columns)
print(town_indexed.loc[SELECTED_TOWNS, endpoint_yrs].round(1).to_string())
print()
# Absolute 2022 and 2047 values for context (since the indexed plot hides them)
abs_table = pd.DataFrame({
    "pop_2022": town_constrained.loc[SELECTED_TOWNS, BASE_YEAR_TOWN].round(0).astype(int),
    "pop_2047": town_constrained.loc[SELECTED_TOWNS, END_YEAR_TOWN].round(0).astype(int),
    "abs_change": (town_constrained.loc[SELECTED_TOWNS, END_YEAR_TOWN]
                   - town_constrained.loc[SELECTED_TOWNS, BASE_YEAR_TOWN]).round(0).astype(int),
    "pct_change": ((town_constrained.loc[SELECTED_TOWNS, END_YEAR_TOWN]
                    / town_constrained.loc[SELECTED_TOWNS, BASE_YEAR_TOWN] - 1) * 100).round(1),
})
print("Absolute 2022 → 2047 (for size context):")
print(abs_table.to_string())
"""),
    md("""
**Reading the plot.** Lines above 100 are towns that grow relative to 2022;
lines below 100 are towns that decline. The dashed black line is the
Washington County total (declining roughly −20% by 2047 in baseline),
providing a reference. Towns whose lines diverge from the county line
positively are gaining share within the county; those that fall below it
are losing share.

This plot uses the **production CCR cap (0.85, 1.20)** per 5-year step.
The numeric values above are what's saved to
`data_interim/town_forecasts.parquet`. Section 5c below shows what these
trajectories looked like under the wider legacy cap — the change is
substantial for the rural northern towns.

**Read these town-level numbers for *insight*, not prediction.** The
Hamilton-Perry method extrapolates one pair of ACS vintages (2015-2019 vs
2020-2024) for 25 years. At the town level — especially for towns under
~3,000 population — that's enough to amplify recent trends, ACS sampling
noise, and any COVID-era movement, into a trajectory that the model
cannot validate. The county-level total (cohort-component) is the
predictive output we trust; the town-level breakdown is descriptive
context for thinking about *which* parts of the county are growing or
declining, not numerical forecasts.

Method-driven caveats:
- The interpolation is *linear* between 5-year endpoints, so within each
  5-year block the trajectory is a straight line by construction (not a
  modeled annual path). The kinks at 2027 / 2032 / 2037 / 2042 are
  interpolation artifacts, not modeled inflection points.
- Annual rescaling to the county total uses a *uniform* per-year factor
  across all 17 towns, preserving within-year shares while pinning the
  annual sum.
"""),
    # ---------------------------------------------------------------
    md("""
### 5c. Sensitivity to the CCR cap

The Hamilton-Perry projector clips CCRs to a band before iterating them
forward. The default cap is wide — (0.5, 2.0) per 5-year step — which
allows ratios to halve or double each step and **compound up to 32x over
the 5-step horizon**. For rural Washington County towns whose ACS
vintages happen to capture COVID-era in-migration, the unconstrained
projection then grows runaway: the sum of all 17 unconstrained towns
reached ~77k by 2047 while the cohort-component county total declines
toward ~46k. The pro-rata constraint resolves the disagreement by
uniformly haircutting every town by ~40% in 2047, which over-corrects
towns whose unconstrained projection wasn't already growing.

The production cap (0.85, 1.20) compresses CCRs to roughly ±15-20% per
step, compounding to about (0.44, 2.49) over the horizon. This still
captures real demographic differences between southern (Capital District
spillover) and northern (rural depopulation) Washington but cuts off the
small-sample noise that drove the extreme legacy-cap trajectories.

Below: the same 7 selected towns under both caps, indexed to 2022 = 100,
post-constraint to the baseline county forecast.
"""),
    code("""
# Project all 17 towns with the LEGACY cap CCRs.
proj_list_legacy = []
for geoid, name in names["geography"].items():
    town_pop = pop_latest[pop_latest["geoid"] == geoid]
    if town_pop.empty:
        continue
    try:
        sub = project_one_county_hp(
            town_pop, ccr_legacy, cwr,
            base_year=BASE_YEAR_TOWN, end_year=END_YEAR_TOWN,
            geoid=geoid, geography=name.split(",")[0],
            scenario="unconstrained",
            projection_vintage=f"hp_legacy_cap{CCR_CAP_LEGACY}",
        )
        proj_list_legacy.append(sub)
    except ValueError:
        pass
unconstrained_legacy = pd.concat(proj_list_legacy, ignore_index=True)

# Apply baseline pro-rata constraint to the legacy projection.
constraint_years_legacy = [y for y in unconstrained_legacy["year"].unique() if y > BASE_YEAR_TOWN]
target_baseline = wash_county[wash_county["scenario"] == "baseline"][["year", "population"]]
target_baseline = target_baseline[target_baseline["year"].isin(constraint_years_legacy)]
sub_legacy = unconstrained_legacy[unconstrained_legacy["year"].isin(constraint_years_legacy)].copy()
constrained_legacy_post = apply_prorata_constraint(sub_legacy, target_baseline)
base_legacy = unconstrained_legacy[unconstrained_legacy["year"] == BASE_YEAR_TOWN].copy()
base_legacy["constraint_factor"] = 1.0
base_legacy["constraint_applied"] = False
constrained_legacy_post["scenario"] = "baseline_legacy_cap"
base_legacy["scenario"] = "baseline_legacy_cap"
town_legacy_constrained = pd.concat([base_legacy, constrained_legacy_post], ignore_index=True)

# Interpolate annual values for the legacy projection (same method as 5b).
tf_legacy_totals = (
    town_legacy_constrained.groupby(["geography", "year"])["population"].sum().reset_index()
)
town_wide_legacy = tf_legacy_totals.pivot(index="geography", columns="year", values="population")
town_annual_legacy = town_wide_legacy.reindex(columns=ANNUAL_YEARS).astype(float).interpolate(
    method="linear", axis=1, limit_area="inside"
)
# Rescale annual sums to the county target (same as 5b).
rescale_legacy = county_target / town_annual_legacy.sum(axis=0)
town_constrained_legacy_annual = town_annual_legacy.multiply(rescale_legacy, axis=1)
town_indexed_legacy = town_constrained_legacy_annual.div(
    town_constrained_legacy_annual[BASE_YEAR_TOWN], axis=0
) * 100.0

# Side-by-side plot: same 7 towns, both caps.
fig, axes = plt.subplots(1, 2, figsize=(15, 6.5), sharey=True)
for ax, town_data, title in [
    (axes[0], town_indexed_legacy, f"LEGACY cap {CCR_CAP_LEGACY}"),
    (axes[1], town_indexed,        f"PRODUCTION cap {CCR_CAP_PRODUCTION}"),
]:
    for town, color in zip(SELECTED_SOUTHERN, southern_colors):
        line = town_data.loc[town]
        ax.plot(line.index, line.values, color=color, linewidth=1.8,
                marker="o", markersize=2.2, label=f"S: {town.replace(' town','')}")
    for town, color in zip(SELECTED_NORTHERN, northern_colors):
        line = town_data.loc[town]
        ax.plot(line.index, line.values, color=color, linewidth=1.8,
                marker="o", markersize=2.2, label=f"N: {town.replace(' town','')}")
    ax.plot(county_indexed.index, county_indexed.values, color="black",
            linewidth=1.3, linestyle="--", alpha=0.7, label="WashCo (reference)")
    ax.axhline(100, color="grey", linewidth=0.5)
    for y in [2027, 2032, 2037, 2042, 2047]:
        ax.axvline(y, color="grey", linewidth=0.3, alpha=0.4)
    ax.set_xlabel("year")
    ax.set_title(title)
    ax.grid(True, alpha=0.3, axis="y")
axes[0].set_ylabel("indexed population (2022 = 100)")
axes[0].legend(loc="best", fontsize=8, ncol=2)
fig.suptitle("CCR cap sensitivity — same 7 towns, baseline scenario, constrained to county forecast",
             y=1.00)
fig.tight_layout()
plt.show()

# Tabular comparison at 2047
end_compare = pd.DataFrame({
    "legacy_2047": town_indexed_legacy.loc[SELECTED_TOWNS, END_YEAR_TOWN].round(1),
    "production_2047": town_indexed.loc[SELECTED_TOWNS, END_YEAR_TOWN].round(1),
})
end_compare["change_in_endpoint"] = (end_compare["production_2047"] - end_compare["legacy_2047"]).round(1)
print(f"\\n{END_YEAR_TOWN} indexed values (2022 = 100), selected towns:")
print(end_compare.to_string())
print(f"\\nThe production cap pulls extreme legacy projections back toward the")
print(f"county trend (≈ 80, since the county declines ~20%). Towns that look")
print(f"qualitatively different from neighbors under the legacy cap are typically")
print(f"the result of ACS sampling noise compounded over 5 steps, not real")
print(f"demographic divergence we can validate.")
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

- **Town-level projections are for insight, not prediction.**
  Hamilton-Perry extrapolates one pair of ACS vintages forward 25 years.
  At the town level this amplifies (a) ACS sampling noise — MOEs in
  small towns rival their populations — and (b) any short-window trend
  the two vintages happened to capture (e.g., COVID-era rural
  in-migration). The county-level total comes from the cohort-component
  engine (Notebook 08); we trust that. The town-level disaggregation is
  best read as a directional answer to "which parts of the county are
  growing or declining," not as a numeric forecast.
- **CCR cap** is set tight at (0.85, 1.20) per 5-year step (production)
  to mitigate the noise-amplification problem (section 5c shows the
  legacy-default (0.5, 2.0) comparison). Even the tight cap allows
  compound divergence up to (0.44, 2.49) over the 5-step horizon —
  enough room for the south-vs-north pattern but not for individual
  small towns to run away.
- **5-year cadence** is built into Hamilton-Perry — town projections only
  exist at 2022, 2027, 2032, ... The county forecast (annual) is sampled
  at those years for the constraint. Section 5b interpolates between
  endpoints linearly with annual rescaling to the county total.
- **Constant CCRs** assume the 2017→2022 cohort dynamics persist through
  2047. For some towns this carries pandemic-era shocks forward.
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
