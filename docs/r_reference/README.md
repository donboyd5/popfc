# R project reference materials

This folder preserves the documents, methodology notes, and R source from the
original R/Quarto project (formerly at `popfc_R/`, deleted in Phase 5) so the
Python project remains self-sufficient as a reference.

## Files

### Methodology and workflow (.qmd — prose + R code)

- `index.qmd` — preface
- `methodology.qmd` — Cornell PAD methodology and demographic balancing equation
- `steps.qmd` — high-level workflow (population, births, deaths, migration)
- `create_county_population_control_totals.qmd` — assembly of county population control totals
- `get-components-of-change.qmd` — births/deaths/migration data wrangling
- `get-year-county-sex-sya-shares.qmd` — single-year-of-age shares by sex
- `births.qmd` — birth-rate analysis
- `counties.qmd` — county metadata
- `misc_data_notes.qmd` — NYSDOH, LAUS, QCEW, NYSDOL projections notes
- `misc_notes.qmd` — scratch notes
- `links.qmd` — curated URLs

### R code

- `setup.R` — library loading and path constants (RStudio equivalent of `src/popfc/paths.py`)
- `constants.R` — small shared constants (e.g., mother's age levels)
- `PopPyramid_US_1970-2017_2020-01-15.r` — age-pyramid plotting example

### Project config

- `_quarto.yml` — Quarto book structure (chapter order)
- `CLAUDE.md` — previous Claude Code guidance for the R project

### Images

- `images/` — figures referenced by `.qmd` files (clipboard/paste snapshots)

## Note

The raw source-data documentation PDFs (Cornell `Washington.pdf`, NYSDOL overviews,
IRS migration doc guides, CDC Bridged-Race readmes, etc.) live with their data
in `../../data_raw/` and are **not duplicated** here.
