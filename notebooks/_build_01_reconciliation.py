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

Following the R project's investigation (see
`docs/r_reference/create_county_population_control_totals.qmd`) plus our own
review:

1. **Decennial census years** (2000, 2010, 2020) — use the decennial census
   count (`CENSUS2010POP` / `Census Base Population`), which is the definitive
   enumeration.
2. **Postcensal years** (≥ 2020) — Census PEP postcensal estimate, latest
   vintage. Census is the authority for the current decade.
3. **Intercensal years** (pre-2020 non-decennial) — **NYSDOL intercensal
   estimate** as primary. Rationale: NYSDOL's annual series extends back to
   1970 with consistent methodology, and was treated as authoritative by the
   legacy R workflow.
4. **Vintage overlap** — when two PEP files cover the same year, prefer the
   later vintage (reflects updated methodology).
5. **Caveat — components of change do NOT reconcile across the decennial
   seam.** Intercensal totals are smoothed to hit the decennial count, but
   the published component series (births, deaths, migration) sums to the
   postcensal (not intercensal) total. We carry both and flag the difference
   as the "intercensal residual" rather than adjusting components.

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
# Rank vintages: later is better.
_VINTAGE_RANK = {"v2010int": 0, "v2020": 1, "v2024": 2}

def resolve_pep_vintage(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["_rank"] = df["vintage"].map(_VINTAGE_RANK).fillna(-1)
    # Within each (geoid, year, kind), keep the highest-ranked vintage.
    idx = (
        df.groupby(["geoid", "year", "kind"])["_rank"].idxmax()
    )
    return df.loc[idx].drop(columns="_rank").reset_index(drop=True)

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
def reconcile(pop_pep_resolved: pd.DataFrame, pop_nysdol: pd.DataFrame) -> pd.DataFrame:
    \"\"\"Apply reconciliation rules; return one row per (geoid, year).\"\"\"
    # --- Rule 1: decennial anchors (2000, 2010, 2020) ----------------
    # Use NYSDOL's "Census Base Population" (kind='census') for all three
    # decennial years. This is a single curated series covering every
    # decennial, making the anchor layer consistent across decades.
    # (Census PEP's CENSUS2010POP agrees; its 2020+ file encodes the April-1
    # 2020 count as ESTIMATESBASE2020, which we keep as kind='estimates_base'
    # in the raw stack rather than re-labeling.)
    decennial = pop_nysdol[
        (pop_nysdol["kind"] == "census")
        & (pop_nysdol["year"].isin([2000, 2010, 2020]))
    ].copy()
    decennial["rule"] = "decennial_census_nysdol"

    # --- Rule 2: postcensal years (2021+) — Census PEP postcensal -----
    postcensal = pop_pep_resolved[
        (pop_pep_resolved["kind"] == "estimate")
        & (pop_pep_resolved["year"] >= 2021)
    ].copy()
    postcensal["rule"] = "postcensal_census_pep"

    # --- Rule 3: intercensal years (non-decennial pre-2020) — NYSDOL --
    intercensal = pop_nysdol[
        (pop_nysdol["kind"] == "intercensal")
        & (pop_nysdol["year"].between(2001, 2019))
        & (~pop_nysdol["year"].isin([2010]))
    ].copy()
    intercensal["rule"] = "intercensal_nysdol"

    chosen = pd.concat(
        [decennial, intercensal, postcensal],
        ignore_index=True,
    )

    # Any (geoid, year) duplicates? There shouldn't be.
    dup = chosen.groupby(["geoid", "year"]).size()
    if (dup > 1).any():
        bad = dup[dup > 1].reset_index()
        raise AssertionError(f"Duplicate (geoid, year) after reconcile:\\n{bad}")

    return (
        chosen.sort_values(["geoid", "year"])
        .reset_index(drop=True)
    )

reconciled = reconcile(pop_pep_resolved, pop_nysdol)
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
## Next steps (Phase 1 continued)

- **Add CDC Bridged-Race loader** for 2010–2020 (age/sex detail; needed for
  cohort-component base year).
- **Add NYSDOH vital statistics loader** (independent births/deaths for
  cross-check against Census rates).
- **Investigate the decennial seam residual** per county — how big is the
  implied mismatch between intercensal smoothing and component sums?
- **Promote the reconciliation logic** from this notebook into
  `src/popfc/reconcile.py` once the rules stabilize.
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
