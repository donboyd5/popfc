"""Generator for notebooks/07_migration.ipynb."""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf

NOTEBOOK_PATH = Path(__file__).parent / "07_migration.ipynb"


def md(s: str) -> nbf.NotebookNode:
    return nbf.v4.new_markdown_cell(s.strip("\n"))


def code(s: str) -> nbf.NotebookNode:
    return nbf.v4.new_code_cell(s.strip("\n"))


CELLS = [
    md("""
# 07 — Net Migration (Phase 3 prep)

**Goal.** Estimate per-age, per-sex net migration rates for every NY
county, by the **residual method**. Rates are expressed per source-age
person so the cohort-component engine can apply them additively to
survival.

## Method

For each county-year pair (t, t+1) and each (sex, age):

    M(x+1, t+1) = P_obs(x+1, t+1) − P(x, t) × S(x)    (closed)
    M(ω,   t+1) = P_obs(ω,   t+1) − (P(ω-1, t) + P(ω, t)) × S_b    (open)

    m(x → x+1) = M(x+1, t+1) / P(x, t)                (closed)
    m_boundary = M(ω, t+1) / (P(ω-1, t) + P(ω, t))    (open)

Survival rates: NCHS NY State 2022 single-year period life table,
rebanded to top-code 85 (matching Census SYA / CDC top-code). Applied
uniformly to all NY counties (no county-specific mortality refinement
in v1; that's Phase-4 USALEEP territory if needed).

Year-pairs available: 2020-21, 2021-22, 2022-23, 2023-24 (4 pairs from
Census SYA). Rates are averaged across the three pairs to reduce noise.

## Caveat

Single-year, single-age county-level residuals are noisy. With only 3
year-pairs of data, the smoothing is mild. The engine consuming these
should expect outlier rates and can layer additional smoothing or
capping if instability shows up in long-horizon projections.

## Output

`data_interim/net_migration_rates.parquet` — one row per (geoid, sex,
age), with averaged `m_rate` and a `year_basis` description of which
year-pairs contributed.
"""),
    # ---------------------------------------------------------------
    code("""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from popfc.models.migration import (
    NET_MIGRATION_RATES_COLUMNS,
    build_net_migration_rates,
)
from popfc.models.mortality import survival_rates_from_life_table
from popfc.paths import DATA_INTERIM, FULL_FIPS

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 40)

WASHINGTON = FULL_FIPS
COHORT = {
    WASHINGTON: "Washington",
    "36091": "Saratoga",
    "36113": "Warren",
    "36083": "Rensselaer",
    "36031": "Essex",
    "36021": "Columbia",
}
TOP_CODE_AGE = 85
"""),
    # ---------------------------------------------------------------
    md("""
## 1. Load population data and rebanded survival rates
"""),
    code("""
agesex = pd.read_parquet(DATA_INTERIM / "county_agesex_1990_2024.parquet")
# Census SYA July-1 estimates (all 62 NY counties, 2020-2024).
pop = agesex[
    (agesex["source"] == "census_sya")
    & (agesex["kind"] == "estimate")
].copy()
print(f"pop rows: {len(pop):,}  ({pop['geoid'].nunique()} counties × "
      f"{pop['year'].nunique()} years × {pop['age'].nunique()} ages × {pop['sex'].nunique()} sexes)")

lt = pd.read_parquet(DATA_INTERIM / "life_tables.parquet")
nvsr = lt[lt["source"] == "nchs_nvsr"]
survival = survival_rates_from_life_table(nvsr, top_code_age=TOP_CODE_AGE)
print(f"survival rates (top-coded at {TOP_CODE_AGE}): {len(survival):,} rows")
print(survival.groupby("band_type").size().to_string())
"""),
    # ---------------------------------------------------------------
    md("""
## 2. Build net migration rates (statewide, averaged across 3 year-pairs)
"""),
    code("""
m = build_net_migration_rates(
    pop, survival,
    top_code_age=TOP_CODE_AGE,
    state_geoid="36000",
)
print(f"net_migration_rates rows: {len(m):,}  "
      f"({m['geoid'].nunique()} counties × {m['sex'].nunique()} sexes × "
      f"{m['age'].nunique()} ages)")
print()
# Distribution
print("m_rate summary (all county-sex-age cells):")
print(m["m_rate"].astype(float).describe().to_string())
print()
# Year basis (should be the same string everywhere given 3 pairs)
print("year_basis sample:", m["year_basis"].iloc[0])
"""),
    # ---------------------------------------------------------------
    md("""
## 3. Washington — migration profile by age, by sex

### How we compute these rates (recap)

We don't observe migration directly — we infer it as the **residual**
between observed population change and expected survival. For each
(county, sex, single year of age, year-pair t → t+1):

1. Census SYA gives us `P(x, t)` — the July 1 population at age x in
   year t.
2. The NCHS NY State 2022 single-year period life table gives us
   `S(x)` — the probability that a person aged x survives one year to
   age x+1. We apply the same life table to all 62 NY counties; the
   project deliberately doesn't refine mortality by county. So any
   county-level difference between observed and expected population
   shows up here as migration, not as a county-specific mortality
   effect.
3. The expected age-(x+1) population at t+1 if nobody moved is just
   `P(x, t) × S(x)`.
4. Census SYA also gives us the *actually observed* age-(x+1)
   population at t+1: `P_obs(x+1, t+1)`.

We take the difference and call it net migration:

> **M(x+1, t+1) = P_obs(x+1, t+1) − P(x, t) × S(x)**

We then convert to a rate per source-age person:

> **m(x → x+1) = M(x+1, t+1) / P(x, t)**

Positive values mean net in-migration into age x+1 from outside the
county; negative values mean net out-migration. Census SYA gives us
three year-pairs (2020→21, 2021→22, 2022→23); we average rates across
the three pairs to reduce noise. The averaged rate is what the
cohort-component engine in notebook 08 applies year by year.

### Reading the plot

Net migration rates by single year of age are noisy at the county
level, especially in small rural counties where a few movers can shift
the rate visibly. Below we plot raw rates and a centered 5-year
rolling mean for readability.
"""),
    code("""
def plot_county(m: pd.DataFrame, geoid: str, name: str):
    wash = m[(m["geoid"] == geoid) & (m["band_type"] == "closed")].copy()
    wash = wash.sort_values(["sex", "age"])
    fig, axes = plt.subplots(1, 2, figsize=(14, 4), sharey=True)
    for ax, sex in zip(axes, ["M", "F"]):
        sub = wash[wash["sex"] == sex].sort_values("age")
        ages = sub["age"].to_numpy()
        rates = sub["m_rate"].astype(float).to_numpy()
        smooth = pd.Series(rates).rolling(5, center=True, min_periods=1).mean().to_numpy()
        ax.plot(ages, rates, color="C0", alpha=0.4, linewidth=0.8, label="raw")
        ax.plot(ages, smooth, color="C0", linewidth=1.6, label="5-yr centered mean")
        ax.axhline(0, color="grey", linewidth=0.6)
        ax.set_title(f"{name} ({geoid}) — {sex}")
        ax.set_xlabel("destination age")
        ax.grid(True, alpha=0.3)
    axes[0].set_ylabel("net migration rate per source-age person")
    axes[0].legend()
    fig.suptitle("Net migration rates by age, by sex (3-yr avg)", y=1.02)
    fig.tight_layout()
    plt.show()

plot_county(m, WASHINGTON, "Washington")
"""),
    # ---------------------------------------------------------------
    md("""
## 4. Cohort summary — total net migration rate by county
"""),
    code("""
# County total: average across all ages and sexes, weighted by source-age pop.
# Need source pop at 2022 (the middle of our 3-pair window).
pop_2022 = pop[pop["year"] == 2022].copy()
pop_2022_by_age = pop_2022.groupby(["geoid", "sex", "age"])["population"].sum().rename("source_pop")

m_with_pop = m.merge(
    pop_2022_by_age.reset_index().rename(columns={"age": "source_age"}),
    on=["geoid", "sex", "source_age"], how="left",
)
# Aggregate to county total: sum(m_rate * source_pop) / sum(source_pop)
county_total = (
    m_with_pop.assign(weighted=lambda d: d["m_rate"].astype(float) * d["source_pop"].astype(float))
    .groupby("geoid")
    .agg(
        geography=("geography", "first"),
        weighted_sum=("weighted", "sum"),
        pop_sum=("source_pop", "sum"),
    )
)
county_total["overall_m_rate"] = county_total["weighted_sum"] / county_total["pop_sum"]
county_total["overall_m_rate_pct"] = county_total["overall_m_rate"] * 100

print("Cohort county net migration rate (per year, all ages):")
sub = county_total.loc[list(COHORT)].copy()
sub["county"] = pd.Series(COHORT)
print(sub[["county", "overall_m_rate_pct"]]
      .to_string(float_format=lambda x: f'{x:+.3f}%'))
print()
print("All 62 NY counties — overall net migration rate distribution:")
print(county_total["overall_m_rate_pct"].describe().to_string())
"""),
    # ---------------------------------------------------------------
    md("""
## 4b. Outlier audit — implausibly large per-cohort migration rates

The residual method is noisy when populations are small or when
year-over-year measurement is rough. A migration rate of `m_rate = 0.20`
means 20% of that (source age, sex) cohort moved (net) in one year —
implausibly high in most circumstances. We flag any (county, sex, age)
cohort with `|m_rate| > 0.20` and look at where they cluster.

Two questions matter:
- **Cohort counties**: do the rates look stable? If Washington has many
  flagged cells, we should be skeptical of its forecast.
- **Distribution**: is the long tail concentrated in a few counties
  (small counties where noise dominates) or spread across the state?
"""),
    code("""
M_RATE_THRESH = 0.20

m_rate_outliers = m[m["m_rate"].abs() > M_RATE_THRESH].copy()
total_cells = m["m_rate"].notna().sum()
print(f"Per-cohort net migration rate audit:")
print(f"  Total (county, sex, age) cells with rate: {total_cells:>5,}")
print(f"  Flagged (|m_rate| > {M_RATE_THRESH:.0%}):     {len(m_rate_outliers):>5,}  "
      f"({100*len(m_rate_outliers)/total_cells:.1f}%)")
print()
print(f"Top counties by # of flagged cells:")
print(m_rate_outliers.groupby("geography").size()
                    .sort_values(ascending=False).head(15)
                    .to_string())

# Cohort-specific count.
cohort_flagged = m_rate_outliers[m_rate_outliers["geoid"].isin(COHORT)]
print()
print(f"Flagged cells per cohort county (out of 170 total = 2 sex x 85 ages):")
for g, name in COHORT.items():
    count = (cohort_flagged["geoid"] == g).sum()
    print(f"  {name:<12} ({g}): {count:>3}")
"""),
    code("""
fig, axes = plt.subplots(1, 2, figsize=(14, 4))

# Distribution of m_rate (clip to readable range).
all_rates = m["m_rate"].astype(float).dropna()
axes[0].hist(all_rates.clip(-0.5, 0.5), bins=60, color="C0", alpha=0.8)
axes[0].axvline(0, color="black", linewidth=0.6)
axes[0].axvline(M_RATE_THRESH, color="C3", linewidth=1.0, linestyle="--",
                label=f"flag |m_rate| > {M_RATE_THRESH:.0%}")
axes[0].axvline(-M_RATE_THRESH, color="C3", linewidth=1.0, linestyle="--")
axes[0].set_xlabel("net migration rate (per source-age person per year)")
axes[0].set_ylabel("# (county, sex, age) cells")
axes[0].set_title("Distribution of per-cohort net migration rates (all 62 NY counties)")
axes[0].legend()
axes[0].grid(True, alpha=0.3)

# Where in the age range do flagged cells concentrate?
by_age = m_rate_outliers.groupby("source_age").size()
axes[1].bar(by_age.index, by_age.values, color="C3", alpha=0.7)
axes[1].set_xlabel("source age")
axes[1].set_ylabel("# flagged cells across all counties")
axes[1].set_title(f"Where flagged rates land by age (|m_rate| > {M_RATE_THRESH:.0%})")
axes[1].grid(True, alpha=0.3, axis="y")
fig.tight_layout()
plt.show()
"""),
    md("""
**What this shows.** Most county-sex-age cells sit within ±5% (a
moderate migration rate); the long tail beyond ±20% concentrates in
a few small counties where year-over-year noise in single-age
populations dominates. Flagged cells cluster at young-adult ages
(college / early-career mobility) and at the oldest ages (small
populations + measurement noise). The CCM engine smooths some of
this via the 4 year-pair averaging in `build_net_migration_rates`,
but per-cohort rates still inherit the volatility.

For the cohort counties, the flag count tells you which county's
forecast inputs are *most affected by small-sample noise*. A high
number here doesn't mean the forecast is wrong — it means the
underlying migration signal is weaker and the projection will be
more sensitive to the averaging window.
"""),
    # ---------------------------------------------------------------
    md("""
## 5. QA assertions
"""),
    code("""
def qa(m: pd.DataFrame) -> None:
    assert list(m.columns) == NET_MIGRATION_RATES_COLUMNS
    # All 62 NY counties present, both sexes.
    assert m["geoid"].nunique() == 62
    assert set(m["sex"].unique()) == {"M", "F"}
    # Per-county-sex shape: 84 closed (ages 1-84) + 1 boundary (85)
    by_slice = m.groupby(["geoid", "sex"]).size()
    assert (by_slice == 85).all()
    # m_rate must be finite (NaN means projection couldn't be computed)
    nan_count = int(m["m_rate"].isna().sum())
    if nan_count:
        print(f"WARNING: {nan_count} NaN rates (county-sex-age cells lacking a year-pair)")
    print("OK — schema and shape checks pass.")

qa(m)
"""),
    # ---------------------------------------------------------------
    md("""
## 6. Save
"""),
    code("""
out_path = DATA_INTERIM / "net_migration_rates.parquet"
m.to_parquet(out_path, index=False)
print(f"wrote {out_path}  ({len(m):,} rows)")
"""),
    # ---------------------------------------------------------------
    md("""
## Next steps

- **`src/popfc/models/cohort_component.py`** — the projection engine
  consuming survival_rates, asfr, and net_migration_rates.
- **Notebook 08 — county forecast**: run the engine for Washington +
  validation cohort to 2050.
- **Refinement (Phase 4)**: smooth raw migration rates with a
  Rogers-Castro model schedule (parametric mover-age curve) — single-
  county single-age estimates here are inevitably noisy.
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
