"""Derive single-year survival rates from period life tables.

Inputs come from `data_interim/life_tables.parquet` (built by Notebook 04),
in the `LIFE_TABLE_COLUMNS` schema. This module emits a parallel schema —
`SURVIVAL_RATES_COLUMNS` — that the Phase-3 cohort-component model consumes
directly.

## Demographic conventions

For a single-year period life table with closed bands at ages 0, 1, 2,
..., ω-1 and an open band at ages ω+ (e.g., ω=100 for NCHS NVSR tables),
we compute three kinds of survival ratios, following Preston / Heuveline
/ Guillot, *Demography* (2001), §6.1:

1. **Closed-band survival** for x = 0, 1, ..., ω-2:

        S(x → x+1) = L(x+1) / L(x)

    The standard "person-years ratio". Gives the per-year survival of a
    person aged x at time t into age x+1 at time t+1.

2. **Open-band combined survival**:

        S(boundary) = L(ω) / [ L(ω-1) + L(ω) ]

    This single rate handles BOTH the inflow from the last closed band
    (ω-1) into the open band AND the retention of those already in the
    open band. Applied to the *sum* of P(ω-1, t) and P(ω, t) to give
    P(ω, t+1). The formula reflects that under stationarity, L(ω)
    person-years above ω are jointly attributable to the cohort flowing
    in from ω-1 and the cohort already at ω+.

    (A naive `L(ω) / L(ω-1)` is **not** a survival probability — it's a
    person-years ratio that can exceed 1, because L(ω) covers many years
    of life while L(ω-1) covers just one. Don't use it directly.)

3. **Birth-to-age-0 survival**:

        S(birth) = L(0) / radix     where radix = l(0), conventionally 100,000

    The fraction of births surviving to age 0 (the next July 1 reference
    date). For 2023 US: L(0) = 99,515 → S = 0.99515.

## Projection identity

Putting the three pieces together, single-year cohort-component projection
of population by single age and sex:

    P(0,    t+1) = B(t)              * S(birth)
    P(x+1,  t+1) = P(x, t)           * S(x → x+1)       for x = 0, ..., ω-2
    P(ω,    t+1) = [P(ω-1, t) + P(ω, t)] * S(boundary)

The cohort-component engine will assemble these into the projection. This
module just produces the survival rates.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

from popfc.data._common import LIFE_TABLE_COLUMNS  # re-exported for callers

# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

SURVIVAL_RATES_COLUMNS: list[str] = [
    "geoid",
    "geography",
    "year_start",
    "year_end",
    "sex",
    "band_type",     # "birth" | "closed" | "boundary"
    "age",           # int. -1 for "birth" rows; x (the FROM age) for "closed";
                     # ω (the open-band start age) for "boundary"
    "Sx",            # nullable Float64 in (0, 1]
    "source",
    "vintage",
    "notes",
]

# Default radix used by NCHS NVSR life tables (and almost every other).
DEFAULT_RADIX = 100_000


# ---------------------------------------------------------------------------
# Scalar / vector building blocks
# ---------------------------------------------------------------------------

def boundary_survival_factor(L_last_closed: float, L_open: float) -> float:
    """Open-band combined survival rate (Preston §6.1).

    Returns L(ω) / [L(ω-1) + L(ω)], to be applied to the SUM of P(ω-1) and
    P(ω) when projecting forward one year. Always in (0, 1).
    """
    if not (np.isfinite(L_last_closed) and np.isfinite(L_open)):
        raise ValueError("boundary_survival_factor: inputs must be finite")
    denom = L_last_closed + L_open
    if denom <= 0:
        raise ValueError("boundary_survival_factor: L_last_closed + L_open must be positive")
    return float(L_open / denom)


def birth_survival_factor(L0: float, radix: float = DEFAULT_RADIX) -> float:
    """Birth-to-age-0 survival ratio L(0) / radix.

    For NCHS NVSR tables radix = l(0) = 100,000.
    """
    if not np.isfinite(L0) or L0 <= 0:
        raise ValueError(f"birth_survival_factor: L0 must be finite-positive, got {L0!r}")
    if radix <= 0:
        raise ValueError(f"birth_survival_factor: radix must be positive, got {radix!r}")
    return float(L0 / radix)


def closed_band_survival(Lx: Sequence[float]) -> np.ndarray:
    """Closed-band survival ratios from a sorted-by-age sequence of Lx values.

    Given Lx of length N (one value per single-year age band, oldest band
    last), returns an array of length N-1 with S(x → x+1) = L(x+1) / L(x).
    The caller treats the last (open) band separately via
    `boundary_survival_factor`.
    """
    arr = np.asarray(Lx, dtype=float)
    if arr.ndim != 1:
        raise ValueError("closed_band_survival: Lx must be 1-D")
    if (arr <= 0).any():
        raise ValueError("closed_band_survival: all Lx must be positive")
    return arr[1:] / arr[:-1]


# ---------------------------------------------------------------------------
# Frame-level builder
# ---------------------------------------------------------------------------

def _single_table_survival(
    lt_sub: pd.DataFrame,
    *,
    radix: float = DEFAULT_RADIX,
) -> pd.DataFrame:
    """Compute survival rates for one (geoid, year, sex) life-table slice."""
    if lt_sub.empty:
        return pd.DataFrame(columns=SURVIVAL_RATES_COLUMNS)

    lt_sub = lt_sub.sort_values("age").reset_index(drop=True)
    is_open = lt_sub["age_band"].astype(str).str.endswith("+")
    if int(is_open.sum()) != 1:
        raise ValueError(
            "_single_table_survival: expected exactly one open band, got "
            f"{int(is_open.sum())} for slice "
            f"geoid={lt_sub['geoid'].iloc[0]!r} sex={lt_sub['sex'].iloc[0]!r}"
        )
    if not bool(is_open.iloc[-1]):
        raise ValueError("_single_table_survival: open band must be the last row after sorting")

    Lx_all = lt_sub["Lx"].astype(float).to_numpy()
    omega = int(lt_sub["age"].iloc[-1])

    # Closed: x = 0, ..., ω-2. Sx[x] = L(x+1)/L(x). That's the first ω-1
    # entries of `closed_band_survival(Lx_all)`. We deliberately do NOT use
    # the last entry of that array (which would be L(ω)/L(ω-1), a person-
    # years ratio rather than a survival probability — see module docstring).
    closed_pairs = closed_band_survival(Lx_all)[:-1]  # length = ω-1
    closed_ages = lt_sub["age"].iloc[:-2].astype(int).to_numpy()  # 0 .. ω-2
    if len(closed_pairs) != len(closed_ages):
        raise AssertionError(
            f"closed-band length mismatch: {len(closed_pairs)} pairs vs "
            f"{len(closed_ages)} ages"
        )

    # Boundary: combined inflow + retention rate for the open band.
    Sx_boundary = boundary_survival_factor(
        L_last_closed=float(Lx_all[-2]),
        L_open=float(Lx_all[-1]),
    )

    # Birth: L(0) / radix.
    L0 = float(lt_sub.loc[lt_sub["age"] == 0, "Lx"].iloc[0])
    Sx_birth = birth_survival_factor(L0, radix=radix)

    meta = {
        "geoid": lt_sub["geoid"].iloc[0],
        "geography": lt_sub["geography"].iloc[0],
        "year_start": int(lt_sub["year_start"].iloc[0]),
        "year_end": int(lt_sub["year_end"].iloc[0]),
        "sex": lt_sub["sex"].iloc[0],
        "source": lt_sub["source"].iloc[0],
        "vintage": lt_sub["vintage"].iloc[0],
    }

    birth_row = pd.DataFrame([{
        **meta,
        "band_type": "birth",
        "age": -1,
        "Sx": Sx_birth,
        "notes": f"L(0)={L0:.2f}, radix={radix:g}",
    }])
    closed_rows = pd.DataFrame({
        **{k: [v] * len(closed_ages) for k, v in meta.items()},
        "band_type": "closed",
        "age": closed_ages,
        "Sx": closed_pairs,
        "notes": "",
    })
    boundary_row = pd.DataFrame([{
        **meta,
        "band_type": "boundary",
        "age": omega,
        "Sx": Sx_boundary,
        "notes": (
            f"L({omega - 1})={Lx_all[-2]:.2f}, L({omega}+)={Lx_all[-1]:.2f}"
        ),
    }])

    out = pd.concat([birth_row, closed_rows, boundary_row], ignore_index=True)
    out["Sx"] = out["Sx"].astype("Float64")
    out["age"] = out["age"].astype(int)
    for col in SURVIVAL_RATES_COLUMNS:
        if col not in out.columns:
            out[col] = None
    return out[SURVIVAL_RATES_COLUMNS]


def survival_rates_from_life_table(
    life_table: pd.DataFrame,
    *,
    radix: float = DEFAULT_RADIX,
    min_rows_per_slice: int = 50,
) -> pd.DataFrame:
    """Compute single-year survival rates from one or more period life tables.

    Splits `life_table` by (geoid, year_start, sex), computes survival
    rates for each slice, and stacks. Slices with fewer than
    `min_rows_per_slice` rows are skipped — they're almost certainly
    abridged (5-year-banded) tables that this single-year code path
    cannot handle.
    """
    required = {"geoid", "year_start", "sex", "age", "age_band", "Lx", "ex"}
    missing = required - set(life_table.columns)
    if missing:
        raise ValueError(
            f"survival_rates_from_life_table: missing required columns {sorted(missing)}"
        )

    frames: list[pd.DataFrame] = []
    for _, sub in life_table.groupby(
        ["geoid", "year_start", "sex"], dropna=False, sort=False
    ):
        if len(sub) < min_rows_per_slice:
            continue
        frames.append(_single_table_survival(sub, radix=radix))
    if not frames:
        return pd.DataFrame(columns=SURVIVAL_RATES_COLUMNS)
    return pd.concat(frames, ignore_index=True).reset_index(drop=True)


def reconstruct_Lx_from_closed_survival(
    survival: pd.DataFrame,
    L0: float | None = None,
    *,
    radix: float = DEFAULT_RADIX,
) -> pd.DataFrame:
    """Round-trip check: rebuild Lx from closed survival rates and L(0).

    Closed survival rates and L(0) uniquely determine the Lx column up to
    age ω-1: L(x+1) = L(x) * Sx_closed(x). The boundary and birth rates
    are not used here.

    If `L0` is None, the function uses `radix * S_birth` (which equals
    L(0) for a standard NCHS table).

    Returns long-format DataFrame with columns
    (geoid, year_start, sex, age, Lx_recon).
    """
    rows = []
    for (geoid, year_start, sex), sub in survival.groupby(
        ["geoid", "year_start", "sex"], dropna=False, sort=False
    ):
        if L0 is None:
            birth = sub[sub["band_type"] == "birth"]
            if birth.empty:
                continue
            Lx = float(birth["Sx"].iloc[0]) * radix
        else:
            Lx = L0
        rows.append({"geoid": geoid, "year_start": year_start, "sex": sex,
                     "age": 0, "Lx_recon": Lx})
        closed = sub[sub["band_type"] == "closed"].sort_values("age")
        for _, r in closed.iterrows():
            Lx = Lx * float(r["Sx"])
            rows.append({"geoid": geoid, "year_start": year_start, "sex": sex,
                         "age": int(r["age"]) + 1, "Lx_recon": Lx})
    return pd.DataFrame(rows)
