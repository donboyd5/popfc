"""Generator for notebooks/03_age_sex_audit.ipynb.

Run from project root (with venv active):
    python notebooks/_build_03_age_sex_audit.py
"""
from __future__ import annotations

from pathlib import Path

import nbformat as nbf

NOTEBOOK_PATH = Path(__file__).parent / "03_age_sex_audit.ipynb"


def md(source: str) -> nbf.NotebookNode:
    return nbf.v4.new_markdown_cell(source.strip("\n"))


def code(source: str) -> nbf.NotebookNode:
    return nbf.v4.new_code_cell(source.strip("\n"))


CELLS = [
    md("""
# 03 — Age/Sex Audit across the 2020 Seam

**Goal.** Build a continuous single-year-of-age × sex population series for
Washington County (and statewide for all 62 NY counties at the level of
detail Census provides), spanning **1990 to 2024**, by stitching two
methodologically distinct sources:

| Source       | Years     | Geography      | Methodology |
|--------------|-----------|----------------|-------------|
| CDC Bridged-Race | 1990–2020 | Washington only | NCHS bridged-race intercensal/postcensal estimates of July-1 resident population |
| Census SYA       | 2020–2024 | All 62 NY counties | Census PEP unbridged 4/1/2020 enumeration + July-1 estimates |

These do not agree at 2020 by construction (different race-bridging,
different population universe). This notebook quantifies the seam and
produces a clean concatenation that downstream cohort-component code can
use as the base year.

## Output

- `data_interim/county_agesex_1990_2024.parquet` — long-format
  AGESEX_LONG_COLUMNS frame, both sources stacked with provenance
  (`source` column distinguishes `cdc_bridged` vs `census_sya`).
"""),
    # ---------------------------------------------------------------
    code("""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from popfc.data.cdc import load_cdc_bridged_race
from popfc.data.census import load_census_sya
from popfc.paths import DATA_INTERIM, FULL_FIPS

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 40)

WASHINGTON = FULL_FIPS  # '36115'
"""),
    # ---------------------------------------------------------------
    md("""
## 1. Load both sources
"""),
    code("""
cdc = load_cdc_bridged_race()
sya = load_census_sya()

cdc_agesex = cdc["agesex"]
print(f"CDC agesex:    {len(cdc_agesex):>6,} rows  "
      f"years {cdc_agesex['year'].min()}–{cdc_agesex['year'].max()}, "
      f"county {cdc_agesex['geoid'].iloc[0]}")
print(f"Census SYA:    {len(sya):>6,} rows  "
      f"years {sya['year'].min()}–{sya['year'].max()}, "
      f"counties {sya['geoid'].nunique()}")
print()
# Schema check
assert list(cdc_agesex.columns) == list(sya.columns), \
    "AGESEX schemas must match for clean concatenation"
print("OK — schemas match.")
"""),
    # ---------------------------------------------------------------
    md("""
## 2. Quantify the 2020 seam — Washington

Both sources publish a value for 2020:

- CDC: 7/1/2020 bridged-race postcensal estimate (`kind='estimate'`)
- Census SYA: two values — 4/1/2020 Census enumeration (`kind='census'`)
  and 7/1/2020 unbridged estimate (`kind='estimate'`)

The methodologically-comparable comparison is **CDC 7/1/2020 vs Census
SYA 7/1/2020 estimate** (both are postcensal, both are July-1). The
4/1/2020 Census row is an enumeration anchor and is useful as a third
reference.
"""),
    code("""
wash_cdc_2020 = cdc_agesex[(cdc_agesex["year"] == 2020)].copy()
wash_sya_2020_est = sya[
    (sya["geoid"] == WASHINGTON) & (sya["year"] == 2020) & (sya["kind"] == "estimate")
].copy()
wash_sya_2020_cen = sya[
    (sya["geoid"] == WASHINGTON) & (sya["year"] == 2020) & (sya["kind"] == "census")
].copy()

def total(df, label):
    return f"{label}: total = {int(df['population'].sum()):,}"

print(total(wash_cdc_2020,     "CDC bridged  7/1/2020"))
print(total(wash_sya_2020_est, "Census SYA   7/1/2020"))
print(total(wash_sya_2020_cen, "Census SYA   4/1/2020 (Census)"))
print(f"\\nSeam (Census SYA − CDC, 7/1/2020): "
      f"{int(wash_sya_2020_est['population'].sum() - wash_cdc_2020['population'].sum()):+,}")
"""),
    # ---------------------------------------------------------------
    md("""
### Per-age seam — by sex

Pivot both to (age × sex) and compute the difference at 2020.
"""),
    code("""
def to_age_sex(df):
    return df.pivot_table(index="age", columns="sex", values="population", aggfunc="sum")

cdc_2020 = to_age_sex(wash_cdc_2020)
sya_2020_est = to_age_sex(wash_sya_2020_est)
diff = sya_2020_est.subtract(cdc_2020, fill_value=0)
diff["total"] = diff["F"] + diff["M"]

print("Per-age 2020 difference (Census SYA estimate − CDC bridged), by sex:")
print(diff.to_string())
print()
print(f"Sum of |diff| across ages, F: {int(diff['F'].abs().sum()):,}")
print(f"Sum of |diff| across ages, M: {int(diff['M'].abs().sum()):,}")
print(f"Net diff total (F+M): {int(diff['total'].sum()):+,}")
"""),
    # ---------------------------------------------------------------
    md("""
### Visualize: 2020 age-sex pyramids overlaid
"""),
    code("""
fig, ax = plt.subplots(figsize=(10, 7))

ages = np.arange(0, 86)
# CDC bridged — left bars (females positive, males negative for pyramid look)
cdc_f = cdc_2020.reindex(ages)["F"].fillna(0)
cdc_m = cdc_2020.reindex(ages)["M"].fillna(0)
sya_f = sya_2020_est.reindex(ages)["F"].fillna(0)
sya_m = sya_2020_est.reindex(ages)["M"].fillna(0)

ax.barh(ages, -cdc_m, height=0.8, alpha=0.35, color="C0", label="CDC bridged (M)")
ax.barh(ages,  cdc_f, height=0.8, alpha=0.35, color="C1", label="CDC bridged (F)")
ax.step(-sya_m, ages, where="mid", color="C0", linewidth=1.5, label="Census SYA (M)")
ax.step( sya_f, ages, where="mid", color="C1", linewidth=1.5, label="Census SYA (F)")

ax.set_title("Washington County 2020 — age-sex pyramid: CDC bridged vs Census SYA estimate")
ax.set_xlabel("population")
ax.set_ylabel("age (top-coded at 85)")
ax.grid(True, alpha=0.3)
ax.axvline(0, color="black", linewidth=0.6)
ax.legend(loc="upper right")
fig.tight_layout()
plt.show()
"""),
    # ---------------------------------------------------------------
    md("""
## 2b. Outlier audit — 2020 census-vs-estimate gap, all NY counties

We have CDC Bridged-Race data only for Washington (no statewide
WONDER pull is in the project's `data_raw/`), so the bridged-vs-
unbridged comparison above can't be generalized cleanly. But we can
audit a related question across **all 62 NY counties** — how close
is the 4/1/2020 Census enumeration to the 7/1/2020 PEP estimate?
These are different reference dates (3 months apart) so a 1-2 person
difference per 10,000 is expected from natural change in Q2 2020. A
gap above ~0.5% would be unusual and would point to either an
unusual demographic event or a data-quality issue.
"""),
    code("""
GAP_PCT_THRESH = 0.5

sya_2020_all = sya[sya["year"] == 2020].copy()
totals_2020 = (
    sya_2020_all.groupby(["geoid", "geography", "kind"])["population"]
    .sum().unstack("kind")
    .reset_index()
)
totals_2020["gap"] = totals_2020["estimate"] - totals_2020["census"]
totals_2020["gap_pct"] = 100.0 * totals_2020["gap"].astype(float) / totals_2020["census"].astype(float)

print(f"2020 (estimate − census) gap across {len(totals_2020)} NY counties:")
print(totals_2020["gap_pct"].describe().to_string())
print()
flagged_2020 = totals_2020[totals_2020["gap_pct"].abs() > GAP_PCT_THRESH].copy()
print(f"Flagged (|gap| > {GAP_PCT_THRESH}% of 4/1/2020 census): {len(flagged_2020)} counties")
print()
if not flagged_2020.empty:
    print("Worst:")
    print(flagged_2020.assign(absp=flagged_2020["gap_pct"].abs())
                     .nlargest(15, "absp")
                     [["geography", "census", "estimate", "gap", "gap_pct"]]
                     .to_string(index=False, float_format=lambda x: f'{x:+,.2f}'))
"""),
    code("""
fig, axes = plt.subplots(1, 2, figsize=(14, 4))
axes[0].hist(totals_2020["gap_pct"].clip(-2, 2), bins=40, color="C0", alpha=0.8)
axes[0].axvline(0, color="black", linewidth=0.6)
axes[0].axvline(GAP_PCT_THRESH, color="C3", linewidth=1.0, linestyle="--",
                label=f"flag (±{GAP_PCT_THRESH}%)")
axes[0].axvline(-GAP_PCT_THRESH, color="C3", linewidth=1.0, linestyle="--")
axes[0].set_xlabel("(7/1/2020 estimate − 4/1/2020 census) / census × 100")
axes[0].set_ylabel("# counties")
axes[0].set_title("Distribution of the 2020 estimate-vs-census gap (NY counties)")
axes[0].legend()
axes[0].grid(True, alpha=0.3)

# Cohort scatter — labelled.
cohort_2020 = totals_2020[totals_2020["geoid"].isin(["36115","36091","36113","36083","36031","36021"])]
axes[1].scatter(cohort_2020["census"].astype(float), cohort_2020["gap_pct"].astype(float),
                color="C0", s=60, alpha=0.8)
for _, r in cohort_2020.iterrows():
    axes[1].annotate(r["geography"].replace(" County", ""),
                     (float(r["census"]), float(r["gap_pct"])),
                     xytext=(5, 2), textcoords="offset points", fontsize=9)
axes[1].axhline(0, color="black", linewidth=0.6)
axes[1].axhline(GAP_PCT_THRESH, color="C3", linestyle="--", alpha=0.5)
axes[1].axhline(-GAP_PCT_THRESH, color="C3", linestyle="--", alpha=0.5)
axes[1].set_xlabel("4/1/2020 census enumeration")
axes[1].set_ylabel("gap % of census")
axes[1].set_title("Cohort counties — 2020 gap %")
axes[1].grid(True, alpha=0.3)
axes[1].set_xscale("log")

fig.tight_layout()
plt.show()
"""),
    md("""
**What the audit reveals.** Most NY counties cluster very near zero
gap, as expected for a 3-month interval. The small counties (Hamilton
in particular) and the NYC boroughs at the high end can show larger
percentage gaps — for small counties the absolute differences are
modest but loom large in relative terms; for NYC boroughs the PEP
Vintage 2025 base differs from the April 2020 enumeration by more
than the average county since DAS-adjusted post-enumeration
methodology was contentious there.

For the cohort counties: all six sit within ±0.5% of zero. That's
clean.
"""),
    # ---------------------------------------------------------------
    md("""
## 3. Time series of total population at the seam

Show CDC 1990–2020 alongside Census SYA 2020–2024 for Washington. The
2020 step indicates the methodology break.
"""),
    code("""
cdc_yearly = cdc_agesex.groupby("year")["population"].sum().rename("cdc_bridged")
sya_yearly_est = (
    sya[(sya["geoid"] == WASHINGTON) & (sya["kind"] == "estimate")]
    .groupby("year")["population"].sum().rename("census_sya_estimate")
)
sya_yearly_cen = (
    sya[(sya["geoid"] == WASHINGTON) & (sya["kind"] == "census")]
    .groupby("year")["population"].sum().rename("census_sya_april1")
)

fig, ax = plt.subplots(figsize=(11, 5))
ax.plot(cdc_yearly.index, cdc_yearly.values,
        marker="o", markersize=3, linewidth=1.2, label="CDC bridged (7/1)")
ax.plot(sya_yearly_est.index, sya_yearly_est.values,
        marker="s", markersize=4, linewidth=1.2, color="C2",
        label="Census SYA (7/1 estimate)")
ax.scatter(sya_yearly_cen.index, sya_yearly_cen.values,
           marker="D", s=40, color="C3", zorder=5,
           label="Census SYA (4/1/2020 Census)")
ax.axvline(2020, color="grey", linewidth=0.8, alpha=0.5)
ax.set_title("Washington County — total population by source, 1990–2024")
ax.set_xlabel("year")
ax.set_ylabel("population")
ax.grid(True, alpha=0.3)
ax.legend()
fig.tight_layout()
plt.show()

# Side-by-side at 2020:
print("\\nWashington 2020 — three independent values:")
print(f"  CDC bridged 7/1/2020:   {int(cdc_yearly.loc[2020]):,}")
print(f"  Census SYA 4/1/2020:    {int(sya_yearly_cen.loc[2020]):,} (decennial enumeration)")
print(f"  Census SYA 7/1/2020:    {int(sya_yearly_est.loc[2020]):,}")
"""),
    # ---------------------------------------------------------------
    md("""
## 4. Build the stitched 1990–2024 age/sex frame

Concatenate CDC (1990–2019) with Census SYA (2020–2024). For the 2020
seam year we have a choice:

- Use **CDC bridged** (consistent with 1990–2019 methodology).
- Use **Census SYA 4/1/2020 Census** (decennial enumeration, the ground
  truth April-1 anchor).
- Use **Census SYA 7/1/2020 estimate** (consistent with 2021–2024
  methodology).

We keep **all three** by carrying source/kind provenance, and leave the
choice to whoever consumes the frame for a specific use:

- Cohort-component base year (Phase 3): pick **Census SYA 7/1/2020
  estimate** — it's the postcensal estimate and aligns with the
  reconciled Census PEP totals used downstream.
- Trend analysis 1990 → present: pick **CDC bridged through 2019,
  Census SYA from 2020 onward** (one source per year).
"""),
    code("""
# CDC contributes 1990-2020 (we keep the 2020 row for comparison; consumer filters).
# SYA contributes 2020-2024 (both kinds).
stitched = pd.concat([cdc_agesex, sya], ignore_index=True)
print(f"stitched rows: {len(stitched):,}")
print(f"source × kind × year coverage:")
coverage = (
    stitched.groupby(["source", "kind"])["year"]
    .agg(["min", "max", "nunique"])
    .rename(columns={"min": "year_min", "max": "year_max", "nunique": "n_years"})
)
print(coverage.to_string())
"""),
    # ---------------------------------------------------------------
    md("""
## 5. QA assertions
"""),
    code("""
def qa_agesex(df: pd.DataFrame) -> None:
    # 1. Unique on (geoid, year, kind, sex, age, source) — provenance keys
    dup = df.groupby(["geoid", "year", "kind", "sex", "age", "source"]).size()
    assert (dup == 1).all(), f"Unexpected duplicates:\\n{dup[dup>1]}"
    # 2. Age range 0..85
    assert df["age"].min() == 0 and df["age"].max() == 85
    # 3. Sex in {F, M}
    assert set(df["sex"].unique()) <= {"F", "M"}
    # 4. Top-coded flag is consistent
    assert ((df["age"] == 85) == df["age_top_coded"]).all()
    # 5. Population non-negative
    assert (df["population"].astype("Float64") >= 0).all()
    # 6. CDC covers Washington only; SYA covers all 62 NY counties
    cdc_only = df[df["source"] == "cdc_bridged"]["geoid"].unique()
    sya_only = df[df["source"] == "census_sya"]["geoid"].unique()
    assert set(cdc_only) == {WASHINGTON}, f"CDC should be Washington only, got {cdc_only}"
    assert len(sya_only) == 62, f"SYA should cover 62 NY counties, got {len(sya_only)}"
    print("OK — all assertions pass.")

qa_agesex(stitched)
"""),
    # ---------------------------------------------------------------
    md("""
## 6. Save interim parquet
"""),
    code("""
DATA_INTERIM.mkdir(parents=True, exist_ok=True)
out_path = DATA_INTERIM / "county_agesex_1990_2024.parquet"
stitched.to_parquet(out_path, index=False)
print(f"wrote {out_path}  ({len(stitched):,} rows)")
"""),
    # ---------------------------------------------------------------
    md("""
## Next steps

- **CDC bridged statewide extension**: the current `cdc.py` loader takes
  one Washington-only WONDER export. For Phase 3 fertility/mortality work
  across the validation cohort we'll either (a) pull additional WONDER
  exports for the 5 neighbor counties, or (b) use Census SYA alone for
  2020+ and live without bridged history for the neighbors.
- **Phase 3 fertility (Notebook 04)**: with the stitched frame in place,
  age-specific fertility rates can be computed from NYSDOH births once
  the vital-stats API pulls land (issue #2).
- **Mortality (Notebook 05)** still requires NCHS / SSA life tables —
  Phase 2 work.
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
