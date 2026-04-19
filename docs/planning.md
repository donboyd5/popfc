# Washington County NY Population Forecast — Python Project Planning

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

## Current Status (as of 2026-04-19)

### Phase 0 — COMPLETE

- Directory layout: `src/popfc` + `pyproject.toml` + `requirements.txt` + `requirements-dev.txt`
- Python 3.12.3 venv at `.venv/` with pandas 2.3.3, numpy 2.4.4, pyarrow 23, scipy 1.17, statsmodels 0.14.6, jupyterlab 4.5.6, pytest 8
- `popfc` package installed in editable mode (`pip install -e .`)
- Jupyter kernel `popfc` (displayed as "Python (popfc)") registered
- Raw data copied from `popfc_R/data_raw/` to `data_raw/` (277 MB)
- Output directories: `data_interim/`, `data_final/`
- R project reference materials (`.qmd`, `setup.R`, `_quarto.yml`, `images/`, `CLAUDE.md`) preserved to `docs/r_reference/`
- Smoke tests: **4 passed**

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

> I'm continuing a Python project to forecast annual population for Washington County, NY and its constituent towns. The project root is `/home/donboyd5/Documents/python_projects/popfc/`. The virtualenv is at `.venv/`; the installable package is at `src/popfc/`; Python is 3.12.
>
> **Start by reading `docs/planning.md` in full.** It has the current status, scope decisions, and next steps.
>
> Key reminders:
> - Phase 0 (env + scaffolding) is complete; smoke tests pass.
> - R project at `popfc_R/` is reference only; its docs are preserved at `docs/r_reference/`. It will eventually be deleted — **do not feel constrained by the R implementation; always apply Python best practices.**
> - Scope: cohort-component engine is county-agnostic (FIPS param). Primary output for Washington County + towns; validation-cohort output for 5 neighbor counties; sanity-sweep totals across all 62.
> - Phase 1 (data reconciliation) is the immediate priority — it's where the user most wants rigor.
>
> Check `docs/planning.md` for the "Next Steps" section to see what's in progress. Check `~/.claude/projects/-home-donboyd5-Documents-python-projects-popfc/memory/MEMORY.md` for cross-session guidance.

---

## Critical files / references

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
