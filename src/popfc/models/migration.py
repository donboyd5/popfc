"""Age-and-sex-specific net migration rates by the residual method.

For a county-year pair (t, t+1), the residual method backs out net migration
by age and sex from the observed population:

    M(x+1, t+1) = P_obs(x+1, t+1)  −  P(x, t) × S(x)             (closed)
    M(ω,   t+1) = P_obs(ω, t+1)    − [P(ω-1, t) + P(ω, t)] × S_b (open)

Then rates are computed relative to the source-age population:

    m(x → x+1) = M(x+1, t+1) / P(x, t)            (closed)
    m(ω-1, ω → ω) = M(ω, t+1) / [P(ω-1, t) + P(ω, t)]   (open)

In the cohort-component engine these rates are applied additively to
survival:

    new_P[x+1] = P(x, t) × (S(x) + m(x))                          (closed)
    new_P[ω]   = (P(ω-1, t) + P(ω, t)) × (S_b + m_boundary)       (open)

so net migration can be thought of as a survival "bonus" (positive) or
"penalty" (negative).

## Top-code matching

Census SYA and CDC bridged-race population data top-code at age 85. NCHS
NVSR life tables top-code at 100. This module always operates with a
rebanded survival schedule whose open band matches the population data's
top-code (`top_code_age=85` by default), using
`survival_rates_from_life_table(..., top_code_age=85)`.

## Smoothing / noise

Single-year residuals are noisy at the county level — a fifteen-person
net migration into age 23 in a county of 60,000 has a rate of < 0.001
relative to the source-age population. We average rates across all
available year-pairs to reduce variance. Heavier smoothing (e.g., 5-year
moving average over age) is intentionally NOT applied here; the engine
or its caller can layer that on if needed.

## Babies (age 0)

Net migration of newborns is computed as a residual against
births × birth-survival, but births by sex are not directly observed
(only total births). For simplicity this module skips age 0 entirely;
the engine assumes zero net migration for newborns. Empirically this
is small.
"""

from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

NET_MIGRATION_RATES_COLUMNS: list[str] = [
    "geoid",
    "geography",
    "year_basis",       # human-readable description of which year-pairs went in
    "sex",
    "band_type",        # "closed" | "boundary"
    "age",              # destination age (x+1 for closed, ω for boundary)
    "source_age",       # source age at year t (x for closed, sentinel for boundary)
    "m_rate",           # nullable Float64 — per-source-person rate (can be ±)
    "n_year_pairs",     # Int64 — how many year-pairs were averaged
    "notes",
]


# ---------------------------------------------------------------------------
# Core residual computation (one year-pair, one sex, one county)
# ---------------------------------------------------------------------------

def _residual_one_pair(
    P_t: pd.Series,            # index = age, values = population at time t
    P_tp1: pd.Series,          # index = age, values = population at time t+1
    closed_survival: pd.Series, # index = age (source), values = S(x→x+1)
    S_boundary: float,
    top_code_age: int,
) -> pd.DataFrame:
    """Return long-format M_count and m_rate rows for one (geoid, sex, year-pair)."""
    rows = []
    # Closed transitions: x → x+1 for x in 0..top_code_age-2
    for source_age in range(0, top_code_age - 1):
        dest_age = source_age + 1
        if source_age not in P_t.index or dest_age not in P_tp1.index:
            continue
        if source_age not in closed_survival.index:
            continue
        P_src = float(P_t.loc[source_age])
        if P_src <= 0:
            continue
        Sx = float(closed_survival.loc[source_age])
        M = float(P_tp1.loc[dest_age]) - P_src * Sx
        rows.append({
            "band_type": "closed",
            "age": dest_age,
            "source_age": source_age,
            "m_rate": M / P_src,
        })
    # Boundary: P(ω-1) + P(ω) → P(ω)
    if (top_code_age - 1) in P_t.index and top_code_age in P_t.index and top_code_age in P_tp1.index:
        P_src = float(P_t.loc[top_code_age - 1]) + float(P_t.loc[top_code_age])
        if P_src > 0:
            M = float(P_tp1.loc[top_code_age]) - P_src * S_boundary
            rows.append({
                "band_type": "boundary",
                "age": top_code_age,
                "source_age": top_code_age - 1,  # sentinel: pair (ω-1, ω)
                "m_rate": M / P_src,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Frame-level builder
# ---------------------------------------------------------------------------

def build_net_migration_rates(
    pop_by_age: pd.DataFrame,
    survival: pd.DataFrame,
    *,
    top_code_age: int = 85,
    state_geoid: str = "36000",
) -> pd.DataFrame:
    """Compute net migration rates per (geoid, sex, age) from year-pairs.

    Parameters
    ----------
    pop_by_age
        Long-format population by single year of age. Must contain
        `geoid`, `year`, `sex`, `age`, `population`. Should already be
        filtered to the relevant `kind` (e.g., 'estimate') by the caller.
    survival
        SURVIVAL_RATES_COLUMNS frame. The function uses one row per
        (sex, age) for `band_type='closed'` plus one boundary per sex.
        Survival rates are expected to be associated with `state_geoid`
        (default: NY state 36000) and applied uniformly across all
        counties — county-specific mortality refinement is a Phase-4
        consideration.
    top_code_age
        Open-band top code (default 85, matching Census SYA / CDC).
    state_geoid
        Which row of `survival` carries the rates to apply.

    Returns
    -------
    NET_MIGRATION_RATES_COLUMNS frame, one row per (geoid, sex, age),
    with `m_rate` averaged across all year-pairs in `pop_by_age`.
    """
    # Subset survival to the state's rates.
    surv = survival[survival["geoid"] == state_geoid].copy()
    if surv.empty:
        raise ValueError(f"build_net_migration_rates: no survival rows for geoid={state_geoid!r}")

    # Per-sex lookups.
    closed_by_sex: dict[str, pd.Series] = {}
    boundary_by_sex: dict[str, float] = {}
    for sex, sub in surv.groupby("sex"):
        closed = sub[sub["band_type"] == "closed"].set_index("age")["Sx"].astype(float)
        boundary_rows = sub[sub["band_type"] == "boundary"]
        if boundary_rows.empty:
            continue
        closed_by_sex[sex] = closed
        boundary_by_sex[sex] = float(boundary_rows["Sx"].iloc[0])

    # Year-pair iterator: per (geoid, sex), use successive observed years.
    out_rows: list[pd.DataFrame] = []
    grouped = pop_by_age.groupby(["geoid", "sex"], dropna=False, sort=False)
    for (geoid, sex), gsub in grouped:
        if sex not in closed_by_sex:
            continue
        gsub = gsub.sort_values(["year", "age"])
        years = sorted(gsub["year"].unique())
        if len(years) < 2:
            continue
        geog = gsub["geography"].iloc[0]
        pair_frames = []
        for y_t, y_tp1 in zip(years, years[1:]):
            if y_tp1 - y_t != 1:
                continue  # only consecutive years
            P_t = gsub[gsub["year"] == y_t].set_index("age")["population"].astype("Float64")
            P_tp1 = gsub[gsub["year"] == y_tp1].set_index("age")["population"].astype("Float64")
            df = _residual_one_pair(
                P_t, P_tp1,
                closed_by_sex[sex], boundary_by_sex[sex],
                top_code_age,
            )
            if df.empty:
                continue
            df["year_pair"] = f"{y_t}-{y_tp1}"
            pair_frames.append(df)
        if not pair_frames:
            continue
        all_pairs = pd.concat(pair_frames, ignore_index=True)
        # Average across pairs.
        avg = (
            all_pairs.groupby(["band_type", "age", "source_age"], as_index=False)
            .agg(
                m_rate=("m_rate", "mean"),
                n_year_pairs=("year_pair", "nunique"),
            )
        )
        avg["geoid"] = geoid
        avg["geography"] = geog
        avg["sex"] = sex
        years_used = sorted(all_pairs["year_pair"].unique())
        avg["year_basis"] = f"avg of {len(years_used)} pairs: {','.join(years_used)}"
        avg["notes"] = ""
        out_rows.append(avg)

    if not out_rows:
        return pd.DataFrame(columns=NET_MIGRATION_RATES_COLUMNS)

    out = pd.concat(out_rows, ignore_index=True)
    out["m_rate"] = out["m_rate"].astype("Float64")
    out["n_year_pairs"] = out["n_year_pairs"].astype("Int64")
    # Reorder.
    return out[NET_MIGRATION_RATES_COLUMNS].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Historical reference periods (for scenario construction)
# ---------------------------------------------------------------------------

# Output columns for the per-county reference-period summary returned by
# `historical_reference_periods()`.
REFERENCE_PERIOD_COLUMNS: list[str] = [
    "geoid",            # 5-char county FIPS
    "geography",        # human-readable county name
    "window_kind",      # "current" | "best" | "worst"
    "year_start",       # first year of the window (inclusive)
    "year_end",         # last year of the window (inclusive)
    "n_years",          # number of years in the window (window_years if data is complete)
    "avg_rate",         # average annual net migration as a fraction of mid-year pop
    "notes",            # free-form
]


def historical_reference_periods(
    components: pd.DataFrame,
    population: pd.DataFrame,
    *,
    window_years: int = 5,
    start_year: int = 2010,
    end_year: int | None = None,
    geoids: list[str] | None = None,
) -> pd.DataFrame:
    """Find per-county best/worst/current rolling-window net migration averages.

    For each county, computes annual net migration as a fraction of mid-year
    population (using PEP's published `net_mig` measure and the reconciled
    annual totals), then identifies three reference windows of `window_years`:

    - **current**: the most recent complete window in the data
    - **best**:    the window with the highest (most positive / least negative)
                   average rate over the eligible range
    - **worst**:   the window with the lowest average rate

    These are used to construct scenario knobs that anchor projections to
    historical experience rather than arbitrary multipliers.

    Parameters
    ----------
    components
        Long-format components frame (`COMPONENTS_LONG_COLUMNS`). Must
        contain rows with `measure == "net_mig"` (counts).
    population
        Reconciled annual population frame (`POP_LONG_COLUMNS`). Used as
        the denominator for rates and to compute mid-year averages.
    window_years
        Window size in years (default 5). Windows are inclusive on both
        ends; a 5-year window covers years y, y+1, ..., y+4.
    start_year
        Earliest year a window may start (default 2010).
    end_year
        Latest year that may appear in a window. Default: max year in
        `components` with `net_mig` data.
    geoids
        Restrict to specific counties. Default: every county that has at
        least `window_years` years of net_mig data.

    Returns
    -------
    DataFrame conforming to `REFERENCE_PERIOD_COLUMNS`, three rows per
    geoid (current, best, worst). When the data is too sparse for a
    county (fewer than `window_years` complete years), that county is
    omitted from the output.
    """
    nm = components[components["measure"] == "net_mig"][
        ["geoid", "geography", "year", "value"]
    ].rename(columns={"value": "net_mig"}).copy()
    nm["net_mig"] = nm["net_mig"].astype("Float64")
    nm = nm.dropna(subset=["net_mig"])

    pop = population[["geoid", "year", "population"]].copy()
    pop["population"] = pop["population"].astype("Float64")
    pop = pop.dropna(subset=["population"]).sort_values(["geoid", "year"])
    pop["pop_prev"] = pop.groupby("geoid")["population"].shift(1)
    pop["mid_pop"] = (pop["population"] + pop["pop_prev"]) / 2.0

    df = nm.merge(pop[["geoid", "year", "mid_pop"]], on=["geoid", "year"], how="inner")
    df["mig_rate"] = df["net_mig"].astype("Float64") / df["mid_pop"]
    df = df.dropna(subset=["mig_rate"])

    if end_year is None:
        end_year = int(df["year"].max())

    df = df[(df["year"] >= start_year) & (df["year"] <= end_year)].copy()

    if geoids is not None:
        df = df[df["geoid"].isin(geoids)].copy()

    out_rows: list[dict] = []
    for geoid, gsub in df.groupby("geoid"):
        gsub = gsub.sort_values("year").reset_index(drop=True)
        years = gsub["year"].to_numpy()
        rates = gsub["mig_rate"].astype(float).to_numpy()
        geog = gsub["geography"].iloc[0]
        n = len(years)
        if n < window_years:
            continue
        # Build rolling-window averages keyed by the window's start year.
        windows = []
        for i in range(n - window_years + 1):
            start = int(years[i])
            stop = int(years[i + window_years - 1])
            # Require the window to be contiguous (no missing years between
            # start and stop) — otherwise the average isn't comparable.
            if stop - start != window_years - 1:
                continue
            avg = float(rates[i : i + window_years].mean())
            windows.append((start, stop, avg))
        if not windows:
            continue

        # Current = the window that ends latest.
        current = max(windows, key=lambda w: w[1])
        # Best = highest avg (most positive); worst = lowest.
        best = max(windows, key=lambda w: w[2])
        worst = min(windows, key=lambda w: w[2])

        for kind, (s, e, avg) in [("current", current), ("best", best), ("worst", worst)]:
            out_rows.append({
                "geoid": geoid,
                "geography": geog,
                "window_kind": kind,
                "year_start": s,
                "year_end": e,
                "n_years": window_years,
                "avg_rate": avg,
                "notes": "",
            })

    if not out_rows:
        return pd.DataFrame(columns=REFERENCE_PERIOD_COLUMNS)
    out = pd.DataFrame(out_rows)
    out["avg_rate"] = out["avg_rate"].astype("Float64")
    out["year_start"] = out["year_start"].astype("Int64")
    out["year_end"] = out["year_end"].astype("Int64")
    out["n_years"] = out["n_years"].astype("Int64")
    return out[REFERENCE_PERIOD_COLUMNS].reset_index(drop=True)
