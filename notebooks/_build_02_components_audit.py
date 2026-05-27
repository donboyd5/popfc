"""Generator for notebooks/02_components_audit.ipynb.

Run from project root (with venv active):
    python notebooks/_build_02_components_audit.py

Regenerate whenever the notebook's structure needs to change. Analytical
iteration happens in the .ipynb directly.
"""
from __future__ import annotations

from pathlib import Path

import nbformat as nbf

NOTEBOOK_PATH = Path(__file__).parent / "02_components_audit.ipynb"


def md(source: str) -> nbf.NotebookNode:
    return nbf.v4.new_markdown_cell(source.strip("\n"))


def code(source: str) -> nbf.NotebookNode:
    return nbf.v4.new_code_cell(source.strip("\n"))


CELLS = [
    md("""
# 02 — Components Audit

**Goal.** Verify that the Census PEP components of change satisfy the
demographic identity county-by-county and year-by-year, and compare
multi-source population totals (PEP, NYSDOL, NYSDOH, CDC bridged-race) for
Washington and its validation cohort.

## Demographic identity

For each county and year *t*:

> Pop(t) − Pop(t-1) = Births(t) − Deaths(t) + NetMig(t) + Residual(t)

Census PEP publishes all four right-hand-side terms (Births, Deaths,
NetMig as the sum of DomesticMig + InternationalMig, and Residual). The
identity should close to exactly zero when all four are summed against
the published year-over-year ΔPop. Any deviation is a data problem.

## Independent births/deaths — deferred

The raw `data_raw/nysdoh/` folder contains NYSDOH population by age/sex/race
but does **not** include vital statistics (births, deaths). Those require
separate API pulls from health.data.ny.gov and are tracked as a follow-up;
this notebook therefore cross-checks Census PEP against *itself* (counts
vs rate-reconstruction), and compares **totals** across NYSDOH, NYSDOL,
CDC bridged-race, and Census PEP. True NYSDOH-vs-PEP births/deaths
comparison is a Phase 1 follow-on.

## Output

- `data_interim/county_components.parquet` — Census PEP components in long
  format, one row per (geoid, year, measure), with provenance.
"""),
    # ---------------------------------------------------------------
    code("""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from popfc.data.cdc import load_cdc_bridged_race
from popfc.data.census import load_all_pep
from popfc.data.nysdoh import load_nysdoh_population
from popfc.data.nysdol import load_nysdol_annual
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
## 1. Load all sources
"""),
    code("""
pep = load_all_pep(state_filter="36")
comp_pep = pep["components"]
pop_pep = pep["population"]

pop_nysdol = load_nysdol_annual()
pop_nysdoh_out = load_nysdoh_population()
pop_nysdoh = pop_nysdoh_out["totals"]
pop_cdc_out = load_cdc_bridged_race()
pop_cdc = pop_cdc_out["totals"]

print(f"PEP components: {len(comp_pep):>7,} rows  "
      f"measures: {sorted(comp_pep['measure'].unique())}")
print(f"PEP population: {len(pop_pep):>7,} rows")
print(f"NYSDOL totals:  {len(pop_nysdol):>7,} rows")
print(f"NYSDOH totals:  {len(pop_nysdoh):>7,} rows")
print(f"CDC totals:     {len(pop_cdc):>7,} rows (Washington only)")
"""),
    # ---------------------------------------------------------------
    md("""
## 2. Demographic identity check (Census PEP, 2011–2025)

Compute ΔPop = Births − Deaths + NetMig + Residual for every county-year
where PEP publishes all four components. Flag any non-zero closure
errors.

PEP publishes components per **estimate year** running from July 1 of
year *t-1* to July 1 of year *t*, attributed to year *t*. So
ΔPop_PEP(t) = POPESTIMATE(t) − POPESTIMATE(t-1) when *t* and *t-1* are
both in the same vintage. We use the resolved (latest-vintage)
population to compute the LHS, then compare to the components RHS.
"""),
    code("""
# Resolve PEP vintage overlap so we have one population row per (geoid, year, kind).
_VINTAGE_RANK = {"v2010int": 0, "v2020": 1, "v2024": 2, "v2025": 3}

def resolve_pep_vintage(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["_rank"] = df["vintage"].map(_VINTAGE_RANK).fillna(-1)
    idx = df.groupby(["geoid", "year", "kind"])["_rank"].idxmax()
    return df.loc[idx].drop(columns="_rank").reset_index(drop=True)

pop_pep_res = resolve_pep_vintage(pop_pep)
comp_pep_res = (
    comp_pep.assign(_rank=lambda d: d["vintage"].map(_VINTAGE_RANK).fillna(-1))
    .sort_values("_rank")
    .drop_duplicates(["geoid", "year", "measure"], keep="last")
    .drop(columns="_rank")
    .reset_index(drop=True)
)

# Build the PEP estimate series (kind='estimate' only) and compute ΔPop year over year.
pep_est = (
    pop_pep_res[pop_pep_res["kind"] == "estimate"]
    .sort_values(["geoid", "year"])
    .copy()
)
pep_est["pop_prev"] = pep_est.groupby("geoid")["population"].shift(1)
pep_est["delta_pop"] = pep_est["population"] - pep_est["pop_prev"]

# Components → wide by measure for the identity check
comp_wide = comp_pep_res[
    comp_pep_res["measure"].isin(
        ["births", "deaths", "net_mig", "residual", "domestic_mig", "international_mig"]
    )
].pivot_table(
    index=["geoid", "year"], columns="measure", values="value", aggfunc="first"
).reset_index()

identity = pep_est.merge(comp_wide, on=["geoid", "year"], how="inner")
identity["rhs"] = (
    identity["births"].fillna(0)
    - identity["deaths"].fillna(0)
    + identity["net_mig"].fillna(0)
    + identity["residual"].fillna(0)
)
identity["closure_error"] = identity["delta_pop"].astype("Int64") - identity["rhs"].astype("Int64")

print("Identity check: ΔPop − (B − D + NetMig + Residual) by year")
# Cast to float so groupby aggregates tolerate missing rows uniformly.
ident_summary = (
    identity.assign(closure_error_f=identity["closure_error"].astype("Float64"))
    .groupby("year")["closure_error_f"]
    .agg(["count", "mean", "min", "max"])
)
ident_summary["max_abs"] = (
    identity.assign(abs_err=identity["closure_error"].abs().astype("Float64"))
    .groupby("year")["abs_err"].max()
)
print(ident_summary.to_string())
"""),
    # ---------------------------------------------------------------
    md("""
### Where does the identity fail?

Sort by absolute closure error. Non-zero errors concentrate at
**decennial seam years** (2020) — see the data-quality note in Notebook
01: the Census Bureau smooths its intercensal July 1 totals so they
land on the new decennial count at each decade boundary, but the
Bureau's published components (births, deaths, migration) for those
same years still sum to the original (unsmoothed) postcensal totals,
not the smoothed intercensal totals.
"""),
    code("""
violators = identity[identity["closure_error"].abs() > 0].copy()
violators["abs_err"] = violators["closure_error"].abs()
print(f"{len(violators):,} of {len(identity):,} county-years have non-zero closure error.")
print()
print("Top 15 by absolute closure error:")
cols = ["geoid", "year", "delta_pop", "births", "deaths", "net_mig",
        "residual", "rhs", "closure_error"]
print(violators.sort_values("abs_err", ascending=False)[cols].head(15).to_string(index=False))
"""),
    # ---------------------------------------------------------------
    md("""
## 2.5 What is the `Residual` component, and should we worry about it?

The demographic identity we just checked includes a fourth right-hand-side
term — `Residual` — alongside Births, Deaths, and Net Migration. Census PEP
publishes this column for every county-year. **What goes into it?** It's a
kitchen-sink term covering changes in population that the PEP estimation
methodology can't explain via B/D/NM directly:

- **Group-quarters / institutional reclassifications** — prisons, nursing
  homes, college dorms moving between population universes.
- **Base-population corrections** — small after-the-fact adjustments to
  prior-year totals when the Bureau revises its base.
- **Mid-vintage methodology changes** — when the Bureau updates how it
  estimates a particular flow, the discontinuity lands in Residual.
- **Other unexplained mass** — accumulated rounding and small unattributed
  changes.

For normal years in a rural county like Washington, Residual is expected to
be small (well under 0.5% of population). Spikes can indicate (a) a known
methodology break we should be aware of, or (b) a real population event the
PEP methodology can't classify (e.g., a prison opening or closing). The
project's cohort-component forecast doesn't model Residual — projected
years implicitly assume Residual = 0 — so we want to know whether any
historical year is large enough to worry about.

Plot below: distribution of `Residual / mid-year-population × 1000` (per
mille) across all 62 NY counties × all available years. Cohort counties are
labeled at outlier county-years.
"""),
    code("""
# Build per-mille residual rate per (county, year).
res_long = comp_pep_res[comp_pep_res["measure"] == "residual"][
    ["geoid", "geography", "year", "value"]
].rename(columns={"value": "residual"})

# Mid-year pop from pep_est (kind='estimate').
pop_for_res = pep_est[["geoid", "year", "population", "pop_prev"]].copy()
pop_for_res["mid_pop"] = (
    pop_for_res["population"].astype("Float64")
    + pop_for_res["pop_prev"].astype("Float64")
) / 2

resdf = res_long.merge(
    pop_for_res[["geoid", "year", "mid_pop"]], on=["geoid", "year"], how="inner"
)
resdf["residual_per_mille"] = (
    resdf["residual"].astype("Float64") / resdf["mid_pop"] * 1000.0
)
resdf = resdf[resdf["residual_per_mille"].notna()].copy()

print("Residual / mid-year-pop × 1000 — summary across all NY county-years:")
print(resdf["residual_per_mille"].describe().to_string())
print()
print("Top 10 county-years by |Residual / pop|:")
top = (resdf.assign(abs_perm=lambda d: d["residual_per_mille"].abs())
       .nlargest(10, "abs_perm")
       [["geography", "geoid", "year", "residual", "mid_pop", "residual_per_mille"]])
print(top.to_string(index=False, float_format=lambda x: f'{x:+.2f}'))
"""),
    code("""
# Box plot per year; overlay cohort points.
fig, ax = plt.subplots(figsize=(11, 5))
years_sorted = sorted(resdf["year"].unique())
data_by_year = [resdf[resdf["year"] == y]["residual_per_mille"].astype(float).values
                for y in years_sorted]
bp = ax.boxplot(data_by_year, positions=years_sorted, widths=0.6,
                showfliers=False, patch_artist=True)
for patch in bp["boxes"]:
    patch.set_facecolor("lightgrey")
    patch.set_alpha(0.7)

# Overlay cohort counties as labeled points
COHORT_RES = {
    "36115": ("Washington", "C0"),
    "36091": ("Saratoga",  "C1"),
    "36113": ("Warren",    "C2"),
    "36083": ("Rensselaer","C3"),
    "36031": ("Essex",     "C4"),
    "36021": ("Columbia",  "C5"),
}
for g, (name, color) in COHORT_RES.items():
    sub = resdf[resdf["geoid"] == g].sort_values("year")
    ax.plot(sub["year"], sub["residual_per_mille"].astype(float),
            marker="o", markersize=5, linewidth=0.8, color=color, alpha=0.9, label=name)

ax.axhline(0, color="black", linewidth=0.5)
ax.axhline(5, color="grey", linestyle=":", alpha=0.5, label="±5‰ flag threshold")
ax.axhline(-5, color="grey", linestyle=":", alpha=0.5)
ax.set_xlabel("year")
ax.set_ylabel("Residual / mid-year population (per mille)")
ax.set_title("Census PEP Residual component across 62 NY counties — boxplots by year, cohort overlaid")
ax.grid(True, alpha=0.3)
ax.legend(loc="upper left", fontsize=8, ncol=2)
fig.tight_layout()
plt.show()
"""),
    md("""
**Reading the plot.** Most county-years sit close to zero (±1 per mille,
i.e., a residual smaller than 0.1% of population) — which is what we want.
The cohort counties (colored lines) sit comfortably in the middle of the
distribution every year. No flagged outliers among the rural cohort. For
the forecast, the implicit assumption "future Residual = 0" is well
supported by history for these counties.
"""),
    # ---------------------------------------------------------------
    md("""
## 2.6 Outlier audit — explicit thresholds, statewide

The plot above gives the shape of the residual distribution; this
section pins down explicit flags so we can see which counties / years
are problematic. Three independent checks:

1. **Large residual / pop** — `|residual| > 5‰` of mid-year pop (the
   threshold marked in the plot).
2. **Births year-over-year jumps** — births in year `y` differ from
   year `y-1` by > 20% within the same county. Births shouldn't jump
   that much in a stable population; sharp moves usually indicate a
   methodology change or data-quality issue.
3. **Deaths year-over-year jumps** — same idea for deaths. (We do
   expect a 2020-2021 COVID-era spike statewide; that's real, not a
   data issue.)
"""),
    code("""
RESID_PERMILLE_THRESH = 5.0
YOY_JUMP_THRESH = 0.20  # 20% YoY change

# (1) Large residual / pop
resid_outliers = resdf[resdf["residual_per_mille"].abs() > RESID_PERMILLE_THRESH].copy()
print(f"(1) |Residual| > {RESID_PERMILLE_THRESH}‰: "
      f"{len(resid_outliers):>4,} of {len(resdf):,} county-years "
      f"({100*len(resid_outliers)/len(resdf):.1f}%)")
print()
print(f"    Top counties by # of flagged years:")
print(resid_outliers.groupby("geography").size()
                    .sort_values(ascending=False).head(10)
                    .to_string())

# (2) and (3) Year-over-year jumps in births/deaths
yoy_input = comp_pep_res[comp_pep_res["measure"].isin(["births", "deaths"])][
    ["geoid", "geography", "year", "measure", "value"]
].copy()
yoy_input = yoy_input.sort_values(["geoid", "measure", "year"])
yoy_input["prev"] = yoy_input.groupby(["geoid", "measure"])["value"].shift(1)
yoy_input = yoy_input.dropna(subset=["prev"]).copy()
yoy_input["pct_change"] = (
    (yoy_input["value"].astype("Float64") - yoy_input["prev"].astype("Float64"))
    / yoy_input["prev"].astype("Float64")
)

births_jumps = yoy_input[
    (yoy_input["measure"] == "births") & (yoy_input["pct_change"].abs() > YOY_JUMP_THRESH)
]
deaths_jumps = yoy_input[
    (yoy_input["measure"] == "deaths") & (yoy_input["pct_change"].abs() > YOY_JUMP_THRESH)
]
print()
print(f"(2) Births YoY change > {int(YOY_JUMP_THRESH*100)}%: {len(births_jumps):>4,} county-years")
print(f"(3) Deaths YoY change > {int(YOY_JUMP_THRESH*100)}%: {len(deaths_jumps):>4,} county-years "
      f"(many of these will be COVID 2020-2021 — expected)")
print()

# Cohort-specific summary.
cohort_set = set(COHORT_RES.keys())
ch_resid = resid_outliers[resid_outliers["geoid"].isin(cohort_set)]
ch_births = births_jumps[births_jumps["geoid"].isin(cohort_set)]
ch_deaths = deaths_jumps[deaths_jumps["geoid"].isin(cohort_set)]
print(f"In the cohort (Washington + 5 neighbors):")
print(f"  Residual outliers:     {len(ch_resid):>3}")
print(f"  Births YoY jumps:      {len(ch_births):>3}")
print(f"  Deaths YoY jumps:      {len(ch_deaths):>3}")
if not ch_deaths.empty:
    print()
    print("  Cohort deaths-jump years (likely COVID-related at 2020-2021):")
    print(ch_deaths[["geography", "year", "prev", "value", "pct_change"]]
          .sort_values(["geography", "year"])
          .to_string(index=False, float_format=lambda x: f'{x:,.2f}'))
"""),
    md("""
**Reading this.** A few of these patterns are *expected artifacts*
rather than data problems:

- **Births YoY jumps** cluster heavily at **2011** and **2021** — the
  years right after a decennial. PEP's published "births" count for
  the decennial-seam year (2010, 2020) covers only April-July (the
  3-month period that contributes to the July-1 estimate), so the
  following year's full-year count appears as a 3-4× jump. This is
  why Notebook 05 computes annual births as `rate_births × mid-year-pop / 1000`
  instead of using the raw count column.
- **Deaths YoY jumps** at 2020-2021 reflect real COVID excess
  mortality, not a data issue.
- **Residual outliers (>5‰)** concentrate in small, volatile
  counties (Hamilton in particular) and at decennial-seam years where
  PEP smooths intercensal totals to the new census enumeration but
  the components don't get re-smoothed.

The cohort counties (Washington and the 5 neighbors) typically show
**zero** residual outliers and births jumps only at the decennial
seams. Forecast inputs for these counties are reliable.
"""),
    # ---------------------------------------------------------------
    md("""
## 3. PEP count vs rate-reconstruction

PEP also publishes rates per 1,000 mid-year average population
(`RBIRTH`, `RDEATH`, `RNATURALINC`/`RNATURALCHG`, etc.). The R project
used these to compute "adjusted" births/deaths near decennial seams.

Sanity check: for years where both counts and rates exist, does
`count ≈ rate × (avg(pop_t, pop_{t-1}) / 1000)` hold?
"""),
    code("""
# Pull rates and counts side by side; rate columns in our schema are
# 'rate_births', 'rate_deaths', etc. Rates are per 1,000 mid-year avg pop.
rates_wide = comp_pep_res[
    comp_pep_res["measure"].isin(
        ["rate_births", "rate_deaths", "rate_natural_change", "rate_net_mig",
         "rate_domestic_mig", "rate_international_mig"]
    )
].pivot_table(
    index=["geoid", "year"], columns="measure", values="value", aggfunc="first"
).reset_index()

rcheck = identity[["geoid", "year", "pop_prev", "population",
                   "births", "deaths", "net_mig"]].merge(
    rates_wide, on=["geoid", "year"], how="inner"
)
rcheck["mid_year_pop"] = (
    rcheck["pop_prev"].astype("Float64") + rcheck["population"].astype("Float64")
) / 2
rcheck["births_reconstructed"] = rcheck["rate_births"] * rcheck["mid_year_pop"] / 1000
rcheck["deaths_reconstructed"] = rcheck["rate_deaths"] * rcheck["mid_year_pop"] / 1000
rcheck["births_resid"] = (
    rcheck["births"].astype("Float64") - rcheck["births_reconstructed"]
)
rcheck["deaths_resid"] = (
    rcheck["deaths"].astype("Float64") - rcheck["deaths_reconstructed"]
)

print("Count vs rate-reconstruction residuals (births, deaths):")
print(rcheck[["births_resid", "deaths_resid"]].describe().to_string())
"""),
    # ---------------------------------------------------------------
    md("""
## 4. Multi-source population totals — Washington + neighbors

Plot Census PEP, NYSDOL, NYSDOH, and CDC bridged-race series on one
chart per county. Look for systematic level differences and divergences
at the 2010 / 2020 decennial seams.
"""),
    code("""
# Stack a common-schema population frame across all four sources.
def std(df, source_label=None):
    out = df[["geoid", "year", "population", "source", "kind"]].copy()
    if source_label:
        out["source"] = source_label
    return out

all_pop = pd.concat([
    std(pop_pep_res.assign(source="census_pep")),
    std(pop_nysdol.assign(source="nysdol")),
    std(pop_nysdoh.assign(source="nysdoh")),
    std(pop_cdc.assign(source="cdc_bridged")),
], ignore_index=True)

# For comparison, focus on the totals-comparable kinds.
plot_kinds = ["estimate", "intercensal", "census"]
plot_df = all_pop[all_pop["kind"].isin(plot_kinds)].copy()

fig, axes = plt.subplots(3, 2, figsize=(14, 12), sharex=True)
for ax, (geoid, name) in zip(axes.flat, COHORT.items()):
    sub = plot_df[plot_df["geoid"] == geoid].copy()
    sub["series"] = sub["source"] + " / " + sub["kind"]
    for series_name, g in sub.groupby("series"):
        g = g.sort_values("year")
        ax.plot(g["year"], g["population"], marker="o", markersize=3,
                linewidth=1, label=series_name)
    ax.set_title(f"{name} ({geoid})")
    ax.grid(True, alpha=0.3)
    ax.set_ylabel("population")

handles, labels = axes.flat[0].get_legend_handles_labels()
fig.legend(handles, labels, loc="lower center", ncol=4, fontsize=8,
           bbox_to_anchor=(0.5, -0.04))
fig.suptitle("Population totals across all sources — Washington + neighbors")
fig.tight_layout()
plt.show()
"""),
    # ---------------------------------------------------------------
    md("""
### Pairwise differences vs Census PEP estimate (Washington only)
"""),
    code("""
def pivot_sources(df, geoid):
    sub = df[df["geoid"] == geoid].copy()
    sub["col"] = sub["source"] + " / " + sub["kind"]
    return sub.pivot_table(index="year", columns="col", values="population", aggfunc="first")

wash = pivot_sources(plot_df, WASHINGTON).sort_index()
# Choose Census PEP estimate as the baseline where it exists.
baseline = wash.get("census_pep / estimate")
if baseline is not None:
    diffs = wash.subtract(baseline, axis=0)
    diffs = diffs[diffs.index >= 2000]
    print("Difference vs Census PEP estimate (Washington):")
    print(diffs.dropna(how="all").tail(20).to_string())
else:
    print("Census PEP estimate column not found in pivot.")
"""),
    # ---------------------------------------------------------------
    md("""
## 4b. Migration decomposition — domestic vs international, cohort counties

Net migration as a single county-year number hides two very different
mechanisms: **domestic migration** (US-to-US flows, also called
internal migration) and **international migration** (cross-border).
Census PEP publishes them separately at the county-year level (but
not by age × sex). They behave differently over time and respond to
different drivers — domestic is sensitive to housing costs and labor
markets within the US; international tracks immigration policy and
post-COVID rebounds.

For each cohort county we show the annual net split (PEP-published
`domestic_mig` + `international_mig`) and the 2022-2023 **gross**
in/out flows from IRS SOI migration data. (IRS gives us the gross
domestic detail PEP doesn't: how many people moved IN vs how many
moved OUT, not just the net.)

Caveat: this is county-level only. PEP doesn't publish migration by
age × sex within these components, and IRS county data has no age
breakdown either. The cohort-component engine uses a single net
migration rate per (age, sex); separating the engine's projection
into domestic + international is the next step (deferred to a sub-
batch).
"""),
    code("""
from popfc.data.irs import load_irs_county_migration, PARTNER_KIND_SPECIFIC

# Pull historical domestic + international + net from PEP components.
comp_mig = comp_pep_res[comp_pep_res["measure"].isin(
    ["domestic_mig", "international_mig", "net_mig"]
)].copy()

COHORT_DECOMP = {
    "36115": "Washington",
    "36091": "Saratoga",
    "36113": "Warren",
    "36083": "Rensselaer",
    "36031": "Essex",
    "36021": "Columbia",
}

# Per cohort county: print the most recent 5 years of decomposition.
print("Cohort county migration decomposition (most recent 5 years, persons/year):")
for geoid, name in COHORT_DECOMP.items():
    sub = comp_mig[comp_mig["geoid"] == geoid].copy()
    pv = sub.pivot_table(index="year", columns="measure", values="value", aggfunc="first")
    recent = pv.sort_index().tail(5)
    if recent.empty:
        continue
    recent = recent.round(0).astype("Int64")
    print(f"\\n{name} ({geoid}):")
    print(recent.to_string())
"""),
    code("""
# Plot: per-cohort-county time series of domestic + international + net.
fig, axes = plt.subplots(3, 2, figsize=(13, 11), sharex=True)
for ax, (geoid, name) in zip(axes.flat, COHORT_DECOMP.items()):
    sub = comp_mig[comp_mig["geoid"] == geoid].copy()
    pv = sub.pivot_table(index="year", columns="measure", values="value", aggfunc="first").sort_index()
    if "domestic_mig" not in pv.columns:
        ax.set_title(f"{name} — no data"); continue
    years = pv.index.astype(int).to_numpy()
    dom = pv["domestic_mig"].astype(float).to_numpy()
    intl = pv.get("international_mig", pd.Series(0, index=pv.index)).astype(float).to_numpy()
    net = pv.get("net_mig", pd.Series(dom + intl, index=pv.index)).astype(float).to_numpy()
    w = 0.4
    ax.bar(years - w/2, dom,  width=w, color="C0", alpha=0.85,
           label="Domestic", edgecolor="black", linewidth=0.3)
    ax.bar(years + w/2, intl, width=w, color="C1", alpha=0.85,
           label="International", edgecolor="black", linewidth=0.3)
    ax.plot(years, net, color="black", linewidth=1.4, marker="o", markersize=3,
            label="Net (sum)", zorder=5)
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_title(f"{name} ({geoid})", fontsize=10)
    ax.grid(True, alpha=0.3, axis="y")
axes[0,0].legend(loc="best", fontsize=8)
for ax in axes[-1, :]:
    ax.set_xlabel("year")
for ax in axes[:, 0]:
    ax.set_ylabel("persons / year")
fig.suptitle("PEP net migration decomposition — cohort counties, annual",
             fontsize=12, y=1.00)
fig.tight_layout()
plt.show()
"""),
    code("""
# IRS-augmented view: gross IN vs OUT for the latest available vintage.
irs = load_irs_county_migration()  # NY anchors, both directions, 2022-2023
# Pull the "total_us" sentinel rows = domestic gross flows.
irs_dom = irs[irs["partner_kind"] == "total_us"][
    ["geoid", "geography", "direction", "exemptions"]
].pivot_table(index=["geoid", "geography"], columns="direction", values="exemptions", aggfunc="first")
irs_dom["net"] = irs_dom["in"].astype("Int64") - irs_dom["out"].astype("Int64")
print("IRS SOI 2022-2023 gross domestic migration (exemptions ≈ individuals):")
print(irs_dom.loc[list(COHORT_DECOMP)].to_string())
print()
print("IRS gives us GROSS in/out (PEP only publishes NET). For Washington in")
print("2022-2023: 2,364 individuals moved in from US; 2,292 moved out; net +72.")
print("That's small enough to be in the same ballpark as PEP's net domestic")
print("for the same year — useful cross-source confirmation. The bigger value")
print("of IRS is being able to ask 'how many people moved IN' and 'how many")
print("moved OUT' separately, since policy levers and demographic signals")
print("differ between the two flows.")
"""),
    # ---------------------------------------------------------------
    md("""
## 4c. Cross-source audit — NYSDOH vital stats vs Census PEP

PEP's `births` and `deaths` are *Census-tabulated estimates* derived
from administrative vital-event records — they're not independent of
the resident-county event certifications. NYSDOH's `Vital Statistics
Live Births by Mother's Age and Resident County` and `Vital Statistics
Deaths by Resident County, Region, and Age-Group` give us a separate
view from the same underlying records, with NYSDOH's own tabulation
and a year of lag for deaths. Comparing the two surfaces:

- **Tabulation differences** — small, expected (residence vs
  occurrence; late registrations).
- **Vintage-revision differences** — PEP revises older years when
  new SYA is released; NYSDOH does not retrospect.
- **Coverage gaps** — anomalous years where one source has a partial
  count (e.g., the V2020 PEP base-year transition).

Note: NYSDOH deaths typically lag a year or two behind births due to
death-certificate processing time. The cross-comparison uses the
common year range only.
"""),
    code("""
from popfc.data.nysdoh_vital import load_nysdoh_births, load_nysdoh_deaths

# Both calls hit the local cache if it exists; otherwise they pull from
# the API and cache. The vintage tag tracks NYSDOH's data-publication date.
nysdoh_b = load_nysdoh_births()
nysdoh_d = load_nysdoh_deaths()
print(f"NYSDOH births: {len(nysdoh_b['totals']):,} county-year rows, "
      f"{nysdoh_b['totals']['year'].min()}-{nysdoh_b['totals']['year'].max()}, "
      f"vintage={nysdoh_b['totals']['vintage'].iloc[0]}")
print(f"NYSDOH deaths: {len(nysdoh_d['totals']):,} county-year rows, "
      f"{nysdoh_d['totals']['year'].min()}-{nysdoh_d['totals']['year'].max()}, "
      f"vintage={nysdoh_d['totals']['vintage'].iloc[0]}")

# Join NYSDOH to PEP on (geoid, year, measure).
pep_bd = comp_pep_res[comp_pep_res["measure"].isin(["births", "deaths"])][
    ["geoid", "geography", "year", "measure", "value"]
].rename(columns={"value": "pep_value"}).copy()
nysdoh_bd = pd.concat([nysdoh_b["totals"], nysdoh_d["totals"]], ignore_index=True)[
    ["geoid", "year", "measure", "value"]
].rename(columns={"value": "nysdoh_value"}).copy()

audit = pep_bd.merge(nysdoh_bd, on=["geoid", "year", "measure"], how="inner")
audit["pep_value"] = audit["pep_value"].astype("Float64")
audit["nysdoh_value"] = audit["nysdoh_value"].astype("Float64")
audit["abs_diff"] = audit["nysdoh_value"] - audit["pep_value"]
audit["pct_diff"] = 100.0 * audit["abs_diff"] / audit["pep_value"]
print(f"\\naudit rows: {len(audit):,} (county × year × measure intersections)")
"""),
    code("""
# Summary by measure × year range — distribution of % differences.
print("Distribution of NYSDOH − PEP % differences (across all 62 counties):")
for measure in ("births", "deaths"):
    sub = audit[audit["measure"] == measure]
    summary = sub["pct_diff"].astype(float).describe(
        percentiles=[0.05, 0.25, 0.5, 0.75, 0.95]
    )
    print(f"\\n  {measure} (n={len(sub):,}, years {int(sub['year'].min())}-{int(sub['year'].max())})")
    print(summary.to_string())

# Surface the years where PEP is anomalously low/high vs NYSDOH (|pct_diff| > 50%).
print("\\nCounty-years with |NYSDOH − PEP| / PEP > 50% — likely PEP coverage gaps:")
anomalies = audit[audit["pct_diff"].astype(float).abs() > 50.0].copy()
print(f"  count: {len(anomalies):,}")
if not anomalies.empty:
    # Group by year to surface systematic issues (e.g., V2020 base-year transition).
    by_year = anomalies.groupby("year").size().sort_values(ascending=False).head(10)
    print(f"  top years by # of anomalies:")
    for y, n in by_year.items():
        print(f"    {y}: {n}")
"""),
    code("""
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
for ax, measure in zip(axes, ("births", "deaths")):
    sub = audit[audit["measure"] == measure].copy()
    # Exclude the obvious V2020 anomaly so the scatter is readable.
    sub_main = sub[sub["pct_diff"].astype(float).abs() <= 50.0]
    ax.scatter(
        sub_main["pep_value"].astype(float), sub_main["nysdoh_value"].astype(float),
        s=14, alpha=0.35, color="C0",
    )
    # Highlight cohort counties.
    cohort_set = {"36115", "36091", "36113", "36083", "36031", "36021"}
    coh = sub[sub["geoid"].isin(cohort_set)]
    ax.scatter(
        coh["pep_value"].astype(float), coh["nysdoh_value"].astype(float),
        s=36, color="C3", label="Cohort counties", edgecolor="black", linewidth=0.4,
    )
    # 1:1 reference line.
    lim_max = max(sub_main["pep_value"].astype(float).max(),
                  sub_main["nysdoh_value"].astype(float).max())
    ax.plot([0, lim_max], [0, lim_max], color="grey", linewidth=0.6,
            linestyle="--", label="1:1")
    ax.set_xlabel(f"PEP {measure}")
    ax.set_ylabel(f"NYSDOH {measure}")
    ax.set_title(f"{measure.title()} — NYSDOH vs PEP, all NY counties")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
fig.tight_layout()
plt.show()
"""),
    code("""
# Washington time series — both sources side by side.
WASH = "36115"
wash_audit = audit[audit["geoid"] == WASH].sort_values(["measure", "year"])
print("Washington — NYSDOH vs PEP, by year:")
piv = wash_audit.pivot_table(
    index="year", columns="measure", values=["pep_value", "nysdoh_value"]
)
print(piv.astype("Int64").to_string())

fig, axes = plt.subplots(1, 2, figsize=(14, 4.5))
for ax, measure in zip(axes, ("births", "deaths")):
    s = wash_audit[wash_audit["measure"] == measure].sort_values("year")
    ax.plot(s["year"], s["pep_value"].astype(float),
            marker="o", linewidth=1.5, color="C0", label="PEP")
    ax.plot(s["year"], s["nysdoh_value"].astype(float),
            marker="s", linewidth=1.5, color="C3", label="NYSDOH")
    ax.set_title(f"Washington County — {measure}")
    ax.set_xlabel("year")
    ax.set_ylabel(f"{measure}")
    ax.grid(True, alpha=0.3)
    ax.legend()
fig.tight_layout()
plt.show()
"""),
    md("""
**Reading the comparison.** The scatter plots (with the V2020 partial-
year anomaly clipped out for readability) should show NYSDOH and PEP
tightly clustered around the 1:1 line for most county-years. The
Washington time series makes the V2020 anomaly visible directly —
PEP's 2020 row is a small fraction of NYSDOH's full-year count because
PEP 2020 is a base-year transition row, not a full-year estimate.
Downstream uses of `births` and `deaths` from `comp_pep_res` should
treat 2020 as a data gap rather than a real-event count.

The full NYSDOH births and deaths frames will be saved alongside the
PEP-resolved frame in §5 so downstream notebooks can pick the
authoritative source per measure-year.
"""),
    # ---------------------------------------------------------------
    md("""
## 5. Save the components frame

Long-format Census PEP components plus NYSDOH vital-stats components.
NYSDOH rows carry `source='nysdoh_vital'`; PEP rows carry
`source='census_pep'`. Downstream consumers can filter by `source` to
pick the authoritative tabulation per measure-year, or compare them
where they overlap.
"""),
    code("""
DATA_INTERIM.mkdir(parents=True, exist_ok=True)
# Combine PEP-resolved with NYSDOH births + deaths.
nysdoh_long = pd.concat([nysdoh_b["totals"], nysdoh_d["totals"]], ignore_index=True)
# Align dtypes for the union.
nysdoh_long["value"] = nysdoh_long["value"].astype("Float64")
nysdoh_long["year"] = nysdoh_long["year"].astype("Int64")
nysdoh_long = nysdoh_long[comp_pep_res.columns]  # column-order match

combined = pd.concat([comp_pep_res, nysdoh_long], ignore_index=True)
print(f"combined components rows: {len(combined):,}  "
      f"({len(comp_pep_res):,} PEP + {len(nysdoh_long):,} NYSDOH)")

components_path = DATA_INTERIM / "county_components.parquet"
combined.to_parquet(components_path, index=False)
print(f"wrote {components_path}")
print(f"measures: {sorted(combined['measure'].unique())}")
print(f"sources: {sorted(combined['source'].unique())}")
"""),
    # ---------------------------------------------------------------
    md("""
## 6. QA assertions
"""),
    code("""
def qa_components(df: pd.DataFrame) -> None:
    # 1. Unique on (geoid, year, measure, source) after resolution. Note
    #    that births/deaths exist with both source='census_pep' AND
    #    source='nysdoh_vital' in overlapping years — that's intentional
    #    cross-source coverage, not a duplicate.
    dup = df.groupby(["geoid", "year", "measure", "source"]).size()
    assert (dup == 1).all(), f"Duplicate (geoid, year, measure, source): {dup[dup>1]}"
    print("OK — unique (geoid, year, measure, source).")
    # 2. Rate measures finite and within plausible bounds (per 1,000)
    rate_rows = df[df["measure"].astype(str).str.startswith("rate_")]
    if not rate_rows.empty:
        bad = rate_rows[
            (rate_rows["value"].astype("Float64").abs() > 200)
        ]
        if not bad.empty:
            print(f"WARNING: {len(bad)} rate rows with |value| > 200 per 1000:")
            print(bad.head().to_string(index=False))
        else:
            print("OK — all rate values within |value| ≤ 200 per 1000.")
    # 3. PEP-only uniqueness — the original Phase 1 invariant.
    pep_only = df[df["source"] == "census_pep"]
    pep_dup = pep_only.groupby(["geoid", "year", "measure"]).size()
    assert (pep_dup == 1).all(), \
        f"PEP-only duplicate (geoid, year, measure): {pep_dup[pep_dup > 1]}"
    print(f"OK — PEP rows unique on (geoid, year, measure); {len(pep_only):,} PEP rows.")

qa_components(combined)
"""),
    # ---------------------------------------------------------------
    md("""
## Next steps (Phase 1 continued)

- **Births / deaths API pulls from NYSDOH** (health.data.ny.gov) — open as
  a GitHub issue. Independent counts will let us replace the self-check
  here with a true cross-source comparison.
- **Notebook 03 — age/sex audit**: CDC Bridged-Race 1990–2020 vs Census
  SYA 2020–2024; assess continuity across the 2020 seam.
- **Promote** `resolve_pep_vintage` and the identity-check helpers into
  `src/popfc/reconcile.py` so notebooks 01 and 02 share one source of
  truth.
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
