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
