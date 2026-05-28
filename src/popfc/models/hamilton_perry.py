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


def cohort_change_ratios_multi_vintage(
    agesex_history: pd.DataFrame,
    *,
    cap: tuple[float, float] | None = (0.85, 1.20),
    vintage_step: int = 5,
) -> pd.DataFrame:
    """Compute CCRs averaged across every available 5-year vintage pair.

    Most rural MCDs have ~1,000-3,000 residents. A single 5-year-vintage
    CCR over a single age × sex cell is noisy (one ACS sample's wobble can
    drive a CCR from 0.9 to 1.5). Averaging across all overlapping
    5-year-apart vintage pairs in `agesex_history` reduces variance while
    preserving the cohort change signal.

    For NY MCDs with the project's town_agesex_history (15 vintages,
    2009-2024 except 2020), this yields ~10 5-year pairs per cohort —
    e.g., 2007→2012, 2008→2013, …, 2017→2022 (with one gap at 2013→2018
    because Census didn't release ACS 2016-2020).

    Parameters
    ----------
    agesex_history
        Long-format frame from Notebook 11 §0 with columns
        ``geoid``, ``geography``, ``sex``, ``age_band_start``,
        ``age_band_end``, ``population``, ``vintage_midpoint_year``,
        plus a vintage label.
    cap
        Per-pair clip applied BEFORE averaging. Default ``(0.85, 1.20)``
        matches the production single-vintage cap. Pass ``None`` to
        disable clipping (averaging alone may not damp small-area noise
        sufficiently).
    vintage_step
        Required midpoint-year gap between vintages in a pair. Default 5
        (one 5-year band per step).

    Returns
    -------
    Long-format with columns:
        geoid, sex, age_band_start, ccr, ccr_pairs_avg, n_pairs,
        n_pairs_clipped
    where ``ccr`` is the averaged (post-clip) value used in projection
    and ``ccr_pairs_avg`` carries the raw arithmetic mean of clipped
    pairs (currently equal to ``ccr`` — they would diverge only if a
    future second-pass cap were applied on the average).
    """
    required = {"geoid", "sex", "age_band_start", "age_band_end",
                "population", "vintage_midpoint_year"}
    missing = required - set(agesex_history.columns)
    if missing:
        raise ValueError(
            f"agesex_history missing required columns: {sorted(missing)}"
        )

    midpoint_years = sorted(int(y) for y in agesex_history["vintage_midpoint_year"].unique())

    # Enumerate (t0, t1) midpoint-year pairs separated by exactly vintage_step.
    pairs: list[tuple[int, int]] = [
        (m0, m0 + vintage_step)
        for m0 in midpoint_years
        if (m0 + vintage_step) in set(midpoint_years)
    ]
    if not pairs:
        raise ValueError(
            f"No vintage-pair separations of {vintage_step} years found in "
            f"the supplied agesex_history midpoint years: {midpoint_years}"
        )

    # Build CCR contributions per pair.
    accum: dict[tuple[str, str, int], list[float]] = {}
    clipped_counts: dict[tuple[str, str, int], int] = {}

    for t0_mid, t1_mid in pairs:
        pop_t0 = agesex_history[agesex_history["vintage_midpoint_year"] == t0_mid][
            ["geoid", "geography", "sex", "age_band_start", "age_band_end",
             "population", "vintage_midpoint_year"]
        ].rename(columns={"vintage_midpoint_year": "year"})
        pop_t1 = agesex_history[agesex_history["vintage_midpoint_year"] == t1_mid][
            ["geoid", "geography", "sex", "age_band_start", "age_band_end",
             "population", "vintage_midpoint_year"]
        ].rename(columns={"vintage_midpoint_year": "year"})
        # `cohort_change_ratios` returns ccr (post-clip), ccr_raw, clipped.
        ccr_one = cohort_change_ratios(pop_t0, pop_t1, cap=cap)
        for _, r in ccr_one.iterrows():
            key = (r["geoid"], r["sex"], int(r["age_band_start"]))
            accum.setdefault(key, []).append(float(r["ccr"]))
            if bool(r["clipped"]):
                clipped_counts[key] = clipped_counts.get(key, 0) + 1

    out_rows = []
    for key, vals in accum.items():
        geoid, sex, start = key
        out_rows.append({
            "geoid": geoid, "sex": sex, "age_band_start": int(start),
            "ccr": float(sum(vals) / len(vals)),
            "ccr_pairs_avg": float(sum(vals) / len(vals)),
            "n_pairs": len(vals),
            "n_pairs_clipped": int(clipped_counts.get(key, 0)),
        })
    return pd.DataFrame(out_rows).sort_values(
        ["geoid", "sex", "age_band_start"]
    ).reset_index(drop=True)


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


# ---------------------------------------------------------------------------
# v3 input-quality refinements (Notebook 12 audit follow-ups)
# ---------------------------------------------------------------------------

def rescale_base_to_target(
    pop_base: pd.DataFrame,
    target_totals: pd.DataFrame | pd.Series | dict,
    *,
    geoid_col: str = "geoid",
    population_col: str = "population",
    min_factor: float = 0.5,
    max_factor: float = 2.0,
) -> pd.DataFrame:
    """Proportionally rescale each geography's age × sex base to a target total.

    Hamilton-Perry feeds an ACS 5-year midpoint pyramid as the base
    population. For small towns the ACS total can disagree materially with
    the authoritative PEP sub-est total (the Notebook-12 audit found
    Hampton's ACS base +33% above PEP, Hartford -13%). This function scales
    every (sex, age band) cell of a geography by a single factor so the
    geography's total matches its `target_totals` value, preserving the ACS
    pyramid *shape* while fixing the *level*.

    Parameters
    ----------
    pop_base
        5-yr-band frame with at least `geoid`, `population` columns
        (output of `aggregate_b01001_to_5yr_bands`).
    target_totals
        Per-geography target totals. Accepts a DataFrame with
        `geoid` + a total column (`population` or `total`), a Series
        indexed by geoid, or a {geoid: total} dict.
    min_factor, max_factor
        Clip the per-geography scale factor to this range. A town whose
        ACS base disagrees with PEP by more than 2× is more likely a
        geography-matching problem than a real level error, so we cap the
        adjustment and warn rather than apply a wild rescale.

    Returns
    -------
    A copy of `pop_base` with `population` rescaled and an added
    `rescale_factor` column recording the per-geography factor applied.
    Geographies absent from `target_totals` are passed through unchanged
    (factor 1.0).
    """
    # Normalize target_totals to a {geoid: total} mapping.
    if isinstance(target_totals, pd.DataFrame):
        total_col = "population" if "population" in target_totals.columns else "total"
        tmap = dict(zip(target_totals[geoid_col].astype(str),
                        target_totals[total_col].astype(float)))
    elif isinstance(target_totals, pd.Series):
        tmap = {str(k): float(v) for k, v in target_totals.items()}
    else:
        tmap = {str(k): float(v) for k, v in dict(target_totals).items()}

    df = pop_base.copy()
    current_totals = df.groupby(geoid_col)[population_col].transform("sum")

    factors = {}
    warnings_list = []
    for g in df[geoid_col].astype(str).unique():
        cur = float(df[df[geoid_col].astype(str) == g][population_col].sum())
        tgt = tmap.get(g)
        if tgt is None or cur <= 0:
            factors[g] = 1.0
            continue
        f = tgt / cur
        if f < min_factor or f > max_factor:
            warnings_list.append((g, f))
            f = max(min_factor, min(max_factor, f))
        factors[g] = f

    if warnings_list:
        import warnings
        worst = ", ".join(f"{g}:{f:.2f}" for g, f in warnings_list[:5])
        warnings.warn(
            f"rescale_base_to_target: {len(warnings_list)} geographies had "
            f"a rescale factor outside [{min_factor}, {max_factor}] and were "
            f"clipped (e.g., {worst}). These usually indicate ACS/PEP "
            "geography mismatch rather than a real level error.",
            stacklevel=2,
        )

    df["rescale_factor"] = df[geoid_col].astype(str).map(factors).fillna(1.0)
    df[population_col] = df[population_col].astype(float) * df["rescale_factor"]
    return df


def aggregate_history_to_parent(
    agesex_history: pd.DataFrame,
    *,
    parent_geoid: str,
    parent_geography: str | None = None,
) -> pd.DataFrame:
    """Sum a multi-geography age × sex history into a single parent geography.

    Used to build a county-aggregate CCR reference from the same ACS town
    history that feeds the per-town CCRs, so the reference is directly
    comparable (same source, same vintages, same bands).

    Parameters
    ----------
    agesex_history
        Long-format frame with `sex`, `age_band_start`, `age_band_end`,
        `population`, `vintage_midpoint_year` (the columns
        `cohort_change_ratios_multi_vintage` requires).
    parent_geoid
        Geoid to assign the aggregated rows.
    parent_geography
        Optional label; defaults to ``f"{parent_geoid} (aggregate)"``.
    """
    group_cols = ["sex", "age_band_start", "age_band_end", "vintage_midpoint_year"]
    missing = set(group_cols) - set(agesex_history.columns)
    if missing:
        raise ValueError(
            f"aggregate_history_to_parent: missing columns {sorted(missing)}"
        )
    agg = agesex_history.groupby(group_cols, as_index=False)["population"].sum()
    agg["geoid"] = parent_geoid
    agg["geography"] = parent_geography or f"{parent_geoid} (aggregate)"
    return agg


def population_shrinkage_weights(
    pop_base: pd.DataFrame,
    *,
    k: float = 2000.0,
    geoid_col: str = "geoid",
    population_col: str = "population",
) -> pd.Series:
    """Per-geography shrinkage weight ``w = P / (P + k)`` for CCR shrinkage.

    Larger geographies trust their own (more reliable) CCRs; smaller ones
    are pulled harder toward the parent. With the default ``k = 2000``
    (the project's rural-town threshold), a town of 2,000 gets w = 0.5,
    a town of 12,000 gets w ≈ 0.86, and a town of 500 gets w = 0.20.

    Returns a Series indexed by geoid with values in (0, 1).
    """
    totals = pop_base.groupby(geoid_col)[population_col].sum().astype(float)
    return totals / (totals + k)


def shrink_ccrs_toward_reference(
    town_ccr: pd.DataFrame,
    reference_ccr: pd.DataFrame,
    *,
    town_weights: pd.Series | dict,
    ccr_col: str = "ccr",
) -> pd.DataFrame:
    """Shrink per-town CCRs toward a parent reference CCR (small-area estimation).

    For each (geoid, sex, age_band_start) cell:

        ccr_shrunk = w_geoid · ccr_town + (1 − w_geoid) · ccr_reference

    where `ccr_reference` is the parent (county-aggregate) CCR for the
    matching (sex, age_band_start). Cells with no reference match keep
    their town value (w effectively 1).

    Parameters
    ----------
    town_ccr
        Per-town CCR frame (`geoid`, `sex`, `age_band_start`, `ccr`, …),
        e.g. from `cohort_change_ratios_multi_vintage`.
    reference_ccr
        Parent CCR frame with `sex`, `age_band_start`, `ccr`. Any `geoid`
        column is ignored.
    town_weights
        geoid → w in [0, 1]. Use `population_shrinkage_weights`.
    ccr_col
        Name of the CCR column in both frames.

    Returns
    -------
    Copy of `town_ccr` with `ccr` replaced by the shrunk value and added
    columns `ccr_town` (pre-shrinkage), `ccr_reference`, `shrink_weight`.
    """
    wmap = ({str(k): float(v) for k, v in town_weights.items()}
            if isinstance(town_weights, (pd.Series, dict))
            else dict(town_weights))

    ref = reference_ccr[["sex", "age_band_start", ccr_col]].rename(
        columns={ccr_col: "ccr_reference"}
    )
    out = town_ccr.merge(ref, on=["sex", "age_band_start"], how="left")
    out["ccr_town"] = out[ccr_col].astype(float)
    out["shrink_weight"] = out["geoid"].astype(str).map(wmap).fillna(1.0)
    # Where no reference cell exists, keep town value (weight → 1).
    has_ref = out["ccr_reference"].notna()
    shrunk = (
        out["shrink_weight"] * out["ccr_town"]
        + (1.0 - out["shrink_weight"]) * out["ccr_reference"]
    )
    out[ccr_col] = shrunk.where(has_ref, out["ccr_town"])
    return out


def shrink_cwr_toward_reference(
    town_cwr: pd.DataFrame,
    reference_cwr: pd.DataFrame,
    *,
    town_weights: pd.Series | dict,
) -> pd.DataFrame:
    """Shrink per-town child-woman ratios toward a parent reference CWR.

    Same small-area logic as `shrink_ccrs_toward_reference`, but the CWR
    is keyed by (geoid, sex) only — there's one 0-4-per-woman-15-49 ratio
    per sex of child. Small-town ACS samples make the CWR especially
    noisy (both the 0-4 count and the women-15-49 count have wide MOE,
    and their ratio compounds it), and the CWR is the births engine of
    the Hamilton-Perry projection — an inflated town CWR projects
    sustained above-county fertility forward, driving spurious growth.

    For each (geoid, sex):
        cwr_shrunk = w_geoid · cwr_town + (1 − w_geoid) · cwr_reference

    Returns a copy of `town_cwr` with `cwr` replaced by the shrunk value
    and added columns `cwr_town`, `cwr_reference`, `shrink_weight`.
    """
    wmap = ({str(k): float(v) for k, v in town_weights.items()}
            if isinstance(town_weights, (pd.Series, dict))
            else dict(town_weights))

    ref = reference_cwr[["sex", "cwr"]].rename(columns={"cwr": "cwr_reference"})
    out = town_cwr.merge(ref, on="sex", how="left")
    out["cwr_town"] = out["cwr"].astype(float)
    out["shrink_weight"] = out["geoid"].astype(str).map(wmap).fillna(1.0)
    has_ref = out["cwr_reference"].notna()
    shrunk = (
        out["shrink_weight"] * out["cwr_town"]
        + (1.0 - out["shrink_weight"]) * out["cwr_reference"]
    )
    out["cwr"] = shrunk.where(has_ref, out["cwr_town"])
    return out
