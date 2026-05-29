# Washington County NY Population Forecast — Python Project Planning

> **Quick resume prompt:** *Please read docs/planning.md then read other files as needed and tell me status and suggest next steps.* (Full session-resume prompt is at the bottom of this file.)

## Goals

I want to forecast annual population of counties in the Washington County area of New York and the towns within Washington County. Those towns sum to the county total. I want the county forecasts to follow a cohort-components method similar to that implemented by Cornell University.

The town forecasts for Washington County should sum to the county forecast. They do not necessarily have to use the same forecasting method as the county method. It might be that we use a simpler method for the towns and then force them to sum to the county using an optimization approach. However we will need to be able to estimate some details of the town forecasts.

One main reason I am doing this is so that I can understand the drivers of population growth or decline in the towns of southern Washington County. Thus the need for components. I also want to be able to understand, going forward, what possibilities there are. For example, to what extent is population decline almost inevitable due to changing demographics and fertility and birth rates? To what extent could that be mitigated or reversed through domestic or international in-migration?

## Context

Rebuild of the legacy R/Quarto project (formerly at `popfc_R/`, deleted in
Phase 5) as a proper Python project with rigorous data validation. The R
project's documents and R source remain available under `docs/r_reference/`;
raw data lives in `data_raw/` (fetched via the download pipeline).

### User priorities (emphasized explicitly)

1. **Careful data checking** — reconcile multiple population series and identify discrepancies
2. **Use the RIGHT total population** for the county (authoritative series selection)
3. **Use the right components** of change (births, deaths, migration)
4. **External data where needed** — ACS for town-level detail, life tables for mortality

### Guiding principles (cross-session)

- **Not constrained by the R implementation.** `docs/r_reference/` is reference material, not a template. Apply Python best practices and modern demographic-forecasting approaches even when they depart from the R code.
- Prefer vectorized / array-based operations over per-unit loops.
- Prefer well-documented, tested library functions over notebook-only code.
- Every notebook ends with assertions / sanity checks.

---

## Scope (confirmed)

- **Forecast engine**: county-agnostic, parameterized by FIPS.
- **Output tiers**:

| Tier | Counties | Purpose |
|---|---|---|
| Primary | Washington (36115) + towns | The actual deliverable |
| Validation cohort | Saratoga, Warren, Rensselaer, Essex, Columbia | Benchmark method vs Cornell PAD across comparable upstate rural counties |
| Sanity sweep | All 62 NY counties (totals only) | Catch gross methodology errors via comparison to Cornell |
| *(Skipped)* | NYC boroughs + Long Island | Different demographics; not useful for WashCo validation |

- **Phase 1 data loading** covers all 62 counties (matches the natural shape of the input files). Reconciliation effort concentrates on Washington; others get a summary table flagging outliers.
- **Towns**: only for Washington County.

---

## Current Status (as of 2026-05-29)

**Where things stand:** Phases 1–5 plus the full post-review program are
complete and merged to `main`. Since the V2025 data refresh the project
has worked through: a methodology book + diagnostic-plot pass, an outlier
audit, a historical-reference scenario redesign, domestic/international
**migration decomposition** (engine + ACS B07001 age shapes), a **NYSDOH
vital-statistics** cross-source audit (closes issue #2), reproducibility
infrastructure (`data_raw/MANIFEST.toml` + inlined foundational files),
**USALEEP-adjusted Washington mortality** (now the production survival
schedule), a **town-forecast audit** (Notebook 12), and **town forecast
v3** (PEP base-year rescaling + CCR/CWR shrinkage toward the county).
`make run-all` (Notebooks 01–10) runs clean end-to-end in ~40s.
**207 tests passing.**

**Headline numbers (Washington County, baseline scenario):** 59,839 in
2024 → 53,361 in 2040 → **47,990 in 2050** (~19.8% decline). The 2050
figure rose from 47,567 once USALEEP-adjusted Washington mortality
became the production survival schedule.

For the chronological "what we did" record see
**[`docs/changelog.md`](changelog.md)** — the canonical current-state
reference, newest first. The phase sections below preserve the original
Phase 1-5 narrative for context; their numbers are frozen at each
phase's merge time. Notebooks now run **01–12**: 01–10 are the forecast
pipeline (`make run-all`); 11 is rural-town descriptive analysis; 12 is
the town-forecast diagnostic/audit (11 and 12 are standalone).

**Current focus / active follow-ups:**
- **New town-forecast approach** under discussion (2026-05-29). The v3
  town forecasts are as good as the ACS/PEP small-area data supports —
  the honest ceiling is sampling noise, not the method. The user is
  proposing a different approach to towns. Current method:
  `docs/methodology.md` §"Town forecast v3".
- **Deferred** (Notebook 12 recommendation #2): extend the town IPF to
  county age × sex *row* marginals via an independent town-total anchor.
  Uncertain payoff — no clearly-better town-total source than the
  Hamilton-Perry cohort-change ratios already in use.
- Untouched, lower-priority: final-deliverable polish (Notebook 10 as a
  reader-facing summary), `data_dictionary.md` / `workflow.md` currency.

### Phase 1 — COMPLETE (refreshed numbers under V2025 refresh)

Merged to `main` at commit `408aaa4`. Phase 1 covers loaders for every raw data source on disk (Census PEP 3 vintages, Census SYA, CDC Bridged-Race, NYSDOL, NYSDOH, Cornell PAD), the `popfc.reconcile` module, Notebooks 01–03, and interim parquet outputs `population_reconciled.parquet`, `county_components.parquet`, and `county_agesex_1990_2024.parquet` (post-V2025-refresh, was `_1990_2023`).

**Post-merge refinement (in progress, branch `feat/july1-decennial-anchor`, 2026-05-24):** The reconciled series now anchors **every year on a July 1 estimate**, including the decennial years 2000/2010/2020. Previously the rule used the April 1 decennial enumeration at those three years, which created a ~3-month phase shift relative to the otherwise July 1 series and distorted year-over-year trend visualizations. New rule:

- **2000–2019**: NYSDOL July 1 intercensal estimate (continuous across the 2000 and 2010 decennials).
- **2020+**: Census PEP July 1 postcensal estimate, latest vintage (covers the 2020 decennial as the base of the postcensal series).

The April 1 decennial enumerations are still loaded into `population_all_sources.parquet` for QA but are not used in `population_reconciled.parquet`. Visual check at `notebooks/figures/decennial_seam_check_new_rule.png` confirms the new July 1 line passes smoothly through what used to be April 1 anchor points (most visible: Saratoga 2000, where the former anchor sat ~900 persons below the trend).

Open Phase-1 follow-ons (deferred): GitHub issues #2 (NYSDOH vital-stats API pulls), #5 (extend reconciled series back to 1970), and #6 (control single-year age × sex frame to reconciled totals — three-layer raw / audit / controlled design).

### Phase 5 — IN PROGRESS on `feat/phase-5-reporting` (not yet merged)

Wrap-up: clean exports for downstream consumers + a summary notebook.

**New code:**

- `src/popfc/reporting/export.py` — `write_final_exports()` produces a tidy set of CSV/parquet artifacts under `data_final/`: `summary_headline.csv`, `washington_history.csv`, `washington_components.csv`, `county_forecast_totals.csv`, `county_forecast_agesex.parquet`, `town_forecast_totals.csv`, `town_forecast_agesex.parquet`.

**Notebook 10 — `notebooks/10_final_summary.ipynb`** — five-section narrative summary: (1) headline trajectory with Cornell PAD overlay, (2) cohort context indexed to 2023, (3) decomposition of decline into natural change vs net migration, (4) age pyramid 2023 vs 2050, (5) per-town table and chart with town shares. Last cell calls `write_final_exports()`.

**Data dictionary** at `docs/data_dictionary.md` — one section per `data_interim/` and `data_final/` artifact with column types and brief descriptions.

#### Phase 5 still-to-do (small)

- Done in Phase 5 cleanup: `popfc_R/` has been deleted (`docs/r_reference/` retains the prose/R code for reference).
- Optional: small README polish; optional Streamlit dashboard.

### Phase 4 — COMPLETE on `feat/phase-4-town-forecasts` (merged to main `acd3e59`)

Hamilton-Perry projector for Washington County's 17 towns plus a pro-rata constraint to the county forecasts under all 3 scenarios.

**New modules:**

- `src/popfc/models/hamilton_perry.py` — `aggregate_b01001_to_5yr_bands()`, `cohort_change_ratios(cap=(0.5, 2.0))`, `child_woman_ratios()`, `project_one_county_hp()`. CCR cap dampens small-area ACS sampling noise.
- `src/popfc/constrain/prorata.py` — `apply_prorata_constraint()` scales sub-areas to match parent totals.

**Notebook 09 — `notebooks/09_town_forecast.ipynb`** uses two ACS vintages (2015-2019 and 2020-2024) to compute CCRs, projects each town 2022 → 2047 in 5-year steps, applies pro-rata constraint at every forecast year for each of low/baseline/high scenarios. Output: `data_interim/town_forecasts.parquet` (11,016 rows = 17 towns × 3 scenarios × 6 years × 2 sexes × 18 bands).

**Headline town trajectories** (baseline 2022 → 2047): 14 of 17 Washington towns decline; Greenwich (+29%), Cambridge (+20%), and Hampton (+188% — flagged as a small-town anomaly even after capping) grow. The fastest declines are in the smallest northern towns (Dresden, Hebron, Putnam).

**Tests: 130 passing** (8 hamilton_perry + 4 prorata added on top of 118).

### Phase 3 — COMPLETE on `feat/phase-3-cohort-component` (merged to main `7b3e7cd`)

Cohort-component projector + the three input prep notebooks are all built and producing results. Tests: 118 passing as of merge.

**Modules** (`src/popfc/models/`):

- `mortality.py` — `survival_rates_from_life_table()` with optional `top_code_age` rebanding for matching population data. Closed-band Sx = L(x+1)/L(x); boundary uses Preston's combined formula L(ω)/[L(ω-1) + L(ω)] applied to (P(ω-1) + P(ω)).
- `fertility.py` — NCHS 2023 reference schedule (TFR = 1.621) + `build_county_year_asfr()` that scales the schedule to match observed total births county-by-county.
- `migration.py` — `build_net_migration_rates()` via the residual method on Census SYA year-pairs. Rates per source-age person, so the engine adds them to survival.
- `cohort_component.py` — `project_one_county()`, the main engine. Single-year by single-year-of-age × sex, with scalar `asfr_multiplier` and `net_mig_multiplier` scenario knobs.

**Notebooks 05-08:**

- 05 — fertility prep → `data_interim/asfr.parquet` (12,760 rows post-V2025-refresh; 62 counties × 5 years 2020-2024 + Washington × 9 historical years)
- 06 — mortality prep → `data_interim/survival_rates.parquet` (606 rows; US 2023 + NY 2022 × 3 sexes × 101 ages)
- 07 — migration prep → `data_interim/net_migration_rates.parquet` (10,540 rows; 4 year-pairs averaged post-V2025-refresh)
- 08 — county forecast → `data_interim/county_forecasts.parquet` (83,592 rows post-V2025-refresh; 6 counties × 3 scenarios × 27 years 2024-2050 × 2 sexes × 86 ages)

**Headline projection** (baseline scenario, Washington County, post-V2025-refresh): 59,839 in 2024 → 52,979 in 2040 → **47,567 in 2050** (~20.5% decline). Less pessimistic than the original 2023-base run (45,342 in 2050, ~24.5% decline) because (a) the base year is one year later and (b) the 2023-24 year-pair softened the pandemic-era out-migration signal in the residual average.

#### Phase 3 follow-ons (not blocking; deferred to Phase 4 / future)

- Replace national ASFR pattern with NYSDOH births-by-mother's-age (issue #2 unblocked).
- Smooth migration with a Rogers-Castro model schedule for stability over long horizons.
- USALEEP-based Washington-specific mortality (currently using state rates).

### Phase 2 — COMPLETE on `feat/phase-2-external-data` (merged to main `e0ff419`)

All external-data loaders, the audit notebook, and the refresh pipeline shipped on commits `0540743` (ACS) and `af5ace7` (NCHS + Notebook 04 + download.py).

**Loaders added** (`src/popfc/data/`):

- `acs.py` — generic ACS 5-year API loader. `load_acs5_group()` for any table group; `get_acs_variables()` for metadata. `LATEST_ACS5_YEAR = 2024` (ACS 2020–2024); update is one line. Reads `CENSUS_API_KEY` env var; cache under `data_raw/acs/<year>/`.
- `nchs.py` — NCHS national life tables (2023, NVSR 74-06), NY state life tables (2022, NVSR 74-12), and USALEEP small-area life expectancy (2010–2015 period, tract-level). All emit the new `LIFE_TABLE_COLUMNS` schema.
- `download.py` — centralized refresh registry. 15 sources registered (9 NCHS XLSX/CSV, 6 ACS group-pulls). CLI: `python -m popfc.data.download [--list | --source NAME | --force]`.

**ACS tables pulled and cached** statewide (62 counties + 1,023 MCDs):

- **B01001** sex by age (49 vars)
- **B07001** geographic mobility by age (96 vars)
- **B06001** place of birth by age (60 vars)
- Sanity check: Washington MCD totals exactly equal county total (60,522).

**Notebook 04 — `notebooks/04_external_data.ipynb`** — ACS-vs-PEP totals check, quick-look on age structure / foreign-born share / mover share, plus life-table audit. Writes `data_interim/life_tables.parquet` (793 rows: 303 US + 303 NY + 187 Washington tracts).

**Tests: 65 passing** (was 39 + 26 for NCHS/download).

#### Next: merge Phase 2 to main, then Phase 3

After merge, cut `feat/phase-3-cohort-component` for the actual forecasting work:

1. **Notebook 05 — fertility prep** (ASFR from Census PEP rate columns; later NYSDOH births when API pulls land — issue #2).
2. **Notebook 06 — mortality prep** (NY state 2022 life table → survival rates `Sx = Lx(t+1) / Lx(t)`, with optional USALEEP tract-level adjustment).
3. **Notebook 07 — migration prep** (residual method using `county_components.parquet` + ACS B07001/B06001).
4. **`src/popfc/models/cohort_component.py`** — county-agnostic forecaster class.
5. **Notebook 08 — county forecast** — primary Washington + 5 validation counties; project to 2050; low/medium/high scenarios; benchmark vs Cornell PAD.



### Phase 0 — COMPLETE

- Directory layout: `src/popfc` + `pyproject.toml` + `requirements.txt` + `requirements-dev.txt`
- Python 3.12.3 venv at `.venv/` with pandas 2.3.3, numpy 2.4.4, pyarrow 23, scipy 1.17, statsmodels 0.14.6, jupyterlab 4.5.6, pytest 8
- `popfc` package installed in editable mode (`pip install -e .`)
- Jupyter kernel `popfc` (displayed as "Python (popfc)") registered
- Raw data copied from `popfc_R/data_raw/` to `data_raw/` (277 MB)
- Output directories: `data_interim/`, `data_final/`
- R project reference materials (`.qmd`, `setup.R`, `_quarto.yml`, `images/`, `CLAUDE.md`) preserved to `docs/r_reference/`
- Smoke tests: **4 passed**
- Git: feature branch `feat/phase-1-data-reconciliation` on primary tree; worktree `.worktree-docs/` pinned to long-lived `docs/main` branch (docs commits land there and are merged into `main` via normal branch flow, so `main` never receives direct commits); repo at https://github.com/donboyd5/popfc

### Data already present in `data_raw/`

- **Census Bureau**: county population estimates & components of change (`co-est2024-alldata.csv`, `co-est2020-alldata.csv`, `co-est2010-alldata.csv`), single-year-of-age by sex 2020–2023 (`cc-est2023-syasex-36.csv`), subcounty estimates (`sub-est2023.csv`, `cc-est2023-alldata.csv`), and pre-2000 files under `census/1970-1980/`, `1980-1990/`, `2000-2010/`, `2010-2020/`, `2020-decennial/`, `2020-plus/`, `levels_components/`, `saipe/`
- **CDC WONDER**: Bridged-Race Population Estimates 1990–2020 for Washington County (single-year-of-age by sex)
- **NYSDOL**: Annual population estimates 1970–2023 for all NY counties + 7 PDFs of documentation
- **NYSDOH**: Population by age/sex/race/county 2003+, vital-stats
- **IRS**: Individual income/migration statistics + doc guides
- **Cornell PAD**: Washington County projections + `Washington.pdf` (1.6 MB methodology)

### Known gaps / external data still to pull

- **ACS 5-year** — town-level demographics, migration (Census API; requires API key)
- **NYSDOH vital statistics** — births/deaths API pulls (health.data.ny.gov)
- **Sub-county vital statistics** — births/deaths at town level (likely only 5-year averages for small places)
- **NCHS / SSA life tables** — age-sex mortality rates (`NY_B.XLSX` small-area file for WashCo tracts)
- **Possibly BEA** — covariates for migration models

### Future data refresh (not urgent)

At some point — likely once the first forecast iteration is complete — we should pull a fresher vintage of every input data source. For most sources an additional year of data is expected to be available (e.g., Census PEP vintage `v2025`, NYSDOL through 2024, NYSDOH through a more recent year, IRS migration through the latest tax year).

Design implications already in place so this is cheap when we do it:

- Every loader accepts a `path` (and usually a `vintage`) parameter and auto-derives the vintage tag from the filename. Replacing an upstream file is a one-line change at the call site, not an edit deep in code.
- Raw files live under `data_raw/<source>/` as a copy of `popfc_R/data_raw/` (refreshable with `rsync -a --delete popfc_R/data_raw/ data_raw/`).
- The reconciliation rules in Notebook 01 handle vintage overlap by keeping the latest, so adding a newer PEP vintage just extends the postcensal series automatically.

When we do refresh: drop newer files into `data_raw/`, update the `DEFAULT_*` constants in each loader (or pass paths explicitly), re-run notebooks 01–03, verify the QA checks still pass, and re-run downstream forecasts. Eventually formalize as `src/popfc/data/download.py` with per-source pull scripts (see "Deferred: data refresh pipeline" in cross-session memory).

---

## Final directory layout

```
popfc/
├── README.md
├── pyproject.toml              PEP-621 project metadata, loose deps
├── requirements.txt            runtime deps (pinned loosely; tighten via pip freeze)
├── requirements-dev.txt        pytest, ruff, nbstripout
├── .gitignore                  ignores .venv, data_*, caches
├── .python-version             "3.12"
├── .venv/                      virtualenv (gitignored)
├── docs/
│   ├── planning.md             this file
│   └── r_reference/            preserved .qmd, .R, images, CLAUDE.md from the legacy R project
├── data_raw/                   raw source data (gitignored; fetched via download pipeline)
├── data_interim/               cleaned/harmonized parquet files (gitignored)
├── data_final/                 forecast outputs (gitignored)
├── notebooks/                  01_population_reconciliation.ipynb, ... 08_town_forecast.ipynb
├── src/popfc/                  installable package
│   ├── __init__.py
│   ├── paths.py                central paths + FIPS constants
│   ├── data/                   census.py, cdc.py, nysdol.py, nysdoh.py, irs.py, cornell.py, acs.py
│   ├── validate/               reconcile.py
│   ├── models/                 cohort_component.py, statistical.py
│   ├── constrain/              ipf.py, prorata.py
│   └── viz/                    pyramids.py, reconcile_plots.py
└── tests/
    └── test_smoke.py
```

---

## Next Steps

### Phase 1 — Data Audit & Reconciliation (the careful part)

1. **Long-format population series** covering all 62 NY counties, all available years, one row per (county, year, source, vintage). Sources:
   - Census PEP intercensal 1970–2000 (archived files in `data_raw/census/1970-1980/`, `1980-1990/`)
   - Census PEP 2000–2010 intercensal
   - Census PEP 2010–2020 (postcensal + intercensal)
   - Census PEP 2020–2024 (postcensal)
   - Decennial 1970/1980/1990/2000/2010/2020
   - NYSDOL published estimates
   - CDC Bridged-Race (Washington only — summed across age/sex)
   - NYSDOH (Washington only — summed)
   - Cornell PAD base year (anchor point)

2. **`notebooks/01_population_reconciliation.ipynb`** — for Washington:
   - Overlay all series on one chart
   - Flag disagreements >~0.5%
   - Document *why* each series differs (vintage revisions, methodology, race bridging)
   - **Decide and document the official control-total series** for each year

3. **`notebooks/02_components_audit.ipynb`**:
   - Births: Census PEP vs NYSDOH vs NCHS
   - Deaths: Census PEP vs NYSDOH vs NCHS
   - Net migration: Census PEP residual vs IRS vs ACS
   - Verify identity: Pop(t) = Pop(t-1) + B − D + NetMig

4. **`notebooks/03_age_sex_audit.ipynb`**:
   - CDC Bridged-Race 1990–2020 vs Census SYA 2020–2023
   - Continuity across 2020 seam; smoothing as needed

5. **Deliverables**:
   - `data_interim/county_pop_series_long.parquet` — all series stacked with provenance
   - `data_interim/county_control_totals.parquet` — single authoritative row per (county, year) with `source_chosen` and `reason` columns; this is what everything downstream depends on
   - `data_interim/county_components.parquet` — reconciled births/deaths/migration

### Phase 2 — ACS & External Data Ingestion

1. ACS 5-year estimates for all 62 NY counties and for Washington County towns via Census API (B01001 sex-by-age, B06001 mobility, B07001 geographic mobility)
2. NCHS / SSA life tables → `data_interim/life_tables.parquet`
3. NCHS small-area life expectancy (USALEEP) for Washington County tracts
4. All persisted with provenance metadata

### Phase 3 — County Cohort-Component Model

1. `notebooks/04_fertility.ipynb` — age-specific fertility rates (ASFR) from NYSDOH births
2. `notebooks/05_mortality.ipynb` — age/sex survival rates from life tables
3. `notebooks/06_migration.ipynb` — age/sex net-migration rates (residual method)
4. `src/popfc/models/cohort_component.py` — county-agnostic forecaster as a class
5. `notebooks/07_county_forecast.ipynb` — run for primary + validation-cohort counties; project to 2050; low/medium/high scenarios
6. Validate against Cornell PAD projections and recent Census estimates

### Phase 4 — Town-Level Forecasts

1. Identify Washington County towns/MCDs and FIPS codes
2. Cohort-component per town using ACS age-sex + allocated components
3. Statistical models (ARIMA, ETS, possibly Prophet) on total town population
4. Ensemble / average per town
5. **Constrain** town forecasts to sum to county forecast (pro-rata or IPF)
6. `notebooks/08_town_forecast.ipynb`

### Phase 5 — Reporting

- Final summary notebook (charts, tables, data dictionary)
- Export CSV/parquet for downstream use
- Optional: Streamlit or Plotly Dash dashboard
- Done in Phase 5 cleanup: `popfc_R/` has been deleted (`docs/r_reference/` retains the prose/R code for reference).

---

## Future analytical extensions (NOT in scope for this project)

These questions are intentionally out of scope for `popfc` but should be
*enabled* by this project's design. The plan is that a sibling project
(e.g., `popny_analysis/`) will `pip install -e ../popfc` and use the loaders
and cleaned interim data directly.

Example questions the user is interested in eventually:

- Which rural NY towns have had rapid population growth?
- Was that growth driven by natural increase, domestic migration, or international migration?
- How large was the growth, and over what horizon?
- What is a practical range of expected growth for Washington County towns given peer-town patterns?

### Design implications for THIS project (to enable that later)

| Decision here | Pays off later when doing the above |
|---|---|
| Loaders are statewide by default (never hardcode WashCo FIPS) | Every NY town is already available |
| Persist interim data statewide in `data_interim/*.parquet` | Descriptive analysis starts from an already-clean dataset |
| Long/tidy format with `geoid`, `county_fips`, `mcd_fips` columns | Cross-county queries are one-liners |
| Data dictionary + provenance columns (`source`, `vintage`, `notes`) | Can always answer "where did this number come from?" |
| Loaders live in `src/popfc/data/`, not in notebooks | Sibling project imports them cleanly |
| Town-level components of change (births/deaths/migration) when available, not just county | Natural-increase-vs-migration decomposition is trivial |
| Age-sex detail preserved (don't collapse prematurely) | Age-profile questions (e.g., "growth came from retirees") stay answerable |

### Raw data that this project should pull even though we don't analyze it here

- ACS 5-year for **all NY MCDs** (not just Washington's towns) in Phase 2
- NYSDOH vital stats for all NY towns where available (even if we only use Washington)
- USDA Rural-Urban Continuum Codes (county) for future rural classification
- IRS SOI migration flows (county-to-county) statewide

### What stays out

- Descriptive analysis of non-Washington towns
- Ranking / exploratory notebooks beyond the validation cohort
- Any visualization targeted at the "rural NY growth" questions

---

## One-time setup (already executed)

```bash
cd /home/donboyd5/Documents/python_projects/popfc
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-dev.txt
pip install -e .
python -m ipykernel install --user --name popfc --display-name "Python (popfc)"
mkdir -p data_raw data_interim data_final
python -m popfc.data.download              # fetch the automated sources
pytest -q
```

## Daily workflow

```bash
cd /home/donboyd5/Documents/python_projects/popfc
source .venv/bin/activate
jupyter lab
# or: code . / positron .
```

---

## Prompt for a new Claude Code session

Copy-paste into a new session to continue:

> I'm continuing the popfc project — Python population forecast for Washington
> County, NY and its 17 towns. Project root is
> `/home/donboyd5/Documents/python_projects/popfc/`. Python 3.12 venv at `.venv/`,
> installable package at `src/popfc/`. Repo at https://github.com/donboyd5/popfc.
>
> **Status: Phases 1-5 plus the full post-review program are COMPLETE and merged
> to main.** The pipeline (Notebooks 01-10) runs clean end-to-end via `make
> run-all` in ~40s; **207 tests pass**. Forecast base year is **2024**; Washington
> baseline 2050 is **47,990** (~19.8% decline from 2024, with USALEEP-adjusted
> Washington mortality as the production survival schedule).
>
> **Where to find current state:** `docs/changelog.md` is the canonical
> "what we did recently" record (newest first) — read it for the latest
> merged work: migration decomposition, NYSDOH vital stats, data-archival,
> USALEEP qx-ratio mortality, the town-forecast audit, and town forecast v3.
> `docs/planning.md`'s phase sections are frozen historical context; the
> changelog has fresher detail.
>
> Start by reading, in order:
> 1. `CLAUDE.md`               — project rules (git workflow, data conventions)
> 2. `docs/workflow.md`        — how to run the pipeline end-to-end
> 3. `docs/methodology.md`     — plain-language reference for every method, acronym, and notation symbol
> 4. `docs/changelog.md`       — recent work, newest first
> 5. `docs/planning.md`        — this status section + frozen phase narrative
> 6. `docs/data_dictionary.md` — column reference for every parquet artifact
>
> Headline outputs already exist:
> - `data_interim/county_forecasts.parquet` — 6 counties × 3 scenarios × 27 yrs (2024-2050) × age × sex
> - `data_interim/county_forecasts_components.parquet` — domestic/international component scenarios (Batch 4b)
> - `data_interim/town_forecasts.parquet`   — 17 Washington towns × 3 scenarios × 6 yrs × age-band × sex (v3: PEP-rescaled base + CCR/CWR shrinkage + IPF)
> - `data_final/*` — clean CSV + parquet exports for downstream use
> - Notebooks: 01-10 forecast pipeline; 11 rural-town descriptive analysis; 12 town-forecast diagnostic/audit
>
> Key reminders:
> - **Never work on main.** Code goes on `feat/*` branches; docs go on the long-lived `docs/main` branch via the worktree at `.worktree-docs/`. Both merge into `main` via normal branch flow — **don't merge to main without my go-ahead.** See `CLAUDE.md`.
> - Loaders use a **string-first ingestion pattern** — read raw CSVs with `dtype=str`, then explicitly coerce with `coerce_numeric()` from `popfc.data._common`. Apply to any new loader.
> - Notebooks are generated from `_build_NN_*.py` scripts; outputs are stripped on commit (nbstripout). Edit the `_build` script, regenerate, re-execute — don't hand-edit the `.ipynb`.
> - `CENSUS_API_KEY` is set in `~/.profile` and in `.claude/settings.local.json` (env); ACS responses are cached under `data_raw/acs/<year>/`.
> - The legacy R/Quarto project was deleted in Phase 5; `docs/r_reference/` retains its prose for reference only.
>
> **What I want to do this session:** [fill in]. Current live thread (2026-05-29):
> designing a **new approach to the town forecasts** — v3 is as good as the
> ACS/PEP small-area data supports, and I'm proposing a different approach. For
> new analyses, add a new notebook (`notebooks/NN_<name>.ipynb` + companion
> `_build_NN_*.py`) rather than modifying existing ones; cut a `feat/<descriptive>`
> branch from main before writing code.
>
> Also check `~/.claude/projects/-home-donboyd5-Documents-python-projects-popfc/memory/MEMORY.md` for cross-session guidance.

---

## Critical files / references

- `CLAUDE.md` (project root) — durable project rules (git workflow, data conventions, code conventions)
- `docs/workflow.md` — operating manual: how to run the pipeline end-to-end
- [docs/r_reference/README.md](r_reference/README.md) — index of preserved R materials
- [docs/r_reference/methodology.qmd](r_reference/methodology.qmd) — Cornell PAD methodology (prose)
- [docs/r_reference/steps.qmd](r_reference/steps.qmd) — high-level forecasting workflow
- [docs/r_reference/misc_data_notes.qmd](r_reference/misc_data_notes.qmd) — NYSDOH / LAUS / QCEW data notes
- `data_raw/cornell/Washington.pdf` — Cornell PAD methodology doc (1.6 MB)
- `data_raw/cornell/washington-county.csv` — Cornell PAD projection benchmark
- `data_raw/cornell/padprojections115.xls` — Cornell PAD projection spreadsheet

## Verification approach

- Every notebook ends with assertions / sanity checks (populations sum, no negatives, year coverage complete)
- Phase 1 deliverable is testable: reconstruct Census PEP population from components and verify identity holds
- County forecast compared to Cornell PAD projections (within a few percent near-term)
- Town forecasts sum to county forecast exactly (by construction)
