# Workflow — how to build the county forecasts (and eventually the towns)

This is the operating manual for actually producing forecasts with this project. It complements [planning.md](planning.md) (project goals and phase status) and [../CLAUDE.md](../CLAUDE.md) (project rules).

If you came here asking "do I run a script or open each notebook?" — the short answer is: **today, you open each notebook in order; eventually we'll wrap them in a `make run-all`-style script.** The notebooks are deterministic and idempotent — re-running 03 produces byte-identical output to the previous run — so a script is just a thin wrapper.

------------------------------------------------------------------------

## The build pipeline at a glance

```
                  ┌────────────────────────────────────────────┐
                  │              data_raw/ (input)             │
                  └────────────────────────────────────────────┘
                                       │
       ┌───────────────┬───────────────┼───────────────┬──────────────┐
       ▼               ▼               ▼               ▼              ▼
  Census PEP       NYSDOL         CDC bridged       NCHS         Cornell PAD
  (counts +     (1970-2023)      (Wash 1990-       (life          (benchmark)
  components)                       2020)         tables)
       │               │               │               │              │
       ▼               ▼               ▼               ▼              ▼
  ┌───────────────────────────────────────────────────────────────────────┐
  │  Loaders in src/popfc/data/*.py emit canonical long-format frames     │
  │  (POP_LONG, COMPONENTS_LONG, AGESEX_LONG, LIFE_TABLE)                  │
  └───────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
  Notebook 01 → population_reconciled.parquet      (single authoritative pop series)
  Notebook 02 → county_components.parquet           (births/deaths/migration)
  Notebook 03 → county_agesex_1990_2023.parquet     (age × sex base for CCM)
  Notebook 04 → life_tables.parquet                 (NCHS + USALEEP stack)
                + ACS B01001/B07001/B06001 caches under data_raw/acs/
  Notebook 05 → asfr.parquet                        (scaled fertility rates)
  Notebook 06 → survival_rates.parquet              (single-year Sx from life table)
  Notebook 07 → net_migration_rates.parquet         (residual method m(x, sex))
                                       │
                                       ▼
  Notebook 08 → county_forecasts.parquet            (CCM run 2023 → 2050,
                                                     low/base/high × 6 counties)
                                       │
                                       ▼
                       Phase 4 (forthcoming):
                       Notebook 09 → town_forecasts.parquet
                       (Hamilton-Perry or ARIMA per MCD, constrained to county totals)
```

Each notebook lives at `notebooks/<NN>_<name>.ipynb` and has a companion `notebooks/_build_<NN>_<name>.py` that **regenerates** the notebook from a Python script. The regeneration is one-way: edit `_build_*.py`, run it, then re-execute the notebook. This keeps the notebook contents diff-friendly in git (stripped outputs via nbstripout).

------------------------------------------------------------------------

## End-to-end run from scratch

Assuming the project is set up (see "First-time setup" below):

```bash
cd ~/Documents/python_projects/popfc
source .venv/bin/activate
export CENSUS_API_KEY=<your-key>   # only needed if you'll re-pull ACS

# Refresh raw data (optional; skips files already cached)
python -m popfc.data.download

# Run the pipeline. Each command takes ~5-60 seconds.
for nb in 01_population_reconciliation 02_components_audit \
          03_age_sex_audit 04_external_data \
          05_fertility 06_mortality 07_migration \
          08_county_forecast; do
  jupyter nbconvert --to notebook --execute "notebooks/${nb}.ipynb" \
                     --output "${nb}.ipynb"
done

# Verify everything is green.
pytest -q
```

That's it. The four "headline" outputs are:

- `data_interim/population_reconciled.parquet` — historical population
- `data_interim/county_components.parquet`     — historical components of change
- `data_interim/county_agesex_1990_2023.parquet` — historical age × sex
- `data_interim/county_forecasts.parquet`      — projections 2023 → 2050

------------------------------------------------------------------------

## Notebook reference card

Every notebook has the same five-section structure: load → transform → diagnostic plots → QA assertions → save. Below is what each one specifically does.

### 01 — Population reconciliation

**Reads:** raw Census PEP (3 vintages) + NYSDOL annual estimates
**Writes:** `population_all_sources.parquet`, `population_reconciled.parquet`
**Decides:** for each (county, year) which source is authoritative.
Rules: NYSDOL census for 2000/2010/2020 decennials; NYSDOL intercensal
for 2001-2019; Census PEP postcensal for 2021-2024.

### 02 — Components audit

**Reads:** Census PEP components + Notebook 01's reconciled totals
**Writes:** `county_components.parquet`
**Verifies:** the demographic identity Pop(t) = Pop(t-1) + Births - Deaths + NetMig + Residual.
Cross-checks PEP counts against PEP rate-reconstruction.

### 03 — Age/sex audit

**Reads:** CDC Bridged-Race + Census SYA
**Writes:** `county_agesex_1990_2023.parquet`
**Quantifies:** the 2020 bridged-vs-unbridged methodology seam (~0.8% in
Washington).

### 04 — External data quick-look

**Reads:** ACS via API (cached) + NCHS life tables
**Writes:** `life_tables.parquet`
**Diagnostic:** ACS county totals vs reconciled PEP at the 5-year midpoint;
quick looks at foreign-born share, mover share, age structure.

### 05 — Fertility prep

**Reads:** `county_components.parquet`, `population_reconciled.parquet`,
`county_agesex_1990_2023.parquet`
**Writes:** `asfr.parquet`
**Method:** scale NCHS 2023 national ASFR schedule to match observed
total births per county-year. The age pattern is national; the level is
local.

### 06 — Mortality prep

**Reads:** `life_tables.parquet`
**Writes:** `survival_rates.parquet`
**Method:** turn the NY state 2022 life table into single-year survival
rates (S(x)=L(x+1)/L(x), boundary at age 100 via Preston's combined formula).

### 07 — Migration prep

**Reads:** `county_agesex_1990_2023.parquet`, `life_tables.parquet`
**Writes:** `net_migration_rates.parquet`
**Method:** residual method — net migration is what's left after
projecting last year's pop forward by survival. Averaged across the
2020-21, 2021-22, 2022-23 year-pairs to reduce noise.

### 08 — County forecast

**Reads:** survival, asfr, net_mig, plus the 2023 base population from
`county_agesex_1990_2023.parquet`
**Writes:** `county_forecasts.parquet`
**Method:** runs the cohort-component engine in `popfc.models.cohort_component`
for Washington + 5 validation counties, 2023 → 2050, under three
scenarios (low / baseline / high). Overlays the Cornell PAD benchmark.

------------------------------------------------------------------------

## Dependencies between notebooks

The notebooks form a DAG. If you re-run an upstream one, you'll want
to re-run everything downstream. The dependencies are:

```
01 ──► 02 ──► 05 ──┐
              │     │
              ▼     │
03 ──────────────────┼──► 08
              │     │
04 ──► 06 ────┘     │
   │                │
   └───► 07 ────────┘
```

Practically:

- Refreshing raw data → re-run 01, 02, 03, 04 (then everything downstream)
- A newer ACS vintage → re-run only 04 (then nothing changes downstream unless ACS is used by a Phase-4 town model)
- A newer NCHS life table → re-run 04, 06, 07, 08
- Changing forecast scenarios → re-run only 08

------------------------------------------------------------------------

## Refreshing raw inputs

Raw files live under `data_raw/<source>/`. Every refreshable source is
registered in `src/popfc/data/download.py`:

```bash
# See what's registered
python -m popfc.data.download --list

# Refresh one source
python -m popfc.data.download --source nchs_us_lt_2023_total

# Refresh everything (skips files already present)
python -m popfc.data.download

# Force re-fetch even if cached
python -m popfc.data.download --force
```

NCHS files are stable URLs (NVSR FTP). ACS pulls require
`CENSUS_API_KEY` in the environment.

To pull a newer NCHS vintage: update `LATEST_ACS5_YEAR` in
`src/popfc/data/acs.py` (one line) for ACS, or change the
`DEFAULT_*` paths in `src/popfc/data/nchs.py` for NCHS life tables.
The `download.py` registry also needs the new URL added.

------------------------------------------------------------------------

## When you want to add a new analytical scenario

Today the forecast knobs are two scalar multipliers (ASFR and net
migration). To add a scenario:

1. Edit `SCENARIOS` in `notebooks/_build_08_county_forecast.py`.
2. Regenerate the notebook: `python notebooks/_build_08_county_forecast.py`.
3. Re-execute the notebook.

To add a more expressive scenario (time-varying paths, age-specific
overrides), you'd extend `project_one_county()` in
`src/popfc/models/cohort_component.py` first — currently it accepts
only scalar multipliers.

------------------------------------------------------------------------

## When you want to add new counties or change the cohort

Edit the `COHORT` dict at the top of Notebook 08 (and 01, 02, 03, 07 if
you want the diagnostic plots to include them). The engine is
county-agnostic; the only constraint is that the county appears in
`asfr.parquet`, `net_migration_rates.parquet`, and the base-year
age/sex frame.

Currently the loaders are all statewide-by-default (per CLAUDE.md rule
1), so any of the 62 NY counties is automatically available — no data
changes needed.

------------------------------------------------------------------------

## Phase 4 — town forecasts (not yet built)

The plan for Washington County's 17 MCDs:

1. Load ACS B01001 for Washington's MCDs (already cached in
   `data_raw/acs/2024/`).
2. Either (a) run a town-level cohort-component model using MCD age × sex
   from ACS, or (b) run simpler statistical models (ARIMA / ETS) on
   total town population from `sub-est2023.csv`.
3. Constrain the town forecasts to sum to the Washington county
   forecast from Notebook 08, via pro-rata or iterative
   proportional fitting (IPF). This will be `notebooks/09_town_forecast.ipynb`.

------------------------------------------------------------------------

## First-time setup (already done, but for reference)

```bash
cd ~/Documents/python_projects/popfc
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-dev.txt
pip install -e .
python -m ipykernel install --user --name popfc --display-name "Python (popfc)"
cp -r popfc_R/data_raw ./data_raw      # initial raw-data copy
mkdir -p data_interim data_final
pytest -q                              # confirms install
```

------------------------------------------------------------------------

## When something breaks

The notebooks are deterministic — same inputs, same outputs. If a
notebook starts failing where it previously worked, the most likely
causes are:

1. **A loader's input file changed**. Run `python -m popfc.data.download
   --list` to see what's cached vs missing. If you intentionally
   refreshed a file, re-run the affected downstream notebook(s).
2. **A schema constant moved**. The canonical schemas live in
   `src/popfc/data/_common.py` (POP_LONG, COMPONENTS_LONG, AGESEX_LONG,
   LIFE_TABLE) and `src/popfc/models/*.py` (SURVIVAL_RATES,
   ASFR_LONG, NET_MIGRATION_RATES, PROJECTION). Loaders' output frames
   must match these column orders exactly.
3. **The test suite catches almost all of this** —
   run `pytest -q` and follow the failures backward.

For real bugs, open a GitHub issue. The current list:
https://github.com/donboyd5/popfc/issues
