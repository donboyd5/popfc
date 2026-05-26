# Methodology

This is the project's plain-language reference for what every method does,
what the notation means, and which acronyms refer to what. Use it as a
companion when reading the notebooks — when a notebook says "we compute Sx
via Preston's combined formula for the open band," this is where you look
up what Sx is, what Preston's formula does, and why the boundary case is
special.

It's organized in three parts:

- **[Acronyms](#acronyms)** — the dictionary
- **[Notation](#notation)** — symbols you'll see in formulas
- **[Methods](#methods)** — one section per technique used in the pipeline

Companion docs:
- `docs/workflow.md` — operational reference (how to run the pipeline)
- `docs/data_dictionary.md` — column-by-column schema for every parquet
- `docs/planning.md` — project status and history

---

## Acronyms

| Acronym | Meaning |
|---|---|
| **ACS** | American Community Survey (U.S. Census Bureau). Annual rolling survey; we use the 5-year-aggregated public-use tables for county and sub-county geographies. |
| **ASFR** | Age-Specific Fertility Rate. Births per 1,000 women in a given single year of age. Summing ASFR across ages gives the TFR. |
| **B01001 / B06001 / B07001** | ACS table IDs we use. B01001 = sex by age, B06001 = place of birth by age, B07001 = geographic mobility by age. |
| **CCM** | Cohort-Component Method (also: cohort-component projection / model). The standard demographic forecasting technique we use for county totals. See [Method: cohort-component projection](#cohort-component-projection). |
| **CCR** | Cohort Change Ratio. The empirically-observed survival-plus-migration factor for a 5-year age cohort over a 5-year period. Used by Hamilton-Perry for towns. See [Method: Hamilton-Perry](#hamilton-perry). |
| **CDC** | Centers for Disease Control and Prevention. |
| **CDC Bridged-Race** | NCHS-published population estimates 1990-2020 that "bridge" the pre-2000 single-race classifications to the post-2000 multi-race classifications, producing a consistent time series. Discontinued after 2020. We use it for Washington County age × sex history before 2020. |
| **CTYNAME / STNAME** | County / state name columns in Census PEP files. |
| **CWR** | Child-Woman Ratio. Children aged 0-4 per woman aged 15-49 in a town; used in Hamilton-Perry to close the youngest cohort (since CCRs only work for ages ≥ 5). |
| **FIPS** | Federal Information Processing Standards code. Geographic identifier: 2 chars for state (NY=`36`), 3 for county (Washington=`115`), 5 for the county geoid (`36115`), 10 for an MCD geoid (state + county + 5-digit MCD code). |
| **GQ** | Group Quarters population (institutional + non-institutional residents in dorms, prisons, nursing homes, etc.). Reported separately by PEP. |
| **Hamilton-Perry (HP)** | A small-area projection method that bypasses the need for vital-stats data by using observed cohort-change ratios between two recent age pyramids. See [Method: Hamilton-Perry](#hamilton-perry). |
| **IPF** | Iterative Proportional Fitting. A constraint method that adjusts a multi-way table to match given marginals. (Not used in the current pipeline; mentioned as a future refinement for town constraints.) |
| **IRS SOI** | Internal Revenue Service Statistics of Income. Includes county-to-county migration tables (gross inflows and outflows) derived from tax-return address changes. |
| **MCD** | Minor Civil Division. The Census-recognized sub-county unit for incorporated places + townships. In NY, an MCD is a town or city. Washington County has 17 MCDs (16 towns + 1 village treated as MCD); FIPS 10-digit code = state + county + 5-digit MCD. |
| **NCHS** | National Center for Health Statistics (CDC). Publishes US and state life tables (NVSR series), USALEEP tract-level tables, and vital statistics. |
| **NVSR** | National Vital Statistics Reports. NCHS's publication series; we use specific issues, e.g., NVSR 74-06 (US 2023 life tables), NVSR 74-12 (state 2022 life tables). |
| **NYSDOH** | New York State Department of Health. Publishes annual population estimates by age × sex × race × county, plus births/deaths/vital statistics. |
| **NYSDOL** | New York State Department of Labor. Publishes annual county/state population estimates back to 1970 via data.ny.gov. We use it as the authoritative intercensal series for 2000-2019. |
| **PEP** | Population Estimates Program (U.S. Census Bureau). Annual mid-year (July 1) population estimates with components of change (births, deaths, net migration). Released in spring of the following year, with each "Vintage YYYY" superseding earlier vintages back to the most recent decennial. |
| **SYA** | Single-Year-of-Age. Census file `cc-est<YYYY>-syasex-36.csv` carries county population by single year of age × sex × year-code. We use the post-2020 SYA file for ages 0-85 (top-coded at 85). |
| **TFR** | Total Fertility Rate. The hypothetical lifetime number of children per woman implied by holding the current year's ASFR schedule constant over her reproductive years. TFR = (sum of ASFR over ages 10-49) / 1000. Replacement level is ~2.1. |
| **USALEEP** | U.S. Small-Area Life Expectancy Estimates Project. NCHS-published 2010-2015 period life tables at the census-tract level. We use it to assess whether Washington tracts diverge from the state average. |

---

## Notation

Demographers use a compact notation that's near-universal in life-table and
projection work. The relevant pieces:

### Population

- **P(x, t)** — population aged exactly `x` at time `t`. In our pipeline,
  `t` is a July-1 reference date and `x` is single year of age 0..85.
- **N(x, t)** — synonym for P(x, t) in some texts; we stick with P.

### Life-table columns

For a period life table at exact age `x` with band width `n` (we use `n = 1`
for closed bands and an open band at the top):

- **l(x)** — *lowercase L-of-x*. Number surviving to exact age `x` out of an
  initial radix (typically 100,000 newborns). Decreases with `x`.
- **L(x)** — *uppercase L-of-x*. Person-years lived between ages `x` and
  `x+n`. Calculated by NCHS as the integral of survivors over the band;
  roughly `(l(x) + l(x+n)) / 2 × n` for closed bands, but with corrections
  for the high mortality at age 0.
- **q(x)** — probability of dying between ages `x` and `x+n` *given* alive
  at `x`. (Mortality rate, not death count.)
- **d(x)** — number of deaths in the band, = `l(x) × q(x)`.
- **e(x)** — *life expectancy at exact age* `x`. Remaining years a person
  alive at `x` is expected to live, on average.

### Survival rate (what we actually use)

- **Sx** or **S(x)** — single-year survival probability: fraction of
  P(x, t) that lives to age x+1 at t+1. For a closed band:

  > S(x) = L(x+1) / L(x)

  We use ratios of `L` values (not `l`) because L captures person-years
  *lived in the band*, which is what links a population pyramid one year
  apart. Using `l(x+1) / l(x)` would systematically over- or under-state
  survival depending on where deaths concentrate within the band.

- **Open-band boundary** — at the top of our age range (`ω = 85`), we have
  P(ω) representing everyone aged 85+. Going forward one year, P(ω, t+1)
  is comprised of (a) survivors from P(ω-1, t) who aged into ω, plus (b)
  survivors from P(ω, t) who remain in ω. The combined survival rate uses
  **Preston's formula**:

  > S(ω) = L(ω) / [L(ω-1) + L(ω)]    applied to    [P(ω-1) + P(ω)]

  In plain English: the open band gathers everyone from the closed band
  below it plus its own existing members, and survival is the ratio of
  person-years lived in the open band to person-years contributing from
  the two source ages. See [Method: survival rates from life tables](#survival-rates-from-life-tables).

### Other

- **ω (omega)** — the open-band boundary age. In our pipeline ω = 85.
- **k** — the multiplicative scaling factor applied to the national ASFR
  schedule to make it match a county's observed total births. County
  TFR = (national TFR) × k.
- **CCR(x, t)** — cohort change ratio for the cohort aged `x` at base time
  `t`: ratio of that cohort's population 5 years later to its initial
  population. Combines survival + net migration over the 5-year period.

---

## Methods

### Cohort-component projection

The cohort-component method (CCM) is the textbook approach to demographic
forecasting. It projects a population forward one year at a time by
applying three transitions to each age × sex cell:

1. **Survival** — most of P(x, t) survives to become P(x+1, t+1), at a
   rate S(x) from the life table.
2. **Net migration** — the surviving population is adjusted up or down
   by a net migration rate, m(x, sex), expressed per source-age person.
3. **Births** — for newborns (P(0, t+1)), we compute total births in the
   year from women in P(x, t) weighted by ASFR(x), then split by the
   sex-ratio at birth (we use 1.05 male per female).

The recurrence for closed bands:

> P(x+1, t+1) = P(x, t) × S(x) × (1 + m(x))

For the open band:

> P(ω, t+1) = [P(ω-1, t) + P(ω, t)] × S(ω) × (1 + m(ω))

Implementation: `popfc.models.cohort_component.project_one_county`. The
engine is county-agnostic — you pass in the survival schedule, ASFR
schedule, and net-migration rate vector, plus a base-year P(x, sex)
pyramid, and it iterates from a base year to an end year.

**Scenario knobs.** The engine accepts three scalar knobs:

- `asfr_multiplier` — uniform multiplier on ASFR. Baseline uses 1.0; low
  uses 0.85 (≈ −15% TFR); high uses 1.15. Fertility is always positive
  so a multiplier is well-defined.
- `net_mig_multiplier` — uniform multiplier on the per-(age, sex)
  migration rate vector. Kept for "amplify-the-shape" experiments;
  rarely the right tool when net migration is signed (positive at some
  ages, negative at others — a multiplier amplifies both, which usually
  isn't what's intended).
- `net_mig_delta` — additive shift to every per-(age, sex) migration
  rate. **This is the preferred way to encode scenarios.** The effective
  rate becomes `m(x, sex) × multiplier + delta`. The shape is preserved
  (kids still move in more than working age, etc.); only the *level*
  shifts.

**Historical-reference scenarios.** Starting with Batch 3 of the post-
V2025-refresh review, scenarios are anchored to **each county's own
observed migration experience**, not arbitrary multipliers. We compute
`historical_reference_periods()` (in `popfc.models.migration`) which
returns, per county, three rolling 5-year-window summaries of net
migration (PEP `net_mig` / mid-year pop):

- **current**: the most recent complete 5-year window
- **best**: the window with the highest (most positive / least negative) average
- **worst**: the window with the lowest average

Scenarios are then:

- baseline = current rate (`net_mig_delta = 0`)
- high = if migration matched the *best* observed window
  (`net_mig_delta = best_rate − current_rate`)
- low = if migration matched the *worst* observed window
  (`net_mig_delta = worst_rate − current_rate`)

For Washington (cohort baseline as of the 2026-05-26 refresh):
- current (2021-2025): -0.20%/yr
- best (2018-2022, brief recovery): -0.05%/yr (close to balanced)
- worst (2013-2017): -0.41%/yr

The resulting low/high scenario range widens by ~5× compared with the
old multiplicative approach (~8,300 persons spread at 2050 vs ~1,700)
*and* the numbers are interpretable: "what if Washington had its worst
observed 5-year migration window from now to 2050?" "What if it matched
its best?" These are grounded counterfactuals.

### Survival rates from life tables

A period life table gives the mortality experience of a real population
over a window (e.g., NY 2022 = the 2022 NY state life table). Each
single-year-of-age row carries l(x), L(x), q(x), d(x), e(x).

We turn this into a single-year **survival probability vector** S(x) that
the cohort-component engine can apply per year:

- **Closed bands** (ages 0 to ω-1):

  > S(x) = L(x+1) / L(x)

- **Open band** (age ω):

  > S(ω) = L(ω) / [L(ω-1) + L(ω)]    applied to    [P(ω-1, t) + P(ω, t)]

  This is **Preston's combined formula** (Preston, Heuveline, & Guillot,
  *Demography: Measuring and Modeling Population Processes*, 2001).
  The intuition: at the open boundary, two source ages flow into the same
  destination band, so the destination's person-years (`L(ω)`) are
  apportioned against the *sum* of the two source person-years.

- **Births** (the special "S(-1)" row): the survival probability from
  birth to the 0-year-old population uses `L(0) / l(0)` (the proportion
  of newborns alive at end-of-year on average) — implementation in
  `survival_rates_from_life_table()`.

Implementation: `popfc.models.mortality.survival_rates_from_life_table`.
Optional `top_code_age` argument rebands a longer life table (say
through age 100) to match the population data's top-code (age 85+).

### Age-specific fertility rates (ASFR) — "national pattern, local level"

We need an ASFR schedule per county per year — i.e., a rate at every
maternal age 15-44 that lets the engine compute county births. Two
options for estimating it:

1. **Local everything**: count actual county births by mother's single
   year of age, divide by county women at that age. Reliable only when
   the births-per-age count is large.
2. **National pattern + local level**: borrow the *shape* of ASFR across
   ages from NCHS national data; rescale the *level* to match each
   county's observed total births.

We use approach (2). Concretely:

```
reference_ASFR(x)        = NCHS 2023 US ASFR by single year of age
county_total_births(y)   = observed annual births for the county in year y
county_women_by_age(y)   = observed female pop at age x in year y

k(county, y)             = county_total_births(y) /
                           sum over x of  [reference_ASFR(x) × county_women_by_age(y, x) / 1000]

county_ASFR(x, y)        = k(county, y) × reference_ASFR(x)
county_TFR(y)            = sum over x of  county_ASFR(x, y) / 1000
                         = k(county, y) × national_TFR
```

The implied county TFR is just `k × national_TFR`. **The shape is
borrowed; the level is local.** Why approach (1) doesn't work at county
scale: Washington has ~545 births per year. Spread across 30 reproductive
ages, that's an average of 18 births per single year of age — way too
few to fit a reliable per-age rate. NCHS national draws from millions of
births and gives a precisely-estimated curve.

Cornell PAD uses the same approach for the same reason. The trade-off:
we won't capture any genuinely-local *pattern* differences (e.g., if
Washington women shift first births later than the national average,
that's invisible). For total-pop forecasts the level dominates.

Implementation: `popfc.models.fertility.NCHS_ASFR_REFERENCE_SCHEDULE` +
`build_county_year_asfr()`.

### Net migration via the residual method

Direct measurement of county net migration would require census-style
in-out questionnaires every year. Instead, we use the **residual method**:

1. Take the population pyramid at year `t`: P(x, sex, t)
2. Apply the year's survival rates: project an *expected* pyramid one
   year later — `expected_P(x+1, sex, t+1) = P(x, sex, t) × S(x, sex)`
3. Observe the actual pyramid one year later: `observed_P(x+1, sex, t+1)`
4. The difference, divided by the source population, gives an implied
   per-source-age migration rate:

   > m(x, sex) = [observed_P(x+1, sex, t+1) − expected_P(x+1, sex, t+1)]
   >             / P(x, sex, t)

This rate captures everything not explained by survival aging: net
migration, but also any data noise in either pyramid.

To reduce noise, we **average over multiple year-pairs**. The current
pipeline uses 4 pairs: 2020-21, 2021-22, 2022-23, 2023-24 — every
overlapping pair available since the 2020 census base.

**What the residual method can and can't do:**
- *Can*: produce a per-cohort net rate that captures the joint effect of
  domestic, international, and within-county movement.
- *Can't*: tell you what *kind* of migration each rate represents. The
  separate domestic vs international flows are published by PEP at the
  *county-level annual* level but not by age × sex.
- *Can't (at town level)*: the residual method requires age × sex pop
  in successive years. PEP doesn't publish that sub-county. ACS gives
  it but only as 5-year averages, which smear the year-over-year signal.

Implementation: `popfc.models.migration.build_net_migration_rates`.

### Migration decomposition — domestic vs international, what we can see

PEP publishes the migration components separately at the **county-year**
level (`domestic_mig` and `international_mig`, both as NET counts). The
historical decomposition is visible in Notebook 02 §4b for every cohort
county — for example, Washington 2022-2024 shows international ramping
from ~+15/yr historically to ~+175/yr (post-COVID rebound) while
domestic stays negative ~ −160/yr. The two flows respond to different
forces (housing markets, labor, immigration policy, post-COVID effects)
and an aggregate "net migration" number conceals that.

**IRS SOI** county migration data (loaded via `popfc.data.irs`) adds
the **gross** in/out detail PEP doesn't publish — Washington 2022-2023
had 2,364 individuals move in (US-domestic) and 2,292 move out, net
+72. Useful for cross-source validation and for answering "how many
people moved in?" / "how many moved out?" as distinct questions, even
when the *net* is small.

**Data limitations to keep in mind:**

- PEP publishes domestic + international net per county but **no age ×
  sex** breakdown for either component. The cohort-component engine
  applies a single net migration rate per (age, sex); separating that
  into domestic + international rate vectors requires estimating each
  component's age × sex shape from external sources.
- IRS county data has **no age or sex breakdown** at the county level
  — only state-level files carry age bands.
- ACS B07001 ("Geographic Mobility by Age") gives **county-level age
  bands** for inflows: "moved from different county same state",
  "different state", and "abroad". But it covers INFLOWS only (where
  you lived a year ago vs now), so it can't directly source outflows.
- Net residual = inflow − outflow at each age, so estimating outflows
  requires either symmetric assumptions or an external data source
  (state-level migration profiles, IRS state-by-age data, etc.).

**Engine extension (deferred to Batch 4b).** A clean implementation
would estimate per-component age × sex profiles by combining:

- ACS B07001 county-level inflow profiles (age × component-of-origin)
  for the **domestic vs international shape of inflows**.
- Demographic-rate assumptions or state-level IRS migration-by-age
  data for the **outflow age profile** (a known compromise).
- PEP-published net domestic + net international counts as the
  per-year levels to match.

The engine would then accept two rate vectors (`net_mig_domestic`
and `net_mig_international`) plus the existing `net_mig_delta` knob.
Scenarios could vary one or both independently — e.g., "what if
domestic out-migration recovered but international stayed at its
post-COVID elevated level?" That work is genuinely a separate piece
because of the per-component shape estimation effort.

### USALEEP-based county mortality differentials (diagnostic only)

Batch 7 adds a tract-to-county life-table aggregator
(`popfc.data.nchs.usaleep_county_life_table`) and uses it in Notebook
06 §6b to compare Washington's mortality experience to NY state's,
both via the same USALEEP 2010-2015 data. The aggregator does proper
weighted-mean of tract qx and Lx values per age band, then rebuilds
lx via cumulative survival from a 100,000 radix and ex via T(x)/l(x).

**Empirical finding**: Washington's aggregate e(0) is **81.43**; NY
statewide aggregate is **80.26** — a **+1.17 year** mortality advantage,
consistent across all age bands (about +1.0 to +1.3 years per band).
For reference, the forecast's current input (NY NVSR 2022) gives
e(0) = 79.53 — lower than either USALEEP figure because it reflects
post-COVID period mortality.

**Why the forecast still uses NY NVSR 2022 as the default**:

- **Period match.** Our forecast base year is 2024. NVSR 2022 is the
  closest period available; USALEEP 2010-2015 predates COVID, so
  applying it as-is would understate current mortality.
- **Granularity.** USALEEP publishes 11 abridged age bands (Under 1,
  1-4, 5-14, ..., 85+). The cohort-component engine needs single-year
  survival probabilities; abridged-to-single-year disaggregation
  (Coale-Demeny or Heligman-Pollard fits) introduces its own
  assumptions.
- **Modest forecast impact.** Translated through the engine, the
  Washington advantage would yield +200 to +500 additional projected
  residents at 2050 against a baseline of 47,567 — meaningful but
  small relative to the migration and fertility scenarios already
  driving the spread.

**Now implemented as the production schedule for Washington.** The
queued refinement is live. New helpers `usaleep_qx_band_ratio()` and
`apply_qx_ratio_to_life_table()` in `popfc.data.nchs` compute the
per-band Washington/NY qx ratio and apply it as a multiplicative
adjustment to NVSR NY 2022 single-year qx. Period match preserved
(NVSR 2022, contemporaneous with the forecast base 2024); Washington
mortality differential captured.

Notebook 06 §6c builds the Washington-adjusted schedule and writes
both `data_interim/survival_rates.parquet` (geoid `36115` added
alongside `36000`) and `data_interim/life_tables.parquet` (so
Notebook 08's recompute path discovers the new rows). Notebook 08
uses `survival_geoid="36115"` for Washington and `"36000"` (NY state)
for the other 5 cohort counties.

Forecast impact: Washington 2050 baseline rose **47,567 → 47,990**
(+423 residents), right in the predicted +200-500 range. e(0) under
the adjusted schedule is 80.11 vs the NVSR NY 2022 baseline of 79.53
(+0.58 years — less than the raw +1.17 USALEEP differential because
per-band ratios mix in both directions; some bands favor Washington
and some don't).

### Town forecast v2 — multi-vintage CCRs + IPF (current default)

The first iteration of the town forecast (Batch 4 of the original
project, pre-review) used Hamilton-Perry with **two ACS vintages**
(2015-2019 and 2020-2024) to compute CCRs, then a **pro-rata
constraint** to make the town sum match the county forecast. Two
known weaknesses:

1. **CCR noise.** With small populations (Hampton ~1,100) and one
   5-year-window CCR per cohort, ACS sampling noise dominates. A
   single noisy cell can compound to a runaway projection — Hampton
   in v1 came out at +188% by 2047, almost certainly an artifact.

2. **Pro-rata is shape-blind.** It multiplies every cell in a town by
   one factor to match the town total to its county-share target. The
   *cross-town* age × sex pyramid (i.e., who is what age across the
   county) doesn't have to match the county forecast's pyramid at all.

The **v2 default** (Batch 6 of the review) addresses both:

- **Multi-vintage CCR averaging.** `cohort_change_ratios_multi_vintage()`
  reads `town_agesex_history` (15 ACS vintages 2009-2024 except 2020,
  built in Batch 5) and computes the per-cohort CCR for every
  available 5-year-midpoint pair, then averages. For Washington MCDs
  this typically yields ~10 pairs per (geoid, sex, age_band) cell.
  Per-pair CCRs are clipped to `(0.85, 1.20)` before averaging — one
  noisy year-pair can't dominate the average. The 10-pair signal is
  much more stable than the 1-pair signal.
- **IPF column-only constraint.** `popfc.constrain.ipf.apply_ipf_constraint()`
  with `column_targets = county_forecast_pyramid_5yr_bands` (no row
  targets) scales every town's (sex, age_band) cell so the cross-town
  sum at each cell exactly matches the county forecast at that cell.
  Single-pass when row targets aren't given (mathematically a
  per-column scaling); equivalent to "rake to a single marginal".
  When both row and column targets are given the function does full
  biproportional fitting iteratively. Useful for future scenarios
  where we want town totals AND county pyramid simultaneously.

For Washington's MCDs, v2 corrects the most extreme v1 outliers
(Hampton +188% → −9.4%) and surfaces real growers v1 missed
(Whitehall +35%). The county total is unchanged by construction.

The v1 method is computed alongside v2 in Notebook 09 §4b for direct
comparison; only v2 is saved to `data_interim/town_forecasts.parquet`
and consumed downstream.

### Hamilton-Perry

Hamilton-Perry (HP) is the small-area projection method we use for
Washington's 17 towns. It bypasses the need for sub-county vital stats
by exploiting that **age × sex pyramids one decade apart already contain
the joint effect of survival + migration**.

The cohort change ratio for a town cohort:

> CCR(x, sex) = P(x + 5, sex, t + 5) / P(x, sex, t)

Where `t` is a base year and `t + 5` is five years later. We use two
ACS 5-year vintages (e.g., 2015-2019 midpoint ≈ 2017, and 2020-2024
midpoint ≈ 2022) to compute CCRs over the implied 5-year interval.

Projection forward: for each town, each 5-year age cohort, multiply by
its CCR to get the population 5 years out. Repeat to project forward
multiple 5-year steps.

The 0-4 cohort needs special handling because there's no source cohort
5 years younger to multiply. We use a **child-woman ratio (CWR)**: the
ratio of children aged 0-4 to women aged 15-49 in the latest vintage,
applied to projected women-15-49 at the next step to imply 0-4 pop.

**Sanity caps**: per-town per-cohort CCRs can be wild when populations
are small. We clamp CCR to a range (current production: `[0.85, 1.20]`
per 5-year step; legacy default `[0.5, 2.0]`). This dampens the worst
small-sample noise at the cost of muting any real demographic divergence
between towns.

**Pro-rata constraint to county**: HP town projections don't naturally
sum to the county cohort-component projection. We rescale per-town
populations at each forecast year by a single multiplicative factor so
the sum matches the county forecast for that scenario. (A future
refinement would use IPF to match county age × sex marginals too.)

Implementation: `popfc.models.hamilton_perry` + `popfc.constrain.prorata`.

### Population reconciliation rule

Population for our project comes from three overlapping series:
- **Census PEP** (postcensal estimates 2020+, intercensal 2010-2020,
  intercensal 2000-2010) — multiple vintages overlap; we keep the latest.
- **NYSDOL annual estimates** (July 1, 1970-current) — uses PEP for
  2020+ but provides earlier coverage with consistent methodology.
- **2020 decennial enumeration** (April 1, 2020) — loaded into
  `population_all_sources.parquet` for QA but **not** entered into the
  reconciled series. We anchor every year on a July 1 value to avoid
  the ~3-month phase shift the April-1 enumeration would inject.

The reconciliation rule (in `popfc.reconcile.reconcile_county_population`):

- **2000-2019**: NYSDOL July-1 intercensal estimate (continuous across
  the 2000 and 2010 decennials).
- **2020+**: Census PEP July-1 postcensal estimate from the latest
  available vintage (V2025 at the time of this writing).

Output: `data_interim/population_reconciled.parquet`, one row per
(county, year) with `source` / `kind` / `vintage` / `rule` provenance.

### Data sources at a glance

For full coverage details see `docs/data_dictionary.md`. Briefly:

| Source | What | Update cadence | We use it for |
|---|---|---|---|
| Census PEP | County + sub-county pop estimates + components | Annual (V2025 released March 2026) | Authoritative 2020+ totals + components of change |
| Census SYA | County single-year-of-age × sex × year | Annual, lagging PEP totals by ~3 months | Age × sex base population for CCM (latest V2024) |
| NYSDOL | NY county/state annual totals (1970+) | Annual (last update 2026-04-01) | Pre-2020 intercensal anchor |
| CDC Bridged-Race | County single-year-of-age × sex × race × year, 1990-2020 | Discontinued | Washington pre-2020 age × sex history |
| NCHS NVSR | National + state life tables | Annual NVSR issues | Survival rates (current: US 2023, NY 2022) |
| NCHS USALEEP | Tract life expectancy 2010-2015 | Static (not refreshed) | Quality check: Washington tracts vs NY state median e(0) |
| ACS 5-year | Detailed county + MCD tables | Annual (current: 2020-2024) | Town age × sex (HP base); migration profiles (B07001, B06001) |
| Cornell PAD | NY county projections (pre-pandemic) | Static | Benchmark for the engine's county forecasts |

### Town historical data + rural-growth analysis (Batch 5)

For descriptive analysis of NY MCDs (towns + cities) over the last
~15 years, we assemble statewide historical age × sex and total-pop
records:

- **`data_interim/town_agesex_history.parquet`** — every NY MCD's
  5-year ACS B01001 age × sex pyramid, across 15 vintages
  (2009-2024, except 2020 which Census did not release due to COVID
  disruption of survey collection). 1,024 MCDs × 15 vintages × 2
  sexes × 18 5-year age bands ≈ 552k rows.
- **`data_interim/town_total_pop_history.parquet`** — annual MCD
  totals from PEP `sub-est2025` (2020-2025) plus 5-year-midpoint
  totals from the ACS frame above (~2007 to ~2022). Long-format,
  multi-source: callers can prefer PEP for recent years and ACS
  midpoints elsewhere.

Both are built by Notebook 11 §0 (idempotent — reused if already on
disk) from the cached raw inputs.

**Rural-town analysis (Notebook 11).** Filter MCDs to pop ≤ 2,000 at
the latest observation; rank by % change between earliest and latest
ACS vintage. Decompose change into components by **allocating
county-level PEP components to towns** using age-aware proportional
shares:

- **Births**: town's share of county women aged 15-49.
- **Deaths**: town's share of county pop aged 65+.
- **Domestic + international migration**: town's share of county
  total population.

The age-share denominators come from the ACS 5-year vintages and are
linearly interpolated to each year. **The allocation preserves county
totals exactly** (verified per-county: allocated sum equals published
county component to float precision).

This is a deliberate **first-pass approximation**:

- Assumes per-allocator rates are uniform within a county (e.g.,
  births per woman 15-49 are the same across all towns in a county).
  Town-level *rate* variation is real but unobserved.
- Intra-county moves cancel out at the county level, so they can't be
  attributed to either inflow or outflow shares — even though they
  are real movements between rural and exurban towns within a county.
- The PEP component series starts at 2011; full-year-pair coverage
  begins 2012.

NYSDOH publishes vital statistics at sub-county geography in some
forms; pulling those (deferred — see GitHub issue #2) would replace
this allocator with direct measurement for births and deaths.

### Reproducibility — MANIFEST.toml + inline foundational data

The project's raw inputs are ~470 MB and most come from URLs (Census,
NCHS, IRS, etc.). URLs rot. The reproducibility approach:

- **`data_raw/MANIFEST.toml`** — generated by
  `scripts/build_manifest.py`. Records for every file under `data_raw/`:
  relative path, SHA-256 hash, size in bytes, mtime, and the source URL
  / download-spec name when registered in `popfc.data.download`.
  102 files, ~470 MB indexed. Committed to the repo. Re-run after any
  data refresh.
- **Small foundational sources are committed inline** (~10 MB total):
  `data_raw/cdc/`, `data_raw/cornell/`, `data_raw/nchs/`,
  `data_raw/nysdol/`. These are the static or near-static reference
  inputs — CDC Bridged-Race is discontinued, NCHS NVSR life tables are
  fixed annual publications, Cornell PAD is a one-time benchmark,
  NYSDOL CSVs are small Socrata pulls. If their URLs vanish, the
  project still builds.
- **Heavy sources stay ignored** (`acs/` ~150 MB JSON cache, `census/`
  ~200 MB archives, `irs/` ~66 MB, `nysdoh/` ~26 MB). All refreshable
  via `python -m popfc.data.download` (or by manual placement for
  archived Census files). The MANIFEST records their hashes so version
  drift is detectable even when the files themselves aren't checked in.

### Engineering conventions (also see CLAUDE.md)

- **Statewide by default**: loaders never hardcode Washington FIPS.
- **Long/tidy parquet**: every artifact has `geoid` + `geography` +
  provenance columns (`source`, `vintage`, `notes`).
- **String-first ingestion**: raw CSVs are read with `dtype=str` and
  explicitly coerced via `coerce_numeric()` so type errors warn instead
  of silently corrupting data.
- **ACS access**: hand-rolled wrapper at `src/popfc/data/acs.py` that
  talks to `api.census.gov/data/{year}/acs/acs5` directly. No
  third-party package (`cenpy`, `census`, `pyacs`) — kept thin to keep
  cache + paging logic visible. Responses cached as JSON under
  `data_raw/acs/<year>/`.

---

## Glossary of methods used vs not used

We chose certain methodological branches and not others. For the record:

| We use | We don't use (alternatives) |
|---|---|
| Cohort-component (CCM) for counties | Trend-based (ARIMA / ETS), structural econometric |
| Hamilton-Perry for towns | Town-level CCM (data not available), regression with rural-classifier covariates |
| Residual-method migration (county) | Direct measurement (not available), gravity models |
| National-pattern + local-level ASFR | Per-county per-age ASFR estimation (too noisy at county scale) |
| Single net migration rate per (age, sex) | Separate domestic + international rates (planned — Batch 4) |
| Pro-rata constraint (town → county) | IPF (matches marginals; planned future refinement) |
| Historical-reference scenarios (additive `net_mig_delta`) | Scalar multipliers (kept for back-compat; deprecated for migration) |

---

## See also

- `notebooks/05_fertility.ipynb` — ASFR construction in action
- `notebooks/06_mortality.ipynb` — survival rate construction
- `notebooks/07_migration.ipynb` — residual method walk-through
- `notebooks/08_county_forecast.ipynb` — CCM engine integration
- `notebooks/09_town_forecast.ipynb` — Hamilton-Perry walk-through
- Preston, S. H., Heuveline, P., & Guillot, M. (2001). *Demography:
  Measuring and Modeling Population Processes.* Blackwell. — canonical
  reference for the demographic notation and formulas used here.
