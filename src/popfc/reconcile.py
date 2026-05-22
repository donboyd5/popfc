"""Population-series reconciliation across Census PEP and NYSDOL.

Single source of truth for the rules first prototyped in
`notebooks/01_population_reconciliation.ipynb` and used again in
`notebooks/02_components_audit.ipynb`.

## Public API

- `resolve_pep_vintage(pop_pep)` — collapse overlapping Census PEP vintages
  (e.g., 2020 appears in both the 2010–2020 intercensal file and the 2020+
  postcensal file) by keeping the latest vintage per `(geoid, year, kind)`.
- `reconcile_county_population(pop_pep_resolved, pop_nysdol)` — apply the
  reconciliation rules to produce one authoritative row per `(geoid, year)`.

The rules and rationale are documented in the markdown of Notebook 01.
"""

from __future__ import annotations

from typing import Mapping

import pandas as pd

# Default vintage ranking — later is better. Override by passing
# `vintage_rank` to `resolve_pep_vintage` when a newer vintage is added.
DEFAULT_PEP_VINTAGE_RANK: Mapping[str, int] = {
    "v2010int": 0,
    "v2020": 1,
    "v2024": 2,
}


def resolve_pep_vintage(
    pop_pep: pd.DataFrame,
    vintage_rank: Mapping[str, int] | None = None,
) -> pd.DataFrame:
    """Keep the highest-ranked vintage for each `(geoid, year, kind)`.

    Parameters
    ----------
    pop_pep
        Long-format Census PEP population frame (POP_LONG_COLUMNS schema).
        Must include `geoid`, `year`, `kind`, and `vintage` columns.
    vintage_rank
        Mapping from vintage tag to rank (higher = preferred). Unknown
        vintages get rank -1 (i.e., kept only if nothing else covers the
        row). Defaults to `DEFAULT_PEP_VINTAGE_RANK`.

    Returns
    -------
    DataFrame with the same schema, deduplicated so that each
    `(geoid, year, kind)` triple appears at most once.
    """
    rank_map = vintage_rank if vintage_rank is not None else DEFAULT_PEP_VINTAGE_RANK
    df = pop_pep.copy()
    df["_rank"] = df["vintage"].map(rank_map).fillna(-1)
    idx = df.groupby(["geoid", "year", "kind"])["_rank"].idxmax()
    return df.loc[idx].drop(columns="_rank").reset_index(drop=True)


def reconcile_county_population(
    pop_pep_resolved: pd.DataFrame,
    pop_nysdol: pd.DataFrame,
) -> pd.DataFrame:
    """Apply the Phase-1 reconciliation rules.

    Rules (see Notebook 01 for full rationale):

    1. **Decennial anchors** (2000, 2010, 2020) — NYSDOL "Census Base
       Population" (`kind='census'`). Single curated series across all
       three decennials.
    2. **Postcensal years** (2021+) — Census PEP postcensal estimate,
       latest vintage (caller is expected to have run
       `resolve_pep_vintage` first).
    3. **Intercensal years** (2001–2019 non-decennial) — NYSDOL
       intercensal estimate.

    The output schema matches the input POP_LONG_COLUMNS with one added
    `rule` column documenting *why* each row was chosen.

    Raises
    ------
    AssertionError
        If the rules produce duplicate `(geoid, year)` rows. Catches bugs
        in rule overlap, not data problems.
    """
    decennial = pop_nysdol[
        (pop_nysdol["kind"] == "census")
        & (pop_nysdol["year"].isin([2000, 2010, 2020]))
    ].copy()
    decennial["rule"] = "decennial_census_nysdol"

    postcensal = pop_pep_resolved[
        (pop_pep_resolved["kind"] == "estimate")
        & (pop_pep_resolved["year"] >= 2021)
    ].copy()
    postcensal["rule"] = "postcensal_census_pep"

    intercensal = pop_nysdol[
        (pop_nysdol["kind"] == "intercensal")
        & (pop_nysdol["year"].between(2001, 2019))
        & (~pop_nysdol["year"].isin([2010]))
    ].copy()
    intercensal["rule"] = "intercensal_nysdol"

    chosen = pd.concat([decennial, intercensal, postcensal], ignore_index=True)

    dup = chosen.groupby(["geoid", "year"]).size()
    if (dup > 1).any():
        bad = dup[dup > 1].reset_index()
        raise AssertionError(
            f"Duplicate (geoid, year) after reconcile_county_population:\n{bad}"
        )

    return chosen.sort_values(["geoid", "year"]).reset_index(drop=True)
