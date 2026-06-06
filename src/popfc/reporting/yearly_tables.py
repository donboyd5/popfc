"""Year-by-year population + components-of-change tables.

Two products, built from the pipeline outputs in `data_interim/` /
`data_final/`:

1. **County** (`build_county_yearly`): a single annual series that splices
   observed history (Census PEP components, via `washington_components.csv`)
   onto the cohort-component *forecast*, decomposed into the same
   components (births, deaths, natural change, net migration). The forecast
   decomposition reproduces Notebook 08's `decompose_county_scenario`
   exactly: births from ASFR × female population, net migration from the
   per-cohort migration rates × source population, and deaths backed out as
   the residual that closes the demographic identity

       ΔPop(t-1→t) = Births − Deaths + NetMig

   so the three components always sum to the annual population change.

2. **Town** (`build_town_yearly`): population + change-from-prior-period at
   the town forecast's native 5-year steps. The Hamilton-Perry town method
   does not decompose into births/deaths/migration, so no component columns
   exist at the town level — population and change only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from popfc.models.fertility import REPRO_AGE_MAX, REPRO_AGE_MIN
from popfc.paths import DATA_FINAL, DATA_INTERIM, FULL_FIPS

# Match Notebook 08's projection constants.
BASE_YEAR = 2024
TOP_CODE_AGE = 85


def decompose_county_forecast(
    geoid: str = FULL_FIPS,
    scenario: str = "baseline",
    *,
    forecasts: pd.DataFrame | None = None,
    asfr_all: pd.DataFrame | None = None,
    net_mig: pd.DataFrame | None = None,
    base_year: int = BASE_YEAR,
    top_code_age: int = TOP_CODE_AGE,
) -> pd.DataFrame:
    """Decompose a county cohort-component forecast into annual components.

    Reproduces Notebook 08's `decompose_county_scenario`. Returns one row
    per forecast year with: total_pop, delta, births, net_mig, deaths,
    natural_change. The base year's delta/components are NaN (no prior
    year inside the forecast to difference against).
    """
    if forecasts is None:
        forecasts = pd.read_parquet(DATA_INTERIM / "county_forecasts.parquet")
    if asfr_all is None:
        asfr_all = pd.read_parquet(DATA_INTERIM / "asfr.parquet")
    if net_mig is None:
        net_mig = pd.read_parquet(DATA_INTERIM / "net_migration_rates.parquet")

    sub = forecasts[
        (forecasts["geoid"] == geoid) & (forecasts["scenario"] == scenario)
    ].copy()
    if sub.empty:
        raise ValueError(
            f"decompose_county_forecast: no forecast rows for geoid={geoid!r}, "
            f"scenario={scenario!r}"
        )
    totals_by_year = sub.groupby("year")["population"].sum()

    asfr_c = (
        asfr_all[(asfr_all["geoid"] == geoid) & (asfr_all["year"] == base_year)]
        .set_index("age")["asfr_per_1000"].astype(float)
    )

    nm_c = net_mig[net_mig["geoid"] == geoid].copy()
    closed = (
        nm_c[nm_c["band_type"] == "closed"][["sex", "source_age", "m_rate"]]
        .rename(columns={"source_age": "age", "m_rate": "m_rate_closed"})
    )
    boundary = (
        nm_c[nm_c["band_type"] == "boundary"][["sex", "m_rate"]]
        .rename(columns={"m_rate": "m_rate_boundary"})
    )

    rows = []
    for t in sorted(sub["year"].unique()):
        gsub = sub[sub["year"] == t]

        # Births: ASFR(age) × female pop(age, t) / 1000 over reproductive ages.
        f_pop = gsub[
            (gsub["sex"] == "F")
            & (gsub["age"].between(REPRO_AGE_MIN, REPRO_AGE_MAX))
        ]
        aligned = (
            f_pop.set_index("age")["population"].astype(float)
            .reindex(asfr_c.index).fillna(0)
        )
        births = float((aligned * asfr_c.reindex(aligned.index).fillna(0) / 1000).sum())

        # Net migration: m_rate × source pop over closed bands + open boundary.
        pop_sa = gsub[["sex", "age", "population"]].copy()
        pop_sa["population"] = pop_sa["population"].astype(float)

        mig_closed = pop_sa.merge(closed, on=["sex", "age"], how="left")
        m_closed = float(
            (mig_closed["m_rate_closed"].astype(float).fillna(0)
             * mig_closed["population"]).sum()
        )

        open_pop = pop_sa[pop_sa["age"].isin([top_code_age - 1, top_code_age])]
        open_by_sex = (
            open_pop.groupby("sex")["population"].sum()
            .rename("source_pop").reset_index()
            .merge(boundary, on="sex", how="left")
        )
        m_open = float(
            (open_by_sex["source_pop"]
             * open_by_sex["m_rate_boundary"].astype(float).fillna(0)).sum()
        )

        rows.append({
            "year": int(t),
            "total_pop": float(totals_by_year[t]),
            "births": births,
            "net_mig": m_closed + m_open,
        })

    df = pd.DataFrame(rows).set_index("year")
    df["delta"] = df["total_pop"].diff()
    # ΔPop = B - D + M  →  D = B + M - ΔPop ; components sum to ΔPop by construction.
    df["deaths"] = df["births"] + df["net_mig"] - df["delta"]
    df["natural_change"] = df["births"] - df["deaths"]
    return df.reset_index()


# Standard component column order shared by history and forecast.
_COMPONENT_COLS = [
    "population", "pop_change", "births", "deaths",
    "natural_change", "net_mig",
]


def build_county_yearly(
    geoid: str = FULL_FIPS,
    scenario: str = "baseline",
    *,
    start_year: int | None = None,
    end_year: int | None = None,
) -> pd.DataFrame:
    """Spliced annual history + forecast with components of change.

    Columns: geoid, geography, year, period (history|forecast), scenario,
    population, pop_change, births, deaths, natural_change, net_mig.

    History rows come from Census PEP components (washington_components.csv);
    forecast rows from the decomposed cohort-component projection. The
    overlap year (the forecast base year) is taken from history so the
    series has exactly one row per year.
    """
    # --- History (observed components of change) ---
    # washington_components.csv carries several vintages per year. The Census
    # PEP vintages (v2020, v2025) hold the complete, identity-consistent set
    # of components; the NYSDOH vital vintages carry only births or only
    # deaths. Keep the complete PEP rows (pop_change present), and where a
    # year appears under more than one PEP vintage, prefer the latest.
    _VINTAGE_RANK = {"v2010int": 0, "v2020": 1, "v2024": 2, "v2025": 3}
    comp = pd.read_csv(DATA_FINAL / "washington_components.csv")
    comp = comp[comp["geoid"].astype(str).str.zfill(5) == geoid].copy()
    comp = comp[comp["pop_change"].notna()].copy()
    comp["_rank"] = comp["vintage"].map(_VINTAGE_RANK).fillna(-1)
    comp = (
        comp.sort_values(["year", "_rank"])
        .drop_duplicates("year", keep="last")
        .drop(columns="_rank")
    )
    hist = pd.DataFrame({
        "year": comp["year"].astype(int),
        "population": pd.NA,                       # filled from history series below
        "pop_change": comp["pop_change"].astype(float),
        "births": comp["births"].astype(float),
        "deaths": comp["deaths"].astype(float),
        "natural_change": comp["natural_change"].astype(float),
        "net_mig": comp["net_mig"].astype(float),
    })
    # Population level from the reconciled history series.
    wh = pd.read_csv(DATA_FINAL / "washington_history.csv")
    pop_by_year = wh.set_index("year")["population"]
    hist["population"] = hist["year"].map(pop_by_year)
    hist["period"] = "history"

    # --- Forecast (decomposed) ---
    dec = decompose_county_forecast(geoid, scenario)
    fc = pd.DataFrame({
        "year": dec["year"].astype(int),
        "population": dec["total_pop"],
        "pop_change": dec["delta"],
        "births": dec["births"],
        "deaths": dec["deaths"],
        "natural_change": dec["natural_change"],
        "net_mig": dec["net_mig"],
    })
    fc["period"] = "forecast"

    # Splice at the forecast base year: observed history owns years up to and
    # including the base year; the forecast contributes base_year+1 onward.
    # Splicing here (rather than at the last observed year) keeps every
    # forecast-year demographic identity exact, since the engine launches
    # from the base-year observed age structure. Observed years beyond the
    # base year (e.g. a newer PEP estimate) are intentionally dropped in
    # favor of the model's internally consistent path.
    fc_base = int(fc["year"].min())
    hist = hist[hist["year"] <= fc_base]
    fc = fc[fc["year"] > fc_base]
    out = pd.concat([hist, fc], ignore_index=True).sort_values("year")

    geography = (
        wh["geography"].iloc[0] if "geography" in wh.columns else "Washington"
    )
    out.insert(0, "geoid", geoid)
    out.insert(1, "geography", geography)
    out.insert(4, "scenario", scenario)

    if start_year is not None:
        out = out[out["year"] >= start_year]
    if end_year is not None:
        out = out[out["year"] <= end_year]

    cols = ["geoid", "geography", "year", "period", "scenario", *_COMPONENT_COLS]
    return out[cols].reset_index(drop=True)


def build_town_yearly(
    geoids: list[str] | None = None,
    scenario: str = "baseline",
) -> pd.DataFrame:
    """Town population + change at the native 5-year forecast steps.

    No component columns — the Hamilton-Perry town method does not produce
    births/deaths/migration. Columns: geoid, geography, year, scenario,
    population, pop_change, pct_change.
    """
    src = pd.read_parquet(DATA_INTERIM / "town_forecasts.parquet")
    src = src[src["scenario"] == scenario]
    totals = (
        src.groupby(["geoid", "geography", "year"])["population"]
        .sum().reset_index()
    )
    if geoids is not None:
        totals = totals[totals["geoid"].isin(geoids)]
    totals = totals.sort_values(["geoid", "year"]).reset_index(drop=True)
    totals["scenario"] = scenario
    totals["pop_change"] = totals.groupby("geoid")["population"].diff()
    totals["pct_change"] = 100.0 * totals.groupby("geoid")["population"].pct_change()
    cols = ["geoid", "geography", "year", "scenario",
            "population", "pop_change", "pct_change"]
    return totals[cols]
