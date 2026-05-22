"""Age-specific fertility rates (ASFR) for the cohort-component model.

## What this module does

For a county-year cohort-component projection we need ASFR(x) — the expected
births per woman aged x in a given year. With those rates plus the female
population by age, we can compute total births and (using the sex ratio at
birth) split them into male and female newborns.

This module:

1. Carries a **reference national ASFR schedule** (NCHS 2023, 5-year age
   bands), expanded to a single-year-of-age step function.
2. Scales the reference to a target county-year by a single multiplicative
   factor `k` so that scaled-ASFR × female-pop sums to **observed births**:

        k(c, t) = B_observed(c, t) / sum_x [ ASFR_ref(x) * P_f(c, x, t) ]
        ASFR(c, x, t) = k(c, t) * ASFR_ref(x)

   The age *pattern* is borrowed from the national schedule; the *level* is
   pinned to the county's observed total. This is standard small-area
   demographic practice — county-level single-year ASFR estimates are too
   noisy to use directly, but national patterns are stable.
3. Provides the sex ratio at birth (`SEX_RATIO_AT_BIRTH = 1.05`) used by
   the cohort-component engine to split newborns into M/F.

## Why a step function?

NCHS publishes ASFR by 5-year age band, not single year of age. We expand
to single-year by replicating the band rate across each age in the band
(constant within the band). This is exact in the sense that integrating
the step function across the band reproduces the published rate, and it
keeps our schedule consistent with the data source. For projection
purposes, finer single-year detail would only matter if the band-internal
age distribution shifted dramatically, which it doesn't over realistic
forecast horizons.

## What this is NOT

This module does NOT use NYSDOH births-by-mother's-age data directly,
because we haven't pulled it yet (issue #2). When that lands, an
alternative `nysdoh_asfr_schedule(county, year)` function can replace
the national reference for the affected county-years. The scaling logic
stays the same.

## Citation

NCHS, *Births: Final Data for 2023*, National Vital Statistics Reports
74(1), March 18, 2025. Table 2 (general and age-specific birth rates).
https://www.cdc.gov/nchs/data/nvsr/nvsr74/nvsr74-1.pdf
"""

from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Reference ASFR schedule (births per 1,000 women per year), by 5-year age
# band, for ALL US races/origins, 2023. From NCHS NVSR 74-1 Table 2 row
# "All races and origins" → "2023". The 45-49 row includes births to
# women aged 45+ (footnote 1 of Table 2).
NCHS_ASFR_5YR_2023_ALL: dict[tuple[int, int], float] = {
    (10, 14):  0.2,
    (15, 19): 13.1,
    (20, 24): 57.7,
    (25, 29): 91.0,
    (30, 34): 94.3,
    (35, 39): 54.3,
    (40, 44): 12.5,
    (45, 49):  1.1,
}
NCHS_ASFR_2023_TFR: float = 1.621  # matches Table 2 column "Total fertility rate"
NCHS_ASFR_2023_VINTAGE: str = "nchs_nvsr74-1_table2_2023_allraces"

# Sex ratio at birth (males per female). The US empirical value has been
# remarkably stable at ~1.05 for decades; we use the demographic-standard
# 1.05. Override in the engine if a more precise value is needed.
SEX_RATIO_AT_BIRTH: float = 1.05
SHARE_MALE_AT_BIRTH: float = SEX_RATIO_AT_BIRTH / (1.0 + SEX_RATIO_AT_BIRTH)
SHARE_FEMALE_AT_BIRTH: float = 1.0 - SHARE_MALE_AT_BIRTH

# Reproductive ages (inclusive) for the cohort-component projection. Births
# to women outside this range exist but are rare and lumped into the edge
# bands by NCHS.
REPRO_AGE_MIN: int = 10
REPRO_AGE_MAX: int = 49

# Output schema for per-county-year scaled ASFR.
ASFR_LONG_COLUMNS: list[str] = [
    "geoid",
    "geography",
    "year",
    "sex",                  # "F" — ASFR are defined for women only
    "age",                  # single-year-of-age
    "asfr_per_1000",        # nullable Float64 — births per 1000 women aged x
    "ref_source",
    "ref_vintage",
    "scaling_factor",       # k(c, t) applied to the reference schedule
    "implied_tfr",          # sum(asfr_per_1000)/1000 — total fertility rate
    "observed_births",      # nullable Int64 — used in scaling
    "notes",
]


# ---------------------------------------------------------------------------
# Reference schedule helpers
# ---------------------------------------------------------------------------

def expand_5yr_to_single_year(
    schedule_5yr: Mapping[tuple[int, int], float],
) -> pd.DataFrame:
    """Replicate each 5-year band's rate across each single year of age.

    Returns a DataFrame with columns (`age`, `asfr_per_1000`) sorted by age.
    """
    rows = []
    for (lo, hi), rate in schedule_5yr.items():
        if lo > hi:
            raise ValueError(f"5-year band {(lo, hi)} is reversed")
        for age in range(int(lo), int(hi) + 1):
            rows.append({"age": int(age), "asfr_per_1000": float(rate)})
    df = pd.DataFrame(rows).sort_values("age").reset_index(drop=True)
    return df


def reference_asfr_schedule(
    *,
    vintage: str = NCHS_ASFR_2023_VINTAGE,
) -> pd.DataFrame:
    """Return the single-year-of-age reference ASFR schedule.

    Currently only one vintage is published (`NCHS_ASFR_2023_VINTAGE`); the
    parameter is in the signature so callers can swap in alternatives once
    they exist.
    """
    if vintage != NCHS_ASFR_2023_VINTAGE:
        raise ValueError(
            f"reference_asfr_schedule: unknown vintage {vintage!r}; "
            f"only {NCHS_ASFR_2023_VINTAGE!r} is currently registered"
        )
    out = expand_5yr_to_single_year(NCHS_ASFR_5YR_2023_ALL)
    out["ref_source"] = "nchs_nvsr"
    out["ref_vintage"] = vintage
    return out


def reference_tfr(schedule: pd.DataFrame | None = None) -> float:
    """Total fertility rate implied by an ASFR schedule (single-year-of-age)."""
    if schedule is None:
        schedule = reference_asfr_schedule()
    return float(schedule["asfr_per_1000"].sum()) / 1000.0


# ---------------------------------------------------------------------------
# County-year scaling
# ---------------------------------------------------------------------------

def implied_births_from_schedule(
    asfr: pd.DataFrame,
    female_pop: pd.DataFrame,
) -> float:
    """Compute total births implied by an ASFR schedule × female population.

    Both inputs must have columns `age` and either `asfr_per_1000` (asfr)
    or `population` (female_pop). Ages present in only one side are dropped.
    """
    merged = asfr[["age", "asfr_per_1000"]].merge(
        female_pop[["age", "population"]], on="age", how="inner"
    )
    return float(
        (merged["asfr_per_1000"].astype(float) * merged["population"].astype(float)
         / 1000.0).sum()
    )


def scale_asfr_to_observed_births(
    reference: pd.DataFrame,
    female_pop: pd.DataFrame,
    observed_births: float,
) -> tuple[pd.DataFrame, float]:
    """Return `(scaled_asfr, k)` such that implied_births equals observed.

    The scaled ASFR DataFrame keeps the reference's age × `asfr_per_1000`
    columns plus the multiplicative factor `k` in `scaling_factor`. Raises
    if the reference produces zero implied births for the given female_pop.
    """
    implied = implied_births_from_schedule(reference, female_pop)
    if implied <= 0:
        raise ValueError(
            "scale_asfr_to_observed_births: reference schedule × female pop "
            "yields non-positive implied births; cannot scale"
        )
    k = float(observed_births) / implied
    out = reference.copy()
    out["asfr_per_1000"] = out["asfr_per_1000"].astype(float) * k
    out["scaling_factor"] = k
    return out, k


def build_county_year_asfr(
    female_pop_long: pd.DataFrame,
    births_long: pd.DataFrame,
    *,
    reference: pd.DataFrame | None = None,
    ref_source: str = "nchs_nvsr",
    ref_vintage: str = NCHS_ASFR_2023_VINTAGE,
) -> pd.DataFrame:
    """Build per-(county, year) scaled ASFR conforming to ASFR_LONG_COLUMNS.

    Parameters
    ----------
    female_pop_long
        Long-format female population by single year of age. Must contain
        columns: `geoid`, `geography`, `year`, `sex` (= "F"), `age`,
        `population`.
    births_long
        Long-format births by county-year. Must contain `geoid`, `year`,
        `value` (births). Only `measure == 'births'` rows should be passed
        in — this function does not filter.
    reference
        Override the reference ASFR schedule. Default uses
        `reference_asfr_schedule()`.

    Returns
    -------
    Long-format scaled ASFR (`ASFR_LONG_COLUMNS`), one row per
    (geoid, year, age) where age covers `REPRO_AGE_MIN..REPRO_AGE_MAX`.
    Rows for county-years lacking either a positive births value or a
    matching female-pop slice are skipped.
    """
    if reference is None:
        reference = reference_asfr_schedule(vintage=ref_vintage)

    # Restrict population to females and reproductive ages.
    fp = female_pop_long[
        (female_pop_long["sex"] == "F")
        & (female_pop_long["age"].between(REPRO_AGE_MIN, REPRO_AGE_MAX))
    ].copy()
    if fp.empty:
        return pd.DataFrame(columns=ASFR_LONG_COLUMNS)

    bd = births_long[["geoid", "year", "value"]].rename(columns={"value": "observed_births"})
    bd = bd[bd["observed_births"].notna() & (bd["observed_births"] > 0)]

    frames: list[pd.DataFrame] = []
    for (geoid, year), pop_slice in fp.groupby(["geoid", "year"], dropna=False):
        births_match = bd[(bd["geoid"] == geoid) & (bd["year"] == year)]
        if births_match.empty:
            continue
        observed = float(births_match["observed_births"].iloc[0])

        scaled, k = scale_asfr_to_observed_births(
            reference[["age", "asfr_per_1000"]],
            pop_slice[["age", "population"]],
            observed_births=observed,
        )
        # Build the long row set with provenance.
        row = pd.DataFrame({
            "geoid": geoid,
            "geography": pop_slice["geography"].iloc[0],
            "year": int(year),
            "sex": "F",
            "age": scaled["age"].astype(int),
            "asfr_per_1000": scaled["asfr_per_1000"].astype(float),
            "ref_source": ref_source,
            "ref_vintage": ref_vintage,
            "scaling_factor": k,
            "implied_tfr": float(scaled["asfr_per_1000"].sum()) / 1000.0,
            "observed_births": observed,
            "notes": "",
        })
        frames.append(row)

    if not frames:
        return pd.DataFrame(columns=ASFR_LONG_COLUMNS)
    out = pd.concat(frames, ignore_index=True)
    out["asfr_per_1000"] = out["asfr_per_1000"].astype("Float64")
    out["observed_births"] = out["observed_births"].astype("Float64")
    return out[ASFR_LONG_COLUMNS]
