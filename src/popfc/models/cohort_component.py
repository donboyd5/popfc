"""Single-year cohort-component population projector.

Consumes the three Phase-3 input frames produced by Notebooks 05–07:

- `survival` — SURVIVAL_RATES_COLUMNS (`popfc.models.mortality`)
- `asfr`     — ASFR_LONG_COLUMNS         (`popfc.models.fertility`)
- `net_mig`  — NET_MIGRATION_RATES_COLUMNS (`popfc.models.migration`)

## Projection identity (single year, per sex)

    P(0,   t+1) = (sex-share of total births) × S(birth)
    P(x+1, t+1) = P(x, t) × (S(x) + m(x))                  for x = 0..ω-2
    P(ω,   t+1) = (P(ω-1, t) + P(ω, t)) × (S_boundary + m_boundary)

with total births = sum_x [ ASFR(x) × P_female(x, t) / 1000 ] over ages
10..49, split into male/female via the sex ratio at birth (default 1.05).

Net migration appears additively to survival per the convention in
`popfc.models.migration`. Conceptually it's an "absorption rate":
positive means more arrivals than would be expected from survival
alone; negative means the opposite.

## Scenarios

The simplest scenario API exposes two scalar multipliers:

- `asfr_multiplier` — uniform multiplier on ASFR (e.g., 0.85 for "low
  fertility", 1.15 for "high")
- `net_mig_multiplier` — uniform multiplier on net-migration rates
  (closed bands and boundary alike)

More expressive scenarios (age-specific overrides, time-varying paths)
are out of scope for v1.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from popfc.models.fertility import (
    REPRO_AGE_MAX,
    REPRO_AGE_MIN,
    SEX_RATIO_AT_BIRTH,
    SHARE_MALE_AT_BIRTH,
)

# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

PROJECTION_COLUMNS: list[str] = [
    "geoid",
    "geography",
    "year",
    "sex",                  # "M" | "F" (the projector tracks each sex separately)
    "age",                  # int, 0..top_code_age (top inclusive = open band)
    "population",           # Float64 — we keep fractional values; round for display
    "scenario",             # e.g., "baseline" | "low_fertility" | "high_migration"
    "projection_vintage",   # tag describing inputs used
]


# ---------------------------------------------------------------------------
# Input-frame helpers
# ---------------------------------------------------------------------------

@dataclass
class _CompiledRates:
    """Arrays indexed by source age (closed) plus scalar open-band rates."""
    top_code_age: int
    # Per-sex closed-band arrays (length = top_code_age - 1, i.e., source ages 0..ω-2)
    Sx_closed: dict[str, np.ndarray]
    m_closed: dict[str, np.ndarray]
    # Per-sex scalars for the open-band boundary
    Sx_boundary: dict[str, float]
    m_boundary: dict[str, float]
    # Per-sex birth-survival scalar (S_birth, applied to that sex's share of births)
    Sx_birth: dict[str, float]
    # Single-year ASFR array indexed by mother's age (REPRO_AGE_MIN..REPRO_AGE_MAX)
    asfr_per_1000: np.ndarray
    srb: float


def _compile_inputs(
    survival: pd.DataFrame,
    asfr: pd.DataFrame,
    net_mig: pd.DataFrame,
    *,
    survival_geoid: str,
    net_mig_geoid: str,
    top_code_age: int,
    srb: float,
    asfr_multiplier: float,
    net_mig_multiplier: float,
) -> _CompiledRates:
    """Turn the three input frames into fast lookup arrays."""
    # Survival arrays per sex.
    Sx_closed: dict[str, np.ndarray] = {}
    Sx_boundary: dict[str, float] = {}
    Sx_birth: dict[str, float] = {}
    surv_sub = survival[survival["geoid"] == survival_geoid]
    if surv_sub.empty:
        raise ValueError(
            f"_compile_inputs: no survival rows for geoid={survival_geoid!r}"
        )
    for sex in ("M", "F"):
        s_sex = surv_sub[surv_sub["sex"] == sex]
        if s_sex.empty:
            raise ValueError(
                f"_compile_inputs: missing survival for sex={sex!r}, "
                f"survival_geoid={survival_geoid!r}"
            )
        closed = (
            s_sex[s_sex["band_type"] == "closed"]
            .set_index("age")["Sx"].astype(float).sort_index()
        )
        # Sanity: closed source ages must cover 0..top_code_age-2.
        expected = set(range(0, top_code_age - 1))
        if set(closed.index) != expected:
            raise ValueError(
                f"_compile_inputs: closed survival ages {sorted(closed.index)} "
                f"don't match expected {sorted(expected)} for top_code_age={top_code_age}"
            )
        Sx_closed[sex] = closed.reindex(range(0, top_code_age - 1)).to_numpy()
        b = s_sex[s_sex["band_type"] == "boundary"]
        if b.empty or int(b["age"].iloc[0]) != top_code_age:
            raise ValueError(
                f"_compile_inputs: missing or misaligned boundary survival "
                f"for sex={sex!r} (expected age={top_code_age})"
            )
        Sx_boundary[sex] = float(b["Sx"].iloc[0])
        birth_rows = s_sex[s_sex["band_type"] == "birth"]
        if birth_rows.empty:
            raise ValueError(f"_compile_inputs: missing birth survival for sex={sex!r}")
        Sx_birth[sex] = float(birth_rows["Sx"].iloc[0])

    # Net migration arrays per sex.
    m_closed: dict[str, np.ndarray] = {}
    m_boundary: dict[str, float] = {}
    nm_sub = net_mig[net_mig["geoid"] == net_mig_geoid]
    if nm_sub.empty:
        raise ValueError(
            f"_compile_inputs: no net_migration rows for geoid={net_mig_geoid!r}"
        )
    for sex in ("M", "F"):
        m_sex = nm_sub[nm_sub["sex"] == sex]
        if m_sex.empty:
            raise ValueError(
                f"_compile_inputs: missing net_mig for sex={sex!r}, "
                f"net_mig_geoid={net_mig_geoid!r}"
            )
        closed_rows = m_sex[m_sex["band_type"] == "closed"]
        closed = (
            closed_rows.set_index("source_age")["m_rate"].astype(float).sort_index()
        )
        # Fill any missing source-age rates with 0 (the engine has to do
        # something — a noisy outlier county-year might miss a few cells).
        full = closed.reindex(range(0, top_code_age - 1)).fillna(0.0)
        m_closed[sex] = full.to_numpy() * net_mig_multiplier
        b = m_sex[m_sex["band_type"] == "boundary"]
        m_boundary[sex] = (
            float(b["m_rate"].iloc[0]) * net_mig_multiplier if not b.empty else 0.0
        )

    # ASFR array indexed by mother's age REPRO_AGE_MIN..REPRO_AGE_MAX.
    asfr_grouped = (
        asfr.set_index("age")["asfr_per_1000"].astype(float).sort_index()
    )
    asfr_full = (
        asfr_grouped.reindex(range(REPRO_AGE_MIN, REPRO_AGE_MAX + 1))
        .fillna(0.0)
        .to_numpy()
        * asfr_multiplier
    )

    return _CompiledRates(
        top_code_age=top_code_age,
        Sx_closed=Sx_closed,
        m_closed=m_closed,
        Sx_boundary=Sx_boundary,
        m_boundary=m_boundary,
        Sx_birth=Sx_birth,
        asfr_per_1000=asfr_full,
        srb=srb,
    )


def _pop_arrays_from_frame(
    base_pop: pd.DataFrame,
    top_code_age: int,
) -> dict[str, np.ndarray]:
    """Convert a base-population long-format frame to per-sex 1-D arrays.

    The arrays have length `top_code_age + 1` so index 0..top_code_age are
    valid; index `top_code_age` is the open band.
    """
    arrays: dict[str, np.ndarray] = {}
    for sex in ("M", "F"):
        sub = base_pop[base_pop["sex"] == sex]
        if sub.empty:
            raise ValueError(f"_pop_arrays_from_frame: no rows for sex={sex!r}")
        arr = np.zeros(top_code_age + 1, dtype=float)
        for _, row in sub.iterrows():
            age = int(row["age"])
            if age < 0 or age > top_code_age:
                continue
            arr[age] = float(row["population"])
        arrays[sex] = arr
    return arrays


# ---------------------------------------------------------------------------
# Single-year step
# ---------------------------------------------------------------------------

def step_one_year(
    P: dict[str, np.ndarray],
    rates: _CompiledRates,
) -> tuple[dict[str, np.ndarray], float]:
    """Project one year forward. Returns (new P arrays, total births)."""
    omega = rates.top_code_age

    # 1. Total births from female population × ASFR.
    F_pop = P["F"]
    # ASFR indexes mother's age REPRO_AGE_MIN..REPRO_AGE_MAX. Clip the
    # multiplication to the overlapping age range (in the unlikely event
    # ω < REPRO_AGE_MAX, e.g., synthetic tests with tiny top codes).
    max_repro = min(REPRO_AGE_MAX, len(F_pop) - 1)
    if max_repro < REPRO_AGE_MIN:
        total_births = 0.0
    else:
        n_ages = max_repro - REPRO_AGE_MIN + 1
        F_repro = F_pop[REPRO_AGE_MIN: max_repro + 1]
        asfr_clip = rates.asfr_per_1000[:n_ages]
        total_births = float((F_repro * asfr_clip / 1000.0).sum())
    share_male = rates.srb / (1.0 + rates.srb)
    sex_births = {"M": total_births * share_male, "F": total_births * (1.0 - share_male)}

    # 2. Project each sex.
    P_new: dict[str, np.ndarray] = {}
    for sex in ("M", "F"):
        old = P[sex]
        new = np.zeros_like(old)
        # Closed transitions: x = 0..ω-2
        # new[x+1] = old[x] * (S(x) + m(x))
        survival_plus_mig = rates.Sx_closed[sex] + rates.m_closed[sex]  # length ω-1
        new[1: omega] = old[: omega - 1] * survival_plus_mig
        # Boundary: combined retention + inflow rate
        new[omega] = (old[omega - 1] + old[omega]) * (
            rates.Sx_boundary[sex] + rates.m_boundary[sex]
        )
        # Age 0: sex's share of births, surviving to first July 1.
        new[0] = sex_births[sex] * rates.Sx_birth[sex]
        P_new[sex] = new

    return P_new, total_births


# ---------------------------------------------------------------------------
# Multi-year projection
# ---------------------------------------------------------------------------

def project_one_county(
    base_pop: pd.DataFrame,
    base_year: int,
    end_year: int,
    *,
    survival: pd.DataFrame,
    asfr: pd.DataFrame,
    net_mig: pd.DataFrame,
    geoid: str,
    geography: str | None = None,
    survival_geoid: str = "36000",
    net_mig_geoid: str | None = None,
    srb: float = SEX_RATIO_AT_BIRTH,
    top_code_age: int = 85,
    asfr_multiplier: float = 1.0,
    net_mig_multiplier: float = 1.0,
    scenario: str = "baseline",
    projection_vintage: str | None = None,
) -> pd.DataFrame:
    """Project one county's population from base_year to end_year (inclusive).

    Returns a long-format DataFrame conforming to PROJECTION_COLUMNS, with
    one row per (year, sex, age) including the base year.
    """
    if end_year < base_year:
        raise ValueError(f"end_year ({end_year}) must be >= base_year ({base_year})")
    if net_mig_geoid is None:
        net_mig_geoid = geoid
    if projection_vintage is None:
        projection_vintage = f"engine_v1_asfr_x{asfr_multiplier}_netmig_x{net_mig_multiplier}"

    rates = _compile_inputs(
        survival, asfr, net_mig,
        survival_geoid=survival_geoid,
        net_mig_geoid=net_mig_geoid,
        top_code_age=top_code_age,
        srb=srb,
        asfr_multiplier=asfr_multiplier,
        net_mig_multiplier=net_mig_multiplier,
    )

    if geography is None:
        # Try to recover from the base-pop frame.
        gcand = base_pop["geography"].dropna().unique() if "geography" in base_pop.columns else []
        geography = str(gcand[0]) if len(gcand) else geoid

    P = _pop_arrays_from_frame(base_pop, top_code_age=top_code_age)

    rows: list[pd.DataFrame] = []

    def emit(year: int, P_now: dict[str, np.ndarray]):
        for sex in ("M", "F"):
            df = pd.DataFrame({
                "geoid": geoid,
                "geography": geography,
                "year": int(year),
                "sex": sex,
                "age": np.arange(0, top_code_age + 1),
                "population": P_now[sex],
                "scenario": scenario,
                "projection_vintage": projection_vintage,
            })
            rows.append(df)

    # Emit base year.
    emit(base_year, P)
    for year in range(base_year + 1, end_year + 1):
        P, _births = step_one_year(P, rates)
        emit(year, P)

    out = pd.concat(rows, ignore_index=True)
    out["population"] = out["population"].astype("Float64")
    return out[PROJECTION_COLUMNS]
