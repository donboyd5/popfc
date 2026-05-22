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

**Goal.** Run the cohort-component engine from the 2023 base year to
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
| `data_interim/county_agesex_1990_2023.parquet` (base) | 03 |
| `data_raw/cornell/padprojections115.xls` (benchmark) | Cornell |

Survival is NCHS NY State 2022 (rebanded to top-code 85). ASFR is the
county-specific scaled-to-2023 schedule. Net migration is the
2020-2023 three-year average per county-sex-age.

## Scenarios

- **baseline**: ASFR × 1.00, net migration × 1.00
- **low**:      ASFR × 0.85, net migration × 0.70 (heavier out / less in,
                lower fertility)
- **high**:     ASFR × 1.15, net migration × 1.30 (lighter out / more in,
                higher fertility)

Scenario knobs are deliberately simple in v1 — single scalar
multipliers. More expressive scenarios (time-varying paths, age-band
overrides) are out of scope.

## Output

`data_interim/county_forecasts.parquet` — one row per (geoid, year,
sex, age, scenario), 2023-2050.
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
from popfc.models.mortality import survival_rates_from_life_table
from popfc.paths import DATA_INTERIM, FULL_FIPS

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 40)

BASE_YEAR = 2023
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

SCENARIOS = {
    "baseline": {"asfr_multiplier": 1.00, "net_mig_multiplier": 1.00},
    "low":      {"asfr_multiplier": 0.85, "net_mig_multiplier": 0.70},
    "high":     {"asfr_multiplier": 1.15, "net_mig_multiplier": 1.30},
}
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

agesex = pd.read_parquet(DATA_INTERIM / "county_agesex_1990_2023.parquet")
base_all = agesex[
    (agesex["source"] == "census_sya")
    & (agesex["kind"] == "estimate")
    & (agesex["year"] == BASE_YEAR)
][["geoid", "geography", "sex", "age", "population"]].copy()
print(f"base pop rows: {len(base_all):,}; counties: {base_all['geoid'].nunique()}")
"""),
    # ---------------------------------------------------------------
    md("""
## 2. Run the engine for each cohort county × each scenario
"""),
    code("""
results: list[pd.DataFrame] = []
for geoid, name in COHORT.items():
    base = base_all[base_all["geoid"] == geoid].copy()
    if base.empty:
        print(f"WARN: no base pop for {geoid} ({name})")
        continue
    # County-specific 2023 ASFR (use as forecast schedule, held constant).
    asfr_c = asfr_all[
        (asfr_all["geoid"] == geoid) & (asfr_all["year"] == BASE_YEAR)
    ][["age", "asfr_per_1000"]].copy()
    if asfr_c.empty:
        print(f"WARN: no ASFR for {geoid} ({name})")
        continue
    for scenario_name, knobs in SCENARIOS.items():
        out = project_one_county(
            base, BASE_YEAR, END_YEAR,
            survival=survival, asfr=asfr_c, net_mig=net_mig,
            geoid=geoid, geography=name,
            survival_geoid="36000", net_mig_geoid=geoid,
            top_code_age=TOP_CODE_AGE,
            scenario=scenario_name,
            **knobs,
        )
        results.append(out)

forecasts = pd.concat(results, ignore_index=True)
print(f"forecasts rows: {len(forecasts):,}")
print(f"  scenarios: {sorted(forecasts['scenario'].unique())}")
print(f"  year range: {forecasts['year'].min()}-{forecasts['year'].max()}")
"""),
    # ---------------------------------------------------------------
    md("""
## 3. Total population by year × scenario — Washington
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

fig, ax = plt.subplots(figsize=(11, 5))
colors = {"baseline": "C0", "low": "C3", "high": "C2"}
for scen, sub in wash.groupby("scenario"):
    sub = sub.sort_values("year")
    ax.plot(sub["year"], sub["population"], marker="o", markersize=2,
            linewidth=1.4, color=colors[scen], label=f"engine: {scen}")
ax.plot(pad_wash["year"], pad_wash["population"], marker="s", markersize=3,
        linewidth=1.2, color="grey", linestyle="--", label="Cornell PAD (2015-2040)")
ax.axvline(BASE_YEAR, color="black", linewidth=0.6, alpha=0.4)
ax.text(BASE_YEAR + 0.3, ax.get_ylim()[1] * 0.98, "base year",
        ha="left", va="top", fontsize=9, color="black")
ax.set_xlabel("year")
ax.set_ylabel("population")
ax.set_title(f"Washington County forecast — {BASE_YEAR} base, scenarios + Cornell PAD")
ax.grid(True, alpha=0.3)
ax.legend()
fig.tight_layout()
plt.show()
"""),
    # ---------------------------------------------------------------
    md("""
## 4. Cohort summary — 2050 outcomes
"""),
    code("""
y2050 = totals[totals["year"] == END_YEAR].copy()
y2023 = totals[totals["year"] == BASE_YEAR].copy()
joined = y2050.merge(
    y2023.rename(columns={"population": "pop_2023"})[["geoid", "scenario", "pop_2023"]],
    on=["geoid", "scenario"], how="left",
)
joined["pct_change"] = (
    100.0 * (joined["population"] / joined["pop_2023"] - 1.0)
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
## 5. Age structure — Washington 2023 vs 2050 baseline pyramid
"""),
    code("""
def age_pyramid(forecasts: pd.DataFrame, geoid: str, year: int, scenario: str = "baseline"):
    sub = forecasts[
        (forecasts["geoid"] == geoid)
        & (forecasts["year"] == year)
        & (forecasts["scenario"] == scenario)
    ].copy()
    return sub.pivot_table(index="age", columns="sex", values="population", aggfunc="sum")

p2023 = age_pyramid(forecasts, WASHINGTON, 2023)
p2050 = age_pyramid(forecasts, WASHINGTON, 2050)

fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True, sharex=True)
for ax, (df, year) in zip(axes, [(p2023, 2023), (p2050, 2050)]):
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
## 6. Components of the Washington decline — natural change vs migration

Decompose the projected change to show how much comes from natural
increase (births minus deaths) vs net migration.
"""),
    code("""
def decompose_washington_baseline():
    sub = forecasts[
        (forecasts["geoid"] == WASHINGTON)
        & (forecasts["scenario"] == "baseline")
    ]
    totals_by_year = sub.groupby("year")["population"].sum()
    # Total change per year = next-year - this-year
    delta = totals_by_year.diff().rename("delta_pop")
    # Births per year: same formula as the engine.
    from popfc.models.fertility import REPRO_AGE_MAX, REPRO_AGE_MIN
    wash_asfr = asfr_all[
        (asfr_all["geoid"] == WASHINGTON) & (asfr_all["year"] == BASE_YEAR)
    ].set_index("age")["asfr_per_1000"].astype(float)
    births_per_year = []
    for year, gsub in sub.groupby("year"):
        f_pop = gsub[(gsub["sex"] == "F") & (gsub["age"].between(REPRO_AGE_MIN, REPRO_AGE_MAX))]
        aligned = f_pop.set_index("age")["population"].astype(float).reindex(wash_asfr.index).fillna(0)
        b = float((aligned * wash_asfr.reindex(aligned.index).fillna(0) / 1000).sum())
        births_per_year.append({"year": year, "births": b})
    births_df = pd.DataFrame(births_per_year).set_index("year")["births"]
    return pd.DataFrame({"total_pop": totals_by_year, "delta": delta, "births": births_df})

decomp = decompose_washington_baseline()
print(decomp.head(15).round(0).astype("Int64").to_string())
"""),
    # ---------------------------------------------------------------
    md("""
## 7. QA assertions
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
## 8. Save
"""),
    code("""
out_path = DATA_INTERIM / "county_forecasts.parquet"
forecasts.to_parquet(out_path, index=False)
print(f"wrote {out_path}  ({len(forecasts):,} rows)")
"""),
    # ---------------------------------------------------------------
    md("""
## Notes and caveats

- **Net migration rates** are averaged across only 3 year-pairs
  (2020-21, 2021-22, 2022-23), all of which include pandemic-era
  disruptions. The baseline projection therefore has a built-in
  "recent trends continue" assumption that may be more pessimistic
  than Cornell PAD's pre-pandemic vintage.
- **Mortality** uses NY state 2022 rates uniformly; no Washington-
  specific adjustment. USALEEP tract-level data shows Washington
  tracts cluster near the NY state median e(0), so the bias is
  expected to be small.
- **ASFR** uses the national 2023 age pattern scaled to each county's
  observed 2023 total births. The age pattern is held fixed across
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
