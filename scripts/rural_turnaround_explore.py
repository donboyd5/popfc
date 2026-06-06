"""Rural NY town turnaround exploration.

GOAL: find rural NY towns (MCDs) that show a trough-and-recovery pattern in
population — declined to a low point, then grew for the most recent observations,
recovering a meaningful share of lost population — and characterize commonalities.

DATA REALITY (verified, see report): the repo has NO multi-decade town-level
population series. The decennial-era raw files (1970-1980, 1980-1990) are
COUNTY-level only. The only town-level history available is:

  * ACS 5-year midpoint totals, 2007-2022 (gap at the 2020 midpoint vintage),
    from data_interim/town_total_pop_history.parquet (kind == 'acs5_midpoint')
  * PEP annual sub-county estimates 2020-2025 (kind == 'estimate')

So "turnaround" is operationalized WITHIN this ~18-year window (2007-2025) as a
trough-and-recovery, not a multi-decade reversal. This is a real limitation and
is stated plainly in the report.

We stitch the two series into one annual-ish trajectory per MCD, deduplicating
overlapping years (prefer PEP for 2020+, ACS for earlier). Component drivers
(births/deaths/migration) only exist at the COUNTY level in
county_components.parquet; there is no town-level vital-statistics file. We
therefore characterize the *county* migration context of each turnaround town
rather than claiming a town-level decomposition.

Run:  .venv/bin/python scripts/rural_turnaround_explore.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from popfc.paths import DATA_INTERIM  # noqa: E402

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 60)
pd.set_option("display.max_colwidth", 40)

# ---- tunables ---------------------------------------------------------------
RURAL_MAX_POP = 5_000      # upper bound on recent pop to count as "rural/small town"
MIN_POP = 500              # lower bound: below this, ACS sampling noise dominates
RECOVERY_MIN_PCT = 25.0    # must recover >= this % of peak->trough loss to qualify
TROUGH_DROP_MIN_PCT = 2.0  # peak->trough decline must be at least this big to be a real decline
RECENT_GROWTH_YEARS = 2    # require growth across at least the last N observation steps

# NY metro / NYC / Long Island counties to EXCLUDE from "rural".
# NYC (5 boroughs) + Long Island (Nassau, Suffolk) + Westchester/Rockland (dense
# downstate suburbs). FIPS are the 3-digit county codes within state 36.
EXCLUDE_COUNTY_FIPS = {
    "005", "047", "061", "081", "085",  # Bronx, Kings, NY, Queens, Richmond (NYC)
    "059", "103",                        # Nassau, Suffolk (Long Island)
    "119", "087",                        # Westchester, Rockland (dense downstate)
}

# County FIPS -> county name (NY), for human-readable output.
COUNTY_NAMES = {
    "001": "Albany", "003": "Allegany", "005": "Bronx", "007": "Broome",
    "009": "Cattaraugus", "011": "Cayuga", "013": "Chautauqua", "015": "Chemung",
    "017": "Chenango", "019": "Clinton", "021": "Columbia", "023": "Cortland",
    "025": "Delaware", "027": "Dutchess", "029": "Erie", "031": "Essex",
    "033": "Franklin", "035": "Fulton", "037": "Genesee", "039": "Greene",
    "041": "Hamilton", "043": "Herkimer", "045": "Jefferson", "047": "Kings",
    "049": "Lewis", "051": "Livingston", "053": "Madison", "055": "Monroe",
    "057": "Montgomery", "059": "Nassau", "061": "New York", "063": "Niagara",
    "065": "Oneida", "067": "Onondaga", "069": "Ontario", "071": "Orange",
    "073": "Orleans", "075": "Oswego", "077": "Otsego", "079": "Putnam",
    "081": "Queens", "083": "Rensselaer", "085": "Richmond", "087": "Rockland",
    "089": "St. Lawrence", "091": "Saratoga", "093": "Schenectady",
    "095": "Schoharie", "097": "Schuyler", "099": "Seneca", "101": "Steuben",
    "103": "Suffolk", "105": "Sullivan", "107": "Tioga", "109": "Tompkins",
    "111": "Ulster", "113": "Warren", "115": "Washington", "117": "Wayne",
    "119": "Westchester", "121": "Wyoming", "123": "Yates",
}


def shorten_name(geog: str) -> str:
    """'Cambridge town, Washington County, New York' -> 'Cambridge town'."""
    return geog.split(",")[0].strip() if isinstance(geog, str) else geog


def build_town_series() -> pd.DataFrame:
    """One stitched annual-ish population trajectory per MCD, with provenance.

    Prefer PEP for 2020+, ACS midpoint for earlier years; dedupe overlaps.
    """
    t = pd.read_parquet(DATA_INTERIM / "town_total_pop_history.parquet")
    t = t.copy()
    t["geoid"] = t["geoid"].astype(str)
    t["county_fips"] = t["geoid"].str[2:5]
    # keep only county subdivisions (towns); drop the few 'city' SUMLEV-style rows
    t["short"] = t["geography"].map(shorten_name)
    is_town = t["short"].str.contains(" town", na=False)
    towns = t[is_town].copy()

    # priority: PEP (estimate) over ACS for the same (geoid, year)
    towns["prio"] = np.where(towns["kind"] == "estimate", 0, 1)
    towns = towns.sort_values(["geoid", "year", "prio"])
    towns = towns.drop_duplicates(["geoid", "year"], keep="first")
    towns["population"] = towns["population"].astype("Int64")
    return towns[
        ["geoid", "county_fips", "geography", "short", "year", "population", "kind"]
    ].reset_index(drop=True)


def per_town_trajectory_stats(towns: pd.DataFrame) -> pd.DataFrame:
    """Vectorized peak / trough / recent stats per MCD over its full series."""
    g = towns.dropna(subset=["population"]).copy()
    g = g.sort_values(["geoid", "year"])

    # earliest / latest observation
    first = g.groupby("geoid").first().rename(
        columns={"year": "first_year", "population": "first_pop"}
    )[["first_year", "first_pop", "county_fips", "geography", "short"]]
    last = g.groupby("geoid").agg(
        last_year=("year", "last"),
        last_pop=("population", "last"),
        n_obs=("year", "size"),
    )

    # peak = max pop and its (earliest) year; trough = min pop AFTER the peak year.
    idx_peak = g.groupby("geoid")["population"].idxmax()
    peak = g.loc[idx_peak, ["geoid", "year", "population"]].rename(
        columns={"year": "peak_year", "population": "peak_pop"}
    ).set_index("geoid")

    # trough strictly at/after peak_year (so we capture decline-then-recovery)
    gm = g.merge(peak["peak_year"], on="geoid", how="left")
    after_peak = gm[gm["year"] >= gm["peak_year"]]
    idx_trough = after_peak.groupby("geoid")["population"].idxmin()
    trough = after_peak.loc[idx_trough, ["geoid", "year", "population"]].rename(
        columns={"year": "trough_year", "population": "trough_pop"}
    ).set_index("geoid")

    stats = (
        first.join(last).join(peak[["peak_year", "peak_pop"]]).join(trough)
    )

    # recovery since trough
    stats["loss_peak_to_trough"] = stats["peak_pop"] - stats["trough_pop"]
    stats["gain_trough_to_last"] = stats["last_pop"] - stats["trough_pop"]
    stats["pct_decline_peak_trough"] = (
        100.0 * stats["loss_peak_to_trough"] / stats["peak_pop"]
    )
    stats["pct_recovered"] = np.where(
        stats["loss_peak_to_trough"] > 0,
        100.0 * stats["gain_trough_to_last"] / stats["loss_peak_to_trough"],
        np.nan,
    )

    # "recent growth across last N steps": compare last_pop to pop N obs earlier
    def recent_growth_flag(geoid_grp: pd.DataFrame) -> bool:
        vals = geoid_grp["population"].astype(float).to_numpy()
        if len(vals) < RECENT_GROWTH_YEARS + 1:
            return False
        tail = vals[-(RECENT_GROWTH_YEARS + 1):]
        return bool(np.all(np.diff(tail) > 0))

    rg = g.groupby("geoid").apply(recent_growth_flag, include_groups=False)
    stats["recent_growth"] = stats.index.map(rg).fillna(False).astype(bool)

    stats["county_name"] = stats["county_fips"].map(COUNTY_NAMES)
    return stats.reset_index()


def flag_turnarounds(stats: pd.DataFrame) -> pd.DataFrame:
    s = stats.copy()
    rural = (
        (~s["county_fips"].isin(EXCLUDE_COUNTY_FIPS))
        & (s["last_pop"] <= RURAL_MAX_POP)
        & (s["last_pop"] >= MIN_POP)
    )
    declined = s["pct_decline_peak_trough"] >= TROUGH_DROP_MIN_PCT
    trough_not_at_end = s["trough_year"] < s["last_year"]
    recovered = s["pct_recovered"] >= RECOVERY_MIN_PCT
    grew_recent = s["recent_growth"]

    s["is_rural"] = rural
    s["turnaround"] = rural & declined & trough_not_at_end & recovered & grew_recent
    return s


# Coarse NY region/amenity tags by county FIPS (general geographic knowledge,
# not derived from in-repo data). Used only to look for commonalities.
ADIRONDACK = {"031", "041", "033", "019", "089", "035", "043", "045", "049"}  # Adk park / North Country
CATSKILLS = {"025", "095", "105", "039", "111"}                                # Catskills / western Hudson
HUDSON_VALLEY = {"021", "027", "071", "079", "111", "039"}                     # Mid-Hudson
FINGER_LAKES = {"123", "099", "097", "069", "109", "051", "011", "117"}        # Finger Lakes
CAPITAL_REGION = {"001", "083", "091", "093", "115", "095", "057"}             # Albany metro orbit
COLLEGE_TOWN_COUNTY = {"109", "007", "055", "067", "001", "083", "049"}        # has a major college nearby


def region_tags(county_fips: str) -> str:
    tags = []
    if county_fips in ADIRONDACK:
        tags.append("Adirondacks/North Country")
    if county_fips in CATSKILLS:
        tags.append("Catskills")
    if county_fips in HUDSON_VALLEY:
        tags.append("Hudson Valley")
    if county_fips in FINGER_LAKES:
        tags.append("Finger Lakes")
    if county_fips in CAPITAL_REGION:
        tags.append("Capital Region orbit")
    return "; ".join(tags) if tags else "other upstate"


def county_migration_context() -> pd.DataFrame:
    """County-level cumulative components 2011-latest, since town components don't exist."""
    comp = pd.read_parquet(DATA_INTERIM / "county_components.parquet")
    comp = comp[comp["source"] == "census_pep"].copy()
    keep = ["births", "deaths", "domestic_mig", "international_mig",
            "natural_change", "net_mig"]
    comp = comp[comp["measure"].isin(keep)]
    comp["county_fips"] = comp["geoid"].astype(str).str[2:5]
    wide = (
        comp.groupby(["county_fips", "measure"])["value"].sum()
            .unstack("measure")
    )
    if "net_mig" not in wide and {"domestic_mig", "international_mig"} <= set(wide.columns):
        wide["net_mig"] = wide["domestic_mig"].fillna(0) + wide["international_mig"].fillna(0)
    if "natural_change" not in wide and {"births", "deaths"} <= set(wide.columns):
        wide["natural_change"] = wide["births"].fillna(0) - wide["deaths"].fillna(0)
    return wide.reset_index()


def main() -> None:
    towns = build_town_series()
    print("=" * 90)
    print("DATA INVENTORY")
    print("=" * 90)
    yr_by_kind = towns.groupby("kind")["year"].agg(["min", "max", "nunique"])
    print("Town-level series, by source kind (years):")
    print(yr_by_kind.to_string())
    print(f"\nDistinct NY towns (MCDs) in stitched series: {towns['geoid'].nunique():,}")
    print(f"Full year span: {int(towns['year'].min())}-{int(towns['year'].max())}")
    print("Years present:", sorted(towns["year"].unique().tolist()))

    stats = per_town_trajectory_stats(towns)
    flagged = flag_turnarounds(stats)

    rural_n = int(flagged["is_rural"].sum())
    ta = flagged[flagged["turnaround"]].copy()
    print("\n" + "=" * 90)
    print("RURAL UNIVERSE & TURNAROUND FLAGGING")
    print("=" * 90)
    print(f"Rural towns (excl NYC/LI/dense-downstate; {MIN_POP}<=last_pop<={RURAL_MAX_POP}): {rural_n:,}")
    print(f"Flagged turnarounds (peak->trough decline >= {TROUGH_DROP_MIN_PCT}%, "
          f"recovered >= {RECOVERY_MIN_PCT}% of loss, growth in last "
          f"{RECENT_GROWTH_YEARS} steps): {len(ta):,}")

    ta["region"] = ta["county_fips"].map(region_tags)
    # rank by pct_recovered then by absolute gain
    ta = ta.sort_values(["pct_recovered", "gain_trough_to_last"], ascending=False)
    cols = ["geoid", "short", "county_name", "first_year", "first_pop",
            "peak_year", "peak_pop", "trough_year", "trough_pop",
            "last_year", "last_pop", "pct_decline_peak_trough",
            "pct_recovered", "n_obs"]
    disp = ta[cols].copy()
    for c in ["pct_decline_peak_trough", "pct_recovered"]:
        disp[c] = disp[c].round(1)
    print("\nRANKED TURNAROUND TOWNS:")
    print(disp.to_string(index=False))

    # Core set: real declines only (>= 10% peak->trough) AND >= 50% recovered.
    core = ta[(ta["pct_decline_peak_trough"] >= 10.0) & (ta["pct_recovered"] >= 50.0)]
    print("\n--- CORE turnarounds (>=10% decline AND >=50% recovered) ---")
    print(core[["short", "county_name", "region", "peak_pop", "trough_pop",
                "last_pop", "pct_decline_peak_trough", "pct_recovered"]]
          .round(1).to_string(index=False))

    print("\n--- Region tally across ALL flagged turnarounds ---")
    print(ta["region"].value_counts().to_string())

    # county migration context for the turnaround set
    mig = county_migration_context()
    ta_cty = (
        ta[["county_fips", "county_name"]]
        .drop_duplicates()
        .merge(mig, on="county_fips", how="left")
        .sort_values("county_name")
    )
    print("\n" + "=" * 90)
    print("COUNTY MIGRATION CONTEXT for turnaround towns (cumulative PEP components)")
    print("(town-level component split does NOT exist in repo; this is the county each town sits in)")
    print("=" * 90)
    show = [c for c in ["county_name", "natural_change", "domestic_mig",
                        "international_mig", "net_mig"] if c in ta_cty.columns]
    cty_disp = ta_cty[show].copy()
    for c in show[1:]:
        cty_disp[c] = cty_disp[c].round(0).astype("Int64")
    print(cty_disp.to_string(index=False))

    # sensitivity: vary recovery threshold
    print("\n" + "=" * 90)
    print("SENSITIVITY to RECOVERY_MIN_PCT (others held)")
    print("=" * 90)
    base = flagged[
        (~flagged["county_fips"].isin(EXCLUDE_COUNTY_FIPS))
        & (flagged["last_pop"].between(MIN_POP, RURAL_MAX_POP))
        & (flagged["pct_decline_peak_trough"] >= TROUGH_DROP_MIN_PCT)
        & (flagged["trough_year"] < flagged["last_year"])
        & (flagged["recent_growth"])
    ]
    for thr in [10, 25, 50, 75, 100]:
        n = int((base["pct_recovered"] >= thr).sum())
        print(f"  recovery >= {thr:3d}% of peak->trough loss : {n:3d} towns")

    # write the ranked table to /tmp for the report
    out = ta[cols + ["county_fips"]].copy()
    out.to_csv("/tmp/rural_turnaround_ranked.csv", index=False)
    flagged.to_csv("/tmp/rural_turnaround_allstats.csv", index=False)
    print("\nWrote /tmp/rural_turnaround_ranked.csv and /tmp/rural_turnaround_allstats.csv")


if __name__ == "__main__":
    main()
