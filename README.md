# popfc — Washington County, NY Population Forecast

Python project to forecast annual population for Washington County, NY and its
constituent towns, using cohort-component methodology at the county level and a
combination of cohort-component + statistical models at the town level (with
towns constrained to sum to the county forecast).

See [docs/planning.md](docs/planning.md) for the full plan.

## Project layout

```
popfc/
├── pyproject.toml           project metadata + loose deps (makes `popfc` importable)
├── requirements.txt         pinned runtime deps for reproducibility
├── requirements-dev.txt     pytest, ruff, nbstripout
├── CLAUDE.md                durable project rules (git workflow, conventions)
├── docs/
│   ├── planning.md          master plan and phase status (read this first)
│   ├── workflow.md          how to run the pipeline end-to-end
│   ├── data_dictionary.md   schemas for every interim/final artifact
│   └── r_reference/         preserved .qmd / .R prose from the legacy R project
├── data_raw/                raw source data (not committed; fetched via download script)
├── data_interim/            cleaned/harmonized parquet files (not committed)
├── data_final/              forecast outputs (not committed)
├── notebooks/               Jupyter notebooks 01–10 (build the forecast in order)
├── src/popfc/               installable Python package
│   ├── paths.py             central path constants
│   ├── data/                loaders: census, cdc, nysdol, nysdoh, cornell, acs, nchs, download
│   ├── models/              mortality, fertility, migration, cohort_component, hamilton_perry
│   ├── constrain/           prorata (town-to-county constraint)
│   ├── reporting/           export (clean data_final/ artifacts)
│   └── reconcile.py         population-series reconciliation
└── tests/                   pytest test suite (130 tests)
```

## One-time setup

Assumes Python 3.12 is available as `python3.12`.

```bash
cd /home/donboyd5/Documents/python_projects/popfc

# 1. Create the virtual environment
python3.12 -m venv .venv

# 2. Activate it (bash/zsh)
source .venv/bin/activate

# 3. Upgrade pip inside the venv
pip install --upgrade pip

# 4. Install runtime + dev deps, and install the popfc package in editable mode
pip install -r requirements-dev.txt
pip install -e .

# 5. Register a Jupyter kernel for this env
python -m ipykernel install --user --name popfc --display-name "Python (popfc)"

# 6. Create the interim/final output directories
mkdir -p data_raw data_interim data_final

# 7. Fetch raw data via the download pipeline (some sources need
#    CENSUS_API_KEY in env; everything else is anonymous-accessible).
export CENSUS_API_KEY=<your-key>          # for ACS pulls
python -m popfc.data.download

# 8. Verify the install
pytest -q
```

For sources without an automated download (Census PEP archives,
NYSDOL CSV exports, NYSDOH population file, CDC Bridged-Race WONDER
exports, Cornell PAD spreadsheet), you'll need to manually drop the
upstream files into `data_raw/<source>/` — see
[docs/workflow.md](docs/workflow.md) for the catalog.

## Daily workflow

```bash
cd /home/donboyd5/Documents/python_projects/popfc
source .venv/bin/activate
jupyter lab
```

In notebooks, select the **"Python (popfc)"** kernel and you can `import popfc`
to get the package paths and utilities.

## Data refresh

The download pipeline (`src/popfc/data/download.py`) registers every
refreshable upstream source. To refresh everything (skips files already
cached):

```bash
python -m popfc.data.download
```

To force a re-pull or list what's registered:

```bash
python -m popfc.data.download --force          # re-fetch everything
python -m popfc.data.download --list           # show the registry
python -m popfc.data.download --source NAME    # one file
```

## Development

```bash
pytest              # run tests
ruff check src/     # lint
ruff format src/    # format
```
