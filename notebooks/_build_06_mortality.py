"""Generator for notebooks/06_mortality.ipynb."""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf

NOTEBOOK_PATH = Path(__file__).parent / "06_mortality.ipynb"


def md(s: str) -> nbf.NotebookNode:
    return nbf.v4.new_markdown_cell(s.strip("\n"))


def code(s: str) -> nbf.NotebookNode:
    return nbf.v4.new_code_cell(s.strip("\n"))


CELLS = [
    md("""
# 06 — Mortality (Phase 3 prep)

**Goal.** Turn period life tables into the single-year survival rates the
Phase-3 cohort-component engine consumes:

- **Birth** survival `L(0) / radix` — fraction of births surviving to age 0
- **Closed-band** survival `S(x) = L(x+1) / L(x)` for x = 0, …, ω-2
- **Open-band boundary** survival `S(ω) = L(ω) / [L(ω-1) + L(ω)]`,
  applied to `P(ω-1) + P(ω)` to produce `P(ω, t+1)`
  (Preston / Heuveline / Guillot §6.1, combined formulation)

The actual math lives in `popfc.models.mortality`; this notebook just
selects a base life table, runs the conversion, visualizes the result,
and writes `data_interim/survival_rates.parquet`.

## Source selection

Three life tables are available in `data_interim/life_tables.parquet`:

| Source             | Geography       | Vintage     | Method   |
|--------------------|-----------------|-------------|----------|
| NCHS US 2023       | National        | NVSR 74-06  | period   |
| NCHS NY State 2022 | NY (all 62 cos) | NVSR 74-12  | period   |
| NCHS USALEEP       | 2010 Census tracts (NY) | 2010-2015 | abridged |

For projecting Washington County the natural choice is **NY State 2022**
— same state and reasonably current. USALEEP is shown as a diagnostic
to confirm Washington tracts cluster near the state average (or to
quantify deviation if they don't); we are NOT yet using USALEEP to
scale state rates, since the 2010-2015 vintage is stale and tract-level
estimates have large standard errors. That refinement can be added in
Phase 3 if state-level rates leave too much projection residual.
"""),
    # ---------------------------------------------------------------
    code("""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from popfc.data.nchs import load_usaleep_life_expectancy
from popfc.models.mortality import (
    SURVIVAL_RATES_COLUMNS,
    reconstruct_Lx_from_closed_survival,
    survival_rates_from_life_table,
)
from popfc.paths import DATA_INTERIM, FULL_FIPS

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 40)

WASHINGTON = FULL_FIPS  # '36115'
NY_STATE = "36000"
US = "US"

COHORT_MORT = {
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
## 1. Load life tables and inspect the headline numbers
"""),
    code("""
lt = pd.read_parquet(DATA_INTERIM / "life_tables.parquet")
print(f"life_tables.parquet rows: {len(lt):,}")
print(lt.groupby(["source", "vintage", "geoid"]).size().to_string())
print()
# Headline life expectancy at birth.
headline = (
    lt[(lt["age"] == 0) & (lt["source"] == "nchs_nvsr")]
    [["geoid", "geography", "vintage", "sex", "ex"]]
    .sort_values(["geoid", "sex"])
)
print("e(0) — national and state, by sex:")
print(headline.to_string(index=False))
"""),
    # ---------------------------------------------------------------
    md("""
## 2. Compute survival rates from the NCHS NVSR tables
"""),
    code("""
nvsr = lt[lt["source"] == "nchs_nvsr"]
survival = survival_rates_from_life_table(nvsr)
print(f"survival_rates rows: {len(survival):,}")
print(f"band_type counts: {survival['band_type'].value_counts().to_dict()}")
print()
print("Birth and boundary rows (one per geoid × sex):")
print(survival[survival["band_type"] != "closed"][
    ["geoid", "geography", "sex", "band_type", "age", "Sx", "notes"]
].to_string(index=False))
"""),
    # ---------------------------------------------------------------
    md("""
## 3. Mortality curves — annual hazard q(x) = 1 - S(x), by sex (NY 2022)

Log scale lets the infant-mortality dip near age 0, the teen "accident
hump" around 18-25, and the geometric ramp at older ages all show up
on one chart.
"""),
    code("""
def annual_hazard(survival_df: pd.DataFrame, geoid: str) -> pd.DataFrame:
    sub = survival_df[(survival_df["geoid"] == geoid) & (survival_df["band_type"] == "closed")].copy()
    sub["qx"] = (1.0 - sub["Sx"].astype(float)).astype(float)
    return sub[["sex", "age", "qx"]]

ny = annual_hazard(survival, NY_STATE)
fig, ax = plt.subplots(figsize=(10, 5))
for sex, color in [("All", "C0"), ("M", "C2"), ("F", "C3")]:
    sub = ny[ny["sex"] == sex].sort_values("age")
    ax.semilogy(sub["age"], sub["qx"], label=f"NY 2022 {sex}", linewidth=1.4, color=color)
ax.set_xlabel("age")
ax.set_ylabel("annual mortality hazard 1 - S(x) (log scale)")
ax.set_title("NY State period life table (2022) — annual mortality hazard by age, by sex")
ax.grid(True, alpha=0.3)
ax.legend()
fig.tight_layout()
plt.show()
"""),
    # ---------------------------------------------------------------
    md("""
### Crossover ages — where do male and female hazards converge?

Up to ~age 5 they're close; teens diverge (male hazard rises faster);
the gap widens through middle age and narrows again at the oldest
ages. Quantify with the ratio of male to female q(x).
"""),
    code("""
piv = ny.pivot(index="age", columns="sex", values="qx")
piv["M_over_F"] = piv["M"] / piv["F"]
print("Male:Female annual hazard ratio at selected ages:")
selected = [0, 1, 5, 15, 20, 25, 40, 60, 80, 95]
print(piv.loc[selected, ["F", "M", "M_over_F"]]
      .to_string(float_format=lambda x: f'{x:.5f}'))
"""),
    # ---------------------------------------------------------------
    md("""
## 4. Round-trip and identity checks

These mirror the unit tests but are useful inline as documentation of
what "the survival rates are correct" means.
"""),
    code("""
recon = reconstruct_Lx_from_closed_survival(survival)
joined = recon.merge(
    nvsr[["geoid", "year_start", "sex", "age", "Lx"]],
    on=["geoid", "year_start", "sex", "age"],
    how="inner",
)
joined["ratio"] = joined["Lx_recon"].astype(float) / joined["Lx"].astype(float)
print("Lx round-trip ratio across all slices: "
      f"min={joined['ratio'].min():.10f}, max={joined['ratio'].max():.10f}")

# Implied e(0) check.
print("\\nImplied vs table e(0):")
rows = []
for (geoid, year, sex), sub in nvsr.groupby(["geoid", "year_start", "sex"]):
    r = recon[(recon["geoid"] == geoid)
              & (recon["year_start"] == year)
              & (recon["sex"] == sex)].set_index("age")["Lx_recon"]
    omega_lx = float(sub[sub["age_band"].str.endswith("+")]["Lx"].iloc[0])
    T0 = float(r.sum()) + omega_lx
    e0_table = float(sub[sub["age"] == 0]["ex"].iloc[0])
    rows.append({
        "geoid": geoid, "year": year, "sex": sex,
        "e0_table": e0_table, "e0_implied": T0 / 100_000,
        "diff": T0 / 100_000 - e0_table,
    })
print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f'{x:.4f}'))
"""),
    # ---------------------------------------------------------------
    md("""
## 5. USALEEP diagnostic — Washington tracts vs NY state e(0)

USALEEP 2010-2015 publishes life expectancy at birth by Census tract for
all NY. Washington has 17 tracts. We expect tract-level e(0) to cluster
around NY state e(0) for that period; large within-county spread would
argue for tract-level mortality refinement in Phase 4.

Caveat: USALEEP's vintage (2010-2015) does not match NY state's (2022),
so the level shift is partly methodological aging. We're looking at
*within-county spread*, not the level.
"""),
    code("""
wash_tracts = lt[
    (lt["source"] == "nchs_usaleep")
    & (lt["geoid"].str.startswith(WASHINGTON))
    & (lt["age"] == 0)
].copy()
ny_state_e0 = float(nvsr[(nvsr["geoid"] == NY_STATE) & (nvsr["sex"] == "All")
                         & (nvsr["age"] == 0)]["ex"].iloc[0])

print(f"USALEEP NY tract e(0), 2010-2015 — Washington County:")
print(f"  n tracts: {len(wash_tracts)}")
print(f"  range:    {wash_tracts['ex'].min():.1f} - {wash_tracts['ex'].max():.1f}")
print(f"  median:   {wash_tracts['ex'].median():.1f}")
print(f"  iqr:      {wash_tracts['ex'].quantile(0.25):.1f} - {wash_tracts['ex'].quantile(0.75):.1f}")
print(f"\\nFor reference: NY state e(0) 2022 = {ny_state_e0:.1f}")
print("(USALEEP vintage is older, so absolute levels are not directly comparable.)")
"""),
    # ---------------------------------------------------------------
    code("""
fig, ax = plt.subplots(figsize=(9, 4))
ax.hist(wash_tracts["ex"].astype(float), bins=8, alpha=0.75, edgecolor="black")
ax.axvline(float(wash_tracts["ex"].median()), color="C1", linestyle="--",
           label=f"Washington median {wash_tracts['ex'].median():.1f}")
ax.axvline(ny_state_e0, color="C3", linestyle="--",
           label=f"NY state 2022 {ny_state_e0:.1f}")
ax.set_xlabel("life expectancy at birth (years)")
ax.set_ylabel("# tracts")
ax.set_title(f"USALEEP 2010-2015 e(0) by tract — Washington County ({len(wash_tracts)} tracts)")
ax.legend()
ax.grid(True, alpha=0.3)
fig.tight_layout()
plt.show()
"""),
    # ---------------------------------------------------------------
    md("""
## 6. Where does Washington stack up vs other NY counties? — USALEEP-aggregated e(0)

The forecast applies NY State 2022 mortality uniformly to every NY county
(this is a deliberate project choice — small-county life tables aren't
reliable). But it's still useful to ask, descriptively, whether Washington
sits at the high, low, or middle of the NY mortality distribution. We use
USALEEP File A (life expectancy at birth by Census tract, 2010–2015) for
all NY tracts and aggregate to county by taking the **simple mean of
tract e(0)** within each county.

Caveats: (a) USALEEP's vintage (2010–2015) is older than the rest of our
mortality data (NY State 2022); cross-time comparisons aren't valid. We
read these as *relative* standing, not absolute levels. (b) Simple mean of
tract e(0) over-weights small-population tracts. Population-weighted means
would be more rigorous; we lack tract population in the current data load,
so we disclose and stick with the simple mean.
"""),
    code("""
usaleep_ny = load_usaleep_life_expectancy()
usaleep_ny["county_geoid"] = usaleep_ny["geoid"].astype(str).str[:5]

county_e0 = (
    usaleep_ny.groupby("county_geoid")["ex"]
    .agg(["mean", "median", "count"])
    .rename(columns={"mean": "ex_mean", "median": "ex_median", "count": "n_tracts"})
    .reset_index()
    .rename(columns={"county_geoid": "geoid"})
)

# Attach county names from county_components (one row per county-year).
comp = pd.read_parquet(DATA_INTERIM / "county_components.parquet")
name_lookup = (comp.drop_duplicates("geoid")[["geoid", "geography"]]
               .rename(columns={"geography": "county"}))
county_e0 = county_e0.merge(name_lookup, on="geoid", how="left")
county_e0 = county_e0.sort_values("ex_mean").reset_index(drop=True)

print("USALEEP county-level e(0) — full NY ranking (low to high):")
print(county_e0[["geoid", "county", "n_tracts", "ex_mean", "ex_median"]]
      .to_string(index=False, float_format=lambda x: f'{x:.2f}'))
print()
print(f"Distribution: median = {county_e0['ex_mean'].median():.2f}, "
      f"min = {county_e0['ex_mean'].min():.2f}, "
      f"max = {county_e0['ex_mean'].max():.2f}")
"""),
    code("""
fig, ax = plt.subplots(figsize=(8, 14))
y_positions = range(len(county_e0))
bar_colors = ["lightgrey"] * len(county_e0)
labels_to_show = []
for i, row in county_e0.iterrows():
    g = row["geoid"]
    if g in COHORT_MORT:
        # Distinct color for cohort counties; Washington gets the highlight color.
        bar_colors[i] = "C0" if g == WASHINGTON else "C1"
        labels_to_show.append((i, row["county"], row["ex_mean"]))

ax.barh(list(y_positions), county_e0["ex_mean"].astype(float).tolist(),
        color=bar_colors, edgecolor="black", linewidth=0.3)
ax.set_yticks(list(y_positions))
ax.set_yticklabels(county_e0["county"].tolist(), fontsize=7)
ax.axvline(county_e0["ex_mean"].median(), color="black", linestyle="--",
           linewidth=0.8, label=f"NY median = {county_e0['ex_mean'].median():.1f}")
ax.set_xlabel("USALEEP-aggregated county e(0) — simple mean of tract values, 2010-2015 (years)")
ax.set_title("NY counties ranked by life expectancy at birth — Washington (blue) and cohort (orange)")
ax.grid(True, alpha=0.3, axis="x")
ax.legend(loc="lower right", fontsize=8)
ax.set_xlim(left=county_e0["ex_mean"].min() - 1)
fig.tight_layout()
plt.show()

# Tabular relative-standing summary for the cohort.
sub = county_e0[county_e0["geoid"].isin(COHORT_MORT)].copy()
sub["ny_rank"] = county_e0["ex_mean"].rank(ascending=True).astype(int).reindex(sub.index)
sub["ny_percentile"] = (sub["ny_rank"] / len(county_e0) * 100).round(0).astype(int)
print()
print("Cohort relative standing (1 = lowest e(0), 62 = highest):")
print(sub[["county", "geoid", "ex_mean", "ny_rank", "ny_percentile"]]
      .sort_values("ny_rank")
      .to_string(index=False, float_format=lambda x: f'{x:.2f}'))
"""),
    # ---------------------------------------------------------------
    md("""
## 6b. USALEEP county-aggregate life table — Washington vs NY state

Section 6 above ranked counties by simple **tract-mean e(0)**. A more
methodologically sound aggregate uses the **full tract life tables**
(USALEEP File B) and averages qx and Lx across tracts band-by-band,
then rebuilds the county-level lx and ex columns.

This sub-section uses the new `usaleep_county_life_table()` helper
(in `popfc.data.nchs`) to do that. It also computes the same aggregate
for *all NY tracts* combined as a USALEEP-statewide benchmark, so the
Washington-vs-state comparison is apples-to-apples (both 2010-2015,
both via the same aggregation method).
"""),
    code("""
from popfc.data.nchs import load_usaleep_life_table, usaleep_county_life_table

tracts = load_usaleep_life_table()
wash_tracts = tracts[tracts["geoid"].str.startswith(WASHINGTON)]

# Washington county aggregate.
wash_agg = usaleep_county_life_table(
    wash_tracts, county_fips="115", county_name="Washington County, NY"
)


# NY statewide aggregate — band-by-band equal-weight mean across all NY tracts.
def _equal_weight_state_aggregate(tracts_df):
    rows = []
    for age, band in tracts_df.groupby("age"):
        rows.append({
            "age": int(age),
            "age_band": band["age_band"].iloc[0],
            "qx": float(band["qx"].astype(float).mean()),
            "Lx": float(band["Lx"].astype(float).mean()),
        })
    df = pd.DataFrame(rows).sort_values("age").reset_index(drop=True)
    lx = []
    lx_curr = 100_000.0
    for i in range(len(df)):
        lx.append(lx_curr)
        lx_curr *= 1.0 - df.iloc[i]["qx"]
    df["lx"] = lx
    df["Tx"] = df["Lx"][::-1].cumsum()[::-1]
    df["ex"] = df["Tx"].astype(float) / df["lx"].astype(float)
    return df

ny_agg = _equal_weight_state_aggregate(tracts)

cmp = pd.DataFrame({
    "age": wash_agg["age"].astype(int),
    "age_band": wash_agg["age_band"],
    "qx_wash": wash_agg["qx"].astype(float),
    "qx_ny":   ny_agg["qx"].astype(float),
    "ex_wash": wash_agg["ex"].astype(float),
    "ex_ny":   ny_agg["ex"].astype(float),
})
cmp["delta_ex"] = cmp["ex_wash"] - cmp["ex_ny"]
print("Washington vs NY statewide USALEEP-aggregate life table (2010-2015):")
print(cmp.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
print()
e0_w = float(cmp.iloc[0]["ex_wash"])
e0_n = float(cmp.iloc[0]["ex_ny"])
print(f"Washington county-aggregate e(0):  {e0_w:.2f}")
print(f"NY statewide aggregate e(0):       {e0_n:.2f}")
print(f"Washington advantage:              {e0_w - e0_n:+.2f} years")
print()
print("For reference — NY NVSR 2022 (current forecast input):")
ny_nvsr_e0 = float(nvsr[(nvsr['geoid']==NY_STATE) & (nvsr['sex']=='All')
                        & (nvsr['age']==0)]['ex'].iloc[0])
print(f"  e(0) = {ny_nvsr_e0:.2f}  (lower than USALEEP NY 2010-2015, mostly due to post-COVID mortality)")
"""),
    md("""
**Reading this finding.** Washington's mortality is genuinely better
than NY statewide by about **+1.17 years** of life expectancy at birth,
based on the apples-to-apples USALEEP 2010-2015 aggregation. The
advantage is consistent across age bands (about +1.0 to +1.3 years per
band).

**Why we keep NY NVSR 2022 as the forecast default anyway**, despite
this Washington advantage:

- **Period match matters.** Our forecast base year is 2024 and projects
  to 2050. NVSR 2022 is the closest period match available. USALEEP's
  2010-2015 period predates COVID; applying it as-is would understate
  current mortality rates.
- **Abridged → single-year disaggregation is real work.** USALEEP
  publishes 11 age bands (Under 1, 1-4, 5-14, ..., 85+). The
  cohort-component engine needs single-year (0, 1, 2, ..., 85)
  survival probabilities. Disaggregation methods (Coale-Demeny,
  Heligman-Pollard fits) introduce their own assumptions.
- **A clean future refinement** would apply the Washington-vs-NY
  USALEEP differential as a multiplicative *adjustment* to the NVSR
  NY 2022 single-year rates — preserving the period match while
  capturing Washington's mortality advantage. This is queued as a
  future batch; the current default still uses NY NVSR uniformly.

The forecast impact of the +1.17-year e(0) differential, if applied,
would be **modest but measurable**: roughly +200 to +500 additional
Washington residents projected at 2050 (most additional survivors at
the oldest ages where the differential bites hardest).
"""),
    # ---------------------------------------------------------------
    md("""
## 7. Recent mortality trend — Census PEP crude death rate

USALEEP is dated 2010–2015. For a more current view of relative mortality
we use Census PEP's published `RDEATH` (crude death rate per 1,000 mid-year
population) for 2011–2024. **Important caveat:** crude death rate is *not*
age-adjusted, so an older county will show a higher crude rate even if its
age-specific mortality risk is identical. Compare cohort lines in light of
each county's known age structure (e.g., Saratoga has a younger profile
than the rural northern counties).

A demographically clean age-adjusted SMR — observed deaths vs expected
deaths under the NY State 2022 life table — is a worthwhile follow-up but
requires combining the age × sex frame with survival rates; it's deferred
to its own analysis pass.
"""),
    code("""
rate_deaths = comp[comp["measure"] == "rate_deaths"][
    ["geoid", "geography", "year", "value"]
].rename(columns={"value": "rate_deaths"})
rate_deaths["rate_deaths"] = rate_deaths["rate_deaths"].astype(float)

# NY state average (population-weighted) for each year using county_components 'deaths' and pop.
# Simpler: just average the rate across NY counties as a context line.
state_avg = (rate_deaths.groupby("year")["rate_deaths"].mean()
             .rename("ny_county_mean").reset_index())

fig, ax = plt.subplots(figsize=(11, 5))
for g, name in COHORT_MORT.items():
    sub = rate_deaths[rate_deaths["geoid"] == g].sort_values("year")
    lw = 2.0 if g == WASHINGTON else 0.9
    alpha = 1.0 if g == WASHINGTON else 0.6
    ax.plot(sub["year"], sub["rate_deaths"], marker="o", markersize=3,
            linewidth=lw, alpha=alpha, label=name)
ax.plot(state_avg["year"], state_avg["ny_county_mean"], color="black",
        linestyle="--", linewidth=1.0, alpha=0.7, label="NY 62-county mean")
ax.set_xlabel("year")
ax.set_ylabel("Census PEP crude death rate (per 1,000 mid-year pop)")
ax.set_title("Crude death rate trend — Washington + cohort counties vs NY county mean")
ax.grid(True, alpha=0.3)
ax.legend(loc="upper left", fontsize=8, ncol=2)
fig.tight_layout()
plt.show()
"""),
    md("""
**Reading the plot.** Washington and Warren (rural, older age structure)
typically run above the NY-county mean. Saratoga (younger, exurban) runs
below. The 2020–2021 bump across all lines reflects pandemic-era excess
mortality. Crude-rate ordering across counties is partly an age-structure
artifact — a proper SMR analysis (deferred) would adjust this out.
"""),
    # ---------------------------------------------------------------
    md("""
## 8. Save survival rates

We save the NCHS NVSR-derived rates for both US (2023) and NY state
(2022), by sex, in a single tidy parquet. Downstream code (the
cohort-component engine) will pick `geoid='36000'` for any NY county
projection by default.
"""),
    code("""
out_path = DATA_INTERIM / "survival_rates.parquet"
survival.to_parquet(out_path, index=False)
print(f"wrote {out_path}  ({len(survival):,} rows)")
print()
print("Coverage:")
print(survival.groupby(["geoid", "geography", "year_start", "vintage"]).size()
      .rename("rows").reset_index().to_string(index=False))
"""),
    # ---------------------------------------------------------------
    md("""
## 9. QA assertions
"""),
    code("""
def qa(survival: pd.DataFrame) -> None:
    # Schema
    assert list(survival.columns) == SURVIVAL_RATES_COLUMNS
    # Sx in (0, 1]
    Sx = survival["Sx"].astype(float)
    assert (Sx > 0).all() and (Sx <= 1).all(), "Sx out of (0, 1]"
    # Exactly one birth, one boundary per (geoid, year, sex)
    for kind in ("birth", "boundary"):
        per_slice = (
            survival[survival["band_type"] == kind]
            .groupby(["geoid", "year_start", "sex"]).size()
        )
        assert (per_slice == 1).all(), f"{kind}: expected one row per slice"
    # Closed bands cover ages 0..98 (since ω=100) — for NVSR tables only
    closed = survival[survival["band_type"] == "closed"]
    by_slice = closed.groupby(["geoid", "year_start", "sex"])["age"].agg(["min", "max", "count"])
    assert (by_slice["min"] == 0).all()
    assert (by_slice["max"] == 98).all()
    assert (by_slice["count"] == 99).all()
    print("OK — all QA checks pass.")

qa(survival)
"""),
    # ---------------------------------------------------------------
    md("""
## Next steps

- **Notebook 05 — fertility prep**: age-specific fertility rates (ASFR) by
  county. Two sources to weigh: Census PEP rate_births (county-level
  total fertility, ready to use) and NYSDOH births by mother's age
  (better for county-level ASFR but blocked on the deferred API pull,
  issue #2).
- **Notebook 07 — migration prep**: residual net migration by age/sex,
  using `county_components.parquet` plus ACS B07001/B06001 for the age
  pattern of movers.
- **`src/popfc/models/cohort_component.py`** — the actual forecaster
  class that consumes survival rates, ASFR, and net-migration rates.
- **Optional refinement**: if Phase 3 calibration shows NY state rates
  don't fit Washington well, add a Brass-relational adjustment using
  USALEEP for a Washington-specific mortality schedule.
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
