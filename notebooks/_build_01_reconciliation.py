"""Generator for notebooks/01_population_reconciliation.ipynb.

Run from project root (with venv active):
    python notebooks/_build_01_reconciliation.py

Regenerate whenever the notebook's structure needs to change. Actual
analytical iteration should happen in the .ipynb directly; this script
just builds the initial skeleton with narrative markdown + skeleton code.
"""
from __future__ import annotations

from pathlib import Path

import nbformat as nbf

NOTEBOOK_PATH = Path(__file__).parent / "01_population_reconciliation.ipynb"


def md(source: str) -> nbf.NotebookNode:
    return nbf.v4.new_markdown_cell(source.strip("\n"))


def code(source: str) -> nbf.NotebookNode:
    return nbf.v4.new_code_cell(source.strip("\n"))


CELLS = [
    # ---------------------------------------------------------------
    md("""
# 01 — Population Reconciliation

**Goal.** Build a single authoritative annual population series for each New
York county and year (2000–present) from multiple overlapping sources, with
clear provenance.

## Sources

| Source | Years | Geography | Kind |
|---|---|---|---|
| Census PEP 2000–2010 intercensal | 2000–2010 | NY counties | totals only |
| Census PEP 2010–2020 intercensal | 2010–2020 | NY counties | totals + components + rates |
| Census PEP 2020+ postcensal | 2020–2024 | NY counties | totals + components + rates |
| NYSDOL annual estimates | 1970–2023 | NY + counties | totals only |

## Reconciliation rules

Every retained value is a **July 1** estimate. We deliberately do not anchor
on the April 1 decennial enumerations at 2000/2010/2020 — using April 1
counts inside an otherwise July 1 series introduces a ~3-month phase shift
at each decade boundary that distorts trend visualizations and confuses
year-over-year change.

1. **2000–2019** — **NYSDOL July 1 intercensal estimate**. NYSDOL publishes
   an annual July 1 series back to 1970 with consistent methodology, and
   the legacy R workflow used it as the authoritative intercensal source.
   The series flows continuously through the 2000 and 2010 decennials.
2. **2020+** — **Census PEP July 1 postcensal estimate**, latest vintage.
   The Census Bureau anchors PEP's July 1, 2020 value to the April 1, 2020
   decennial count and then carries it forward year by year — so 2020+ is
   PEP's natural domain and we follow that.
3. **Vintage overlap** — when two PEP files cover the same year, we keep
   the later vintage because the Census Bureau revised its methodology in
   the newer release.
4. **Caveat — components of change do NOT reconcile across the decennial
   seam.** The Census Bureau smooths its intercensal July 1 totals so they
   land on the new decennial count at each decade boundary, but the Bureau's
   published components (births, deaths, migration) for those same years
   still sum to the original (unsmoothed) postcensal totals. We carry both
   and flag the difference as the "intercensal residual" rather than
   adjusting the components ourselves.

## Output

- `data_interim/population_all_sources.parquet` — stacked long-format raw series for QA
- `data_interim/population_reconciled.parquet` — single authoritative value per `(geoid, year)`
"""),
    # ---------------------------------------------------------------
    code("""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from popfc.data.census import load_all_pep
from popfc.data.nysdol import load_nysdol_annual
from popfc.paths import DATA_INTERIM, FULL_FIPS
from popfc.reconcile import reconcile_county_population, resolve_pep_vintage

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 40)

WASHINGTON = FULL_FIPS  # '36115'

# Five demographic neighbors used for Phase-1 validation cohort.
NEIGHBORS = {
    "36091": "Saratoga",
    "36113": "Warren",
    "36083": "Rensselaer",
    "36031": "Essex",
    "36021": "Columbia",
}
COHORT = {WASHINGTON: "Washington", **NEIGHBORS}
"""),
    # ---------------------------------------------------------------
    md("""
## 1. Load all raw sources

Each loader emits the canonical long-format `POP_LONG_COLUMNS` schema so we
can stack without any source-specific cleanup here.
"""),
    code("""
pep = load_all_pep(state_filter="36")
pop_pep = pep["population"]
comp_pep = pep["components"]

pop_nysdol = load_nysdol_annual()

# Stack population frames only (components come from Census alone).
# Coerce population to a common nullable Int64 dtype. NYSDOL already emits
# Int64; PEP emits object-dtype (the 2010-2020 CENSUS2010POP column has
# mixed int/str values in the raw CSV). `to_numeric` handles both uniformly.
pop_pep["population"] = pd.to_numeric(
    pop_pep["population"], errors="coerce"
).astype("Int64")
pop_nysdol["population"] = pop_nysdol["population"].astype("Int64")
pop_all = pd.concat([pop_pep, pop_nysdol], ignore_index=True)

print(f"pop_pep:     {len(pop_pep):>6,} rows  "
      f"(vintages: {sorted(pop_pep['vintage'].unique())})")
print(f"pop_nysdol:  {len(pop_nysdol):>6,} rows  "
      f"(vintage:  {pop_nysdol['vintage'].unique().tolist()})")
print(f"comp_pep:    {len(comp_pep):>6,} rows")
print(f"pop_all:     {len(pop_all):>6,} rows (stacked)")
"""),
    # ---------------------------------------------------------------
    md("""
## 2. Source inventory

What years, kinds, and sources are actually covered?
"""),
    code("""
inventory = (
    pop_all.groupby(["source", "vintage", "kind"])["year"]
    .agg(["min", "max", "count"])
    .rename(columns={"min": "year_min", "max": "year_max", "count": "n_rows"})
    .reset_index()
    .sort_values(["source", "year_min", "kind"])
)
inventory
"""),
    # ---------------------------------------------------------------
    md("""
## 3. Washington County across all sources

Pivot every source × kind into a single table so we can see the disagreements
directly. Column headers encode `(source | kind | vintage)`.
"""),
    code("""
def pivot_county(df: pd.DataFrame, geoid: str) -> pd.DataFrame:
    sub = df[df["geoid"] == geoid].copy()
    sub["col"] = (
        sub["source"] + " | " + sub["kind"] + " | " + sub["vintage"]
    )
    wide = (
        sub.pivot_table(
            index="year", columns="col", values="population", aggfunc="first"
        )
        .sort_index()
    )
    return wide

wash_wide = pivot_county(pop_all, WASHINGTON)
wash_wide.tail(15)
"""),
    # ---------------------------------------------------------------
    md("""
### Where do sources disagree?

For each year that has ≥ 2 values, show the spread (max − min) and range.
"""),
    code("""
def spread(df_wide: pd.DataFrame) -> pd.DataFrame:
    stats = pd.DataFrame(index=df_wide.index)
    stats["n_values"] = df_wide.notna().sum(axis=1)
    stats["min"] = df_wide.min(axis=1)
    stats["max"] = df_wide.max(axis=1)
    stats["spread"] = stats["max"] - stats["min"]
    return stats[stats["n_values"] >= 2].sort_values("spread", ascending=False)

spread(wash_wide).head(20)
"""),
    # ---------------------------------------------------------------
    md("""
## 4. Visualize disagreement — Washington + 5 neighbors

One subplot per county. Each line is a (source, kind) combination.
"""),
    code("""
def plot_county_series(df: pd.DataFrame, geoid: str, name: str, ax) -> None:
    sub = df[df["geoid"] == geoid].copy()
    sub["series"] = sub["source"] + "/" + sub["kind"]
    for series_name, g in sub.groupby("series"):
        g = g.sort_values("year")
        ax.plot(g["year"], g["population"], marker="o", markersize=3,
                linewidth=1, label=series_name)
    ax.set_title(f"{name} ({geoid})")
    ax.grid(True, alpha=0.3)
    ax.set_xlabel("year")
    ax.set_ylabel("population")

fig, axes = plt.subplots(3, 2, figsize=(14, 12), sharex=True)
for ax, (geoid, name) in zip(axes.flat, COHORT.items()):
    plot_county_series(pop_all, geoid, name, ax)
# Single legend outside
handles, labels = axes.flat[0].get_legend_handles_labels()
fig.legend(handles, labels, loc="lower center", ncol=3, fontsize=8,
           bbox_to_anchor=(0.5, -0.03))
fig.suptitle("Population series by source/kind — Washington + neighbors",
             fontsize=13)
fig.tight_layout()
plt.show()
"""),
    # ---------------------------------------------------------------
    md("""
## 5. Handle PEP vintage overlap

The three Census PEP files overlap at decennial years (e.g., 2020 appears in
both the 2010–2020 intercensal file and the 2020+ postcensal file). We keep
the **later vintage** for non-decennial overlap, and keep both kinds
(`census` vs `estimate`) for decennial years since they carry distinct
semantic meaning.
"""),
    code("""
# Implementation lives in popfc.reconcile (DEFAULT_PEP_VINTAGE_RANK there).
pop_pep_resolved = resolve_pep_vintage(pop_pep)
print(f"pop_pep:           {len(pop_pep):>6,} rows")
print(f"pop_pep_resolved:  {len(pop_pep_resolved):>6,} rows")
print(f"dropped (older vintage duplicates): "
      f"{len(pop_pep) - len(pop_pep_resolved):,}")

# Sanity: no remaining duplicates on (geoid, year, kind)
dup = pop_pep_resolved.groupby(["geoid", "year", "kind"]).size()
assert (dup == 1).all(), "Unexpected residual duplicates after vintage resolution"
print("OK — no residual duplicates on (geoid, year, kind).")
"""),
    # ---------------------------------------------------------------
    md("""
## 6. Build the reconciled series

Apply the rules from the opening section in priority order. Each row in the
output carries the `source`/`kind`/`vintage` of the selected value, plus a
`rule` column documenting *why* it was chosen.
"""),
    code("""
# Reconciliation rules live in popfc.reconcile.reconcile_county_population.
reconciled = reconcile_county_population(pop_pep_resolved, pop_nysdol)
print(f"reconciled rows: {len(reconciled):,}")
print("\\nRule usage:")
print(reconciled["rule"].value_counts().to_string())
print("\\nYear coverage:",
      f"{reconciled['year'].min()} – {reconciled['year'].max()}")
"""),
    # ---------------------------------------------------------------
    md("""
### Reconciled series — Washington County
"""),
    code("""
reconciled[reconciled["geoid"] == WASHINGTON][
    ["year", "population", "source", "kind", "vintage", "rule"]
].sort_values("year").to_string(index=False)
"""),
    # ---------------------------------------------------------------
    md("""
## 7. QA checks

Verify that the reconciled series satisfies basic sanity constraints:

- one row per `(geoid, year)`
- all 62 NY counties present in every year we claim to cover
- no gaps in the year range per county
- population strictly positive and plausible
"""),
    code("""
def qa_checks(df: pd.DataFrame) -> None:
    # 1. Unique on (geoid, year)
    dup = df.groupby(["geoid", "year"]).size()
    assert (dup == 1).all(), f"Duplicate (geoid, year) rows: {dup[dup > 1]}"

    # 2. All NY counties present every year. NY has 62 counties + 1 state row.
    # State row uses county_fips '000' -> geoid '36000'.
    counties = df[df["county_fips"] != "000"]
    n_counties_per_year = counties.groupby("year")["geoid"].nunique()
    # Some early years might be state-only in some sources; warn rather than fail.
    bad_years = n_counties_per_year[n_counties_per_year != 62]
    if not bad_years.empty:
        print(f"WARNING: years with != 62 counties:\\n{bad_years}")
    else:
        print("OK — all 62 counties present in every year.")

    # 3. No per-county gaps
    def has_gap(g: pd.DataFrame) -> bool:
        years = sorted(g["year"].unique())
        return any(b - a > 1 for a, b in zip(years, years[1:]))
    gaps = counties.groupby("geoid").apply(has_gap, include_groups=False)
    gap_counties = gaps[gaps].index.tolist()
    if gap_counties:
        print(f"WARNING: counties with year gaps: {gap_counties}")
    else:
        print("OK — no per-county year gaps.")

    # 4. Sane populations (positive, ≤ 25M — NY state total ~20M).
    bad_pop = df[(df["population"] <= 0) | (df["population"] > 25_000_000)]
    assert bad_pop.empty, f"Implausible populations:\\n{bad_pop}"
    print(f"OK — all populations in (0, 25M]; min={df['population'].min():,}, "
          f"max={df['population'].max():,}")

qa_checks(reconciled)
"""),
    # ---------------------------------------------------------------
    md("""
## 8. Save outputs

Two parquet files into `data_interim/`:

- `population_all_sources.parquet` — stacked raw series for reference / QA
- `population_reconciled.parquet` — the authoritative series
"""),
    code("""
DATA_INTERIM.mkdir(parents=True, exist_ok=True)

all_sources_path = DATA_INTERIM / "population_all_sources.parquet"
reconciled_path = DATA_INTERIM / "population_reconciled.parquet"

pop_all.to_parquet(all_sources_path, index=False)
reconciled.to_parquet(reconciled_path, index=False)

print(f"wrote {all_sources_path}  ({len(pop_all):,} rows)")
print(f"wrote {reconciled_path}  ({len(reconciled):,} rows)")
"""),
    # ---------------------------------------------------------------
    md("""
## 9. Benchmark overlay — Cornell PAD projection (Washington)

The reconciled Census/NYSDOL series is the *history*. Cornell PAD's
`padprojections115.xls` is the *projection benchmark* this project's
forecast will eventually be compared against. Show them on the same
chart so we can see (a) how PAD lined up with subsequent observed
history, and (b) where PAD projects Washington's population over the
2025–2040 horizon.
"""),
    code("""
from popfc.data.cornell import load_cornell_pad

pad = load_cornell_pad()
pad_totals = pad["totals"]

wash_recon = reconciled[reconciled["geoid"] == WASHINGTON].sort_values("year")
wash_pad = pad_totals[pad_totals["geoid"] == WASHINGTON].sort_values("year")

fig, ax = plt.subplots(figsize=(11, 5))
ax.plot(wash_recon["year"], wash_recon["population"],
        marker="o", markersize=3, linewidth=1.4,
        label="Reconciled (Census/NYSDOL)")
ax.plot(wash_pad["year"], wash_pad["population"],
        marker="s", markersize=3, linewidth=1.2, linestyle="--",
        label=f"Cornell PAD ({wash_pad['vintage'].iloc[0]})")
ax.axvline(2024.5, color="grey", linewidth=0.8, alpha=0.5)
ax.text(2024.7, ax.get_ylim()[1], "→ projection horizon",
        va="top", ha="left", fontsize=9, color="grey")
ax.set_title("Washington County (36115): history vs Cornell PAD projection")
ax.set_xlabel("year")
ax.set_ylabel("population")
ax.grid(True, alpha=0.3)
ax.legend()
fig.tight_layout()
plt.show()

# Side-by-side table for the overlap window 2015–2024.
overlap = pd.merge(
    wash_recon[["year", "population"]].rename(columns={"population": "reconciled"}),
    wash_pad[["year", "population"]].rename(columns={"population": "cornell_pad"}),
    on="year", how="inner",
)
overlap["pad_minus_recon"] = (
    overlap["cornell_pad"].astype("Int64") - overlap["reconciled"].astype("Int64")
)
overlap["pct_diff"] = 100.0 * overlap["pad_minus_recon"].astype("Float64") / overlap["reconciled"].astype("Float64")
print("PAD vs reconciled, overlap years (Washington):")
print(overlap.to_string(index=False, float_format=lambda x: f'{x:,.2f}'))
"""),
    # ---------------------------------------------------------------
    md("""
## Next steps (Phase 1 continued)

- **CDC Bridged-Race loader** — done (`src/popfc/data/cdc.py`).
- **NYSDOH population loader** — done (`src/popfc/data/nysdoh.py`).
- **NYSDOH vital statistics (births/deaths)** — deferred to a follow-on
  API pull (see GitHub issue).
- **Notebook 03 — age/sex audit** (CDC Bridged-Race 1990–2020 vs Census
  SYA 2020–2023, continuity across the 2020 seam).
- **Investigate the decennial seam residual** per county — how big is the
  implied mismatch between intercensal smoothing and component sums?
- **Reconciliation logic** promoted to `src/popfc/reconcile.py` — done.
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
