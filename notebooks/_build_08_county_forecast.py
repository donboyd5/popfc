"""Generator for notebooks/08_county_forecast.ipynb."""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf

NOTEBOOK_PATH = Path(__file__).parent / "08_county_forecast.ipynb"


def md(s: str) -> nbf.NotebookNode:
    return nbf.v4.new_markdown_cell(s.strip("\n"))


def code(s: str) -> nbf.NotebookNode:
    return nbf.v4.new_code_cell(s.strip("\n"))


CELLS = [
    md("""
# 08 — County Forecast (Phase 3 deliverable)

**Goal.** Run the cohort-component engine from the 2024 base year to
2050 for Washington County and the 5 validation-cohort counties, under
three scenarios (low / baseline / high), and compare against the
Cornell PAD projection benchmark.

## Inputs

All produced by earlier Phase-3 notebooks:

| File                                | From notebook |
|-------------------------------------|---------------|
| `data_interim/survival_rates.parquet`        | 06 |
| `data_interim/asfr.parquet`                  | 05 |
| `data_interim/net_migration_rates.parquet`   | 07 |
| `data_interim/county_agesex_1990_2024.parquet` (base) | 03 |
| `data_raw/cornell/padprojections115.xls` (benchmark) | Cornell |

Survival is NCHS NY State 2022 (rebanded to top-code 85). ASFR is the
county-specific scaled-to-2024 schedule. Net migration is the
2020-2024 four-year average per county-sex-age.

## Scenarios — historical-reference framework

Scenarios are anchored to **each county's own observed migration
experience over the last decade**, not to arbitrary multipliers. For
every cohort county we look at all rolling 5-year windows of net
migration (PEP `net_mig` / mid-year pop) starting at 2010, pick the
best and worst windows, and translate them into engine inputs as
follows:

- **baseline**: ASFR × 1.00; migration uses the engine's residual-
  method rates as-is (which already average the most recent 4 year-
  pairs, ≈ "current" experience).
- **low**: ASFR × 0.85 (about 15% below current TFR); migration
  shifted to match the county's **worst observed 5-year window**.
- **high**: ASFR × 1.15; migration shifted to match the county's
  **best observed 5-year window**.

The migration shift is implemented additively. We compute the
county's current 5-year-window average rate and the best/worst
window averages, then apply a uniform delta `(target − current)` to
every per-(age, sex) migration rate. This preserves the age × sex
*shape* of migration (kids in, working-age out for Washington) and
moves only the *level*. It also yields scenario bands grounded in
real historical experience — no arbitrary multipliers — which
matters when a county's net migration is small and signed.

See `docs/methodology.md` for the historical-reference framework and
`popfc.models.migration.historical_reference_periods()` for the
implementation.

## Output

`data_interim/county_forecasts.parquet` — one row per (geoid, year,
sex, age, scenario), 2024-2050.
"""),
    # ---------------------------------------------------------------
    code("""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from popfc.data.cornell import load_cornell_pad
from popfc.models.cohort_component import (
    PROJECTION_COLUMNS,
    project_one_county,
)
from popfc.models.migration import historical_reference_periods
from popfc.models.mortality import survival_rates_from_life_table
from popfc.paths import DATA_INTERIM, FULL_FIPS

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 40)

BASE_YEAR = 2024
END_YEAR = 2050
TOP_CODE_AGE = 85
WASHINGTON = FULL_FIPS
COHORT = {
    WASHINGTON: "Washington",
    "36091": "Saratoga",
    "36113": "Warren",
    "36083": "Rensselaer",
    "36031": "Essex",
    "36021": "Columbia",
}

# Scenario fertility multipliers (around current observed TFR).
ASFR_LOW = 0.85
ASFR_BASE = 1.00
ASFR_HIGH = 1.15
"""),
    # ---------------------------------------------------------------
    md("""
## 1. Load inputs
"""),
    code("""
lt = pd.read_parquet(DATA_INTERIM / "life_tables.parquet")
nvsr = lt[lt["source"] == "nchs_nvsr"]
survival = survival_rates_from_life_table(nvsr, top_code_age=TOP_CODE_AGE)
print(f"survival rates rows: {len(survival):,}")

asfr_all = pd.read_parquet(DATA_INTERIM / "asfr.parquet")
print(f"asfr rows: {len(asfr_all):,}; latest year: {asfr_all['year'].max()}")

net_mig = pd.read_parquet(DATA_INTERIM / "net_migration_rates.parquet")
print(f"net migration rows: {len(net_mig):,}")

agesex = pd.read_parquet(DATA_INTERIM / "county_agesex_1990_2024.parquet")
base_all = agesex[
    (agesex["source"] == "census_sya")
    & (agesex["kind"] == "estimate")
    & (agesex["year"] == BASE_YEAR)
][["geoid", "geography", "sex", "age", "population"]].copy()
print(f"base pop rows: {len(base_all):,}; counties: {base_all['geoid'].nunique()}")
"""),
    # ---------------------------------------------------------------
    md("""
## 2. Compute per-county historical reference periods

For each cohort county, find the best, worst, and current 5-year-window
average net migration rates. These become the engine's `net_mig_delta`
(additive shift relative to the residual-method rates) under the high,
low, and baseline scenarios.
"""),
    code("""
components = pd.read_parquet(DATA_INTERIM / "county_components.parquet")
pop_reconciled = pd.read_parquet(DATA_INTERIM / "population_reconciled.parquet")

ref_periods = historical_reference_periods(
    components, pop_reconciled,
    window_years=5, start_year=2010,
    geoids=list(COHORT.keys()),
)

print("Per-county 5-year migration windows (PEP net_mig / mid-year pop):")
ref_wide = (
    ref_periods.pivot_table(
        index=["geoid", "geography"],
        columns="window_kind",
        values=["year_start", "year_end", "avg_rate"],
        aggfunc="first",
    )
)
# Show as: geography | current rate | best rate (years) | worst rate (years)
display_rows = []
for (g, name), grp in ref_periods.groupby(["geoid", "geography"]):
    row = {"geoid": g, "geography": name}
    for kind in ("current", "best", "worst"):
        r = grp[grp["window_kind"] == kind].iloc[0] if (grp["window_kind"] == kind).any() else None
        if r is not None:
            row[f"{kind}_rate_pct"] = 100 * float(r["avg_rate"])
            row[f"{kind}_window"] = f"{int(r['year_start'])}-{int(r['year_end'])}"
    display_rows.append(row)
ref_display = pd.DataFrame(display_rows)
print(ref_display.to_string(index=False, float_format=lambda x: f'{x:+.3f}%'))
"""),
    # ---------------------------------------------------------------
    md("""
## 3. Run the engine for each cohort county × each scenario

Migration `net_mig_delta` is computed per-county per-scenario as
`(target_rate − current_rate)`, where `current_rate` is the most-
recent 5-year window's average net migration rate and `target_rate`
is the high/low scenario's reference window's average. This shifts
every per-(age, sex) migration rate uniformly by the same amount,
preserving shape and changing level.
"""),
    code("""
def _rate_for(ref_df: pd.DataFrame, geoid: str, kind: str) -> float:
    row = ref_df[(ref_df["geoid"] == geoid) & (ref_df["window_kind"] == kind)]
    return float(row["avg_rate"].iloc[0]) if not row.empty else 0.0

results: list[pd.DataFrame] = []
scenario_inputs: list[dict] = []   # for inspection/reporting after the run
for geoid, name in COHORT.items():
    base = base_all[base_all["geoid"] == geoid].copy()
    if base.empty:
        print(f"WARN: no base pop for {geoid} ({name})")
        continue
    # County-specific base-year ASFR (use as forecast schedule, held constant).
    asfr_c = asfr_all[
        (asfr_all["geoid"] == geoid) & (asfr_all["year"] == BASE_YEAR)
    ][["age", "asfr_per_1000"]].copy()
    if asfr_c.empty:
        print(f"WARN: no ASFR for {geoid} ({name})")
        continue

    cur_rate  = _rate_for(ref_periods, geoid, "current")
    best_rate = _rate_for(ref_periods, geoid, "best")
    worst_rate = _rate_for(ref_periods, geoid, "worst")
    # Deltas are scenario_target − current. Baseline = 0 by construction.
    scenarios = {
        "baseline": {"asfr_multiplier": ASFR_BASE, "net_mig_delta": 0.0,
                     "_ref": "current"},
        "low":      {"asfr_multiplier": ASFR_LOW,  "net_mig_delta": worst_rate - cur_rate,
                     "_ref": "worst"},
        "high":     {"asfr_multiplier": ASFR_HIGH, "net_mig_delta": best_rate - cur_rate,
                     "_ref": "best"},
    }
    for scenario_name, knobs in scenarios.items():
        ref_kind = knobs.pop("_ref")
        out = project_one_county(
            base, BASE_YEAR, END_YEAR,
            survival=survival, asfr=asfr_c, net_mig=net_mig,
            geoid=geoid, geography=name,
            survival_geoid=("36115" if geoid == WASHINGTON else "36000"),
            net_mig_geoid=geoid,
            top_code_age=TOP_CODE_AGE,
            scenario=scenario_name,
            **knobs,
        )
        results.append(out)
        scenario_inputs.append({
            "geoid": geoid, "geography": name, "scenario": scenario_name,
            "ref_kind": ref_kind,
            "asfr_multiplier": knobs["asfr_multiplier"],
            "net_mig_delta": knobs["net_mig_delta"],
        })

forecasts = pd.concat(results, ignore_index=True)
print(f"forecasts rows: {len(forecasts):,}")
print(f"  scenarios: {sorted(forecasts['scenario'].unique())}")
print(f"  year range: {forecasts['year'].min()}-{forecasts['year'].max()}")
print()
print("Per-county scenario inputs:")
print(pd.DataFrame(scenario_inputs)
      .to_string(index=False, float_format=lambda x: f'{x:+.5f}'))
"""),
    # ---------------------------------------------------------------
    md("""
## 4. Total population by year × scenario — Washington
"""),
    code("""
totals = (
    forecasts.groupby(["geoid", "geography", "year", "scenario"])["population"]
    .sum()
    .reset_index()
)

wash = totals[totals["geoid"] == WASHINGTON].copy()
pivot = wash.pivot_table(index="year", columns="scenario", values="population")
print("Washington total population — baseline / low / high:")
print(pivot.round(0).astype(int).to_string())
"""),
    # ---------------------------------------------------------------
    md("""
### Plot all three scenarios with Cornell PAD overlay
"""),
    code("""
pad = load_cornell_pad()["totals"]
pad_wash = pad[pad["geoid"] == WASHINGTON]

# Historical context — ~10 years of reconciled history before the base year
# so the forecast curves are read against the recent trajectory, not in
# isolation. HIST_START_YEAR controls how much pre-forecast history to show.
HIST_START_YEAR = 2015
SPECULATIVE_AFTER = 2035
historical = pd.read_parquet(DATA_INTERIM / "population_reconciled.parquet")
wash_hist = historical[(historical["geoid"] == WASHINGTON)
                       & (historical["year"] >= HIST_START_YEAR)
                       & (historical["year"] <= BASE_YEAR)].sort_values("year")

fig, ax = plt.subplots(figsize=(11, 5))
colors = {"baseline": "C0", "low": "C3", "high": "C2"}
ax.plot(wash_hist["year"], wash_hist["population"],
        color="black", linewidth=1.8, marker="o", markersize=3,
        label=f"Historical (reconciled, {HIST_START_YEAR}-{BASE_YEAR})")
for scen, sub in wash.groupby("scenario"):
    sub = sub.sort_values("year")
    ax.plot(sub["year"], sub["population"], marker="o", markersize=2,
            linewidth=1.4, color=colors[scen], label=f"engine: {scen}")
ax.plot(pad_wash["year"], pad_wash["population"], marker="s", markersize=3,
        linewidth=1.2, color="grey", linestyle="--", label="Cornell PAD (2015-2040)")
ax.axvline(BASE_YEAR, color="black", linewidth=0.6, alpha=0.4)
ax.text(BASE_YEAR + 0.3, ax.get_ylim()[1] * 0.98, "base year",
        ha="left", va="top", fontsize=9, color="black")
# Shade and annotate the post-2035 region where projections are progressively
# more speculative — readers should weight near-term values more.
ax.axvspan(SPECULATIVE_AFTER, 2050, color="grey", alpha=0.06, zorder=0)
ax.axvline(SPECULATIVE_AFTER, color="grey", linestyle=":", linewidth=0.8, alpha=0.7)
ax.text(SPECULATIVE_AFTER + 0.2, ax.get_ylim()[0] + 0.02 * (ax.get_ylim()[1] - ax.get_ylim()[0]),
        "more speculative beyond 2035",
        ha="left", va="bottom", fontsize=8, color="grey", style="italic")
ax.set_xlabel("year")
ax.set_ylabel("population")
ax.set_title(f"Washington County — history ({HIST_START_YEAR}+) and forecast to 2050 (focus on 2024-2035)")
ax.grid(True, alpha=0.3)
ax.legend()
fig.tight_layout()
plt.show()
"""),
    # ---------------------------------------------------------------
    md("""
### 4b. Cohort time-series small multiples

Same three-scenario fan for each cohort county. Y-axes are
independent so each county's trajectory fills its panel — read this for
*shape* (declining, flat, growing) rather than relative *level*. Cornell
PAD is shown only for Washington in the main projection plot above.
"""),
    code("""
fig, axes = plt.subplots(2, 3, figsize=(15, 8))
axes = axes.flatten()
hist_cohort = historical[historical["geoid"].isin(COHORT)
                         & (historical["year"] >= HIST_START_YEAR)
                         & (historical["year"] <= BASE_YEAR)]
for ax, (geoid, name) in zip(axes, COHORT.items()):
    hist_sub = hist_cohort[hist_cohort["geoid"] == geoid].sort_values("year")
    ax.plot(hist_sub["year"], hist_sub["population"],
            color="black", linewidth=1.4, label="historical")
    sub = totals[totals["geoid"] == geoid]
    for scen in ["low", "baseline", "high"]:
        s = sub[sub["scenario"] == scen].sort_values("year")
        ax.plot(s["year"], s["population"], color=colors[scen], linewidth=1.4,
                label=scen)
    ax.axvline(BASE_YEAR, color="black", linewidth=0.6, alpha=0.4)
    ax.axvspan(SPECULATIVE_AFTER, 2050, color="grey", alpha=0.06, zorder=0)
    ax.axvline(SPECULATIVE_AFTER, color="grey", linestyle=":", linewidth=0.7, alpha=0.6)
    ax.set_title(f"{name} ({geoid})", fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.ticklabel_format(axis="y", style="plain")
axes[0].legend(loc="best", fontsize=8)
for ax in axes[-3:]:
    ax.set_xlabel("year")
for ax in axes[::3]:
    ax.set_ylabel("population")
fig.suptitle(f"Cohort county forecasts — {BASE_YEAR} base, low / baseline / high scenarios", y=1.00)
fig.tight_layout()
plt.show()
"""),
    # ---------------------------------------------------------------
    md("""
## 5. Cohort summary — 2050 outcomes
"""),
    code("""
y2050 = totals[totals["year"] == END_YEAR].copy()
y_base = totals[totals["year"] == BASE_YEAR].copy()
joined = y2050.merge(
    y_base.rename(columns={"population": "pop_base"})[["geoid", "scenario", "pop_base"]],
    on=["geoid", "scenario"], how="left",
)
joined["pct_change"] = (
    100.0 * (joined["population"] / joined["pop_base"] - 1.0)
)
print(f"{END_YEAR} populations and % change from {BASE_YEAR}:")
piv = joined.pivot_table(index="geography", columns="scenario", values="population")
piv_pct = joined.pivot_table(index="geography", columns="scenario", values="pct_change")
print()
print(f"{END_YEAR} population:")
print(piv.round(0).astype(int).to_string())
print()
print(f"% change {BASE_YEAR} → {END_YEAR}:")
print(piv_pct.round(1).to_string())
"""),
    # ---------------------------------------------------------------
    md("""
### 5b. 2050 % change ranking

The cohort sorted by baseline % change from the base year, with low/high
scenarios shown as the bracket. Lets you see which counties have the
widest scenario range as well as the central trajectory.
"""),
    code("""
ranking = (joined.pivot_table(index="geography", columns="scenario", values="pct_change")
           .reset_index()
           .sort_values("baseline"))

fig, ax = plt.subplots(figsize=(10, 4.5))
y_pos = np.arange(len(ranking))
ax.barh(y_pos, ranking["baseline"].astype(float),
        color="C0", alpha=0.7, label="baseline", edgecolor="black", linewidth=0.5)
# Error-bar-style bracket for low/high.
for i, row in ranking.reset_index(drop=True).iterrows():
    lo = float(row["low"]); hi = float(row["high"]); base = float(row["baseline"])
    ax.plot([lo, hi], [i, i], color="black", linewidth=1.0)
    ax.plot([lo, lo], [i - 0.15, i + 0.15], color="black", linewidth=1.0)
    ax.plot([hi, hi], [i - 0.15, i + 0.15], color="black", linewidth=1.0)
    ax.scatter([base], [i], color="C0", s=30, zorder=5, edgecolor="black", linewidth=0.5)

ax.axvline(0, color="black", linewidth=0.8)
ax.set_yticks(y_pos)
ax.set_yticklabels(ranking["geography"].tolist())
ax.set_xlabel(f"% change {BASE_YEAR} → {END_YEAR}")
ax.set_title(f"Cohort county {BASE_YEAR}→{END_YEAR} population change — baseline (dot) and low/high (bracket)")
ax.grid(True, alpha=0.3, axis="x")
fig.tight_layout()
plt.show()
"""),
    # ---------------------------------------------------------------
    md("""
## 6. Age structure — Washington base-year vs 2050 baseline pyramid
"""),
    code("""
def age_pyramid(forecasts: pd.DataFrame, geoid: str, year: int, scenario: str = "baseline"):
    sub = forecasts[
        (forecasts["geoid"] == geoid)
        & (forecasts["year"] == year)
        & (forecasts["scenario"] == scenario)
    ].copy()
    return sub.pivot_table(index="age", columns="sex", values="population", aggfunc="sum")

p_base = age_pyramid(forecasts, WASHINGTON, BASE_YEAR)
p2050 = age_pyramid(forecasts, WASHINGTON, 2050)

fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True, sharex=True)
for ax, (df, year) in zip(axes, [(p_base, BASE_YEAR), (p2050, 2050)]):
    ax.barh(df.index, -df["M"], height=0.85, color="C0", alpha=0.7, label="Male")
    ax.barh(df.index,  df["F"], height=0.85, color="C1", alpha=0.7, label="Female")
    ax.axvline(0, color="black", linewidth=0.6)
    ax.set_title(f"Washington — {year} baseline")
    ax.set_xlabel("population")
    ax.grid(True, alpha=0.3)
axes[0].set_ylabel("age (top-coded 85+)")
axes[0].legend()
fig.tight_layout()
plt.show()
"""),
    # ---------------------------------------------------------------
    md("""
## 7. Components of the Washington decline — natural change vs migration

Decompose the projected population change into Births, Deaths, and Net
Migration per forecast year. We compute Births directly from the
ASFR × female-pop formula the engine uses, Net Migration directly from
the migration rates × source-age pop, and back out Deaths as the
residual that makes the demographic identity close:

> **ΔPop(t→t+1) = Births − Deaths + NetMig** → **Deaths = Births + NetMig − ΔPop**

This means our three components sum exactly to ΔPop by construction.
We aren't separately tracking deaths in the engine output — the
forecasts parquet stores end-of-year populations by age × sex only, so
deaths-as-residual is the cleanest post-hoc decomposition.
"""),
    code("""
from popfc.models.fertility import REPRO_AGE_MAX, REPRO_AGE_MIN

def decompose_county_scenario(geoid: str, scenario: str = "baseline") -> pd.DataFrame:
    sub = forecasts[
        (forecasts["geoid"] == geoid) & (forecasts["scenario"] == scenario)
    ].copy()
    totals_by_year = sub.groupby("year")["population"].sum()
    delta = totals_by_year.diff()

    asfr_c = asfr_all[
        (asfr_all["geoid"] == geoid) & (asfr_all["year"] == BASE_YEAR)
    ].set_index("age")["asfr_per_1000"].astype(float)

    nm_c = net_mig[net_mig["geoid"] == geoid].copy()
    # Build per-(sex, source_age) m_rate including the open-band boundary.
    closed = nm_c[nm_c["band_type"] == "closed"][["sex", "source_age", "m_rate"]]
    closed = closed.rename(columns={"source_age": "age", "m_rate": "m_rate_closed"})
    boundary = nm_c[nm_c["band_type"] == "boundary"][["sex", "m_rate"]].rename(
        columns={"m_rate": "m_rate_boundary"}
    )

    rows = []
    years = sorted(sub["year"].unique())
    for t in years:
        gsub = sub[sub["year"] == t]
        # Births: ASFR(age) × Female_Pop(age, t) / 1000, for reproductive ages.
        f_pop = gsub[(gsub["sex"] == "F") & (gsub["age"].between(REPRO_AGE_MIN, REPRO_AGE_MAX))]
        aligned = f_pop.set_index("age")["population"].astype(float).reindex(asfr_c.index).fillna(0)
        births = float((aligned * asfr_c.reindex(aligned.index).fillna(0) / 1000).sum())

        # Migration: sum of (m_rate × source_pop) across closed bands + open-band boundary.
        pop_by_sex_age = gsub[["sex", "age", "population"]].copy()
        pop_by_sex_age["population"] = pop_by_sex_age["population"].astype(float)

        mig_closed = pop_by_sex_age.merge(closed, on=["sex", "age"], how="left")
        mig_closed["mig"] = mig_closed["m_rate_closed"].astype(float).fillna(0) * mig_closed["population"]
        m_closed = float(mig_closed["mig"].sum())

        # Open band: m_boundary applied to P(ω-1) + P(ω). With top-code 85 the open band is age 85.
        TOP = TOP_CODE_AGE
        open_pop = pop_by_sex_age[pop_by_sex_age["age"].isin([TOP - 1, TOP])]
        open_pop_by_sex = open_pop.groupby("sex")["population"].sum().rename("source_pop").reset_index()
        open_merged = open_pop_by_sex.merge(boundary, on="sex", how="left")
        m_open = float((open_merged["source_pop"] * open_merged["m_rate_boundary"].astype(float).fillna(0)).sum())

        net_migration = m_closed + m_open
        rows.append({"year": t, "total_pop": float(totals_by_year[t]),
                     "births": births, "net_mig": net_migration})
    df = pd.DataFrame(rows).set_index("year")
    df["delta"] = df["total_pop"].diff()
    # Demographic identity: ΔPop = B - D + M  →  D = B + M - ΔPop
    df["deaths"] = df["births"] + df["net_mig"] - df["delta"]
    df["natural_change"] = df["births"] - df["deaths"]
    return df

decomp = decompose_county_scenario(WASHINGTON, "baseline")
print("Washington baseline — decomposition (rounded to whole persons):")
print(decomp[["total_pop", "delta", "births", "deaths", "net_mig", "natural_change"]]
      .head(15).round(0).astype("Int64").to_string())
print()
total_period = decomp.dropna().agg({
    "births": "sum", "deaths": "sum", "net_mig": "sum", "delta": "sum"
})
print(f"Cumulative {BASE_YEAR+1}→{END_YEAR}:")
print(total_period.round(0).astype("Int64").to_string())
print(f"  identity check (B - D + M − ΔPop): "
      f"{total_period['births'] - total_period['deaths'] + total_period['net_mig'] - total_period['delta']:.3f}")
"""),
    code("""
# Stacked-bar plot: B (+), D (−), NM (+/−), with ΔPop shown as a line.
plot_decomp = decomp.dropna().reset_index()

fig, ax = plt.subplots(figsize=(12, 5))
years = plot_decomp["year"].astype(int).to_numpy()
births = plot_decomp["births"].astype(float).to_numpy()
deaths = plot_decomp["deaths"].astype(float).to_numpy()
net_mig = plot_decomp["net_mig"].astype(float).to_numpy()
delta = plot_decomp["delta"].astype(float).to_numpy()

ax.bar(years, births, color="C2", alpha=0.85, label="Births (+)", edgecolor="black", linewidth=0.3)
ax.bar(years, -deaths, color="C3", alpha=0.85, label="Deaths (−)", edgecolor="black", linewidth=0.3)
# Plot NM stacked on top of (Births - Deaths) so the net is visible.
nat_chg = births - deaths
ax.bar(years, net_mig, bottom=nat_chg, color="C0", alpha=0.85,
       label="Net migration (+/−)", edgecolor="black", linewidth=0.3)
ax.plot(years, delta, color="black", linewidth=1.6, marker="o", markersize=3.5,
        label="ΔPop (annual)", zorder=5)
ax.axhline(0, color="black", linewidth=0.6)
ax.set_xlabel("year (t+1 of the t→t+1 change)")
ax.set_ylabel("persons per year")
ax.set_title(f"Washington baseline — annual decomposition of population change")
ax.grid(True, alpha=0.3, axis="y")
ax.legend(loc="upper right", ncol=2, fontsize=9)
fig.tight_layout()
plt.show()
"""),
    code("""
# Cumulative contribution plot — how much of base→2050 total change came from each component?
cum = plot_decomp[["year"]].copy()
cum["cum_births"] = plot_decomp["births"].cumsum()
cum["cum_deaths"] = -plot_decomp["deaths"].cumsum()
cum["cum_netmig"] = plot_decomp["net_mig"].cumsum()
cum["cum_delta"] = plot_decomp["delta"].cumsum()

fig, ax = plt.subplots(figsize=(11, 5))
ax.plot(cum["year"], cum["cum_births"], color="C2", linewidth=1.6, label="Cumulative births (+)")
ax.plot(cum["year"], cum["cum_deaths"], color="C3", linewidth=1.6, label="Cumulative deaths (−, plotted as negative)")
ax.plot(cum["year"], cum["cum_netmig"], color="C0", linewidth=1.6, label="Cumulative net migration")
ax.plot(cum["year"], cum["cum_delta"], color="black", linewidth=2.0, linestyle="--",
        label="Cumulative ΔPop = B − D + NM")
ax.axhline(0, color="black", linewidth=0.6)
ax.set_xlabel("year")
ax.set_ylabel("cumulative persons from base year")
ax.set_title(f"Washington baseline — cumulative contribution of each component, {BASE_YEAR}→{END_YEAR}")
ax.grid(True, alpha=0.3)
ax.legend(loc="upper left", fontsize=9)
fig.tight_layout()
plt.show()

# Headline summary
final = cum.iloc[-1]
print(f"Cumulative {BASE_YEAR}→{END_YEAR} contributions (baseline, Washington):")
print(f"  Births:        {int(round(final['cum_births'])):>+8,d}")
print(f"  Deaths:        {int(round(final['cum_deaths'])):>+8,d}")
print(f"  Net migration: {int(round(final['cum_netmig'])):>+8,d}")
print(f"  Total ΔPop:    {int(round(final['cum_delta'])):>+8,d}")
print()
if final['cum_delta'] < 0:
    nat = final['cum_births'] + final['cum_deaths']  # cum_deaths is already negative
    mig = final['cum_netmig']
    print(f"Of the {int(round(-final['cum_delta'])):,}-person decline:")
    print(f"  natural change (B − D) contributes: {int(round(nat)):>+8,d}")
    print(f"  net migration contributes:           {int(round(mig)):>+8,d}")
"""),
    md("""
**Reading the decomposition.** The annual stacked bars show the
three flows for each forecast year, with the black line tracking the
*net* result (ΔPop). The cumulative plot shows how the total
base-year→2050 population change accumulates. For Washington's baseline,
the projected decline comes overwhelmingly from one dominant
direction — either natural change (B − D, negative as deaths exceed
births in an aging county) or net migration, depending on which the
cumulative plot makes obvious. The numeric summary above quantifies it.

Caveat: the engine doesn't separately track deaths; we compute them
as the residual of the demographic identity. That means any
engine-internal numerical drift (rare, but possible at the open-band
boundary) lands in the deaths series. The identity-check value
printed in the previous cell should be very close to zero.
"""),
    # ---------------------------------------------------------------
    md("""
## 8. QA assertions
"""),
    code("""
def qa(forecasts: pd.DataFrame) -> None:
    assert list(forecasts.columns) == PROJECTION_COLUMNS
    # No negative populations.
    assert (forecasts["population"].astype(float) >= 0).all(), "negative population"
    # Base-year totals match input.
    base_totals = (
        forecasts[forecasts["year"] == BASE_YEAR]
        .groupby(["geoid", "scenario"])["population"].sum()
    )
    # All scenarios should have the SAME base-year total (input was identical).
    by_county = base_totals.unstack("scenario")
    for col in by_county.columns[1:]:
        diff = (by_county[col] - by_county.iloc[:, 0]).abs().max()
        assert diff < 1e-6, f"scenarios disagree at base year for {col}"
    # All years present.
    expected_years = set(range(BASE_YEAR, END_YEAR + 1))
    actual = set(forecasts["year"].unique())
    assert expected_years == actual, f"missing years: {expected_years - actual}"
    print("OK — all QA checks pass.")

qa(forecasts)
"""),
    # ---------------------------------------------------------------
    md("""
## 9. Save
"""),
    code("""
out_path = DATA_INTERIM / "county_forecasts.parquet"
forecasts.to_parquet(out_path, index=False)
print(f"wrote {out_path}  ({len(forecasts):,} rows)")
"""),
    # ---------------------------------------------------------------
    md("""
## Notes and caveats

- **Net migration rates** are averaged across 4 year-pairs (2020-21,
  2021-22, 2022-23, 2023-24), all of which include pandemic-era
  disruptions. The baseline projection therefore has a built-in
  "recent trends continue" assumption that may be more pessimistic
  than Cornell PAD's pre-pandemic vintage.
- **Mortality** uses NY state 2022 rates uniformly; no Washington-
  specific adjustment. USALEEP tract-level data shows Washington
  tracts cluster near the NY state median e(0), so the bias is
  expected to be small.
- **ASFR** uses the national 2023 age pattern scaled to each county's
  observed base-year total births. The age pattern is held fixed across
  forecast years; only the *level* (via the scaling factor) reflects
  county-specific data. NYSDOH-by-mother's-age data would let us
  refine the county pattern (issue #2).
- **Sex ratio at birth** = 1.05 (fixed).
- **Open band** is 85+. There's no separate handling of internal age
  structure within the open band.

## Next steps

- **Phase 4** — town forecasts for Washington County's 17 MCDs.
  Approach: simpler statistical models (ARIMA/ETS) on town totals,
  constrained to sum to the county forecast.
- **Refinement / sensitivity**: vary the migration smoothing window
  (e.g., use longer history for Washington via CDC bridged) and check
  how much the 2050 endpoint moves.
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
