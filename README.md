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
├── docs/planning.md         master plan (read this first)
├── popfc_R/                 previous R/Quarto implementation, kept for reference
├── data_raw/                raw source data (not committed; copied from popfc_R/data_raw)
├── data_interim/            cleaned/harmonized parquet files (not committed)
├── data_final/              forecast outputs (not committed)
├── notebooks/               Jupyter analysis + documentation
├── src/popfc/               installable Python package
│   ├── paths.py             central path constants
│   ├── data/                loaders: census, cdc, nysdol, nysdoh, irs, cornell
│   ├── validate/            cross-source reconciliation
│   ├── models/              cohort_component.py, statistical.py
│   ├── constrain/           town-to-county controlling (IPF / pro-rata)
│   └── viz/                 plots, age pyramids
└── tests/                   pytest smoke tests
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

# 6. Copy raw data from the R project (~277 MB; takes ~30s)
cp -r popfc_R/data_raw ./data_raw

# 7. Create the interim/final output directories
mkdir -p data_interim data_final

# 8. Verify the install
pytest -q
```

## Daily workflow

```bash
cd /home/donboyd5/Documents/python_projects/popfc
source .venv/bin/activate
jupyter lab
```

In notebooks, select the **"Python (popfc)"** kernel and you can `import popfc`
to get the package paths and utilities.

## Data refresh

Because `data_raw/` is a **copy** of `popfc_R/data_raw/` (not a symlink), if new
source data is added to the R project you must re-copy:

```bash
rsync -a --delete popfc_R/data_raw/ data_raw/
```

## Development

```bash
pytest              # run tests
ruff check src/     # lint
ruff format src/    # format
```
