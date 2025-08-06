# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an R/Quarto project for developing population forecasts for Washington County, NY (and potentially towns within the county). The project follows demographic forecasting methodology based on the Demographic Balancing Equation: **Pop end = Pop start + Births – Deaths + In-migration – Out-migration**.

## Key Commands

### Quarto Book Building

- `quarto render` - Build the entire Quarto book
- `quarto preview` - Preview the book locally
- `quarto publish netlify --no-render` - Publish to Netlify without rendering
- `quarto publish netlify --no-browser --no-prompt` - Publish silently

### R Project Setup

- Open in RStudio using `popfc.Rproj` I plan to work primarily in positron, but this makes it easy to work in RStudio, too.
- Run `source("setup.R")` to load all required libraries and setup paths

## Architecture and Structure

### Data Organization

The project uses a structured data workflow with these key directories:

- `data_raw/` - Raw data from various sources (Census, CDC, NY State agencies)
- `data_work/` - Intermediate processed data files (.rds format)
- `data/` - Final processed data for analysis

### Key Data Sources

- **Census Bureau**: Population estimates and components of change (`data_raw/census/`)
- **CDC**: Bridged-race population estimates (`data_raw/cdc/`)
- **NY State DOL**: Annual population estimates (`data_raw/nysdol/`)
- **NY State DOH**: Population and vital statistics (`data_raw/nysdoh/`)
- **Cornell PAD**: Projection methodology reference (`data_raw/cornell/`)

### Core Analysis Files (.qmd)

The project is structured as a Quarto book with these main chapters:

- `index.qmd` - Project preface and introduction
- `methodology.qmd` - Cornell methodology and demographic principles
- `create_county_population_control_totals.qmd` - Population control total creation
- `get-components-of-change.qmd` - Births, deaths, migration analysis
- `births.qmd` - Birth rate analysis and forecasting
- `get-year-county-sex-sya-shares.qmd` - Single year of age population shares

### Setup and Configuration

- `setup.R` - Central library loading and path configuration
  - Loads tidyverse, readxl, vroom, fs, skimr, Hmisc, gt, btools
  - Defines key paths: DRAW (data_raw), DDATA (data), DWORK (data_work)
  - Sets up subdirectories for different data sources
- `_quarto.yml` - Quarto book configuration with HTML output
- `.Rproj` - RStudio project configuration

### Data Processing Patterns

- All analysis files start with `source(here::here("setup.R"))`
- Intermediate results saved as .rds files in `data_work/`
- Final outputs saved as .rds files in `data/`
- Consistent use of `here::here()` for path management

### Output Structure

- HTML output goes to `_web/` directory
- Uses Quarto freeze for caching computations
- Code folding enabled in HTML output
- Cosmo theme with expanded TOC

## Development Notes

- The project focuses on Washington County, NY (FIPS code 36115)
- Uses Cornell Program on Applied Demographics methodology
- Demographic forecasting based on sex/age-specific population components
- In positron, air is used to format R code when files are saved
- In RStudio, all R code uses 2-space indentation (configured in .Rproj)
