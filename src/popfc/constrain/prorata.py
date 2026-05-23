"""Pro-rata constraint to align sub-area projections to a parent total.

Given an array of sub-area populations and a target parent total for a
particular year, multiply every sub-area's age × sex × population by

    k = target_total / sum(sub-area populations)

so that the sums match exactly. Age × sex structure within each sub-area
is preserved; only the level is rescaled.

This is the simplest plausible constraint method. It assumes every age
and sex contributes equally to the level adjustment, which is rarely
exactly true but is defensible for small adjustments. For very large
discrepancies between unconstrained towns and the county target,
iterative proportional fitting (IPF) — which simultaneously matches
county age × sex marginals — would be a refinement. That's
`ipf.py` (not yet built).
"""

from __future__ import annotations

import pandas as pd


def apply_prorata_constraint(
    sub_projections: pd.DataFrame,
    parent_targets: pd.DataFrame,
    *,
    sub_id_col: str = "geoid",
    year_col: str = "year",
    pop_col: str = "population",
    target_pop_col: str = "population",
    scenario_col: str | None = None,
) -> pd.DataFrame:
    """Scale `sub_projections` so the sum per year equals `parent_targets`.

    Parameters
    ----------
    sub_projections
        Long-format DataFrame with at least: `sub_id_col`, `year_col`,
        `pop_col`. Each row is one (sub-area, year, sex, age) cell.
    parent_targets
        DataFrame with one row per `year_col` (and optionally
        `scenario_col`) giving the parent-level target total
        (column `target_pop_col`).
    sub_id_col / year_col / pop_col / target_pop_col / scenario_col
        Column names; defaults are sensible.

    Returns
    -------
    Copy of `sub_projections` with `pop_col` rescaled and an additional
    `constraint_factor` column showing the k applied per year (and
    per scenario, if scenario_col given).
    """
    out = sub_projections.copy()

    # Sum sub-area pops per (year[, scenario])
    group_cols = [year_col]
    if scenario_col and scenario_col in out.columns:
        group_cols.append(scenario_col)
    sub_totals = out.groupby(group_cols)[pop_col].sum().rename("sub_total").reset_index()

    # Align target frame's columns.
    target_group_cols = group_cols.copy()
    if scenario_col and scenario_col not in parent_targets.columns:
        # Single-scenario target — broadcast to whichever scenarios appear.
        # Drop scenario from grouping for the merge, then re-merge.
        target_group_cols.remove(scenario_col)
    targets = parent_targets[target_group_cols + [target_pop_col]].rename(
        columns={target_pop_col: "target_total"}
    )

    merged = sub_totals.merge(targets, on=target_group_cols, how="left")
    if merged["target_total"].isna().any():
        missing = merged[merged["target_total"].isna()][group_cols].drop_duplicates()
        raise ValueError(
            f"apply_prorata_constraint: missing parent targets for:\n{missing.to_string(index=False)}"
        )
    merged["constraint_factor"] = (
        merged["target_total"].astype(float) / merged["sub_total"].astype(float)
    )

    out = out.merge(merged[group_cols + ["constraint_factor"]], on=group_cols, how="left")
    out[pop_col] = out[pop_col].astype(float) * out["constraint_factor"].astype(float)
    return out
