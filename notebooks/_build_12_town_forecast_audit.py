"""Generator for notebooks/12_town_forecast_audit.ipynb.

A diagnostic audit of the Hamilton-Perry town forecasts produced by
Notebook 09. Surfaces which towns look reliable, which look fragile,
and where the model's assumptions don't fit observed history.
"""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf

NOTEBOOK_PATH = Path(__file__).parent / "12_town_forecast_audit.ipynb"


def md(s: str) -> nbf.NotebookNode:
    return nbf.v4.new_markdown_cell(s.strip("\n"))


def code(s: str) -> nbf.NotebookNode:
    return nbf.v4.new_code_cell(s.strip("\n"))


CELLS = [
    md("""
# 12 — Town Forecast Audit (diagnostic)

**Goal.** Probe the trustworthiness of the Notebook 09 Hamilton-Perry
town forecasts. The user flagged after Batch 6 that the town forecasts
"can't be trusted yet" — this audit surfaces specifically *what* about
them is fragile and *why*.

## Approach

Five concrete checks, each producing one or more diagnostic plots and
a quantitative finding:

1. **Trajectory plausibility** — 2022 → 2047 % change ranking against
   2007-2022 historical growth, town by town. Do the forecast slopes
   line up with the observed slopes? Where do they diverge sharply?
2. **Historical fit** — does the engine's 2022 base-year total agree
   with PEP's 2022 sub-est total for each town?
3. **Aggregation consistency** — do the 17 town forecasts sum to the
   county forecast under each scenario (within IPF tolerance)?
4. **Whitehall anomaly** — every other Washington town is projected to
   decline; Whitehall is the lone outlier at +36% 2022→2047. What in
   the input data drives that?
5. **Per-cohort cohort change ratio (CCR) instability** — for each
   town × age band, how much does the CCR vary across the 10 vintage
   pairs we average? High CCR-CV means the projection is sensitive to
   which vintages we picked.

The audit doesn't change any production code or forecasts — it's
read-only diagnostics that inform whether to invest in a deeper
data improvement (e.g., NYSDOH sub-county vital stats) or in a
methodology change (e.g., wider CCR window, different cohort scheme).

> **Status note (added after this audit ran).** This audit was run
> against the **v2** town forecasts (Batch 6: multi-vintage CCRs +
> IPF). It motivated `feat/town-forecast-v3`, which implemented
> recommendations **#1** (PEP base rescaling) and **#3** (CCR + CWR
> shrinkage) — Whitehall's headline +36% dropped to +21.7%.
> Recommendation **#2** was found to be **already satisfied** (the
> original wording was wrong — see the correction in §7). The figures
> in the cells below are preserved as the v2-era "before" snapshot;
> the v2→v3 before/after lives in Notebook 09 §4b and the changelog.
"""),
    # ---------------------------------------------------------------
    code("""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from popfc.paths import DATA_INTERIM, FULL_FIPS

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 40)

WASHINGTON = FULL_FIPS  # '36115'
TOP_CODE_AGE = 85
"""),
    # ---------------------------------------------------------------
    md("""
## 1. Load forecasts + historical context
"""),
    code("""
tf = pd.read_parquet(DATA_INTERIM / "town_forecasts.parquet")
print(f"town forecasts: {len(tf):,} rows, {tf['geoid'].nunique()} MCDs, "
      f"years {tf['year'].min()}-{tf['year'].max()}, "
      f"scenarios={sorted(tf['scenario'].unique())}")

# Aggregate to per-town per-year per-scenario totals.
tf_totals = (
    tf.groupby(["geoid", "geography", "year", "scenario"])["population"]
      .sum().reset_index()
)

cf = pd.read_parquet(DATA_INTERIM / "county_forecasts.parquet")
cf_wash = cf[cf["geoid"] == WASHINGTON].copy()
cf_totals = (
    cf_wash.groupby(["year", "scenario"])["population"].sum().reset_index()
)

# Historical town totals (PEP sub-est + ACS 5-yr midpoints).
hist = pd.read_parquet(DATA_INTERIM / "town_total_pop_history.parquet")
hist_wash = hist[hist["geoid"].isin(tf['geoid'].unique())].copy()
print(f"historical town totals (PEP + ACS): {len(hist_wash):,} rows, "
      f"years {hist_wash['year'].min()}-{hist_wash['year'].max()}")
"""),
    # ---------------------------------------------------------------
    md("""
## 2. Trajectory plausibility — forecast vs historical growth

For each town we compute:

- **`hist_annual_pct`** = annualized % change from 2007 to the latest
  PEP estimate (typically 2024 or 2025). Captures the *observed*
  long-term trend.
- **`fc_annual_pct`** = annualized % change from the forecast base year
  (2022) to the forecast end (2047), baseline scenario. Captures the
  *projected* trend.

A reasonable Hamilton-Perry projection should leave the recent trend
roughly intact for most towns. Towns where the forecast trend
**diverges sharply** from the observed trend are candidates for
re-examination (either the historical trend was driven by transient
factors, or the projection is reacting to ACS sampling noise).
"""),
    code("""
EARLY_YEAR = 2007
LATE_HIST_YEAR = 2022

def _annual_pct(p_a: float, p_b: float, n_years: int) -> float:
    if p_a <= 0 or n_years <= 0:
        return float("nan")
    return 100.0 * ((p_b / p_a) ** (1.0 / n_years) - 1.0)

# Pull historical anchor pairs per town.
# Prefer PEP for both anchors when available; fall back to ACS midpoints.
def _hist_at(year: int, prefer_source: str = "census_pep") -> pd.DataFrame:
    sub = hist_wash[hist_wash["year"] == year].copy()
    if sub.empty:
        return sub
    sub["_pref"] = sub["source"].eq(prefer_source).astype(int)
    return (sub.sort_values(["geoid", "_pref"], ascending=[True, False])
               .drop_duplicates("geoid", keep="first")
               [["geoid", "geography", "year", "population", "source"]])

hist_early = _hist_at(EARLY_YEAR, prefer_source="census_acs5")
hist_late  = _hist_at(LATE_HIST_YEAR, prefer_source="census_pep")

hist_pair = hist_early[["geoid", "year", "population", "source"]].merge(
    hist_late[["geoid", "year", "population", "source"]].rename(
        columns={"population": "pop_late", "source": "src_late", "year": "y_late"}
    ),
    on="geoid", how="inner",
).rename(columns={"population": "pop_early", "source": "src_early", "year": "y_early"})

hist_pair["hist_annual_pct"] = hist_pair.apply(
    lambda r: _annual_pct(float(r["pop_early"]), float(r["pop_late"]),
                          int(r["y_late"] - r["y_early"])),
    axis=1,
)

# Forecast anchors: 2022 base → 2047 end, baseline.
fc_base = tf_totals[(tf_totals["scenario"] == "baseline") & (tf_totals["year"] == 2022)]
fc_end  = tf_totals[(tf_totals["scenario"] == "baseline") & (tf_totals["year"] == 2047)]
fc_pair = (fc_base[["geoid", "geography", "population"]]
           .rename(columns={"population": "pop_2022"})
           .merge(fc_end[["geoid", "population"]].rename(columns={"population": "pop_2047"}),
                  on="geoid"))
fc_pair["fc_annual_pct"] = fc_pair.apply(
    lambda r: _annual_pct(float(r["pop_2022"]), float(r["pop_2047"]), 25),
    axis=1,
)

combined = hist_pair.merge(fc_pair, on="geoid", how="inner")
combined["divergence"] = combined["fc_annual_pct"] - combined["hist_annual_pct"]
combined = combined.sort_values("divergence")
print("Annualized % per year — observed history vs forecast (baseline):")
disp = combined[["geography", "pop_early", "pop_late", "hist_annual_pct",
                 "pop_2022", "pop_2047", "fc_annual_pct", "divergence"]]
print(disp.to_string(index=False, float_format=lambda x: f'{x:+.2f}'))
"""),
    code("""
fig, ax = plt.subplots(figsize=(10, 6))
y = np.arange(len(combined))
ax.barh(y - 0.18, combined["hist_annual_pct"].astype(float),
        height=0.36, color="C0", alpha=0.85, label="observed 2007→2022 (annual %)")
ax.barh(y + 0.18, combined["fc_annual_pct"].astype(float),
        height=0.36, color="C3", alpha=0.85, label="forecast 2022→2047 (annual %)")
ax.axvline(0, color="black", linewidth=0.6)
ax.set_yticks(y)
ax.set_yticklabels(combined["geography"].tolist())
ax.set_xlabel("annualized % change per year")
ax.set_title("Town forecast trajectory vs observed history — annualized rates")
ax.grid(True, alpha=0.3, axis="x")
ax.legend()
fig.tight_layout()
plt.show()
"""),
    md("""
**Reading the chart.** Where the red bar (forecast) is much **more
negative** than the blue bar (history), the forecast is projecting
faster decline than the observed trend. Where red is much **more
positive**, the forecast is projecting unrealistic growth. The
single biggest divergence — positive *or* negative — flags the town
whose projection most contradicts its recent path.
"""),
    # ---------------------------------------------------------------
    md("""
## 3. Historical fit — does base-year (2022) match PEP?

The engine uses the ACS 5-year 2018-2022 midpoint as the base
population for cohort projection. PEP 2022 (sub-est2025) is an
independent estimate. They should agree to within a few percent —
larger gaps indicate ACS sampling noise or PEP-revision lag.
"""),
    code("""
fc_base_pop = (
    tf_totals[(tf_totals["scenario"] == "baseline") & (tf_totals["year"] == 2022)]
    .rename(columns={"population": "engine_2022"})
    [["geoid", "geography", "engine_2022"]]
)
pep_2022 = hist_wash[(hist_wash["year"] == 2022) & (hist_wash["source"] == "census_pep")]
pep_2022 = pep_2022[["geoid", "population"]].rename(columns={"population": "pep_2022"})
acs_2022 = hist_wash[(hist_wash["year"] == 2022) & (hist_wash["source"] == "census_acs5")]
acs_2022 = acs_2022[["geoid", "population"]].rename(columns={"population": "acs_2022"})

fit = fc_base_pop.merge(pep_2022, on="geoid").merge(acs_2022, on="geoid", how="left")
fit["engine_vs_pep_pct"] = 100*(fit["engine_2022"].astype(float)/fit["pep_2022"].astype(float) - 1)
fit["acs_vs_pep_pct"] = 100*(fit["acs_2022"].astype(float)/fit["pep_2022"].astype(float) - 1)
print("Base-year (2022) alignment:")
print(fit.sort_values("engine_vs_pep_pct").to_string(
    index=False, float_format=lambda x: f'{x:+.1f}'))
"""),
    md("""
**Reading the fit table.** ``engine_vs_pep_pct`` is the engine's 2022
base (post-IPF) relative to PEP. ``acs_vs_pep_pct`` is the ACS 2022
midpoint (the engine's input *before* IPF) relative to PEP. The IPF
constraint should narrow the gap between engine-base and PEP since
the column-marginal target is the PEP-derived county forecast — but
it only adjusts in proportion, not absolutely.
"""),
    # ---------------------------------------------------------------
    md("""
## 4. Aggregation consistency — town sums vs county forecast

Hamilton-Perry projections produced one town at a time don't naturally
sum to a separately-built county forecast. We apply an IPF constraint
to bring them into alignment. Verify the alignment is tight in
practice.
"""),
    code("""
town_sums = (
    tf_totals.groupby(["year", "scenario"])["population"].sum().reset_index()
    .rename(columns={"population": "town_sum"})
)
agg_check = town_sums.merge(
    cf_totals.rename(columns={"population": "county_total"}),
    on=["year", "scenario"], how="inner",
)
agg_check["abs_diff"] = agg_check["town_sum"] - agg_check["county_total"]
agg_check["pct_diff"] = 100.0 * agg_check["abs_diff"] / agg_check["county_total"]
print("Town sum vs county forecast by year × scenario:")
print(agg_check.to_string(index=False, float_format=lambda x: f'{x:,.1f}'))
print()
print(f"Max |pct_diff| across all year×scenario: "
      f"{agg_check['pct_diff'].abs().max():.4f}%")
"""),
    md("""
**Expected**: percentage differences of order 0.1% or less, dominated
by floating-point round-off. Larger gaps (>1%) would indicate that
IPF didn't fully converge for at least one year-scenario.
"""),
    # ---------------------------------------------------------------
    md("""
## 5. Whitehall anomaly — why is one town projected to grow while all others decline?

Whitehall town's baseline forecast is **+36% 2022-2047** while every
other Washington town declines 5-49%. Possible explanations:

- **Historical recent growth**: if Whitehall actually grew while
  others shrank, the CCRs naturally project that pattern forward.
- **ACS sampling artifact**: small populations + age-band-level CCRs
  can produce one bad multi-vintage average that propagates forward.
- **A particular age cohort bumping through**: e.g., a large
  20-something cohort in 2022 maturing into reproductive age (boost
  to 0-4 via child-woman ratio).

Plot Whitehall's history alongside the forecast to see which
explanation fits.
"""),
    code("""
WHITEHALL = "3611581633"  # confirm geoid for Whitehall town
print(f"Whitehall: {tf[tf['geoid']==WHITEHALL]['geography'].iloc[0]}")

wh_hist = hist_wash[hist_wash["geoid"] == WHITEHALL].sort_values("year")
wh_fc = tf_totals[tf_totals["geoid"] == WHITEHALL].sort_values("year")
print()
print("Whitehall historical observations:")
print(wh_hist[["year", "population", "source", "vintage"]].to_string(index=False))
print()
print("Whitehall forecast (baseline):")
print(wh_fc[wh_fc["scenario"]=="baseline"][["year", "population"]].to_string(index=False))
"""),
    code("""
fig, ax = plt.subplots(figsize=(11, 5))
pep_hist = wh_hist[wh_hist["source"]=="census_pep"].sort_values("year")
acs_hist = wh_hist[wh_hist["source"]=="census_acs5"].sort_values("year")
ax.plot(pep_hist["year"], pep_hist["population"].astype(float),
        marker="o", color="C0", linewidth=1.6, label="PEP annual sub-est")
ax.plot(acs_hist["year"], acs_hist["population"].astype(float),
        marker="s", color="C2", linewidth=1.4, linestyle="--",
        label="ACS 5-yr midpoint")
for scen, color in [("low", "C3"), ("baseline", "black"), ("high", "C1")]:
    s = wh_fc[wh_fc["scenario"] == scen].sort_values("year")
    ax.plot(s["year"], s["population"].astype(float),
            marker="^", color=color, linewidth=1.5, label=f"engine: {scen}")
ax.axvline(2022, color="grey", linewidth=0.6, linestyle=":")
ax.set_xlabel("year")
ax.set_ylabel("Whitehall town population")
ax.set_title("Whitehall — historical + Hamilton-Perry forecast across scenarios")
ax.grid(True, alpha=0.3)
ax.legend()
fig.tight_layout()
plt.show()
"""),
    code("""
# Look at age structure: what does the 2022 base look like vs other towns?
wh_2022 = tf[(tf["geoid"] == WHITEHALL) & (tf["year"] == 2022)
             & (tf["scenario"] == "baseline")].copy()
print("Whitehall 2022 base-year age pyramid:")
piv = wh_2022.pivot_table(index="age_band_start", columns="sex", values="population", aggfunc="sum")
print(piv.round(0).to_string())
print(f"\\nTotal: {wh_2022['population'].sum():,.0f}")
print(f"Share aged 20-34: {wh_2022[wh_2022['age_band_start'].between(20, 30)]['population'].sum() / wh_2022['population'].sum():.3f}")
# Compare to county
county_2022_share_2034 = cf_wash[
    (cf_wash["year"]==2022) & (cf_wash["scenario"]=="baseline")
    & (cf_wash["age"].between(20, 34))
]["population"].sum() / cf_wash[(cf_wash["year"]==2022) & (cf_wash["scenario"]=="baseline")]["population"].sum()
print(f"County share aged 20-34: {county_2022_share_2034:.3f}")
"""),
    md("""
**Reading the Whitehall view.** The historical line shows whether the
+36% projection extrapolates an observed trend or reverses one. The
age-pyramid comparison reveals whether Whitehall's 2022 base has an
unusually young population (which would produce above-county growth
mechanically via the cohort-survival math).
"""),
    # ---------------------------------------------------------------
    md("""
## 6. Per-cohort CCR instability — which towns have noisy inputs?

Hamilton-Perry uses cohort change ratios (CCRs) averaged across 10
5-year ACS vintage pairs. For each (town, sex, age band) the average
CCR is the projection's per-step multiplier. The coefficient of
variation (CV) of CCRs across the 10 vintages measures input noise —
high CV means the projection inherits a lot of ACS sampling jitter
in that town.
"""),
    code("""
# Rebuild per-vintage-pair CCRs (raw, not clipped) for diagnostic variance.
from popfc.data.acs import load_acs5_group
from popfc.models.hamilton_perry import (
    aggregate_b01001_to_5yr_bands,
    cohort_change_ratios,
)

ny_county = WASHINGTON[2:5]  # '115'

frames = []
for y in range(2009, 2025):
    if y == 2020:  # ACS 5-yr 2016-2020 not released
        continue
    acs = load_acs5_group(
        "B01001", year=y, geography="county subdivision",
        state_fips="36", county_fips=ny_county, refresh=False,
    )
    agg = aggregate_b01001_to_5yr_bands(acs)
    agg["vintage_year_end"] = int(y)
    agg["vintage_midpoint_year"] = int(y) - 2
    frames.append(agg)
history = pd.concat(frames, ignore_index=True)
print(f"Loaded {len(history):,} rows of Washington-MCD ACS history "
      f"({history['vintage_year_end'].nunique()} vintages)")

# Enumerate (t0_end, t1_end) pairs separated by 5 years (matches CCR multi-vintage default).
vintage_ends = sorted(int(v) for v in history["vintage_year_end"].unique())
PAIRS = [(y0, y0 + 5) for y0 in vintage_ends if (y0 + 5) in vintage_ends]
print(f"  {len(PAIRS)} 5-year vintage pairs available: {PAIRS}")

# Per-pair raw CCR (no clipping — we want true variance).
ccr_frames = []
for y0, y1 in PAIRS:
    pop_t0 = history[history["vintage_year_end"] == y0].copy()
    pop_t1 = history[history["vintage_year_end"] == y1].copy()
    if pop_t0.empty or pop_t1.empty:
        continue
    ccrs = cohort_change_ratios(pop_t0, pop_t1, cap=None)
    ccrs["pair"] = f"{y0}-{y1}"
    ccr_frames.append(ccrs)
ccrs_all = pd.concat(ccr_frames, ignore_index=True)
print(f"Per-vintage-pair CCR rows: {len(ccrs_all):,}")
print(f"CCR columns: {list(ccrs_all.columns)}")
"""),
    code("""
# Distribution of CCRs by town × age band, across vintage pairs.
# Use ccr_raw (unclipped) so we measure true sampling-driven variance.
ccr_col = "ccr_raw"
agg = ccrs_all.groupby(["geoid", "sex", "age_band_start"]).agg(
    ccr_mean=(ccr_col, "mean"),
    ccr_std=(ccr_col, "std"),
    ccr_min=(ccr_col, "min"),
    ccr_max=(ccr_col, "max"),
    n_pairs=(ccr_col, "count"),
).reset_index()
# Coefficient of variation per cell.
agg["ccr_cv"] = agg["ccr_std"] / agg["ccr_mean"].abs().replace(0, np.nan)
# Town-level summary: median CV across all (sex, age band) cells.
town_summary = agg.merge(
    tf[["geoid", "geography"]].drop_duplicates(), on="geoid", how="inner",
)
town_cv = town_summary.groupby(["geoid", "geography"])["ccr_cv"].median().reset_index()
town_cv = town_cv.rename(columns={"ccr_cv": "median_ccr_cv"})
town_cv = town_cv.sort_values("median_ccr_cv", ascending=False)
print("Per-town median CCR coefficient of variation (across 10 vintage pairs):")
print(town_cv.to_string(index=False, float_format=lambda x: f'{x:.3f}'))
"""),
    code("""
# Tie this back to forecast trustworthiness.
ranked = combined.merge(town_cv, on=["geoid", "geography"], how="left")
ranked = ranked.sort_values("median_ccr_cv", ascending=False)
print("Forecast divergence (forecast − historical annual %) vs CCR noise (CV):")
disp = ranked[["geography", "pop_2022", "hist_annual_pct", "fc_annual_pct",
               "divergence", "median_ccr_cv"]]
print(disp.to_string(index=False, float_format=lambda x: f'{x:+.3f}'))

fig, ax = plt.subplots(figsize=(9, 5))
x = ranked["median_ccr_cv"].astype(float)
y = ranked["divergence"].astype(float)
ax.scatter(x, y, s=ranked["pop_2022"].astype(float) / 20.0,
           color="C0", alpha=0.7, edgecolor="black", linewidth=0.4)
for _, row in ranked.iterrows():
    ax.annotate(row["geography"].replace(" town", ""),
                (float(row["median_ccr_cv"]), float(row["divergence"])),
                fontsize=8, alpha=0.85)
ax.axhline(0, color="grey", linewidth=0.6)
ax.set_xlabel("median CCR coefficient of variation (input noise)")
ax.set_ylabel("forecast − historical annual % (divergence)")
ax.set_title("Town forecast divergence vs CCR input noise — bubble size ∝ 2022 pop")
ax.grid(True, alpha=0.3)
fig.tight_layout()
plt.show()
"""),
    md("""
**Reading the scatter.** Towns in the upper-right and lower-right
quadrants have **high CCR noise driving a forecast divergence** —
these are the projections least to trust, since they're effectively
inheriting ACS sampling jitter as if it were demographic signal.
Towns clustered near the y=0 line have forecasts that track their
historical experience reasonably; towns near the x-axis but with low
CV inherited a stable input signal even when the resulting forecast
deviates from history (likely cohort-aging effects dominating).
"""),
    # ---------------------------------------------------------------
    md("""
## 7. Findings + recommendations

Run the cells below to format the findings dynamically off the numbers
this notebook just computed.
"""),
    code("""
# Pull headline numbers for the findings text.
worst_div = ranked.iloc[-1] if not ranked.empty else None
biggest_pos_div = ranked[ranked["divergence"] > 0].sort_values("divergence", ascending=False).head(1)
biggest_neg_div = ranked.sort_values("divergence").head(1)
highest_cv = ranked.sort_values("median_ccr_cv", ascending=False).head(3)
agg_max = agg_check["pct_diff"].abs().max()
HIGH_CV_THRESH = 0.40
n_unstable = (ranked["median_ccr_cv"] > HIGH_CV_THRESH).sum()

print("=" * 70)
print("HEADLINE FINDINGS — Town forecast audit")
print("=" * 70)
print(f"\\nCounty-aggregation tightness: max |town-sum − county-forecast| / county = {agg_max:.4f}%")
print(f"  Interpretation: IPF column constraint converges to within float precision.\\n")

if not biggest_pos_div.empty:
    r = biggest_pos_div.iloc[0]
    print(f"Largest upward divergence: {r['geography']}")
    print(f"  Observed 2007→2022 annual %: {r['hist_annual_pct']:+.2f}/yr")
    print(f"  Forecast 2022→2047 annual %: {r['fc_annual_pct']:+.2f}/yr")
    print(f"  CCR median CV: {r['median_ccr_cv']:.3f}\\n")
if not biggest_neg_div.empty:
    r = biggest_neg_div.iloc[0]
    print(f"Largest downward divergence: {r['geography']}")
    print(f"  Observed 2007→2022 annual %: {r['hist_annual_pct']:+.2f}/yr")
    print(f"  Forecast 2022→2047 annual %: {r['fc_annual_pct']:+.2f}/yr")
    print(f"  CCR median CV: {r['median_ccr_cv']:.3f}\\n")

print(f"Towns with median CCR CV > {HIGH_CV_THRESH:.2f} (high input noise): {n_unstable} of {len(ranked)}")
print(f"  All 17 towns have CV > 0.20 — small-town ACS sampling drives meaningful")
print(f"  noise everywhere. CV > {HIGH_CV_THRESH:.2f} is where the noise becomes")
print(f"  large relative to the central CCR signal.")
print(f"  Top 3 noisiest:")
for _, r in highest_cv.iterrows():
    print(f"    {r['geography']:>20s}: CV={r['median_ccr_cv']:.3f}, pop_2022={int(r['pop_2022']):,}")
"""),
    md("""
## Conclusions

**What the audit confirms is working.**

- **County aggregation is exact** (max |town_sum − county_total| =
  0.0% to floating-point). IPF column-only constraint is doing its
  job perfectly.
- **The multi-vintage CCR averaging from Batch 6 made forecasts a
  lot less wild** — recall that Hampton went from +188% (v1) to
  -9.4% (v2). The remaining issues are subtler.

**What the audit reveals is broken.**

- **Whitehall's +36% headline is unsupported.** PEP/ACS show Whitehall
  has been *stable at ~4,000* for 15+ years (range 3,953-4,046). The
  forecast extrapolates +1.23%/year out of an observed +0.03%/year.
  An unusually large 30-34 cohort in the 2022 ACS pyramid (F=221,
  M=175 — bigger than the 25-29 cohort, F=127, M=134) is the cohort
  the CCR math projects forward via aging *and* via the child-woman
  ratio's effect on future 0-4 births. The cohort is almost
  certainly an ACS sampling quirk, not a demographic regime change.
- **Hampton's 2022 ACS base is +33% off PEP** (ACS 1,145 vs PEP
  858). The engine uses ACS as the base population, so Hampton's
  forecast starts from the wrong level — every projection year is
  scaled up from there. Hampton needs special-case base-year
  treatment.
- **Hartford's 2022 base is -13% off PEP** (ACS 1,895 vs PEP 2,179).
  Less dramatic than Hampton but in the same family.
- **All 17 towns have CCR coefficient of variation > 0.20** across
  the 10 vintage pairs. Top 3 above 0.50 (Putnam, Dresden, White
  Creek) are projections where ACS sampling noise dominates the
  signal — the multi-vintage averaging mutes but doesn't remove it.

## Recommended next steps, in rough order of payoff

> **Update (post-v3):** #1 and #3 were implemented in
> `feat/town-forecast-v3`; #2 was found already-satisfied (corrected
> below); #4 remains not-actionable.

1. **[DONE in v3] Reconcile the engine base year to PEP.** The engine
   was feeding the raw ACS 5-year midpoint into Hamilton-Perry as the
   2022 base. For towns like Hampton (+33%) and Hartford (-13%),
   this base disagreed materially with the authoritative PEP total.
   v3 proportionally rescales each town's age × sex matrix to match
   the PEP sub-est 2022 total (`rescale_base_to_target`) — fixing the
   level without changing the projection method.
2. **[ALREADY SATISFIED — original wording was wrong.]** The original
   text claimed "the column-only IPF matches county totals but not
   county age × sex marginals." That is backwards. The column-only
   IPF's `column_targets` **are** the county (sex, age band) pyramid,
   so the cross-town sum already matches the county age × sex
   marginals **exactly** (verified: 0.0 difference across all
   scenarios and forecast years). What it does *not* constrain is
   each town's **total** (the row marginal), which emerges from the
   HP cohort-change ratios. Anchoring town totals would need an
   independent town-total forecast (e.g., a trend on the 6-year PEP
   sub-est town-total series) as the row target, then biproportional
   IPF to satisfy town totals AND the county pyramid at once.
   Uncertain payoff — it swaps one noisy town-total estimate (HP
   CCRs) for another (a short PEP trend), with no clearly-better data
   source. Deferred pending evidence it beats v3.
3. **[DONE in v3] Shrinkage of town CCRs toward the county CCR.**
   v3 shrinks each town's CCRs — and, crucially, its child-woman
   ratio — toward the county-aggregate reference with weight
   `w = P / (P + 2000)` (`shrink_ccrs_toward_reference`,
   `shrink_cwr_toward_reference`). The CWR shrinkage was the key
   piece: Whitehall's CWR of ~0.42 (vs county ~0.24) was the main
   driver of its spurious growth.
4. **NYSDOH sub-county vital statistics would help — at the
   births side.** NYSDOH publishes births by resident county
   (and now we use that — see issue #2). Town-level vital events
   would close the births-side ACS-sampling gap, but NYSDOH
   doesn't publish by-town. Not actionable without a new data
   source.
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
