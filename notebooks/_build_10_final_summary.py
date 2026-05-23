"""Generator for notebooks/10_final_summary.ipynb."""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf

NOTEBOOK_PATH = Path(__file__).parent / "10_final_summary.ipynb"


def md(s: str) -> nbf.NotebookNode:
    return nbf.v4.new_markdown_cell(s.strip("\n"))


def code(s: str) -> nbf.NotebookNode:
    return nbf.v4.new_code_cell(s.strip("\n"))


CELLS = [
    md("""
# 10 — Final Summary

The Washington County population forecast in five sections:

1. The headline: trajectory under three scenarios + how it compares to
   Cornell PAD.
2. Cohort context: Washington vs five demographic neighbors.
3. Decomposition: how much of the decline is natural change (births −
   deaths) vs net migration.
4. Age structure: 2023 vs 2050 pyramids.
5. Town view: trajectory per MCD, town shares of the county.

At the end, the notebook regenerates the `data_final/` exports
(headline CSV, per-county trajectories, per-town trajectories, full
age × sex parquets) for downstream consumers.
"""),
    # ---------------------------------------------------------------
    code("""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from popfc.data.cornell import load_cornell_pad
from popfc.paths import DATA_FINAL, DATA_INTERIM, FULL_FIPS
from popfc.reporting.export import VALIDATION_COHORT, write_final_exports

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 40)

WASHINGTON = FULL_FIPS

# Load the key artifacts produced by Notebooks 01-09.
hist = pd.read_parquet(DATA_INTERIM / "population_reconciled.parquet")
components = pd.read_parquet(DATA_INTERIM / "county_components.parquet")
county_fc = pd.read_parquet(DATA_INTERIM / "county_forecasts.parquet")
town_fc = pd.read_parquet(DATA_INTERIM / "town_forecasts.parquet")
pad = load_cornell_pad()["totals"]

print(f"reconciled history: {len(hist):,} rows")
print(f"components:         {len(components):,} rows")
print(f"county forecasts:   {len(county_fc):,} rows")
print(f"town forecasts:     {len(town_fc):,} rows")
"""),
    # ---------------------------------------------------------------
    md("""
## 1. Headline — Washington County under three scenarios
"""),
    code("""
def county_totals_by_year(df, geoid):
    return df[df["geoid"] == geoid].groupby(["scenario", "year"])["population"].sum().reset_index()

wash = county_totals_by_year(county_fc, WASHINGTON)
hist_wash = hist[hist["geoid"] == WASHINGTON][["year", "population"]].rename(columns={"population": "historical"})
pad_wash = pad[pad["geoid"] == WASHINGTON][["year", "population"]].rename(columns={"population": "pad"})

print("Washington County — key milestones:")
piv = wash.pivot_table(index="year", columns="scenario", values="population").round(0).astype(int)
print(piv.loc[[2023, 2030, 2040, 2050]].to_string())
print()
print(f"Decline 2023 → 2050: "
      f"low  {int(piv.loc[2050, 'low']) - int(piv.loc[2023, 'low']):+,}  ({100*(piv.loc[2050,'low']/piv.loc[2023,'low']-1):+.1f}%)")
print(f"                       baseline {int(piv.loc[2050, 'baseline']) - int(piv.loc[2023, 'baseline']):+,}  ({100*(piv.loc[2050,'baseline']/piv.loc[2023,'baseline']-1):+.1f}%)")
print(f"                       high {int(piv.loc[2050, 'high']) - int(piv.loc[2023, 'high']):+,}  ({100*(piv.loc[2050,'high']/piv.loc[2023,'high']-1):+.1f}%)")
"""),
    # ---------------------------------------------------------------
    code("""
fig, ax = plt.subplots(figsize=(12, 5))
# History
ax.plot(hist_wash["year"], hist_wash["historical"], color="black",
        linewidth=1.6, marker="o", markersize=3, label="Reconciled history")
# PAD
ax.plot(pad_wash["year"], pad_wash["pad"], color="grey", linestyle="--",
        linewidth=1.2, marker="s", markersize=3, label="Cornell PAD (pre-pandemic)")
# Scenarios — show baseline solid + low/high as a shaded band
for scen, color, ls in [("baseline", "C0", "-")]:
    sub = wash[wash["scenario"] == scen].sort_values("year")
    ax.plot(sub["year"], sub["population"], color=color, linewidth=1.6,
            marker="o", markersize=3, label=f"forecast: {scen}")
low = wash[wash["scenario"] == "low"].sort_values("year")
high = wash[wash["scenario"] == "high"].sort_values("year")
ax.fill_between(low["year"], low["population"], high["population"],
                color="C0", alpha=0.18, label="low–high range")
ax.axvline(2023, color="black", linewidth=0.5, alpha=0.5)
ax.text(2023.3, ax.get_ylim()[1] * 0.97, "base year",
        ha="left", va="top", fontsize=9, color="black")
ax.set_title("Washington County, NY — population history and forecast")
ax.set_xlabel("year"); ax.set_ylabel("population")
ax.grid(True, alpha=0.3)
ax.legend(loc="lower left")
fig.tight_layout()
plt.show()
"""),
    # ---------------------------------------------------------------
    md("""
## 2. Cohort context — Washington vs neighbors

Baseline scenario only, indexed to 100 at 2023 to make trajectory
shape easier to compare across counties of different sizes.
"""),
    code("""
fig, ax = plt.subplots(figsize=(11, 5))
for geoid, name in VALIDATION_COHORT.items():
    sub = county_fc[(county_fc["geoid"] == geoid) & (county_fc["scenario"] == "baseline")]
    sub = sub.groupby("year")["population"].sum().reset_index().sort_values("year")
    if sub.empty:
        continue
    base = float(sub.loc[sub["year"] == 2023, "population"].iloc[0])
    sub["indexed"] = 100.0 * sub["population"] / base
    lw = 2.0 if geoid == WASHINGTON else 1.0
    alpha = 1.0 if geoid == WASHINGTON else 0.7
    ax.plot(sub["year"], sub["indexed"], linewidth=lw, alpha=alpha,
            label=name, marker="o", markersize=2)
ax.axhline(100, color="grey", linewidth=0.6)
ax.set_title("Cohort trajectories — baseline scenario, indexed to 2023 = 100")
ax.set_xlabel("year"); ax.set_ylabel("population (2023 = 100)")
ax.grid(True, alpha=0.3)
ax.legend()
fig.tight_layout()
plt.show()

# 2050 endpoint table
end = (
    county_fc[(county_fc["year"] == 2050) & (county_fc["scenario"] == "baseline")]
    .groupby(["geoid", "geography"])["population"]
    .sum().reset_index()
)
end["county"] = end["geoid"].map(VALIDATION_COHORT)
base = (
    county_fc[(county_fc["year"] == 2023) & (county_fc["scenario"] == "baseline")]
    .groupby(["geoid"])["population"].sum()
)
end["pop_2023"] = end["geoid"].map(base)
end["pct_change"] = 100 * (end["population"] / end["pop_2023"] - 1)
print("Cohort 2023 → 2050, baseline:")
print(end[["county", "pop_2023", "population", "pct_change"]]
      .rename(columns={"population": "pop_2050"})
      .sort_values("pct_change")
      .to_string(index=False, float_format=lambda x: f'{x:.1f}'))
"""),
    # ---------------------------------------------------------------
    md("""
## 3. Decomposition — natural change vs net migration

How much of Washington's projected decline is driven by deaths exceeding
births (natural decrease), and how much is driven by net out-migration?
This uses the engine's internal projection logic.
"""),
    code("""
from popfc.models.fertility import (
    REPRO_AGE_MAX, REPRO_AGE_MIN, SHARE_MALE_AT_BIRTH,
)

# Births per year from the forecast.
asfr = pd.read_parquet(DATA_INTERIM / "asfr.parquet")
wash_asfr = (
    asfr[(asfr["geoid"] == WASHINGTON) & (asfr["year"] == 2023)]
    .set_index("age")["asfr_per_1000"].astype(float)
)

wash_baseline = county_fc[
    (county_fc["geoid"] == WASHINGTON) & (county_fc["scenario"] == "baseline")
]
years = sorted(wash_baseline["year"].unique())

# Births per year = sum(F pop[15-49] × ASFR / 1000)
births_per_year = []
for y in years:
    f_pop = wash_baseline[
        (wash_baseline["year"] == y) & (wash_baseline["sex"] == "F")
        & (wash_baseline["age"].between(REPRO_AGE_MIN, REPRO_AGE_MAX))
    ].set_index("age")["population"].astype(float)
    aligned = f_pop.reindex(wash_asfr.index).fillna(0)
    b = float((aligned * wash_asfr.reindex(aligned.index).fillna(0) / 1000).sum())
    births_per_year.append({"year": y, "births": b})
births_df = pd.DataFrame(births_per_year).set_index("year")["births"]

# Year-over-year total pop change.
totals = wash_baseline.groupby("year")["population"].sum().rename("total")
delta = totals.diff().rename("delta_total")

# Implied deaths: requires survival math. Approximation: deaths ≈
# total at t × (overall annual mortality rate). For a quick decomposition
# we'll use the implied: natural change = births - deaths, but compute
# deaths as (sum_t P × survival-loss). Simpler proxy: use Census PEP's
# implied (rate_deaths × mid_year_pop / 1000) from county_components.
comp = pd.read_parquet(DATA_INTERIM / "county_components.parquet")
wash_comp = comp[comp["geoid"] == WASHINGTON].copy()
deaths_hist = (
    wash_comp[wash_comp["measure"] == "rate_deaths"]
    [["year", "value", "vintage"]]
    .sort_values(["year", "vintage"])
    .drop_duplicates(subset="year", keep="last")
    .set_index("year")["value"].astype(float)
)
# Use the 2023 rate going forward as a hold-constant approximation.
death_rate_2023 = float(deaths_hist.iloc[-1])
deaths_fc = (totals * death_rate_2023 / 1000.0).rename("deaths_approx")

decomp = pd.concat([totals, delta, births_df.rename("births"), deaths_fc], axis=1)
decomp["natural_change_approx"] = decomp["births"] - decomp["deaths_approx"]
decomp["net_migration_approx"] = decomp["delta_total"] - decomp["natural_change_approx"]
print("Approximate annual decomposition, Washington baseline:")
print(decomp.loc[2024:2050:5].round(0).astype("Int64").to_string())
print()
print("Cumulative 2023-2050:")
print(f"  Total change:       {int(totals.loc[2050] - totals.loc[2023]):+,}")
print(f"  Natural change:     {int(decomp['natural_change_approx'].iloc[1:].sum()):+,}")
print(f"  Net migration:      {int(decomp['net_migration_approx'].iloc[1:].sum()):+,}")
print("(Approximation: deaths use the 2023 rate × population each year. "
      "True engine values include survival aging within each cohort.)")
"""),
    # ---------------------------------------------------------------
    md("""
## 4. Age structure — Washington 2023 vs 2050
"""),
    code("""
def pyramid(df, year, scenario="baseline"):
    sub = df[(df["geoid"] == WASHINGTON) & (df["year"] == year) & (df["scenario"] == scenario)]
    return sub.pivot_table(index="age", columns="sex", values="population", aggfunc="sum")

p23 = pyramid(county_fc, 2023)
p50 = pyramid(county_fc, 2050)

fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True, sharex=True)
for ax, (df, year, color_m, color_f) in zip(axes, [(p23, 2023, "C0", "C1"), (p50, 2050, "C0", "C1")]):
    ax.barh(df.index, -df["M"], height=0.85, color=color_m, alpha=0.7, label="Male")
    ax.barh(df.index,  df["F"], height=0.85, color=color_f, alpha=0.7, label="Female")
    ax.axvline(0, color="black", linewidth=0.6)
    ax.set_title(f"Washington — {year} (baseline)")
    ax.set_xlabel("population")
    ax.grid(True, alpha=0.3)
axes[0].set_ylabel("age (top-coded 85+)")
axes[0].legend()
fig.suptitle("Age pyramid: aging visible in the shift up the chart")
fig.tight_layout()
plt.show()

# Headline aging stats
def share_over_65(p):
    return float(p.loc[65:][["M", "F"]].sum().sum()) / float(p[["M", "F"]].sum().sum())
print(f"Share of population aged 65+: 2023 {100*share_over_65(p23):.1f}%, 2050 {100*share_over_65(p50):.1f}%")
def share_under_18(p):
    return float(p.loc[:17][["M", "F"]].sum().sum()) / float(p[["M", "F"]].sum().sum())
print(f"Share of population aged <18: 2023 {100*share_under_18(p23):.1f}%, 2050 {100*share_under_18(p50):.1f}%")
"""),
    # ---------------------------------------------------------------
    md("""
## 5. Town view — Washington's 17 MCDs
"""),
    code("""
twn_base = town_fc[town_fc["scenario"] == "baseline"]
twn_totals = (
    twn_base.groupby(["geoid", "geography", "year"])["population"].sum().reset_index()
)
piv = twn_totals.pivot_table(index="geography", columns="year", values="population").round(0).astype(int)
piv["pct_change_22_47"] = (100 * (piv[2047] / piv[2022] - 1)).round(1)
piv = piv.sort_values("pct_change_22_47")
print("Town summary — 2022 → 2047 baseline:")
print(piv.to_string())
"""),
    # ---------------------------------------------------------------
    code("""
fig, ax = plt.subplots(figsize=(12, 6))
for geoid, g in twn_totals.groupby("geoid"):
    g = g.sort_values("year")
    name = g["geography"].iloc[0]
    pct = float(piv.loc[name, "pct_change_22_47"])
    color = "C3" if pct < -50 else "C1" if pct < -20 else "C2" if pct > 0 else "C0"
    ax.plot(g["year"], g["population"], marker="o", markersize=3, linewidth=1.2,
            color=color, alpha=0.75, label=f"{name} ({pct:+.0f}%)")
ax.set_xlabel("year"); ax.set_ylabel("population")
ax.set_title("Washington County towns — baseline trajectory, color-coded by 2022-2047 change")
ax.grid(True, alpha=0.3)
ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=8)
fig.tight_layout()
plt.show()
"""),
    # ---------------------------------------------------------------
    md("""
### Town shares of the county — changing composition
"""),
    code("""
shares = []
for year in (2022, 2047):
    yr = twn_totals[twn_totals["year"] == year].copy()
    county_total = yr["population"].sum()
    yr["share_pct"] = 100 * yr["population"] / county_total
    yr["year"] = year
    shares.append(yr)
shares_df = pd.concat(shares, ignore_index=True)
share_piv = shares_df.pivot_table(index="geography", columns="year", values="share_pct").round(2)
share_piv["delta_pp"] = (share_piv[2047] - share_piv[2022]).round(2)
print("Town share of county pop (%) — 2022 vs 2047:")
print(share_piv.sort_values("delta_pp", ascending=False).to_string())
"""),
    # ---------------------------------------------------------------
    md("""
## 6. Regenerate `data_final/` exports
"""),
    code("""
paths = write_final_exports()
for name, p in paths.items():
    rel = p.relative_to(p.parents[1])
    print(f"  {name:<30}  {rel}  ({p.stat().st_size:,} bytes)")
"""),
    # ---------------------------------------------------------------
    md("""
## What's in `data_final/`

| File                             | Purpose                                |
|----------------------------------|----------------------------------------|
| `summary_headline.csv`           | One-row-per-scenario county totals at key years |
| `washington_history.csv`         | Reconciled annual pop 2000-2024        |
| `washington_components.csv`      | Births / deaths / migration history    |
| `county_forecast_totals.csv`     | Cohort counties × year × scenario      |
| `county_forecast_agesex.parquet` | Full age × sex × year × scenario       |
| `town_forecast_totals.csv`       | 17 Washington towns × year × scenario  |
| `town_forecast_agesex.parquet`   | Full age-band × sex × year × scenario  |

The CSVs are for analysts who want to open data in a spreadsheet; the
parquets carry the full schema with dtypes preserved. Both can be read
without any of the codebase.

The data dictionary in `docs/data_dictionary.md` documents every
column in every `data_interim/` and `data_final/` artifact.

## Notebook reference card

- 01: reconciled population
- 02: components of change
- 03: age × sex stitched 1990-2023
- 04: external data quick-look (ACS, NCHS life tables)
- 05: ASFR
- 06: survival rates
- 07: net migration rates
- 08: county forecast (cohort-component, 6 counties × 3 scenarios)
- 09: town forecast (Hamilton-Perry + pro-rata, 17 Washington MCDs)
- 10: this notebook
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
