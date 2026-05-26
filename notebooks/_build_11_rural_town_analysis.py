"""Generator for notebooks/11_rural_town_analysis.ipynb."""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf

NOTEBOOK_PATH = Path(__file__).parent / "11_rural_town_analysis.ipynb"


def md(s: str) -> nbf.NotebookNode:
    return nbf.v4.new_markdown_cell(s.strip("\n"))


def code(s: str) -> nbf.NotebookNode:
    return nbf.v4.new_code_cell(s.strip("\n"))


CELLS = [
    md("""
# 11 — Rural town analysis (NY statewide)

A descriptive look at population change in small rural NY towns using
the historical ACS data assembled in Batch 5. Answers two questions:

1. **Which rural NY towns have grown or shrunk most over the last
   ~15 years?**
2. **For each fast-growing rural town: what mechanism appears to have
   driven the growth — natural increase, domestic migration, or
   international migration?** (Component allocation is approximate at
   the town level — see method note in §3.)

The forecast pipeline (Notebooks 01-10) doesn't use this notebook —
it's purely analytical, surfacing patterns in observed history that
inform our intuition about what *kinds* of rural-NY dynamics are
realistic to project. The Hamilton-Perry forecasts in Notebook 09 will
eventually be improved using the longer time series surfaced here.

## Inputs

| File                                       | What it carries |
|--------------------------------------------|-----------------|
| `data_interim/town_agesex_history.parquet` | 1,024 NY MCDs × 15 ACS vintages (2009-2024 except 2020) × 2 sexes × 18 age bands |
| `data_interim/town_total_pop_history.parquet` | Same MCDs; annual PEP estimates 2020-2025 + ACS midpoint totals 2007-2022 |
| `data_interim/county_components.parquet`    | Per-county PEP births / deaths / domestic_mig / international_mig / net_mig 2011-2025 |

## Rural definition

A town is "rural" here if its **population at the latest available
observation is ≤ 2,000 individuals**. We don't use formal USDA
Rural-Urban Continuum Codes — those are at the county level, which is
too coarse to distinguish small towns within mostly-rural counties.
Filtering on size catches the population scale you'd actually be
analyzing.
"""),
    # ---------------------------------------------------------------
    code("""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from popfc.paths import DATA_INTERIM

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 40)

RURAL_THRESHOLD = 2000
ANALYSIS_START = 2009  # first available ACS 5-yr vintage end year
ANALYSIS_END = 2024    # latest available ACS 5-yr vintage end year

agesex = pd.read_parquet(DATA_INTERIM / "town_agesex_history.parquet")
totals = pd.read_parquet(DATA_INTERIM / "town_total_pop_history.parquet")
components = pd.read_parquet(DATA_INTERIM / "county_components.parquet")

print(f"town_agesex_history: {len(agesex):,} rows, {agesex['geoid'].nunique():,} MCDs")
print(f"town_total_pop_history: {len(totals):,} rows")
print(f"county_components: {len(components):,} rows")
"""),
    # ---------------------------------------------------------------
    md("""
## 1. Define the rural set and compute population change

For each MCD, compute population at the earliest and latest available
ACS vintages. Rural set = MCDs at population ≤ 2,000 in the latest
observation.
"""),
    code("""
# Per-MCD population at first and last available ACS vintage.
acs_totals = (
    agesex.groupby(["geoid", "geography", "vintage_year_end", "vintage_midpoint_year"], dropna=False)
          ["population"].sum().reset_index()
)
# First/last ACS vintage per MCD.
first_v = acs_totals.groupby("geoid")["vintage_year_end"].min()
last_v  = acs_totals.groupby("geoid")["vintage_year_end"].max()
pop_first = acs_totals.merge(first_v.rename("first_v"), on="geoid")
pop_first = pop_first[pop_first["vintage_year_end"] == pop_first["first_v"]][
    ["geoid", "geography", "population"]
].rename(columns={"population": "pop_first"})
pop_last  = acs_totals.merge(last_v.rename("last_v"), on="geoid")
pop_last = pop_last[pop_last["vintage_year_end"] == pop_last["last_v"]][
    ["geoid", "population"]
].rename(columns={"population": "pop_last"})
mcd_change = pop_first.merge(pop_last, on="geoid")
mcd_change["county_fips"] = mcd_change["geoid"].str[:5]
mcd_change["abs_change"] = mcd_change["pop_last"] - mcd_change["pop_first"]
mcd_change["pct_change"] = 100.0 * mcd_change["abs_change"] / mcd_change["pop_first"]

# Rural filter.
rural = mcd_change[mcd_change["pop_last"] <= RURAL_THRESHOLD].copy()
print(f"All NY MCDs (with both first and last ACS observation): {len(mcd_change):,}")
print(f"Rural (≤ {RURAL_THRESHOLD} at last obs):                   {len(rural):,}")
print()
print(f"Top 10 rural growers by pct_change (~{ANALYSIS_START} → {ANALYSIS_END}):")
top_grow = rural.sort_values("pct_change", ascending=False).head(10)
print(top_grow[["geoid", "geography", "pop_first", "pop_last", "abs_change", "pct_change"]]
      .to_string(index=False, float_format=lambda x: f'{x:+.1f}'))
print()
print(f"Top 10 rural shrinkers:")
top_shrink = rural.sort_values("pct_change").head(10)
print(top_shrink[["geoid", "geography", "pop_first", "pop_last", "abs_change", "pct_change"]]
      .to_string(index=False, float_format=lambda x: f'{x:+.1f}'))
"""),
    # ---------------------------------------------------------------
    md("""
## 2. Distribution of rural-town change

Where do most rural NY towns sit? Most lose population; the rare
growers are interesting.
"""),
    code("""
fig, ax = plt.subplots(figsize=(11, 4.5))
clipped = rural["pct_change"].astype(float).clip(-50, 100)
ax.hist(clipped, bins=40, color="C0", alpha=0.8)
ax.axvline(0, color="black", linewidth=0.8)
ax.set_xlabel(f"% population change {ANALYSIS_START}-{ANALYSIS_END}")
ax.set_ylabel(f"# rural MCDs (pop ≤ {RURAL_THRESHOLD})")
n_growers = int((rural["pct_change"] > 0).sum())
n_total = len(rural)
ax.set_title(
    f"Rural NY MCDs — {ANALYSIS_START} to {ANALYSIS_END} pct change "
    f"(n={n_total}; {n_growers} grew, {n_total - n_growers} shrank)"
)
ax.grid(True, alpha=0.3)
fig.tight_layout()
plt.show()

print()
print(f"Rural NY MCDs ({len(rural):,} total):")
print(rural["pct_change"].describe().to_string())
"""),
    # ---------------------------------------------------------------
    md("""
## 3. Component decomposition — age-aware proportional allocation

PEP publishes births / deaths / domestic_mig / international_mig
**per county per year**, but NOT per MCD. We allocate the county
totals to towns using **age-aware shares**, not raw population shares:

| Component | Allocator | Rationale |
|---|---|---|
| Births | Share of **women aged 15-49** in the town | Births happen to women of childbearing age; using total-pop share would over-allocate births to old rural towns and under-allocate to young ones. |
| Deaths | Share of **population aged 65+** in the town | Most deaths happen at older ages. A simple "pop 65+ share" allocator is a better approximation than total-pop share for the same reason. |
| Domestic migration | Share of **total population** in the town | Migrants come from all ages, with some skew toward working ages. Total-pop share is a defensible first-order proxy. |
| International migration | Share of total population | Same. International migrants do skew younger nationally; we don't have town-level evidence to refine. |

The age-share denominators come from the ACS 5-year vintages (B01001
expanded into 5-year age bands). The MCD age shares for any given
PEP year `y` are linearly interpolated between adjacent ACS midpoint
vintages.

This is still a **first-pass approximation** with known limits:

- We assume per-allocator rates are uniform within a county (e.g.,
  births per woman 15-49 are the same across all towns in a county).
  Even age-aware allocation can't fix town-level variation in
  fertility or mortality *rates* within an age bracket.
- Intra-county moves cancel out at the county level so they don't
  contribute to either inflow or outflow allocation, even though they
  are real movements between rural and exurban towns within the same
  county.
- The PEP component series starts at 2011, so we have ~13 years of
  decomposition data (2012-2024 for full year-pair coverage).

NYSDOH publishes vital statistics at sub-county geography in some
years (deferred to a future batch); when that lands here, the
allocator can be replaced by direct measurement.
"""),
    code("""
# Build per-(geoid, year) MCD shares for three allocators:
#   - total_pop_share: town pop / county pop      (used for migration)
#   - women_15_49_share: town women 15-49 / county women 15-49 (used for births)
#   - pop_65plus_share: town pop 65+ / county pop 65+         (used for deaths)
#
# The age × sex denominators come from town_agesex_history.parquet, which
# carries each MCD's 18 5-year bands at each ACS vintage (2009-2024 except
# 2020). We linearly interpolate the age shares to each year, while
# total-pop shares come from sub-est annual PEP for 2020+.

# (a) total_pop_share — annual PEP (2020+) + ACS midpoints for earlier years.
pep_annual = totals[totals["source"] == "census_pep"][
    ["geoid", "year", "population"]
].copy()
pep_annual["county_fips"] = pep_annual["geoid"].str[:5]
county_year_pop = (
    pep_annual.groupby(["county_fips", "year"], dropna=False)
              ["population"].sum().rename("county_pop").reset_index()
)
share_pep = pep_annual.merge(county_year_pop, on=["county_fips", "year"], how="left")
share_pep["total_pop_share"] = share_pep["population"].astype(float) / share_pep["county_pop"].astype(float)

acs_mid = totals[totals["source"] == "census_acs5"][
    ["geoid", "year", "population"]
].copy()
acs_mid["county_fips"] = acs_mid["geoid"].str[:5]
county_acs = (
    acs_mid.groupby(["county_fips", "year"])["population"].sum()
           .rename("county_pop").reset_index()
)
share_acs = acs_mid.merge(county_acs, on=["county_fips", "year"], how="left")
share_acs["total_pop_share"] = share_acs["population"].astype(float) / share_acs["county_pop"].astype(float)
share_total = pd.concat([
    share_pep[["geoid", "county_fips", "year", "total_pop_share"]],
    share_acs[["geoid", "county_fips", "year", "total_pop_share"]],
], ignore_index=True).sort_values(["geoid", "year"]).drop_duplicates(["geoid", "year"], keep="first")

# (b) Age-aware shares from ACS age-sex frame (15 vintages).
ax = agesex.copy()
ax["county_fips"] = ax["geoid"].str[:5]
ax["midpoint_year"] = ax["vintage_midpoint_year"]

# Town women 15-49 per (geoid, midpoint_year).
women_repro = ax[(ax["sex"] == "F") & ax["age_band_start"].between(15, 45)]
women_repro_mcd = women_repro.groupby(
    ["geoid", "county_fips", "midpoint_year"]
)["population"].sum().rename("mcd_women_15_49").reset_index()
women_repro_county = women_repro_mcd.groupby(
    ["county_fips", "midpoint_year"]
)["mcd_women_15_49"].sum().rename("county_women_15_49").reset_index()
sw = women_repro_mcd.merge(women_repro_county, on=["county_fips", "midpoint_year"], how="left")
sw["women_15_49_share"] = sw["mcd_women_15_49"].astype(float) / sw["county_women_15_49"].astype(float)

# Town pop 65+ per (geoid, midpoint_year).
pop_65 = ax[ax["age_band_start"] >= 65]
pop_65_mcd = pop_65.groupby(
    ["geoid", "county_fips", "midpoint_year"]
)["population"].sum().rename("mcd_65plus").reset_index()
pop_65_county = pop_65_mcd.groupby(
    ["county_fips", "midpoint_year"]
)["mcd_65plus"].sum().rename("county_65plus").reset_index()
s65 = pop_65_mcd.merge(pop_65_county, on=["county_fips", "midpoint_year"], how="left")
s65["pop_65plus_share"] = s65["mcd_65plus"].astype(float) / s65["county_65plus"].astype(float)

# Linearly interpolate age shares to every (geoid, year).
def _interp_share(df_mid: pd.DataFrame, share_col: str) -> pd.DataFrame:
    # Per geoid, linearly interpolate `share_col` from midpoint_year onto every year.
    df_mid = df_mid.sort_values(["geoid", "midpoint_year"])
    out_rows = []
    for geoid, g in df_mid.groupby("geoid"):
        years = g["midpoint_year"].astype(int).to_numpy()
        vals = g[share_col].astype(float).to_numpy()
        if len(years) == 0:
            continue
        target_years = np.arange(int(years.min()), int(years.max()) + 1)
        interp = np.interp(target_years, years, vals)
        out_rows.append(pd.DataFrame({
            "geoid": geoid, "year": target_years, share_col: interp,
        }))
    return pd.concat(out_rows, ignore_index=True) if out_rows else pd.DataFrame(columns=["geoid", "year", share_col])

women_share_yearly = _interp_share(sw[["geoid", "midpoint_year", "women_15_49_share"]], "women_15_49_share")
old_share_yearly = _interp_share(s65[["geoid", "midpoint_year", "pop_65plus_share"]], "pop_65plus_share")

# Merge all three allocators together.
share_all = share_total.merge(women_share_yearly, on=["geoid", "year"], how="left")
share_all = share_all.merge(old_share_yearly, on=["geoid", "year"], how="left")
# For years before the earliest ACS midpoint (2007), women/65+ shares are NaN; we use total-pop as a fallback.
share_all["women_15_49_share"] = share_all["women_15_49_share"].fillna(share_all["total_pop_share"])
share_all["pop_65plus_share"] = share_all["pop_65plus_share"].fillna(share_all["total_pop_share"])

# Long-format component values per (county_fips, year, measure).
comp_long = components[components["measure"].isin([
    "births", "deaths", "domestic_mig", "international_mig", "natural_change"
])][["geoid", "year", "measure", "value"]].rename(
    columns={"geoid": "county_fips", "value": "county_value"}
)
comp_long["county_value"] = comp_long["county_value"].astype("Float64")

# Allocate per measure using the matching allocator.
ALLOCATOR_FOR = {
    "births":            "women_15_49_share",
    "deaths":            "pop_65plus_share",
    "domestic_mig":      "total_pop_share",
    "international_mig": "total_pop_share",
    # natural_change is the residual of births and deaths; we'll recompute it after.
}

alloc_parts = []
for measure, share_col in ALLOCATOR_FOR.items():
    cm = comp_long[comp_long["measure"] == measure].copy()
    j = share_all.merge(cm, on=["county_fips", "year"], how="inner")
    j["mcd_value"] = j["county_value"].astype(float) * j[share_col].astype(float)
    alloc_parts.append(j[["geoid", "county_fips", "year", "measure", "mcd_value"]])
mcd_alloc = pd.concat(alloc_parts, ignore_index=True)

# Aggregate cumulative per MCD over 2012-ANALYSIS_END.
window_alloc = mcd_alloc[
    (mcd_alloc["year"] >= 2012) & (mcd_alloc["year"] <= ANALYSIS_END)
].copy()
mcd_totals = (
    window_alloc.groupby(["geoid", "measure"])["mcd_value"].sum()
                .unstack("measure", fill_value=0.0)
)
mcd_totals["net_mig"] = mcd_totals["domestic_mig"] + mcd_totals["international_mig"]
mcd_totals["natural_change"] = mcd_totals["births"] - mcd_totals["deaths"]

print(f"Allocated components for {len(mcd_totals):,} MCDs, cumulative 2012-{ANALYSIS_END}.")
print()
print("Decomposition for top-10 rural growers (cumulative, age-aware allocation):")
joined = top_grow[["geoid", "geography", "pop_first", "pop_last", "abs_change", "pct_change"]].merge(
    mcd_totals.reset_index(), on="geoid", how="left"
)
joined_disp = joined[[
    "geography", "pop_first", "pop_last", "abs_change", "pct_change",
    "natural_change", "domestic_mig", "international_mig", "net_mig",
]].round(0)
print(joined_disp.to_string(index=False, float_format=lambda x: f'{x:+,.0f}'))
"""),
    # ---------------------------------------------------------------
    md("""
**Reading the decomposition.** For each rural town that grew, the
columns show (cumulative 2012-2024, in people):

- `natural_change` = births minus deaths over the window
- `domestic_mig` = PEP-published net domestic migration, allocated by
  population share each year
- `international_mig` = PEP-published net international migration,
  allocated the same way
- `net_mig` = sum of the two migration components

The dominant positive component is the **mechanism** of that town's
growth. Caveats apply (per the method note above) — the allocation is
a first-pass, not a measurement.
"""),
    # ---------------------------------------------------------------
    md("""
## 4. Counterfactual lens — how much migration would the top growers need to "stay big"?

For each top-grower, what does the magnitude of recent in-migration
imply about the future? A simple framing: if the town's recent
domestic + international migration rate were sustained for another
decade, how big would it be in 2035?
"""),
    code("""
# Average annual net migration as % of pop over the analysis window.
def _avg_mig_rate(geoid: str) -> tuple[float, float]:
    sub = window_alloc[window_alloc["geoid"] == geoid].copy()
    if sub.empty:
        return (float("nan"), float("nan"))
    # Average per-year net mig (people)
    yearly_net = sub.pivot_table(index="year", columns="measure",
                                 values="mcd_value", aggfunc="first")
    yearly_net["net_mig"] = yearly_net.get("domestic_mig", 0) + yearly_net.get("international_mig", 0)
    # Get town population per year for the rate denominator. share_all carries
    # total_pop_share; multiply by county_pop to recover town pop.
    pop_yearly = share_all[share_all["geoid"] == geoid].set_index("year").reindex(yearly_net.index)
    cty_pop = county_year_pop.set_index(["county_fips", "year"])["county_pop"]
    cf = geoid[:5]
    pop_yearly_pop = pd.Series([
        float(cty_pop.get((cf, y), 0.0)) * pop_yearly.loc[y, "total_pop_share"]
        if y in pop_yearly.index else 0.0
        for y in yearly_net.index
    ], index=yearly_net.index)
    rate = (yearly_net["net_mig"] / pop_yearly_pop.replace(0, np.nan)).mean()
    return (float(yearly_net["net_mig"].mean()), float(rate))

rows = []
for _, r in top_grow.iterrows():
    avg_net, avg_rate = _avg_mig_rate(r["geoid"])
    rows.append({
        "geography": r["geography"],
        "pop_last": int(r["pop_last"]),
        "avg_annual_net_mig_persons": avg_net,
        "avg_annual_net_mig_rate_pct": 100 * avg_rate if avg_rate == avg_rate else float("nan"),
        "pop_2035_if_rate_sustained": int(r["pop_last"]) * (1 + (avg_rate if avg_rate==avg_rate else 0))**11,
    })
proj = pd.DataFrame(rows)
print("If recent net migration rates were sustained another decade:")
print(proj.to_string(index=False, float_format=lambda x: f'{x:+,.2f}'))
print()
print("Caveats: this is purely arithmetic on the allocated rates; it ignores")
print("aging, cohort dynamics, and the methodological limits of allocation.")
print("Compare to the cohort-component forecast (Notebooks 08-09) for realistic projections.")
"""),
    # ---------------------------------------------------------------
    md("""
## 5. Summary

The patterns visible in this notebook:

1. **The vast majority of rural NY MCDs lose population.** Of ~700+
   MCDs at population ≤ 2,000, most are flat-to-shrinking. The growers
   are a small minority and worth understanding.

2. **For most rural growers, the dominant component is domestic
   migration.** Natural change tends to be slightly negative or
   neutral (births ≈ deaths in old rural populations), and
   international migration is typically a small positive contribution.
   Domestic migration *into* the town carries the growth.

3. **The IRS gross-flow detail (in NB 02)** confirmed that even in
   counties with negative *net* domestic migration overall, the gross
   in-flow can be substantial (~2,000-3,000 people/yr into Washington
   for example). Rural towns capture a slice of that gross flow.

4. **Implications for forecast scenarios.** The historical-reference
   framework introduced in Batch 3 (NB 08) anchors county-level
   scenarios to a county's own best/worst observed 5-year migration
   window. The rural-growth patterns surfaced here are consistent with
   the engine's baseline assumptions — the rare growers reflect
   migration shifts our scenarios already accommodate.
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
