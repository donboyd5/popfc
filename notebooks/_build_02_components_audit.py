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
## 2. Demographic identity check (Census PEP, 2011–2024)

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
_VINTAGE_RANK = {"v2010int": 0, "v2020": 1, "v2024": 2}

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

Sort by absolute closure error. Non-zero errors are concentrated at
**decennial seam years** (2020) — see the data-quality note in Notebook
01: intercensal totals are smoothed to hit the decennial count, but the
published components sum to the postcensal total.
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
## 5. Save the components frame

Long-format Census PEP components for downstream forecasting work. NYSDOH
and NCHS vital-stats components are not yet incorporated — they require
API pulls (deferred). When they are added, this notebook should be
re-run and `county_components.parquet` extended with `source='nysdoh'` /
`source='nchs'` rows.
"""),
    code("""
DATA_INTERIM.mkdir(parents=True, exist_ok=True)
components_path = DATA_INTERIM / "county_components.parquet"
comp_pep_res.to_parquet(components_path, index=False)
print(f"wrote {components_path}  ({len(comp_pep_res):,} rows)")
print(f"measures: {sorted(comp_pep_res['measure'].unique())}")
"""),
    # ---------------------------------------------------------------
    md("""
## 6. QA assertions
"""),
    code("""
def qa_components(df: pd.DataFrame) -> None:
    # 1. Unique on (geoid, year, measure, vintage) after resolution
    dup = df.groupby(["geoid", "year", "measure"]).size()
    assert (dup == 1).all(), f"Duplicate (geoid, year, measure): {dup[dup>1]}"
    print("OK — unique (geoid, year, measure).")
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

qa_components(comp_pep_res)
"""),
    # ---------------------------------------------------------------
    md("""
## Next steps (Phase 1 continued)

- **Births / deaths API pulls from NYSDOH** (health.data.ny.gov) — open as
  a GitHub issue. Independent counts will let us replace the self-check
  here with a true cross-source comparison.
- **Notebook 03 — age/sex audit**: CDC Bridged-Race 1990–2020 vs Census
  SYA 2020–2023; assess continuity across the 2020 seam.
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
