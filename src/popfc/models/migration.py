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


# ---------------------------------------------------------------------------
# Domestic / international decomposition (Batch 4b)
# ---------------------------------------------------------------------------
#
# The residual method gives us *net* migration rates m_total(g, s, a). For
# analytical and scenario purposes we want to split each cell into a
# domestic component m_dom and an international component m_int such that
# m_dom + m_int = m_total. The decomposition combines three inputs:
#
#   1. **Per-county aggregate shares**: PEP V2025 publishes county-year
#      `domestic_mig` and `international_mig` counts. Their ratio gives a
#      *signed* county-level domestic factor `p_dom_county`. Counties
#      where the two components have opposite signs (e.g., Washington
#      with negative domestic and positive international net) yield
#      p_dom outside [0, 1] — this is the correct sign-carrying factor,
#      not a probability.
#
#   2. **Age × component shape**: ACS B07001 (Geographical Mobility in
#      the Past Year by Age) gives the relative fraction of inflows at
#      each age band that come from domestic vs international origins.
#      For NY state-aggregate this fraction is fairly flat (0.81-0.91
#      across age bands) but the tilt is non-trivial at college (18-19,
#      tilts domestic) and child / very old ages (tilts international).
#
#   3. **Per-cell residual rates**: m_total(g, s, a) from the residual
#      method. The decomposition preserves these cell-by-cell so the
#      baseline forecast (all multipliers = 1, all deltas = 0) is
#      identical to the pre-decomposition engine.

B07001_AGE_BANDS: list[tuple[int, int | None, str]] = [
    (1, 4, "1 to 4 years"),
    (5, 17, "5 to 17 years"),
    (18, 19, "18 and 19 years"),
    (20, 24, "20 to 24 years"),
    (25, 29, "25 to 29 years"),
    (30, 34, "30 to 34 years"),
    (35, 39, "35 to 39 years"),
    (40, 44, "40 to 44 years"),
    (45, 49, "45 to 49 years"),
    (50, 54, "50 to 54 years"),
    (55, 59, "55 to 59 years"),
    (60, 64, "60 to 64 years"),
    (65, 69, "65 to 69 years"),
    (70, 74, "70 to 74 years"),
    (75, None, "75 years and over"),
]

# Components within B07001 that count toward "domestic" net migration.
# We exclude "Moved within same county" since intra-county moves don't
# affect county-level net migration.
_B07001_DOMESTIC_COMPONENTS = (
    "Moved from different county within same state",
    "Moved from different state",
)
_B07001_INTERNATIONAL_COMPONENTS = ("Moved from abroad",)


# Output columns for `b07001_age_component_shape()`.
AGE_COMPONENT_SHAPE_COLUMNS: list[str] = [
    "age_lower",       # Int — lower bound of the band (inclusive)
    "age_upper",       # Int — upper bound of the band (inclusive); pandas.NA for the open top band
    "age_band",        # B07001 label
    "domestic",        # Float — aggregated inflow count for domestic components
    "international",   # Float — aggregated inflow count for international
    "f_dom",           # domestic / (domestic + international) ∈ [0, 1]
    "source",
    "vintage",
    "notes",
]


def b07001_age_component_shape(
    b07001_long: pd.DataFrame,
    *,
    state_filter: str | None = "36",
    label_col: str = "label",
    value_col: str = "value",
    state_fips_col: str = "state_fips",
) -> pd.DataFrame:
    """Aggregate B07001 (Mobility by Age) to a single age-band × component shape.

    Parameters
    ----------
    b07001_long
        Long-format frame returned by `popfc.data.acs.load_acs5_group("B07001", ...)`.
        Must contain a `label` column with the human-readable ACS variable
        label and a `value` column with the estimate. Other columns are used
        for filtering only.
    state_filter
        Restrict to rows where `state_fips` matches. ``None`` aggregates
        nationwide (or whatever's in the frame).
    label_col, value_col, state_fips_col
        Column names; override only if the caller has renamed them.

    Returns
    -------
    DataFrame with one row per age band conforming to
    `AGE_COMPONENT_SHAPE_COLUMNS`. ``f_dom`` is the fraction of
    (domestic + international) inflows at each band age that are
    domestic; intra-county moves and non-movers are excluded.
    """
    df = b07001_long
    if state_filter is not None and state_fips_col in df.columns:
        df = df[df[state_fips_col].astype(str).str.zfill(2) == state_filter]

    parsed = df[label_col].astype(str).map(_parse_b07001_label)
    df = df.assign(
        _component=parsed.map(lambda t: t[0]),
        _age_band=parsed.map(lambda t: t[1]),
    )
    df = df.dropna(subset=["_component", "_age_band"]).copy()

    agg = (
        df.groupby(["_component", "_age_band"], as_index=False)[value_col].sum()
        .rename(columns={"_component": "component", "_age_band": "age_band"})
    )
    piv = agg.pivot_table(
        index="age_band", columns="component", values=value_col, aggfunc="sum",
    ).fillna(0.0)

    dom_cols = [c for c in _B07001_DOMESTIC_COMPONENTS if c in piv.columns]
    int_cols = [c for c in _B07001_INTERNATIONAL_COMPONENTS if c in piv.columns]
    if not dom_cols or not int_cols:
        raise ValueError(
            "b07001_age_component_shape: B07001 frame is missing required "
            f"components. Found columns: {sorted(piv.columns)}"
        )
    piv["domestic"] = piv[dom_cols].sum(axis=1)
    piv["international"] = piv[int_cols].sum(axis=1)
    piv["dom_int_total"] = piv["domestic"] + piv["international"]
    piv["f_dom"] = piv["domestic"] / piv["dom_int_total"].replace(0.0, pd.NA)

    # Attach age_lower / age_upper for downstream interpolation.
    band_bounds = {label: (lo, hi) for lo, hi, label in B07001_AGE_BANDS}
    out_rows = []
    for band, row in piv.iterrows():
        if band not in band_bounds:
            continue  # ignore any unexpected labels
        lo, hi = band_bounds[band]
        out_rows.append({
            "age_lower": lo,
            "age_upper": hi if hi is not None else pd.NA,
            "age_band": band,
            "domestic": float(row["domestic"]),
            "international": float(row["international"]),
            "f_dom": float(row["f_dom"]) if pd.notna(row["f_dom"]) else pd.NA,
            "source": "acs5_B07001",
            "vintage": "",
            "notes": "",
        })
    out = pd.DataFrame(out_rows).sort_values("age_lower").reset_index(drop=True)
    out["age_lower"] = out["age_lower"].astype("Int64")
    out["age_upper"] = out["age_upper"].astype("Int64")
    out["f_dom"] = out["f_dom"].astype("Float64")
    return out[AGE_COMPONENT_SHAPE_COLUMNS]


def _parse_b07001_label(label: str) -> tuple[str | None, str | None]:
    """Extract (component, age_band) from a B07001 ACS variable label.

    Labels are double-bang-separated like
    ``"Estimate!!Total:!!Moved from abroad:!!20 to 24 years"``. Returns
    (None, None) for header rows that don't carry a specific age band
    (e.g., "Estimate!!Total:" or "Estimate!!Total:!!Same house 1 year ago:").
    """
    parts = [p.rstrip(":").strip() for p in str(label).split("!!") if p.strip()]
    if len(parts) < 4:
        return (None, None)
    return (parts[2], parts[3])


def expand_age_shape_to_single_year(
    shape_band: pd.DataFrame,
    *,
    top_code_age: int = 85,
    f_dom_col: str = "f_dom",
) -> pd.DataFrame:
    """Expand a band-level age shape to single-year ages 0..top_code_age.

    Single-year `f_dom` is uniform within each band. Ages outside the
    band coverage are extrapolated from the nearest band: age 0 uses the
    1-4 band; ages above the open top band (e.g., 76..85) use the 75+ value.

    Returns
    -------
    DataFrame with columns ``age``, ``f_dom``.
    """
    rows: list[dict] = []
    sb = shape_band.sort_values("age_lower").reset_index(drop=True)
    youngest = sb.iloc[0]
    oldest = sb.iloc[-1]
    for age in range(0, top_code_age + 1):
        if age < int(youngest["age_lower"]):
            f = float(youngest[f_dom_col])
        elif pd.isna(oldest["age_upper"]) and age >= int(oldest["age_lower"]):
            f = float(oldest[f_dom_col])
        else:
            match = sb[
                (sb["age_lower"] <= age)
                & ((sb["age_upper"].isna()) | (sb["age_upper"] >= age))
            ]
            if match.empty:
                # Falls between bands (shouldn't happen with B07001's contiguous
                # bands, but be defensive)
                f = float(youngest[f_dom_col])
            else:
                f = float(match[f_dom_col].iloc[0])
        rows.append({"age": age, "f_dom": f})
    out = pd.DataFrame(rows)
    out["f_dom"] = out["f_dom"].astype("Float64")
    return out


# Output columns for `decompose_net_migration()`.
NET_MIGRATION_COMPONENTS_COLUMNS: list[str] = [
    "geoid",
    "geography",
    "year_basis",          # carried from net_mig
    "sex",
    "band_type",           # carried from net_mig
    "age",
    "source_age",
    "m_total_rate",        # cell-level total (== existing m_rate)
    "m_dom_rate",           # decomposed domestic component
    "m_int_rate",           # decomposed international component
    "p_dom_county",         # signed county-aggregate domestic share (PEP)
    "p_dom_age_effective",  # cell-level effective domestic factor after age tilt
    "n_year_pairs",
    "share_year_basis",     # description of the PEP years used to compute p_dom_county
    "source",               # provenance for the decomposition itself
    "vintage",
    "notes",
]


def _per_county_pep_dom_share(
    pep_components: pd.DataFrame,
    *,
    years: tuple[int, int],
) -> pd.DataFrame:
    """Compute per-county signed domestic share from PEP components.

    Returns a DataFrame with columns ``geoid``, ``p_dom_county``,
    ``years_used``. `p_dom_county` is summed_dom / (summed_dom + summed_int)
    over `years`; it can fall outside [0, 1] when the two components have
    opposite signs.
    """
    y0, y1 = years
    sub = pep_components[
        pep_components["measure"].isin(["domestic_mig", "international_mig"])
        & pep_components["year"].between(y0, y1)
    ].copy()
    if sub.empty:
        raise ValueError(
            f"_per_county_pep_dom_share: no domestic/international rows for "
            f"years {y0}-{y1}"
        )
    sub["value"] = sub["value"].astype("Float64")
    piv = (
        sub.pivot_table(
            index=["geoid", "geography"], columns="measure", values="value",
            aggfunc="sum",
        )
        .reset_index()
        .rename(columns={"domestic_mig": "dom_sum", "international_mig": "int_sum"})
    )
    piv["denom"] = piv["dom_sum"].astype("Float64") + piv["int_sum"].astype("Float64")
    # Use signed share; let downstream callers handle the unusual range.
    piv["p_dom_county"] = piv["dom_sum"].astype("Float64") / piv["denom"]
    piv["share_year_basis"] = f"PEP {y0}-{y1} sum-of-components"
    return piv[["geoid", "geography", "p_dom_county", "share_year_basis"]]


def decompose_net_migration(
    net_mig: pd.DataFrame,
    pep_components: pd.DataFrame,
    *,
    age_shape_single_year: pd.DataFrame | None = None,
    share_years: tuple[int, int] = (2019, 2024),
    age_tilt_factor: float = 1.0,
    p_dom_clip: tuple[float, float] = (-100.0, 100.0),
    instability_threshold: float = 5.0,
) -> pd.DataFrame:
    """Decompose net migration rates into domestic + international components.

    Parameters
    ----------
    net_mig
        NET_MIGRATION_RATES_COLUMNS frame produced by
        `build_net_migration_rates`.
    pep_components
        Long-format components frame (`COMPONENTS_LONG_COLUMNS`) containing
        rows with `measure in ("domestic_mig", "international_mig")`.
    age_shape_single_year
        Optional DataFrame with columns ``age``, ``f_dom`` produced by
        `expand_age_shape_to_single_year(b07001_age_component_shape(...))`.
        When provided, the decomposition includes an age-specific tilt
        (Tier 3); when None, the decomposition uses the county-aggregate
        share for every cell (Tier 1 — degenerate at the age level).
    share_years
        Inclusive year range used to average PEP domestic / international
        for the county-aggregate share.
    age_tilt_factor
        Multiplier on the age-specific tilt (deviation of `f_dom(a)` from
        the state-aggregate average). 1.0 = full tilt; 0.0 = degenerate
        to Tier 1. Useful for sensitivity analysis.
    p_dom_clip
        (lower, upper) clip bounds applied to `p_dom_age_effective`. The
        signed factor can legitimately fall well outside [0, 1] for
        counties whose two components have opposite signs and a near-zero
        net (Essex, Columbia in NY). Default is permissive (-100, 100) so
        real signed factors pass through; tighten only for safety-bound
        scenario work.
    instability_threshold
        Counties with ``|p_dom_county| > instability_threshold`` get a
        ``"p_dom_unstable: ..."`` annotation in the ``notes`` column.
        These counties have offsetting components whose individual scale
        is large relative to their net, so multiplicative scenario knobs
        on m_dom or m_int can produce dramatic net-rate swings. The
        decomposition itself is exact — the flag is a downstream caution.

    Returns
    -------
    NET_MIGRATION_COMPONENTS_COLUMNS frame, one row per (geoid, sex, age).
    For each cell:
        m_dom_rate + m_int_rate == m_total_rate
    """
    pep_share = _per_county_pep_dom_share(pep_components, years=share_years)

    if age_shape_single_year is not None:
        # Centered tilt: deviation of each age's f_dom from the
        # population-weighted average (over the shape frame). We use
        # the SIMPLE mean of f_dom across ages 0..ω as the centering point;
        # this approximates the population-weighted average for our flat
        # shape (NY state f_dom varies 0.81-0.91), and keeps the function
        # self-contained (no dependency on a population frame).
        f_dom_arr = age_shape_single_year["f_dom"].astype(float).to_numpy()
        f_dom_mean = float(f_dom_arr.mean())
        age_arr = age_shape_single_year["age"].astype(int).to_numpy()
        tilt_lookup = dict(zip(age_arr, f_dom_arr - f_dom_mean))
        age_tilt_basis = f"B07001 single-year shape, centered at mean={f_dom_mean:.4f}"
    else:
        tilt_lookup = {}
        age_tilt_basis = "none (Tier 1 — county-aggregate share only)"

    # Merge net_mig with pep_share.
    df = net_mig.merge(
        pep_share, on=["geoid", "geography"], how="inner",
    ).copy()
    if df.empty:
        # No counties had both net_mig rows AND PEP components.
        return pd.DataFrame(columns=NET_MIGRATION_COMPONENTS_COLUMNS)

    # Effective p_dom per cell.
    age_for_tilt = df["age"].astype(int).map(tilt_lookup).fillna(0.0).astype(float)
    p_dom_eff = df["p_dom_county"].astype(float) + age_for_tilt * age_tilt_factor
    lo, hi = p_dom_clip
    p_dom_eff = p_dom_eff.clip(lo, hi)

    m_total = df["m_rate"].astype(float)
    df["m_total_rate"] = m_total.astype("Float64")
    df["m_dom_rate"] = (m_total * p_dom_eff).astype("Float64")
    df["m_int_rate"] = (m_total * (1.0 - p_dom_eff)).astype("Float64")
    df["p_dom_age_effective"] = p_dom_eff.astype("Float64")
    df["source"] = "decompose_net_migration"
    df["vintage"] = f"net_mig+pep+{age_tilt_basis}"
    unstable = df["p_dom_county"].abs() > instability_threshold
    df["notes"] = ""
    df.loc[unstable, "notes"] = (
        "p_dom_unstable: |p_dom_county| > "
        f"{instability_threshold:.1f}; component scenario knobs may produce large net swings"
    )

    return df[NET_MIGRATION_COMPONENTS_COLUMNS].reset_index(drop=True)
