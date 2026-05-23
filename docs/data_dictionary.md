# Data dictionary

Schemas and column descriptions for every artifact in `data_interim/`
(intermediate pipeline outputs) and `data_final/` (cleaned exports for
downstream use). Schemas are also defined as Python constants in
`src/popfc/data/_common.py` and `src/popfc/models/*.py`; this file is
the human-readable mirror.

Conventions:

- **FIPS** are zero-padded strings (`"36"`, `"115"`, `"36115"`). Never
  integers — leading zeros matter for parsing.
- **`geoid`** is the full identifier: 5 chars for a county
  (`"36115"`), 10 for an MCD (`"3611530037"`), 11 for a tract
  (`"36115080100"`), or `"US"` for national-level rows.
- **`population`** is nullable `Int64` for counts, `Float64` for rates
  or projection outputs (we keep fractional projection values; round
  for display only).
- Provenance columns (`source`, `vintage`, `notes`) travel with every
  row so any value can be traced back to its upstream file.

------------------------------------------------------------------------

## `data_interim/` — pipeline outputs

These files are produced by Notebooks 01–09. They carry full schema
detail and intermediate steps useful for debugging or extending the
pipeline. Always regenerable from `data_raw/` by re-running the
notebooks.

### `population_all_sources.parquet` (Notebook 01) — POP_LONG_COLUMNS

Stacked raw population series from all upstream sources, with vintage
overlap preserved. Used for the reconciliation diagnostics, not
consumed by downstream code directly.

| Column        | Type            | Description |
|---------------|-----------------|-------------|
| `state_fips`  | string (2 chars) | "36" for NY |
| `county_fips` | string (3 chars) | "115" for Washington; "000" for state-level rows |
| `geoid`       | string (5 chars) | `state_fips + county_fips` |
| `geography`   | string           | Human-readable name (e.g., "Washington County") |
| `year`        | Int64            | Calendar year |
| `kind`        | string           | `estimate` / `estimates_base` / `census` / `projection` / `intercensal` |
| `population`  | nullable Int64   | Population count |
| `source`      | string           | `census_pep` / `nysdol` / `cdc_bridged` / `nysdoh` / `cornell_pad` |
| `vintage`     | string           | Source-specific vintage tag (e.g., `v2024`, `nysdol_2025-04-20`) |
| `notes`       | string           | Free-form notes |

### `population_reconciled.parquet` (Notebook 01) — POP_LONG_COLUMNS + `rule`

The single authoritative population per (geoid, year). Same schema as
`population_all_sources.parquet` plus one extra column:

| Column | Type | Description |
|--------|------|-------------|
| `rule` | string | Why this row was chosen: `decennial_census_nysdol`, `intercensal_nysdol`, `postcensal_census_pep` |

Coverage: 63 entities (62 NY counties + state total) × 25 years
(2000-2024). 1,575 rows.

### `county_components.parquet` (Notebook 02) — COMPONENTS_LONG_COLUMNS

Census PEP components of change in long form.

| Column        | Type            | Description |
|---------------|-----------------|-------------|
| `state_fips`  | string           | "36" |
| `county_fips` | string           | 3-char FIPS |
| `geoid`       | string           | 5-char FIPS |
| `geography`   | string           | Human-readable name |
| `year`        | Int64            | Calendar year |
| `measure`     | string           | `births` / `deaths` / `natural_change` / `international_mig` / `domestic_mig` / `net_mig` / `residual` / `gq_estimate` / `pop_change` / `rate_births` / `rate_deaths` / etc. |
| `value`       | nullable Float64 | Count (Int-like) or rate (per 1,000) depending on measure |
| `source`      | string           | `census_pep` |
| `vintage`     | string           | `v2020` or `v2024` (whichever vintage is latest for that year) |
| `notes`       | string           |             |

Coverage: 13,797 rows (2010-2024).

### `county_agesex_1990_2023.parquet` (Notebook 03) — AGESEX_LONG_COLUMNS

Single-year-of-age × sex × year population, stitched across CDC
Bridged-Race (Washington 1990-2020) and Census SYA (all NY counties
2020-2023).

| Column           | Type           | Description |
|------------------|----------------|-------------|
| `state_fips`     | string         | "36" |
| `county_fips`    | string         | 3-char FIPS |
| `geoid`          | string         | 5-char FIPS |
| `geography`      | string         | Human-readable name |
| `year`           | Int64          | Calendar year |
| `kind`           | string         | `estimate` / `census` / `estimates_base` / `projection` |
| `sex`            | string         | `M` / `F` |
| `age`            | Int64          | 0-85 (top-coded at 85) |
| `age_top_coded`  | bool           | True only for the 85+ row |
| `population`     | nullable Int64 | Count |
| `source`         | string         | `cdc_bridged` / `census_sya` |
| `vintage`        | string         | Source-specific tag |
| `notes`          | string         |             |

Coverage: 58,652 rows.

### `life_tables.parquet` (Notebook 04) — LIFE_TABLE_COLUMNS

NCHS period life tables (US national + NY state) and USALEEP tract-
level small-area tables.

| Column        | Type           | Description |
|---------------|----------------|-------------|
| `geoid`       | string         | `"US"` / `"36000"` (NY state) / 11-char tract ID |
| `geography`   | string         | Name |
| `year_start`  | Int64          | First year of the period table |
| `year_end`    | Int64          | Last year of the period (same as start for single-year tables) |
| `sex`         | string         | `All` / `M` / `F` |
| `age`         | Int64          | Start age of the band (0, 1, 5, …) |
| `age_band`    | string         | `"0-1"`, `"1-5"`, `"85+"`, `"100+"`, `"Under 1"` |
| `qx`          | nullable Float64 | Probability of dying between x and x+n |
| `lx`          | nullable Float64 | Number surviving to exact age x (radix 100,000) |
| `Lx`          | nullable Float64 | Person-years lived between x and x+n |
| `ex`          | nullable Float64 | Expectation of life at age x (years) |
| `source`      | string         | `nchs_nvsr` / `nchs_usaleep` |
| `vintage`     | string         | `nvsr74-06` (US 2023), `nvsr74-12` (NY 2022), `usaleep_2010_2015` |
| `notes`       | string         |             |

Coverage: 793 rows (303 US + 303 NY + 187 Washington USALEEP tracts).

### `asfr.parquet` (Notebook 05) — ASFR_LONG_COLUMNS

County-year age-specific fertility rates, scaled from the NCHS 2023
national reference schedule.

| Column              | Type            | Description |
|---------------------|-----------------|-------------|
| `geoid`             | string          | 5-char FIPS |
| `geography`         | string          | Name |
| `year`              | Int64           | Calendar year |
| `sex`               | string          | Always `F` (ASFR defined for women) |
| `age`               | Int64           | Mother's age (10-49) |
| `asfr_per_1000`     | nullable Float64 | Births per 1,000 women per year |
| `ref_source`        | string          | Origin of the reference schedule (`nchs_nvsr`) |
| `ref_vintage`       | string          | Reference vintage tag |
| `scaling_factor`    | Float64         | Multiplicative `k` applied to the national schedule |
| `implied_tfr`       | Float64         | `sum(asfr_per_1000)/1000` |
| `observed_births`   | nullable Float64 | Total births used in the scaling |
| `notes`             | string          |             |

Coverage: 10,280 rows (62 counties × 4 years 2020-2023 + Washington
× 9 historical years 2011-2019).

### `survival_rates.parquet` (Notebook 06) — SURVIVAL_RATES_COLUMNS

Single-year survival rates derived from period life tables.

| Column         | Type            | Description |
|----------------|-----------------|-------------|
| `geoid`        | string          | `"US"` or `"36000"` (NY state) |
| `geography`    | string          | Name |
| `year_start`   | Int64           | Source life-table year |
| `year_end`     | Int64           | Same as `year_start` for single-year tables |
| `sex`          | string          | `All` / `M` / `F` |
| `band_type`    | string          | `birth` / `closed` / `boundary` |
| `age`          | Int64           | `-1` for birth rows; `x` (source age) for closed bands; `ω` for the boundary |
| `Sx`           | nullable Float64 | Survival probability in (0, 1] |
| `source`       | string          | `nchs_nvsr` |
| `vintage`      | string          |             |
| `notes`        | string          | For birth/boundary rows includes the L values |

Coverage: 606 rows (6 slices × 101 rates per slice).

### `net_migration_rates.parquet` (Notebook 07) — NET_MIGRATION_RATES_COLUMNS

Per-source-age net migration rates by the residual method.

| Column          | Type            | Description |
|-----------------|-----------------|-------------|
| `geoid`         | string          | 5-char FIPS |
| `geography`     | string          | Name |
| `year_basis`    | string          | Description of year-pairs averaged (e.g., `"avg of 3 pairs: 2020-2021,2021-2022,2022-2023"`) |
| `sex`           | string          | `M` / `F` |
| `band_type`     | string          | `closed` / `boundary` |
| `age`           | Int64           | Destination age (x+1 for closed, ω for boundary) |
| `source_age`    | Int64           | Source age (x for closed; ω-1 for boundary) |
| `m_rate`        | nullable Float64 | Net migration per source-age person (can be ±, often noisy) |
| `n_year_pairs`  | Int64           | Number of year-pairs averaged |
| `notes`         | string          |             |

Coverage: 10,540 rows (62 counties × 2 sexes × 85 ages).

### `county_forecasts.parquet` (Notebook 08) — PROJECTION_COLUMNS

Single-year-of-age cohort-component projections for cohort counties.

| Column                | Type            | Description |
|-----------------------|-----------------|-------------|
| `geoid`               | string          | 5-char FIPS |
| `geography`           | string          | Name |
| `year`                | Int64           | Calendar year (2023-2050) |
| `sex`                 | string          | `M` / `F` |
| `age`                 | Int64           | 0-85 (top-coded at 85) |
| `population`          | nullable Float64 | Projected pop |
| `scenario`            | string          | `baseline` / `low` / `high` |
| `projection_vintage`  | string          | Tag identifying the engine run (e.g., `engine_v1_asfr_x1.0_netmig_x1.0`) |

Coverage: 86,688 rows (6 counties × 3 scenarios × 28 years × 2 sexes × 86 ages).

### `town_forecasts.parquet` (Notebook 09) — HP_PROJECTION_COLUMNS + 2 cols

5-year-cadence Hamilton-Perry projections for Washington's 17 towns.

| Column                | Type            | Description |
|-----------------------|-----------------|-------------|
| `geoid`               | string          | 10-char FIPS (state + county + MCD) |
| `geography`           | string          | Town name |
| `year`                | Int64           | Calendar year (2022, 2027, …, 2047) |
| `sex`                 | string          | `M` / `F` |
| `age_band_start`      | Int64           | 0, 5, 10, …, 85 |
| `age_band_end`        | Int64           | 4, 9, …, 84, 199 (sentinel for 85+) |
| `population`          | nullable Float64 | Projected pop |
| `scenario`            | string          | `baseline` / `low` / `high` |
| `projection_vintage`  | string          | `hp_v1_acs2017_to_2022` |
| `constraint_factor`   | Float64         | Pro-rata multiplier applied at this year |
| `constraint_applied`  | bool            | False at base year 2022; True at forecast years |

Coverage: 11,016 rows (17 towns × 3 scenarios × 6 years × 2 sexes × 18 bands).

------------------------------------------------------------------------

## `data_final/` — exports

These files are stripped-down, schema-stable artifacts for analysts
who want to consume the forecast without setting up the codebase.
Produced by `popfc.reporting.export.write_final_exports()` (called
from Notebook 10).

### `summary_headline.csv`

One row per scenario.

| Column                  | Description |
|-------------------------|-------------|
| `scenario`              | `baseline` / `low` / `high` |
| `2023`, `2030`, `2040`, `2050` | Washington County total population at each key year |
| `pct_change_2023_2050`  | Percentage change |

### `washington_history.csv`

Annual reconciled population for Washington County, 2000-2024.

| Column | Description |
|--------|-------------|
| `year` | Calendar year |
| `population` | Total |
| `source`, `kind`, `vintage`, `rule` | Provenance — which series we used |

### `washington_components.csv`

Components of change for Washington, wide-format (one row per year ×
vintage, columns for each measure).

### `county_forecast_totals.csv`

| Column      | Description |
|-------------|-------------|
| `geoid`     | 5-char FIPS |
| `geography` | County name |
| `year`      | 2023-2050 |
| `scenario`  | `baseline` / `low` / `high` |
| `population`| Total population |

Covers the 6 cohort counties.

### `county_forecast_agesex.parquet`

Same as `county_forecasts.parquet` but limited to the cohort counties.
Parquet only — too wide for CSV at age × sex × year × scenario.

### `town_forecast_totals.csv`

| Column      | Description |
|-------------|-------------|
| `geoid`     | 10-char FIPS |
| `geography` | Town name |
| `year`      | 2022, 2027, …, 2047 |
| `scenario`  | `baseline` / `low` / `high` |
| `population`| Total |

### `town_forecast_agesex.parquet`

Full town × age-band × sex × year × scenario detail. Parquet only.
