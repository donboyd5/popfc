# Project changelog

Chronological record of what the project has actually done — methodology
changes, data refreshes, fixes, and major refactors. **This is the
canonical "current state" reference.** `docs/planning.md` retains the
historical phase narrative; this file is what you read to see what's
been built recently and what's currently in motion.

Each entry: date, branch, one-line summary, plus a short bullet list of
the substantive changes. Entries are newest first.

---

## 2026-05-27 — `feat/nysdoh-vital-county` (in progress)

Closes [issue #2](https://github.com/donboyd5/popfc/issues/2). Pulls
NYSDOH vital statistics (births + deaths) via Socrata, adds a
cross-source audit panel to Notebook 02, and extends
`county_components.parquet` with `source='nysdoh_vital'` rows.

**New code** in `popfc.data.nysdoh_vital`:

- `load_nysdoh_births()` — pulls `i7yg-w5rg` (Live Births by Mother's
  Age and Resident County, 2008+). Returns `totals` (county-year
  totals in `COMPONENTS_LONG_COLUMNS`) and `by_mother_age` (full
  detail). Uses the API's published `Total` row, not summed detail.
- `load_nysdoh_deaths()` — pulls `xit9-mprv` (Deaths by Resident
  County, Region, Age-Group, 2003+). Same shape.
- Caches raw API responses under `data_raw/nysdoh/api/` keyed by
  the dataset's data-publication date (from Socrata `rowsUpdatedAt`).
  UTC date used for cross-machine determinism.
- Vintage tag format: `nysdoh_vital_YYYYMMDD`.
- Supports `NYSDOH_SOCRATA_APP_TOKEN` env var for higher rate limits
  (anonymous queries also work — datasets are small enough).

**Notebook 02 §4c** — cross-source audit comparing NYSDOH vs PEP
births and deaths for every county-year intersection. Reports
distribution of % differences, scatter (1:1 line + cohort highlight),
and Washington time-series side-by-side. Section §5 now saves the
combined PEP + NYSDOH frame to `county_components.parquet`
(14,742 PEP rows + 2,170 NYSDOH rows = 16,912 total).

**Headline finding**: PEP's 2020 county births/deaths rows are
**fragmentary base-year transition values**, not full-year counts.
Washington 2020:

| Source | 2020 births | 2020 deaths |
|---|---|---|
| PEP | 142 | 164 |
| NYSDOH | 532 | 765 |

Pre-2020 and post-2021 the two sources agree to ±5%. The 2020 gap
was previously invisible because PEP was self-checking. Downstream
code that uses `births` and `deaths` from `comp_pep_res` should
treat 2020 as a data gap.

**Notebook 11** updated to filter to `source='census_pep'` in its
town-level component allocator, so the new NYSDOH rows don't
double-count through the population-share merge.

**QA invariants** updated: uniqueness now keyed on
`(geoid, year, measure, source)` to allow the deliberate dual-source
coverage. The original PEP-only uniqueness invariant is checked
separately.

**9 new tests** for the Socrata fetch + parse, cache round-trip,
vintage formatting, aggregate-row handling, and a live-data smoke
check that runs when a prior cache is present. **191 total tests pass.**
Forecasts unchanged at baseline.

---

## 2026-05-27 — `feat/migration-decomposition-engine` (in progress)

Batch 4b: closes the queued "biggest remaining piece" by decomposing
each per-cell net migration rate into domestic + international
components and extending the cohort-component engine to accept separate
per-component scenario knobs.

**Data integration**:

- **PEP V2025** publishes county-year `domestic_mig` and
  `international_mig` separately — these provide the county-level
  *signed* domestic share `p_dom_county = sum(dom) / (sum(dom) + sum(int))`
  averaged over 2019-2024. The factor is *signed* (can fall outside
  [0, 1] when components offset each other — e.g., Washington's
  `p_dom = +1.60`, Essex's `-3.92`, Columbia's `+13.74`).
- **ACS B07001** (Geographical Mobility by Age, 5-year 2019-2023) pulled
  via the existing ACS infrastructure. State-aggregate `f_dom(age)`
  varies modestly (0.81 at age 5-17 → 0.91 at age 18-19, with most
  ages 0.83-0.87), providing a mild age tilt to the per-cell
  decomposition.

**New code** in `popfc.models.migration`:

- `b07001_age_component_shape(b07001_long, state_filter=...)` — parses
  the 96-variable B07001 long frame and returns a per-band
  domestic / international / f_dom DataFrame.
- `expand_age_shape_to_single_year(shape_band, top_code_age=85)` —
  expands band-level shape to single-year ages (uniform within band).
- `decompose_net_migration(net_mig, pep_components, age_shape_single_year=None, ...)`
  — produces a NET_MIGRATION_COMPONENTS frame: per (geoid, sex, age)
  cell with `m_total_rate`, `m_dom_rate`, `m_int_rate`,
  `p_dom_county`, `p_dom_age_effective`. Cell-sum identity
  `m_dom + m_int = m_total` is exact (drift < 1e-12).
- Counties with `|p_dom_county| > 5` (8 counties — Columbia, Erie,
  Niagara, Richmond, Rockland, Suffolk, Wayne, Westchester) are
  annotated as **`p_dom_unstable`** because their components offset
  each other near zero net — component multiplier scenarios produce
  outsized swings in those counties and the flag warns downstream
  users.

**Engine extension** in `popfc.models.cohort_component`:

- `project_one_county()` gains three new keyword args:
  `net_mig_components`, `net_mig_dom_multiplier`, `net_mig_int_multiplier`.
- Effective rate (component mode):
  `m_eff = m_dom × dom_mult + m_int × int_mult + delta`.
- **Baseline invariance**: with all multipliers = 1.0 and
  `m_dom + m_int = m_total`, the projection is bit-identical to
  total mode (verified to 1e-9 across all years/sexes/ages).
- The auto-generated `projection_vintage` tag now distinguishes
  `engine_v3_...` (component mode) from `engine_v2_...` (total mode).

**Notebook 07 §7** — new decomposition section: pulls B07001, computes
state-aggregate shape, decomposes statewide, plots f_dom by age band,
plots per-county p_dom distribution (highlighting unstable counties),
plots Washington's m_dom vs m_int by age, and saves
`net_migration_components.parquet` (10,540 rows × 17 cols).

**Notebook 08 §5c** — new component scenarios section runs three
component scenarios alongside the historical-reference framework:
`comp_baseline`, `comp_low_int` (international × 0.5),
`comp_low_dom` (domestic × 0.5). Saves
`county_forecasts_components.parquet`.

**Component scenario impact, Washington 2050**:

| Scenario | 2050 pop | Δ vs comp_baseline |
|---|---|---|
| comp_baseline (= regular baseline) | 47,991 | base |
| comp_low_int | 46,710 | −1,281 |
| comp_low_dom | 50,674 | +2,683 |

Washington's two components are signed-opposite: domestic is net
out (-135/yr), international is net in (+51/yr). Halving
international amplifies the net out-migration → smaller pop.
Halving domestic out-migration → larger pop. The asymmetry
(low_dom Δ > |low_int Δ|) reflects domestic's larger absolute size.

**15 new tests** across `tests/test_migration.py` (B07001 shape
parser, age-band expansion, decomposition cell-sum identity,
opposite-sign components, instability flag, age-tilt zero-factor
matches Tier 1) and `tests/test_cohort_component.py` (baseline
invariance, scenario directionality, delta still applied,
vintage tag distinguishes modes). **182 total tests pass.**

---

## 2026-05-26 — `feat/mortality-usaleep-ratio` (in progress)

Post-review follow-up #2: closes the Batch 7 "queued refinement" by
turning the USALEEP qx-ratio adjustment into the production mortality
schedule for Washington. Other 5 cohort counties continue on NY state
NVSR.

**New code** in `popfc.data.nchs`:

- `usaleep_qx_band_ratio(target, reference)` — per-band qx ratio
  between two USALEEP-aggregate life tables.
- `apply_qx_ratio_to_life_table(nvsr_table, qx_ratios, ...)` —
  rebuild an NVSR-style single-year life table with adjusted qx,
  reconstructed lx/Lx/Tx/ex. Output schema-conforming; vintage gains
  a `_usaleep_adj` suffix.

**Notebook 06 §6c**: builds Washington-adjusted schedule and adds
geoid `36115` rows to both `survival_rates.parquet` and
`life_tables.parquet`.

**Notebook 08**: `survival_geoid="36115" if geoid==WASHINGTON else
"36000"` — Washington uses the adjusted schedule, others use NY
state as before.

**Headline forecast impact** (baseline scenario):

| Year | Pre-adjustment | Post-adjustment | Delta |
|---|---|---|---|
| 2024 | 59,839 | 59,839 | 0 (base year) |
| 2030 | 57,722 | 57,910 | +188 |
| 2040 | 52,979 | 53,361 | +382 |
| 2050 | 47,567 | **47,990** | **+423** |

Right in the +200-500 range predicted in Batch 7. e(0) under the
adjusted schedule is **80.11** vs NVSR NY 2022 baseline **79.53**
(+0.58 years).

**6 new tests** for the qx-ratio helpers (happy path, error paths,
ratio identity, qx clipping at 1.0). 2 existing test assertions
updated to tolerate the new 36115 slices in life_tables.parquet.
**167 total tests pass.**

---

## 2026-05-26 — `feat/data-archival` (merged to main)

Post-review follow-up #1: reproducibility infrastructure. Closes the
loop on a concern surfaced during the V2025 refresh (Census reorganizes
URLs every few years; NYSDOH/IRS data can get withdrawn).

**Code:**

- **`scripts/build_manifest.py`** — generator that walks `data_raw/`,
  computes SHA-256 + size + mtime per file, looks up source URLs in
  the existing `popfc.data.download` registry, and writes
  `data_raw/MANIFEST.toml`. ~120 lines, no external deps beyond what
  the project already has.
- **`data_raw/MANIFEST.toml`** — generated. 102 files indexed,
  ~470 MB total. Committed.
- **Inline-commit of ~10 MB foundational sources**: `data_raw/cdc/`,
  `data_raw/cornell/`, `data_raw/nchs/`, `data_raw/nysdol/`. These
  are the static or near-static reference inputs (CDC Bridged-Race
  discontinued; NCHS NVSR life tables fixed-annual; Cornell PAD
  one-time; NYSDOL Socrata pulls small). Project now reproduces from
  a fresh clone even if all upstream URLs vanish.
- **`.gitignore`** updated to selectively re-include the small subdirs
  + MANIFEST.toml while keeping the heavy ones (acs ~150 MB,
  census ~200 MB, irs ~66 MB, nysdoh ~26 MB) ignored.

**Open follow-ups remaining after this:**

- USALEEP qx-ratio adjustment to NVSR (Batch 7 finding)
- Migration engine extension (Batch 4b — domestic + international as
  separate engine inputs)
- NYSDOH sub-county vital statistics pulls (issue #2)

---

## 2026-05-26 — `feat/mortality-usaleep` (merged to main `a8bdff9`)

Batch 7 of the review (the last in the originally-planned set):
USALEEP-based mortality diagnostic for Washington.

**Code:**

- New `popfc.data.nchs.usaleep_county_life_table()` — aggregates
  tract-level USALEEP life tables into a county-level abridged life
  table. Per band: weighted mean qx and Lx across tracts; lx
  reconstructed from a 100,000 radix; ex re-derived from T(x)/l(x).
  Equal-weight by default; accepts a population-weighted `weights`
  argument when tract pop is available. Caught and documented a
  subtle bug along the way: Lx in USALEEP tract tables is *per-100k
  radix*, so summing across tracts (the naive aggregation) would
  multiply person-years by tract count. The mean is correct.
- Small unrelated cleanup: replaced the IPF divide-by-zero
  `np.where` warning with a clean `np.divide(..., where=)` pattern.

**Empirical finding** (Notebook 06 §6b):

- Washington county-aggregate e(0) (USALEEP 2010-2015): **81.43**
- NY statewide aggregate e(0) (same period, same method): **80.26**
- **+1.17 year Washington mortality advantage**, consistent across all
  age bands

For reference, the forecast's current input (NY NVSR 2022, post-COVID)
has e(0) = 79.53. The pre-COVID USALEEP era looks ~0.7 years better
overall.

**Decision**: keep NY NVSR 2022 as the forecast's default mortality
schedule. Documented reasons:

- Period match (NVSR 2022 → forecast base 2024) is closer than
  USALEEP 2010-2015 → 2024.
- USALEEP is abridged (11 bands); switching the forecast to USALEEP
  would require abridged-to-single-year disaggregation.
- Forecast impact of applying the Washington advantage is modest
  (~+200-500 residents at 2050 against a baseline of 47,567).

**Queued as future refinement**: apply the Washington-vs-NY USALEEP qx
*ratio* as a multiplicative adjustment to NVSR NY 2022 single-year
rates. Captures the Washington advantage while keeping the period
match. The tract aggregator built here is the building block needed.

**Tests:** 6 new for the aggregator. **161 total pass.**

This concludes the originally-planned review batch list (Batches
1-7). Open follow-ups noted across the changelog:
- `feat/data-archival` — manifest + small files inline (deferred from
  the V2025 refresh)
- `feat/migration-decomposition-engine` (Batch 4b) — extend the
  engine to project domestic + international separately
- USALEEP qx-ratio adjustment to NVSR (this batch)
- NYSDOH sub-county vital statistics pulls (issue #2)

---

## 2026-05-26 — `feat/town-forecast-v2` (merged to main `51e3465`)

Batch 6: better Washington town forecasts. Two methodology upgrades
targeting the most-flagged weakness from earlier batches — small-area
ACS sampling noise compounding into runaway per-town projections.

**Code:**

- **`popfc.models.hamilton_perry.cohort_change_ratios_multi_vintage()`**
  — new helper that reads `town_agesex_history` (built in Batch 5)
  and averages CCRs across every available 5-year-midpoint vintage
  pair. For NY MCDs this yields ~10 pairs per (geoid, sex, age_band)
  cell. Per-pair CCRs are clipped to `(0.85, 1.20)` before averaging
  so no single noisy year-pair can dominate.
- **`popfc.constrain.ipf` — new module** with `apply_ipf_constraint()`.
  Single-pass column-only constraint when row targets are omitted
  (equivalent to per-column raking); biproportional iterative fitting
  when both marginals are specified. Replaces pro-rata as the town
  forecast's default constraint.

**Notebook 09:**

- §2 now computes both v1 (single-vintage) and v2 (multi-vintage)
  CCRs side by side.
- §3 projects all 17 towns under both CCR methods.
- §4 applies IPF (v2 production) using the county-forecast 5-yr-band
  pyramid as the column marginal. Verified: IPF identity holds
  exactly (cross-town sums match the county pyramid to float
  precision at every (sex, age_band) cell).
- §4b new: direct v1-vs-v2 side-by-side comparison per town with
  back-to-back bar chart.

**Headline corrections (baseline scenario, 2022 → 2047):**

| Town | v1 (pro-rata) | v2 (IPF + multi-vintage) |
|---|---|---|
| Hampton | +188% (noise artifact) | **−9.4%** |
| Whitehall | small decline | **+35.4%** (real grower revealed) |
| Greenwich | +29% | −32.3% (v1 growth was partly noise) |
| Cambridge | +20% | −30.0% (same) |
| Dresden | sharp decline | −50.1% |

The county total is unchanged — IPF constrains the cross-town sum to
the same county forecast that v1 was constrained to. The
redistribution across towns is what improved.

**Tests:** 8 new (4 multi-vintage CCR, 4 IPF). **155 total pass.**

**Methodology.md** gains a "Town forecast v2 — multi-vintage CCRs +
IPF (current default)" section in §Methods documenting both
improvements and the v1 weaknesses they address.

---

## 2026-05-26 — `feat/town-historicals` (merged to main `6f61aff`)

Batch 5 of the review: statewide NY town historical data + a
rural-growth descriptive notebook.

**Data assembled (idempotent, built by Notebook 11 §0):**

- **`data_interim/town_agesex_history.parquet`** — every NY MCD's
  age × sex pyramid across 15 ACS 5-year vintages (2009-2024 except
  2020). 1,024 MCDs × 15 vintages × 2 sexes × 18 5-yr age bands ≈
  552k rows. Built by pulling B01001 statewide at every available
  vintage and aggregating via the existing Hamilton-Perry
  age-band helper.
- **`data_interim/town_total_pop_history.parquet`** — annual MCD
  totals from PEP `sub-est2025` (2020-2025) plus 5-year-midpoint
  totals from the ACS frame above (~2007 to ~2022). Multi-source
  long-format.

**New API pulls:** added 13 ACS B01001 vintages (statewide NY MCDs)
to the cache. Vintage 2020 is intentionally absent — Census did not
release ACS 5-yr 2016-2020 due to COVID survey disruption.

**Operational fix:** `CENSUS_API_KEY` was being set per-session via
`export`. Moved the export to `~/.profile` (instead of `~/.bashrc`,
because Ubuntu's stock `~/.bashrc` has the "if not interactive,
return" guard at the top, so the export there would never run in
non-interactive shells). Login shells now pick up the key
unconditionally.

**Notebook 11 — `notebooks/11_rural_town_analysis.ipynb`**
(descriptive, not in the forecast DAG):

§1-2: Per-MCD population change first-vs-latest ACS observation. 377
rural NY MCDs (pop ≤ 2,000 at latest obs); 140 grew, 224 shrank, 13
~flat. Hampton (Washington Co) shows up as a real grower (+67%
2009→2024), which explains its outlier appearance in the Notebook 09
town forecast (where Hamilton-Perry on small populations amplified
the historical growth into the +188% forecast).

§3: Component decomposition via **age-aware proportional allocation**
(per user feedback that births should be allocated by share of women
of childbearing age, not total pop):

| Component | Allocator |
|---|---|
| Births | Town's share of county women aged 15-49 |
| Deaths | Town's share of county pop aged 65+ |
| Domestic / international migration | Town's share of total population |

Verified that per-county allocated sums exactly match published
county components. Documented as a first-pass approximation in
methodology.md.

§4: Counterfactual lens — if each top-grower's recent net migration
rate were sustained another decade, the implied 2035 population.
Pure arithmetic; not a forecast.

§5: Pattern summary. Most rural NY MCDs lose population; the few
growers tend to have **domestic migration as the dominant
component**. Consistent with the Batch 3 historical-reference
scenario framework — meaning real rural growth has occurred and is
reflected in the engine's "best window" scenarios.

**147 tests pass.** No new tests added in this batch — the new code
is all notebook-level + idempotent build helpers; the building blocks
(ACS loader, age-band aggregator, components data) all have existing
test coverage.

---

## 2026-05-26 — `feat/migration-decomposition` (merged to main `4faf665`)

Batch 4 of the review: migration depth. Surfacing the
domestic-vs-international split + IRS gross flow detail in the
historical analysis. The original Batch 4 scope also included
extending the engine to project domestic and international
separately, but that work has been re-scoped to a follow-up batch
(see "deferred" below).

**What landed:**

- **`popfc.data.irs.load_irs_county_migration`** — new loader for
  IRS SOI county migration data (the gross in/out flows from tax-
  return address changes). Schema documented in
  `src/popfc/data/irs.py`; handles all summary-row sentinels
  (96/97/98 = totals; 57-59 = aggregate buckets; non-migrant rows
  detected by partner_geoid == anchor_geoid).
- **Two new DownloadSpecs** for the 2022-2023 vintage:
  `countyinflow2223.csv` and `countyoutflow2223.csv`. Filename pattern
  is parameterized so back-vintages (e.g., 2021-22, 2020-21) can be
  added by registering with a different `vintage_tag`.
- **Discovery / correction**: the pre-existing `data_raw/irs/*.csv`
  files (filenames like `22incyallagi.csv`) turned out to be
  county-level INCOME tax statistics (returns, AGI, wages by income
  bracket), NOT migration data. Decoded "in" as "income" rather than
  "inflow". The actual migration files are now in the same directory
  under `countyinflow<YYZZ>.csv` / `countyoutflow<YYZZ>.csv`.
- **Notebook 02 §4b** — Historical migration decomposition for all
  six cohort counties. Annual bars of `domestic_mig` +
  `international_mig` + net per county, plus the IRS 2022-2023 gross
  flow lookup. Surfaces patterns like Washington's post-COVID
  international uptick (+15/yr → +175/yr) and the cross-source
  net-domestic agreement.
- **`docs/methodology.md`** — new "Migration decomposition — domestic
  vs international, what we can see" section. Documents what each
  source publishes, the age × sex coverage gap (PEP and IRS county
  don't carry age), and the data limitations that constrain a clean
  engine extension.

**Deferred to a follow-up `feat/migration-decomposition-engine` batch:**

The original Batch 4 plan included extending `project_one_county()`
with separate `net_mig_domestic` and `net_mig_international` rate
vectors so scenarios could vary the two components independently
("what if domestic recovers but international stays elevated?").
After exploring the data more closely:

- ACS B07001 gives county-level age bands for INFLOWS only (lived-1-
  year-ago breakdown by age × component-of-origin) — useful for the
  inflow age shape but doesn't directly source outflow profiles.
- County-level IRS has no age detail (only state-level files do).
- Estimating per-component age × sex profiles requires a compromise
  on outflows (symmetric-to-inflow assumption, or state-level IRS
  by-age data) and a small design conversation.

This is meaningful work (~1-2 days) that should get its own branch +
explicit design choice on the outflow assumption. The methodology
section now documents what the extension would do and what
constraints it would face.

---

## 2026-05-26 — `feat/scenarios-historical` (merged to main `84da257`)

Batch 3 of the review: replace multiplicative migration scenarios with
a historical-reference framework grounded in each county's own
observed experience.

The old design applied scalar multipliers (`net_mig_multiplier`) to
per-cohort migration rates. That works poorly when rates are signed
(e.g., Washington has positive net in-migration of kids aged 0-4 and
negative net out-migration at working ages — multiplying by 1.30
amplifies *both*, which is rarely the intended scenario). It also
produced uninterpretable scenario bands: the multiplier ±30% on small
net numbers gave very narrow ranges (~1,700 person spread at 2050 for
Washington).

The new design:

- **`popfc.models.migration.historical_reference_periods()`** — per
  county, find best/worst/current rolling 5-year windows of net
  migration (PEP `net_mig` / mid-year pop). Returns rate + year-range
  per window.
- **`popfc.models.cohort_component.project_one_county()`** gains a new
  `net_mig_delta` argument: an additive shift to per-(age, sex)
  migration rates. Effective rate is `m × multiplier + delta`. The
  multiplier is kept for back-compat; new code uses `delta`.
- **Notebook 08** computes per-county scenarios from
  `historical_reference_periods()`:
  - baseline = current rate (delta = 0)
  - low = if migration matched the *worst* observed 5-year window
    (delta = worst_rate − current_rate)
  - high = if migration matched the *best* observed window
- **New methodology section** (`docs/methodology.md`) explains the
  framework and reports the Washington reference periods.
- **5 new tests** for `historical_reference_periods` covering schema,
  three-windows-per-county, ordering invariants, sparse-data handling,
  and arithmetic correctness. 135 tests pass.

**Washington 2050 (baseline) didn't change** — that's by construction,
since baseline uses the same per-cohort rates as before. The
**range widens dramatically** because low/high now reflect real
extremes:

- Old (multiplier): low 46,642 / baseline 47,567 / high 48,366 — spread 1,724.
- New (historical): low 43,203 / baseline 47,567 / high 51,469 — spread 8,266.

Concretely, Washington's "worst observed 5-year migration window"
(2013-2017) was -0.41%/yr; if migration matched that going forward,
the county lands at ~43,200 by 2050 (-28%). "Best observed"
(2018-2022, brief near-balanced period) was -0.05%/yr; matching that
yields ~51,500 (-14%).

Status: in progress on the branch.

---

## 2026-05-25 — `feat/outlier-audit` (merged to main `5ca03e6`)

Batch 2 of the post-V2025-refresh review: explicit outlier-detection
sections in every notebook that produces forecast inputs, plus a
cohort-level data-quality summary in Notebook 10.

- **Notebook 01 §4b** — statewide source-disagreement audit. Flags
  county-years where `(max - min) / max > 0.5%` across available
  sources. Top offender: Hamilton County (7-15% spread across multiple
  years). Cohort: Washington is the cleanest (17% of years flagged);
  Saratoga and Warren show ~38% (decennial-seam intercensal vs
  postcensal drift, which the reconciliation rule already handles).
- **Notebook 02 §2.6** — explicit identity-check thresholds:
  `|residual|/pop > 5‰`, plus births/deaths YoY changes > 20%.
  Surfaces the known PEP decennial-seam artifact (partial-year
  births at 2010/2020 → 4× "jump" at 2011/2021). Notebook 05 already
  works around this by using rate-based annualization.
- **Notebook 03 §2b** — across all 62 NY counties, gap between the
  4/1/2020 census enumeration and 7/1/2020 estimate. Cohort all
  within ±0.5%; small counties (Hamilton) and NYC boroughs are the
  outliers.
- **Notebook 05 §6b** — extreme ASFR scaling factor `k` and implied
  TFR. Real outliers surfaced: Tompkins County (Cornell U) at
  TFR ~0.75; Rockland County (Orthodox communities) at TFR ~3.3.
- **Notebook 07 §4b** — implausible per-cohort migration rates
  `|m_rate| > 20%/yr`. 1.3% of cells flagged; concentrated in small
  rural counties and college towns. Cohort counties: 0-2 flagged
  cells each (Washington 1).
- **Notebook 10 §5b** — cross-notebook outlier summary. Per-cohort-
  county table consolidating flag counts from all five audits, plus
  reading guide. Conclusion: cohort-county forecast inputs are clean;
  the constraining limitations are *methodological* (single net
  migration rate, scenario knobs, national ASFR pattern) rather
  than data-quality.

Status: in progress on the branch. Pushed once complete.

---

## 2026-05-25 — `feat/quickfixes-batch1` (merged to main `b384ab1`)

Batch 1 of the post-V2025-refresh review: quick wins, plus the
methodology book as the centerpiece.

- **`docs/methodology.md`** — new comprehensive reference: acronyms
  (ACS, ASFR, CCM, CCR, CWR, MCD, NCHS, NVSR, NYSDOH, NYSDOL, PEP, SYA,
  USALEEP, plus more); demographic notation (l(x), L(x), q(x), S(x),
  ω, P(x,t), CCR); plain-language method explanations (cohort-component
  projection, survival from life tables, Preston open-band formula,
  scaled fertility, residual migration, Hamilton-Perry, pro-rata
  constraint); data-source quick reference; methods-we-use vs
  methods-we-don't table.
- **NYSDOL vintage now reflects data publication, not retrieval.**
  Filenames carry both: `..._d20260401_r20260525.csv` = data
  published 2026-04-01, retrieved 2026-05-25. Parquet `vintage` column
  reads `nysdol_2026-04-01`. Loader's `_derive_vintage` parses the
  publication date; legacy single-date filenames fall back to
  `nysdol_retrieved_<date>`.
- **Forecast plots gain history + speculation emphasis.** Notebooks 08
  and 10: all forecast time-series plots now show reconciled history
  back to 2015 (~10 years of context). Years beyond 2035 are visually
  deemphasized via a faint grey band + "more speculative beyond 2035"
  annotation. Parquet retains full 2024-2050 horizon; only display
  changes.
- **"Headline" jargon removed** from plot titles and section headers
  ("Headline — Washington" → "Main projected trajectory — Washington").
- **ASFR documentation clarified** in notebook 05: explicit
  "national pattern, local level" walk-through with the small-N
  rationale (Washington has ~545 births / 30 reproductive ages = 18
  per age, too noisy to fit locally).
- **`Makefile`** — convenience targets: `make help | refresh-data |
  build-nb | run-all | test | export-final | all`. Uses
  `.venv/bin/python` directly.
- **`docs/workflow.md`** — clarified the decennial-year rule (every
  retained value is July-1; April-1 census enumerations stay in
  `population_all_sources` for QA only). Documented the ACS pull
  mechanism (hand-rolled wrapper, no third-party package, JSON cache
  layout). Documented the NYSDOL filename convention.
- **`docs/changelog.md`** — this file. New convention for "what we did
  recently"; `docs/planning.md` retains the historical phase narrative.

Status: in progress on the branch. Pushed once complete.

---

## 2026-05-24 — `feat/data-refresh-v2025` (merged to main `3111c0f`)

End-to-end pipeline refresh on the latest available upstream data.

- **Census PEP V2025** (`co-est2025-alldata.csv`, released 2026-03-26)
  replaces V2024 — extends totals + components of change through 2025.
- **Census SYA V2024** (`cc-est2024-syasex-36.csv`, released
  2025-06-26) replaces V2023 — extends age × sex through 2024.
  YEAR-code 6 added to the SYA loader (`_SYA_YEAR_MAP_V2024`).
- **Census V2025 subcounty** (`sub-est2025.csv`) dropped into
  `data_raw/` but unused by the pipeline currently (kept as a future
  hook for town-base anchoring).
- **NYSDOL** refreshed from data.ny.gov (now through 2025). Loader
  gains space-to-underscore column normalization for the direct-download
  header style.
- **`data_interim/county_agesex_1990_2023.parquet`** →
  **`county_agesex_1990_2024.parquet`** (one more year).
- **Forecast base year**: 2023 → 2024. Cohort-component run now
  2024-2050 (was 2023-2050).
- **Migration averaged over 4 year-pairs** (2020-21..2023-24) instead
  of 3.
- **Washington baseline 2050: 47,567** (was 45,342 from the 2023
  base) — less pessimistic, mostly because the 2023-24 year softened
  the residual-method migration average and partly because the base
  year shifted one year forward.
- **`download.py`** extended with `DownloadSpec`s for Census PEP +
  SYA + sub-est + NYSDOL so refreshes are one command.
- **130 tests passing** after refresh. SYA test fixtures updated to
  V2024 expectations.

Open follow-up (deferred to a separate branch): `feat/data-archival`
will add `data_raw/MANIFEST.toml` with SHA-256 hashes + URLs and
commit small foundational raw files inline for long-term
reproducibility against URL rot.

---

## Earlier work

For the original Phase 1-5 build (data reconciliation → external data
loaders → cohort-component engine → town forecasts → reporting),
see `docs/planning.md` (sections "Phase 1" through "Phase 5"). Those
sections document the original development; the changes since merge
to main are tracked in this file.
