"""Hamilton-Perry projection for sub-county geographies.

Hamilton-Perry projects each age × sex cohort forward by multiplying it
by an empirical "cohort change ratio" (CCR) derived from two prior
observations of the population pyramid. It's the canonical method for
small areas where the data needed for a full cohort-component model
(births, deaths, migration by single year of age) doesn't exist or is
too noisy to estimate cleanly.

## Conventions used here

- 5-year age bands: 0-4, 5-9, ..., 80-84, 85+. ACS B01001 publishes
  pop by age and sex in irregular bands (5-yr but with extra splits
  around 15-21 and 60-69 for legal-age detail); we aggregate to clean
  5-year bands via `aggregate_b01001_to_5yr_bands()`.
- Two time points exactly 5 years apart. Currently ACS 5-yr 2015-2019
  (midpoint ≈ 2017) and ACS 5-yr 2020-2024 (midpoint ≈ 2022).
- Projection step is 5 years to align with the band width.

## Math

For each (geoid, sex), let P(a, t) be population in age band a (or in
the youngest band) at time t. Cohort change ratios:

    Closed bands a ≥ 5-9:
        CCR(a, t-5 → t) = P(a, t) / P(a-5, t-5)
        P(a, t+5) = CCR(a) × P(a-5, t)

    Open band 85+:
        CCR(85+) = P(85+, t) / [P(80-84, t-5) + P(85+, t-5)]
        P(85+, t+5) = CCR(85+) × [P(80-84, t) + P(85+, t)]

    Youngest band 0-4 — use child-to-woman ratio (CWR):
        CWR(sex) = P(0-4, sex, t) / P(women 15-49, t)
        P(0-4, sex, t+5) = CWR(sex) × P(women 15-49, t+5)

CWR(sex) is computed and held constant for the projection. This is a
simple closure consistent with the "hold recent fertility constant"
assumption used in our county-level model.

## Output

Frame conforming to `HP_PROJECTION_COLUMNS`. Distinct from
`PROJECTION_COLUMNS` (cohort-component) because the band granularity
differs (5-yr here, single-year there).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

HP_PROJECTION_COLUMNS: list[str] = [
    "geoid",
    "geography",
    "year",
    "sex",                # "M" | "F"
    "age_band_start",     # 0, 5, 10, ..., 85
    "age_band_end",       # 4, 9, ..., 84, 199 (sentinel for 85+)
    "population",
    "scenario",
    "projection_vintage",
]

# Standard 5-year age bands used throughout this module.
# 199 is the upper-bound sentinel for the open band.
FIVE_YEAR_BANDS: list[tuple[int, int]] = [
    (0, 4),   (5, 9),   (10, 14), (15, 19),
    (20, 24), (25, 29), (30, 34), (35, 39),
    (40, 44), (45, 49), (50, 54), (55, 59),
    (60, 64), (65, 69), (70, 74), (75, 79),
    (80, 84), (85, 199),
]
OPEN_BAND = (85, 199)
YOUNGEST_BAND = (0, 4)


# ---------------------------------------------------------------------------
# ACS B01001 aggregation
# ---------------------------------------------------------------------------

# B01001 variable numbers → clean 5-year age band, for the male side.
# Female side is the same offset + 24 (vars 027..049 mirror 003..025).
_MALE_VAR_TO_BAND: dict[int, tuple[int, int]] = {
    3:  (0,   4),    4:  (5,   9),    5:  (10, 14),
    6:  (15, 19),    7:  (15, 19),                       # 15-17 + 18-19
    8:  (20, 24),    9:  (20, 24),    10: (20, 24),      # 20 + 21 + 22-24
    11: (25, 29),    12: (30, 34),    13: (35, 39),
    14: (40, 44),    15: (45, 49),    16: (50, 54),
    17: (55, 59),
    18: (60, 64),    19: (60, 64),                       # 60-61 + 62-64
    20: (65, 69),    21: (65, 69),                       # 65-66 + 67-69
    22: (70, 74),    23: (75, 79),    24: (80, 84),
    25: (85, 199),
}


def aggregate_b01001_to_5yr_bands(acs_long: pd.DataFrame) -> pd.DataFrame:
    """Collapse ACS B01001 long-format into clean 5-year-band pop by sex.

    `acs_long` is the frame returned by `popfc.data.acs.load_acs5_group(
    'B01001', ...)`. Variables 002 (Male total) and 026 (Female total)
    are dropped; the remaining 23 male and 23 female bins are summed
    into the 18 clean 5-year bands.

    Returns DataFrame with columns:
        geoid, geography, year, vintage, sex, age_band_start,
        age_band_end, population
    """
    df = acs_long.copy()
    # Parse variable number from name like "B01001_017E" → 17.
    df["var_no"] = df["variable"].str.extract(r"_(\d{3})E$", expand=False).astype(int)
    df = df[df["var_no"] >= 3]  # drop the totals (002, 026) and the grand total (001)

    # Determine sex and age band per row.
    is_male = df["var_no"].between(3, 25)
    df["sex"] = np.where(is_male, "M", "F")
    # Male offset = 0; female offset = 24 → subtract 24 for female to use male map.
    male_var = np.where(is_male, df["var_no"], df["var_no"] - 24)
    df["_male_var"] = male_var
    df = df[df["_male_var"].isin(_MALE_VAR_TO_BAND)].copy()
    bands = df["_male_var"].map(lambda v: _MALE_VAR_TO_BAND[int(v)])
    df["age_band_start"] = bands.map(lambda t: t[0]).astype(int)
    df["age_band_end"] = bands.map(lambda t: t[1]).astype(int)

    grouped = (
        df.groupby(
            ["geoid", "geography_level" if "geography_level" in df.columns else "geoid",
             "name", "year", "vintage", "sex", "age_band_start", "age_band_end"],
            as_index=False,
            dropna=False,
        )["value"].sum().rename(columns={"value": "population"})
    )
    # The duplicate-key trick above is to handle ACS frames that might
    # not have a `geography_level` column (depends on loader version).
    grouped = grouped.rename(columns={"name": "geography"})
    cols = ["geoid", "geography", "year", "vintage", "sex",
            "age_band_start", "age_band_end", "population"]
    return grouped[cols].sort_values(
        ["geoid", "sex", "age_band_start"]
    ).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Cohort change ratios + CWR
# ---------------------------------------------------------------------------

def _pop_pivot(pop_5yr: pd.DataFrame) -> pd.DataFrame:
    """Pivot 5-yr-band pop to (geoid, sex, age_band_start) → population."""
    return (
        pop_5yr.set_index(["geoid", "sex", "age_band_start"])["population"]
        .astype(float)
        .sort_index()
    )


def cohort_change_ratios(
    pop_t0: pd.DataFrame,
    pop_t1: pd.DataFrame,
    *,
    cap: tuple[float, float] | None = (0.5, 2.0),
) -> pd.DataFrame:
    """Compute CCR for each (geoid, sex, age_band_start).

    Both inputs must be 5-yr-band frames (output of
    `aggregate_b01001_to_5yr_bands`). The two frames are assumed to be
    5 years apart; the function does NOT verify the gap from the
    `year` column.

    Parameters
    ----------
    cap
        `(lower, upper)` bounds to clip raw CCRs. Default `(0.5, 2.0)`
        prevents runaway projections when ACS small-area sampling noise
        produces implausible per-cohort ratios — e.g., Hampton town
        (pop ~1,100) had a raw CCR of 9.5 for males aging from 0-4 to
        5-9, which would compound to a 60,000× cohort over 5 steps.
        Pass `None` to disable clipping (useful for diagnostics and
        tests).

    Returns
    -------
    Long-format with columns:
        geoid, sex, age_band_start, ccr, ccr_raw, clipped
    `age_band_start` is the destination band's start age. The CCR for
    the youngest band (0-4) is NOT returned — that band is projected
    via child-to-woman ratio instead (`child_woman_ratios()`).
    """
    p0 = _pop_pivot(pop_t0)
    p1 = _pop_pivot(pop_t1)
    rows = []
    for (geoid, sex), p1_slice in p1.groupby(level=[0, 1]):
        p0_slice = p0.loc[geoid, sex] if (geoid, sex) in p0.index.droplevel(2).unique() else None
        if p0_slice is None or p0_slice.empty:
            continue
        for (start, end) in FIVE_YEAR_BANDS:
            if (start, end) == YOUNGEST_BAND:
                continue
            if (start, end) == OPEN_BAND:
                # Denominator is sum of 80-84 + 85+ at t0
                denom = float(p0_slice.get(80, 0.0)) + float(p0_slice.get(85, 0.0))
                numer = float(p1_slice.loc[(geoid, sex, 85)]) if (geoid, sex, 85) in p1.index else 0.0
            else:
                prev_start = start - 5
                denom = float(p0_slice.get(prev_start, 0.0))
                key = (geoid, sex, start)
                numer = float(p1.loc[key]) if key in p1.index else 0.0
            if denom <= 0:
                continue
            raw = numer / denom
            ccr_val = raw
            clipped = False
            if cap is not None:
                lo, hi = cap
                if raw < lo:
                    ccr_val = lo; clipped = True
                elif raw > hi:
                    ccr_val = hi; clipped = True
            rows.append({
                "geoid": geoid, "sex": sex,
                "age_band_start": start,
                "ccr": ccr_val,
                "ccr_raw": raw,
                "clipped": clipped,
            })
    return pd.DataFrame(rows)


def child_woman_ratios(pop_t1: pd.DataFrame) -> pd.DataFrame:
    """CWR per (geoid, sex of child) at time t1.

    CWR(sex) = P(0-4, sex, t1) / P(women 15-49, t1)

    Returns DataFrame with columns: geoid, sex, cwr.
    """
    p = _pop_pivot(pop_t1)
    rows = []
    for geoid, _sub in p.groupby(level=0):
        # Women 15-49 = sum of female pop in bands 15-19 .. 45-49.
        women_total = 0.0
        for start in (15, 20, 25, 30, 35, 40, 45):
            key = (geoid, "F", start)
            if key in p.index:
                women_total += float(p.loc[key])
        if women_total <= 0:
            continue
        for sex in ("M", "F"):
            key = (geoid, sex, 0)
            if key not in p.index:
                continue
            rows.append({
                "geoid": geoid, "sex": sex,
                "cwr": float(p.loc[key]) / women_total,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

def project_one_county_hp(
    pop_base: pd.DataFrame,
    ccr: pd.DataFrame,
    cwr: pd.DataFrame,
    *,
    base_year: int,
    end_year: int,
    step_years: int = 5,
    geoid: str | None = None,
    geography: str | None = None,
    scenario: str = "baseline",
    projection_vintage: str = "hamilton_perry_v1",
) -> pd.DataFrame:
    """Project one geography forward in 5-year steps via Hamilton-Perry.

    `pop_base` is a 5-yr-band frame at `base_year` for one geography.
    `ccr` and `cwr` may carry multiple geoids; this function filters
    by the `geoid` argument (or by the unique geoid in `pop_base` if
    `geoid=None`).

    Returns a HP_PROJECTION_COLUMNS frame with rows at `base_year` and
    every `base_year + k*step_years` ≤ `end_year`.
    """
    if (end_year - base_year) % step_years != 0:
        raise ValueError(
            f"end_year ({end_year}) - base_year ({base_year}) must be a "
            f"multiple of step_years ({step_years})"
        )
    if geoid is None:
        geos = pop_base["geoid"].unique()
        if len(geos) != 1:
            raise ValueError(
                "project_one_county_hp: pop_base must contain one geoid or "
                "geoid= must be provided"
            )
        geoid = str(geos[0])
    if geography is None:
        geography = str(pop_base["geography"].iloc[0])

    # CCR and CWR lookups for this geoid.
    ccr_sub = ccr[ccr["geoid"] == geoid].set_index(["sex", "age_band_start"])["ccr"]
    cwr_sub = cwr[cwr["geoid"] == geoid].set_index("sex")["cwr"]

    if ccr_sub.empty:
        raise ValueError(f"project_one_county_hp: no CCR for geoid={geoid!r}")
    if cwr_sub.empty:
        raise ValueError(f"project_one_county_hp: no CWR for geoid={geoid!r}")

    # Build the current pop dict: {sex: {age_band_start: population}}
    P: dict[str, dict[int, float]] = {"M": {}, "F": {}}
    for _, row in pop_base.iterrows():
        sex = str(row["sex"])
        if sex not in P:
            continue
        P[sex][int(row["age_band_start"])] = float(row["population"])

    rows_out: list[pd.DataFrame] = []

    def emit(year: int, P_now: dict[str, dict[int, float]]):
        chunks = []
        for sex in ("M", "F"):
            for (start, end) in FIVE_YEAR_BANDS:
                chunks.append({
                    "geoid": geoid,
                    "geography": geography,
                    "year": int(year),
                    "sex": sex,
                    "age_band_start": start,
                    "age_band_end": end,
                    "population": float(P_now[sex].get(start, 0.0)),
                    "scenario": scenario,
                    "projection_vintage": projection_vintage,
                })
        rows_out.append(pd.DataFrame(chunks))

    emit(base_year, P)

    for year in range(base_year + step_years, end_year + 1, step_years):
        new_P: dict[str, dict[int, float]] = {"M": {}, "F": {}}
        # Project closed and open bands.
        for sex in ("M", "F"):
            for (start, end) in FIVE_YEAR_BANDS:
                if (start, end) == YOUNGEST_BAND:
                    # Project via CWR: P(0-4, sex) = CWR(sex) × women 15-49.
                    # `women 15-49` is computed from THIS sex's new pop only
                    # if we've already projected female 15-49 — but we may
                    # not have. Compute from current P (before update of
                    # closed bands) instead, after the closed-band loop
                    # below.
                    continue
                if (start, end) == OPEN_BAND:
                    pool = P[sex].get(80, 0.0) + P[sex].get(85, 0.0)
                    ccr_val = float(ccr_sub.get((sex, 85), 0.0))
                    new_P[sex][85] = ccr_val * pool
                else:
                    prev_start = start - 5
                    src = P[sex].get(prev_start, 0.0)
                    ccr_val = float(ccr_sub.get((sex, start), 0.0))
                    new_P[sex][start] = ccr_val * src
        # Now compute women 15-49 in the NEW pop and apply CWR.
        women_15_49_new = sum(new_P["F"].get(s, 0.0) for s in (15, 20, 25, 30, 35, 40, 45))
        for sex in ("M", "F"):
            new_P[sex][0] = float(cwr_sub.get(sex, 0.0)) * women_15_49_new
        # Fill missing bands with 0.
        for sex in ("M", "F"):
            for (start, _) in FIVE_YEAR_BANDS:
                new_P[sex].setdefault(start, 0.0)
        P = new_P
        emit(year, P)

    out = pd.concat(rows_out, ignore_index=True)
    out["population"] = out["population"].astype("Float64")
    return out[HP_PROJECTION_COLUMNS]
