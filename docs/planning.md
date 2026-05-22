# Washington County NY Population Forecast — Python Project Planning

> **Quick resume prompt:** *Please read docs/planning.md then read other files as needed and tell me status and suggest next steps.* (Full session-resume prompt is at the bottom of this file.)

## Goals

I want to forecast annual population of counties in the Washington County area of New York and the towns within Washington County. Those towns sum to the county total. I want the county forecasts to follow a cohort-components method similar to that implemented by Cornell University.

The town forecasts for Washington County should sum to the county forecast. They do not necessarily have to use the same forecasting method as the county method. It might be that we use a simpler method for the towns and then force them to sum to the county using an optimization approach. However we will need to be able to estimate some details of the town forecasts.

One main reason I am doing this is so that I can understand the drivers of population growth or decline in the towns of southern Washington County. Thus the need for components. I also want to be able to understand, going forward, what possibilities there are. For example, to what extent is population decline almost inevitable due to changing demographics and fertility and birth rates? To what extent could that be mitigated or reversed through domestic or international in-migration?

## Context

Rebuild of the R/Quarto project in `popfc_R/` as a proper Python project with
rigorous data validation. The original R project is preserved as reference and
will eventually be deleted; all its documents and R source have been preserved
under `docs/r_reference/`, and all its raw data copied to `data_raw/`.

### User priorities (emphasized explicitly)

1. **Careful data checking** — reconcile multiple population series and identify discrepancies
2. **Use the RIGHT total population** for the county (authoritative series selection)
3. **Use the right components** of change (births, deaths, migration)
4. **External data where needed** — ACS for town-level detail, life tables for mortality

### Guiding principles (cross-session)

- **Not constrained by the R implementation.** `popfc_R/` is reference material, not a template. Apply Python best practices and modern demographic-forecasting approaches even when they depart from the R code.
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

## Current Status (as of 2026-05-22)

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

### Phase 1 — IN PROGRESS

**Loaders built** (`src/popfc/data/`):

- `_common.py` — canonical long-format schemas (`POP_LONG_COLUMNS`, `COMPONENTS_LONG_COLUMNS`), FIPS helpers, and **string-first ingestion helpers** (`read_csv_strings`, `coerce_numeric`). All raw CSVs are read with `dtype=str` and explicitly coerced at the melt step so data anomalies surface as warnings instead of being silently masked by pandas' auto-inference.
- `census.py` — three PEP vintage loaders (2000–2010 intercensal, 2010–2020 intercensal, 2020+ postcensal) plus `load_all_pep()` stack. Emits both population totals and components of change, including the RATE columns (`RBIRTH`, `RDEATH`, etc., per-1000 mid-year average population) used in the R project's "adjusted births/deaths" formula for decennial seams.
- `nysdol.py` — NYSDOL annual estimates 1970–2023, program-type labels mapped to canonical `kind` values (`estimate` / `intercensal` / `census`).

All loaders accept `path` and `vintage` parameters so swapping in a newer file is a one-line change (see "Deferred: data refresh pipeline" in MEMORY.md).

**Notebook 01 — `notebooks/01_population_reconciliation.ipynb`** complete and executing cleanly end-to-end. Produces:

- `data_interim/population_all_sources.parquet` — 5,796 rows (stacked raw PEP + NYSDOL for QA)
- `data_interim/population_reconciled.parquet` — **1,575 rows** (63 entities × 25 years 2000–2024, one authoritative value per `(geoid, year)`)

Companion generator `notebooks/_build_01_reconciliation.py` produces the notebook from Python source so cells can be regenerated deterministically.

#### Reconciliation rules applied (Phase 1)

1. **Decennial anchors** (2000, 2010, 2020) — NYSDOL "Census Base Population" (`kind='census'`). Single curated series covers all three decennials consistently; Census PEP's `CENSUS2010POP` agrees for 2010, and Census encodes the April-1 2020 count as `ESTIMATESBASE2020` which we preserve in the raw stack rather than re-labeling.
2. **Postcensal years** (2021+) — Census PEP postcensal estimate from the latest vintage (`v2024`).
3. **Intercensal years** (2001–2019 non-decennial) — NYSDOL intercensal estimate. Rationale: NYSDOL's annual series extends back to 1970 with consistent methodology and was treated as authoritative by the legacy R workflow.
4. **Vintage overlap resolution** — when two PEP files cover the same `(geoid, year, kind)`, keep the later vintage (v2024 > v2020 > v2010int).

#### Key data-quality finding (carried forward from R)

**Components of change do NOT reconcile across the decennial seam.** Census intercensal estimates smooth the *totals* to hit the decennial count, but the published component series (births, deaths, migration) sums to the *postcensal* total — not the intercensal total. The rate columns (RBIRTH, RDEATH, etc.) combined with mid-year average population can be used to compute "adjusted" counts near the seam; this is documented in `docs/r_reference/get-components-of-change.qmd` and will be revisited in Notebook 02.

#### Phase 1 still-to-do

Active chunk (in progress on `feat/phase-1-data-reconciliation`):

1. **CDC Bridged-Race loader** (`src/popfc/data/cdc.py`) — Washington-only WONDER export, 1990–2020 single-year-of-age by sex. Unblocks Phase 3 cohort base year as well as the age/sex audit.
2. **NYSDOH loader** (`src/popfc/data/nysdoh.py`) — population by age/sex/race/county 2003+ from the existing file; flag births/deaths API pulls as a follow-on issue.
3. **Notebook 02 — components audit** (`notebooks/02_components_audit.ipynb` + companion `_build_02_components_audit.py`): cross-check Census PEP vs NYSDOH births/deaths; verify the demographic identity Pop(t) = Pop(t-1) + B − D + NetMig per county; write `data_interim/county_components.parquet`.
4. **Promote reconciliation logic** from Notebook 01 into `src/popfc/reconcile.py` with a unit test.

After this chunk:

- Notebook 03 — age/sex audit (CDC Bridged-Race 1990–2020 vs Census SYA 2020–2023; continuity across 2020 seam).
- Cornell PAD loader (forecast benchmark; small, can ride with Notebook 03 or later).
- Decision: extend the reconciled series back to 1970 using NYSDOL?

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
│   └── r_reference/            preserved .qmd, .R, images, CLAUDE.md from popfc_R
├── popfc_R/                    will be deleted once Phase 1 confirms nothing is lost
├── data_raw/                   copy of popfc_R/data_raw (gitignored)
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
- Decision on whether to delete `popfc_R/`

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
cp -r popfc_R/data_raw ./data_raw
mkdir -p data_interim data_final
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

> I'm continuing a Python project to forecast annual population for Washington County, NY and its constituent towns. The project root is `/home/donboyd5/Documents/python_projects/popfc/`. The virtualenv is at `.venv/`; the installable package is at `src/popfc/`; Python is 3.12. The repo is at https://github.com/donboyd5/popfc.
>
> **Start by reading `docs/planning.md` in full.** It has the current status, scope decisions, and next steps.
>
> Key reminders:
> - Phase 0 (env + scaffolding) is complete; smoke tests pass.
> - Phase 1 is partially complete: loaders for Census PEP (3 vintages) and NYSDOL are in `src/popfc/data/`; notebook `01_population_reconciliation.ipynb` produces `data_interim/population_reconciled.parquet` (1,575 rows, 2000–2024, no gaps). See planning.md for reconciliation rules.
> - Loaders use a **string-first ingestion pattern** — raw CSVs are read with `dtype=str`, then explicitly coerced with `coerce_numeric()` from `popfc.data._common`. Coercion failures warn (don't silently mask). Apply this pattern to every new loader.
> - R project at `popfc_R/` is reference only; its docs are preserved at `docs/r_reference/`. It will eventually be deleted — **do not feel constrained by the R implementation; always apply Python best practices.**
> - Scope: cohort-component engine is county-agnostic (FIPS param). Primary output for Washington County + towns; validation-cohort output for 5 neighbor counties; sanity-sweep totals across all 62.
> - Git workflow: **never work on main**. Primary tree is on a feature branch (code). Worktree `.worktree-docs/` is pinned to a long-lived `docs/main` branch (docs). Both code and docs merge into `main` via normal branch flow — `main` never receives direct commits. Push feature branches to GitHub; merges to main are lightweight (solo repo, PRs optional).
>
> Check `docs/planning.md` "Current Status" and "Phase 1 still-to-do" sections for what's next. Check `~/.claude/projects/-home-donboyd5-Documents-python-projects-popfc/memory/MEMORY.md` for cross-session guidance (including the string-first preference).

---

## Critical files / references

- `CLAUDE.md` (project root) — durable project rules (git workflow, data conventions, code conventions)
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
