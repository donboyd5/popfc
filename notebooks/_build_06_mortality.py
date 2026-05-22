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
## 6. Save survival rates

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
## 7. QA assertions
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
