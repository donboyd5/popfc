"""Iterative proportional fitting (IPF) constraint for sub-area populations.

When sub-area (town) projections need to sum to a parent-area (county)
forecast that breaks down by age × sex, *pro-rata* scaling (every cell
multiplied by one factor per town) preserves each town's *shape* but
loses information about the parent's *shape*. IPF iteratively scales
the cross-town cell array until **both** marginals match:

1. The cross-town sum at each (sex, age_band) equals the parent
   forecast at that (sex, age_band). (Column-marginal constraint.)
2. Each town's total population is conserved against its
   pre-constraint total. (Row-marginal constraint, optional.)

For our use case — Hamilton-Perry town projections constrained to a
county cohort-component forecast — we typically use **column-only**
constraints because we want the county's age × sex pyramid to drive
the town pyramids, while the town totals are implied. That collapses
the iteration to a single pass: per (sex, age_band), scale all towns
by ``county_target / cross_town_sum``.

When *both* marginals are constrained, IPF iterates row-scaling and
column-scaling until convergence.

The implementation follows the standard biproportional-fitting algorithm
described in Bishop, Fienberg & Holland (1975), *Discrete Multivariate
Analysis*, ch. 3, with the caveats that:

- Zero rows or columns are passed through unchanged (no division by 0).
- Convergence is declared when the maximum absolute change in any cell
  drops below ``tol`` between iterations. Default ``tol=1e-6``.
- A safety ``max_iter`` (default 200) prevents pathological cases from
  looping forever; if reached, the function returns the partial result
  with ``converged=False`` in the return object.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class IPFResult:
    """Outcome of an IPF run.

    Attributes
    ----------
    adjusted
        Long-format DataFrame matching the input ``seed`` with the
        ``population`` column replaced by the constrained values.
    converged
        True if the iteration converged within ``max_iter``.
    iterations
        Number of iterations actually run.
    max_abs_change
        The final iteration's max absolute change in any cell. Useful
        for inspecting near-convergence cases.
    """
    adjusted: pd.DataFrame
    converged: bool
    iterations: int
    max_abs_change: float


def apply_ipf_constraint(
    seed: pd.DataFrame,
    *,
    column_targets: pd.DataFrame,
    row_targets: pd.DataFrame | None = None,
    sub_id_col: str = "geoid",
    pop_col: str = "population",
    column_dims: tuple[str, ...] = ("sex", "age_band_start"),
    target_pop_col: str = "population",
    tol: float = 1e-6,
    max_iter: int = 200,
) -> IPFResult:
    """Adjust a sub-area cross-classification to match marginal targets.

    Parameters
    ----------
    seed
        Long-format DataFrame of sub-area populations to be adjusted.
        Each row is one (sub_id × column_dim values) cell. The ``pop_col``
        column carries the unconstrained populations.
    column_targets
        DataFrame keyed by ``column_dims`` with a ``target_pop_col``
        column giving the **parent-area** target for each (sex, age_band)
        cell — i.e., what every column should sum to across all sub-areas.
    row_targets
        Optional DataFrame keyed by ``sub_id_col`` with ``target_pop_col``
        giving the per-sub-area target total. If omitted, only the column
        marginal is enforced (single-pass; equivalent to per-column
        proration).
    sub_id_col
        Column in ``seed`` identifying the sub-area (e.g., ``geoid``).
    pop_col
        Column carrying the value to adjust (default ``population``).
    column_dims
        Tuple of columns that together define a "column" cell. For our
        usual case these are ``("sex", "age_band_start")``.
    target_pop_col
        Column carrying the target value in ``column_targets`` and
        ``row_targets``.
    tol
        Convergence tolerance on per-cell absolute change.
    max_iter
        Safety cap on iterations.

    Returns
    -------
    IPFResult with the adjusted long-format frame plus convergence info.
    """
    df = seed.copy()
    df[pop_col] = df[pop_col].astype(float)

    # Pivot to wide for fast vectorized scaling.
    pivot = df.pivot_table(
        index=sub_id_col,
        columns=list(column_dims),
        values=pop_col,
        aggfunc="sum",
        fill_value=0.0,
    )
    sub_ids = pivot.index.tolist()
    col_keys = pivot.columns.tolist()

    # Align column targets to pivot columns.
    ct = column_targets.set_index(list(column_dims))[target_pop_col].astype(float)
    col_targets_aligned = pd.Series(
        [float(ct.get(c, 0.0)) for c in col_keys], index=pivot.columns
    )

    # Align row targets if given.
    if row_targets is not None:
        rt = row_targets.set_index(sub_id_col)[target_pop_col].astype(float)
        row_targets_aligned = pd.Series(
            [float(rt.get(s, 0.0)) for s in sub_ids], index=pivot.index
        )
    else:
        row_targets_aligned = None

    mat = pivot.to_numpy(dtype=float)
    converged = False
    last_max_change = float("inf")

    if row_targets_aligned is None:
        # Single-pass column-only IPF (equivalent to per-column proration).
        col_sums = mat.sum(axis=0)
        # Avoid 0/0: where col_sum == 0 leave the column unchanged.
        scale = np.where(col_sums > 0, col_targets_aligned.to_numpy() / col_sums, 1.0)
        prev = mat.copy()
        mat = mat * scale[np.newaxis, :]
        last_max_change = float(np.max(np.abs(mat - prev)))
        converged = True
        iterations = 1
    else:
        # Biproportional fitting: iterate column- then row-scaling.
        row_targets_np = row_targets_aligned.to_numpy()
        col_targets_np = col_targets_aligned.to_numpy()
        iterations = 0
        for _ in range(max_iter):
            iterations += 1
            prev = mat.copy()
            # Column step.
            col_sums = mat.sum(axis=0)
            col_scale = np.where(col_sums > 0, col_targets_np / col_sums, 1.0)
            mat = mat * col_scale[np.newaxis, :]
            # Row step.
            row_sums = mat.sum(axis=1)
            row_scale = np.where(row_sums > 0, row_targets_np / row_sums, 1.0)
            mat = mat * row_scale[:, np.newaxis]
            last_max_change = float(np.max(np.abs(mat - prev)))
            if last_max_change < tol:
                converged = True
                break

    # Unpivot back to long format.
    adjusted_pivot = pd.DataFrame(mat, index=pivot.index, columns=pivot.columns)
    adjusted_long = (
        adjusted_pivot.stack(list(range(len(column_dims))), future_stack=True)
        .rename(pop_col).reset_index()
    )
    # Merge back any extra columns from the seed (e.g., geography, age_band_end, scenario).
    extra_cols = [
        c for c in seed.columns
        if c not in {sub_id_col, *column_dims, pop_col}
    ]
    if extra_cols:
        # Preserve first-seen extra-col values per (sub_id, *column_dims).
        keep = seed[[sub_id_col, *column_dims, *extra_cols]].drop_duplicates(
            subset=[sub_id_col, *column_dims], keep="first"
        )
        adjusted_long = adjusted_long.merge(
            keep, on=[sub_id_col, *column_dims], how="left"
        )

    return IPFResult(
        adjusted=adjusted_long,
        converged=converged,
        iterations=iterations,
        max_abs_change=last_max_change,
    )
