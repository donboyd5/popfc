# popfc — convenience targets for the build pipeline.
#
# Usage:
#   make help          # this listing
#   make refresh-data  # fetch/cache raw data via popfc.data.download
#   make build-nb      # regenerate .ipynb files from notebooks/_build_*.py
#   make run-all       # execute notebooks 01-10 in order
#   make test          # pytest -q
#   make export-final  # regenerate data_final/ exports without re-running notebooks
#   make all           # refresh-data + build-nb + run-all + test
#
# Notebooks are executed in order; each writes its interim parquet(s) to
# data_interim/ which the next notebook reads.

PYTHON  := .venv/bin/python
JUPYTER := .venv/bin/jupyter
PYTEST  := .venv/bin/pytest

# Notebook stems — `.ipynb` files live in notebooks/.
NOTEBOOKS := \
    01_population_reconciliation \
    02_components_audit \
    03_age_sex_audit \
    04_external_data \
    05_fertility \
    06_mortality \
    07_migration \
    08_county_forecast \
    09_town_forecast \
    10_final_summary

.PHONY: help refresh-data build-nb run-all test export-final all

help:
	@echo "popfc make targets"
	@echo "  refresh-data   Fetch/cache raw data via popfc.data.download"
	@echo "                 (skips files already on disk; use --force to re-fetch)"
	@echo "  build-nb       Regenerate notebooks/*.ipynb from notebooks/_build_*.py"
	@echo "                 (one-way: _build_NN_*.py is the source of truth for cells)"
	@echo "  run-all        Execute notebooks 01-10 in dependency order"
	@echo "                 (writes data_interim/*.parquet and refreshes data_final/)"
	@echo "  test           Run pytest -q"
	@echo "  export-final   Refresh data_final/ exports from existing parquets"
	@echo "                 (faster than run-all when only Notebook 10 needs to re-run)"
	@echo "  all            refresh-data + build-nb + run-all + test"

refresh-data:
	$(PYTHON) -m popfc.data.download

build-nb:
	@for script in notebooks/_build_*.py; do \
	    echo ">> $$script"; \
	    $(PYTHON) "$$script"; \
	done

run-all:
	@for nb in $(NOTEBOOKS); do \
	    echo ">> executing notebooks/$$nb.ipynb"; \
	    $(JUPYTER) nbconvert --to notebook --execute "notebooks/$$nb.ipynb" --output "$$nb.ipynb" || exit $$?; \
	done

test:
	$(PYTEST) -q

export-final:
	$(PYTHON) -c "from popfc.reporting.export import write_final_exports; \
paths = write_final_exports(); \
[print(f'wrote {p}') for p in paths.values()]"

all: refresh-data build-nb run-all test
