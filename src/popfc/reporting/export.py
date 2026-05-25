"""Export interim/forecast parquets into a clean `data_final/` set.

Phase-5 cleanup: take the pipeline outputs in `data_interim/` and write a
small number of human-friendly artifacts (CSV + parquet) into
`data_final/` that downstream consumers can use without needing the
codebase or the full historical data.

Outputs written by `write_final_exports()`:

| File                              | What it contains                       |
|-----------------------------------|----------------------------------------|
| `washington_history.csv`          | reconciled annual pop, Washington 2000-present |
| `washington_components.csv`       | components of change, Washington       |
| `county_forecast_totals.csv`      | year × scenario × geoid totals (cohort)|
| `county_forecast_agesex.parquet`  | full age × sex forecast (cohort), parquet only — too wide for CSV |
| `town_forecast_totals.csv`        | year × scenario × MCD totals, Washington |
| `town_forecast_agesex.parquet`    | full age-band × sex × scenario, towns  |
| `summary_headline.csv`            | one-row-per-scenario headline numbers  |

Counties exported: Washington plus the 5 validation-cohort counties.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from popfc.paths import DATA_FINAL, DATA_INTERIM, FULL_FIPS

# Validation cohort (same as Notebook 08).
VALIDATION_COHORT: dict[str, str] = {
    FULL_FIPS: "Washington",
    "36091": "Saratoga",
    "36113": "Warren",
    "36083": "Rensselaer",
    "36031": "Essex",
    "36021": "Columbia",
}


def _ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_washington_history(out_dir: Path) -> Path:
    """Reconciled annual Washington population (full coverage from reconciliation parquet)."""
    src = pd.read_parquet(DATA_INTERIM / "population_reconciled.parquet")
    wash = (
        src[src["geoid"] == FULL_FIPS]
        [["year", "population", "source", "kind", "vintage", "rule"]]
        .sort_values("year")
        .reset_index(drop=True)
    )
    path = out_dir / "washington_history.csv"
    wash.to_csv(path, index=False)
    return path


def write_washington_components(out_dir: Path) -> Path:
    """Components of change (births, deaths, migration) for Washington."""
    src = pd.read_parquet(DATA_INTERIM / "county_components.parquet")
    wash = src[src["geoid"] == FULL_FIPS].copy()
    wide = wash.pivot_table(
        index=["geoid", "year", "vintage"],
        columns="measure",
        values="value",
        aggfunc="first",
    ).reset_index()
    path = out_dir / "washington_components.csv"
    wide.to_csv(path, index=False)
    return path


def write_county_forecast_totals(
    out_dir: Path,
    cohort: Iterable[str] = VALIDATION_COHORT.keys(),
) -> Path:
    """Year × scenario × geoid total population, cohort counties only."""
    src = pd.read_parquet(DATA_INTERIM / "county_forecasts.parquet")
    sub = src[src["geoid"].isin(list(cohort))].copy()
    totals = (
        sub.groupby(["geoid", "geography", "year", "scenario"])["population"]
        .sum()
        .reset_index()
        .sort_values(["geoid", "scenario", "year"])
    )
    path = out_dir / "county_forecast_totals.csv"
    totals.to_csv(path, index=False)
    return path


def write_county_forecast_agesex(
    out_dir: Path,
    cohort: Iterable[str] = VALIDATION_COHORT.keys(),
) -> Path:
    """Full age × sex × year × scenario forecast for the cohort, parquet."""
    src = pd.read_parquet(DATA_INTERIM / "county_forecasts.parquet")
    sub = src[src["geoid"].isin(list(cohort))].copy()
    path = out_dir / "county_forecast_agesex.parquet"
    sub.to_parquet(path, index=False)
    return path


def write_town_forecast_totals(out_dir: Path) -> Path:
    """Year × scenario × MCD total population, Washington."""
    src = pd.read_parquet(DATA_INTERIM / "town_forecasts.parquet")
    totals = (
        src.groupby(["geoid", "geography", "year", "scenario"])["population"]
        .sum()
        .reset_index()
        .sort_values(["geoid", "scenario", "year"])
    )
    path = out_dir / "town_forecast_totals.csv"
    totals.to_csv(path, index=False)
    return path


def write_town_forecast_agesex(out_dir: Path) -> Path:
    """Full age-band × sex × year × scenario forecast for Washington towns."""
    src = pd.read_parquet(DATA_INTERIM / "town_forecasts.parquet")
    path = out_dir / "town_forecast_agesex.parquet"
    src.to_parquet(path, index=False)
    return path


def write_summary_headline(out_dir: Path) -> Path:
    """One-row-per-scenario headline: Washington pop at key years + decline %."""
    county = pd.read_parquet(DATA_INTERIM / "county_forecasts.parquet")
    wash = (
        county[county["geoid"] == FULL_FIPS]
        .groupby(["scenario", "year"])["population"]
        .sum().reset_index()
    )
    pv = wash.pivot_table(index="scenario", columns="year", values="population")
    base_year = int(pv.columns.min())  # forecast base year — first year in the data
    key_years = [y for y in (base_year, 2030, 2040, 2050) if y in pv.columns]
    out = pv[key_years].round(0).astype(int).reset_index()
    if base_year in pv.columns and 2050 in pv.columns:
        out[f"pct_change_{base_year}_2050"] = (
            100.0 * (pv[2050] / pv[base_year] - 1)
        ).round(2).to_numpy()
    path = out_dir / "summary_headline.csv"
    out.to_csv(path, index=False)
    return path


def write_final_exports(out_dir: Path | None = None) -> dict[str, Path]:
    """Run every export and return a dict of {name: path}."""
    out_dir = _ensure_dir(Path(out_dir) if out_dir is not None else DATA_FINAL)
    return {
        "washington_history":          write_washington_history(out_dir),
        "washington_components":       write_washington_components(out_dir),
        "county_forecast_totals":      write_county_forecast_totals(out_dir),
        "county_forecast_agesex":      write_county_forecast_agesex(out_dir),
        "town_forecast_totals":        write_town_forecast_totals(out_dir),
        "town_forecast_agesex":        write_town_forecast_agesex(out_dir),
        "summary_headline":            write_summary_headline(out_dir),
    }
