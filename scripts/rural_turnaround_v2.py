"""Rural NY turnaround analysis v2 — built on decennial census anchors.

v1 (scripts/rural_turnaround_explore.py) used the 2007-2025 ACS/PEP stitch,
whose 2019/2020 methodology seam made troughs/peaks hard to trust. This version
uses HARD CENSUS COUNTS at 2000/2010/2020 (from subcounty_decennial_history.parquet)
as the backbone, optionally extended to 2025 with PEP annual estimates, so a
"turnaround" reflects a real multi-decade decline-then-rebound rather than
estimation noise.

Two analyses:
  A. Towns (county subdivisions): 2000/2010/2020 census + 2025 PEP -> turnaround.
  B. Villages (places): 2000/2010/2020 census only (V-shape) -> turnaround.

Writes ranked CSVs to /tmp and prints summaries.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from popfc.paths import DATA_INTERIM  # noqa: E402

# NYC + Long Island + dense downstate -> excluded from "rural".
EXCLUDE_COUNTIES = {
    "005", "047", "061", "081", "085",  # NYC
    "059", "103",                        # Nassau, Suffolk
    "119", "087",                        # Westchester, Rockland
}

# Hand-coded amenity/region tags by NY county FIPS (coarse; for commonality
# narrative only, NOT derived from repo data).
REGION = {
    # Adirondacks / North Country
    "019": "Adirondacks", "031": "Adirondacks", "033": "Adirondacks",
    "041": "Adirondacks", "043": "Adirondacks", "049": "Adirondacks",
    "089": "Adirondacks", "113": "Adirondacks",
    # Catskills
    "025": "Catskills", "039": "Catskills", "105": "Catskills", "111": "Catskills",
    # Finger Lakes
    "011": "Finger Lakes", "051": "Finger Lakes", "069": "Finger Lakes",
    "097": "Finger Lakes", "099": "Finger Lakes", "123": "Finger Lakes",
    # Hudson Valley (rural / second-home)
    "021": "Hudson Valley", "027": "Hudson Valley", "079": "Hudson Valley",
    # Capital Region orbit
    "001": "Capital orbit", "083": "Capital orbit", "091": "Capital orbit",
    "093": "Capital orbit", "115": "Capital orbit",
    # Leatherstocking / college towns
    "053": "Leatherstocking", "077": "Leatherstocking",
    # Great Lakes / Thousand Islands
    "013": "Great Lakes", "045": "Great Lakes", "075": "Great Lakes",
}


def _short_name(s: pd.Series) -> pd.Series:
    return s.str.split(",").str[0].str.strip()


def load_town_backbone() -> pd.DataFrame:
    dec = pd.read_parquet(DATA_INTERIM / "subcounty_decennial_history.parquet")
    towns = dec[dec["geo_level"] == "cousub"].copy()
    # Wide on census years.
    wide = towns.pivot_table(
        index=["geoid", "county_fips"], columns="year",
        values="population", aggfunc="first"
    ).rename(columns={2000: "c2000", 2010: "c2010", 2020: "c2020"})
    names = (towns.sort_values("year").groupby("geoid")["geography"]
             .first().map(lambda s: s.split(",")[0].strip()))
    wide = wide.reset_index().merge(names.rename("name"), on="geoid")

    # Latest PEP point (2025) from the existing annual history.
    hist = pd.read_parquet(DATA_INTERIM / "town_total_pop_history.parquet")
    pep = hist[hist["source"] == "census_pep"].copy()
    p25 = (pep[pep["year"] == 2025].drop_duplicates("geoid")
           .set_index("geoid")["population"].rename("p2025"))
    wide = wide.merge(p25, on="geoid", how="left")
    return wide


def classify_towns(wide: pd.DataFrame) -> pd.DataFrame:
    df = wide.copy()
    df = df[~df["county_fips"].isin(EXCLUDE_COUNTIES)]
    # Rural-ish size band on the 2020 census count.
    df = df[df["c2020"].between(500, 8000)]

    pts = ["c2000", "c2010", "c2020"]
    df = df.dropna(subset=pts)
    # Trough among CENSUS points (avoid letting noisy PEP define the trough).
    df["trough_pop"] = df[pts].min(axis=1)
    df["trough_year"] = df[pts].idxmin(axis=1).map(
        {"c2000": 2000, "c2010": 2010, "c2020": 2020})
    df["peak_pop"] = df[pts].max(axis=1)
    df["peak_year"] = df[pts].idxmax(axis=1).map(
        {"c2000": 2000, "c2010": 2010, "c2020": 2020})
    # Latest available point (prefer 2025 PEP, else 2020 census).
    df["latest"] = df["p2025"].fillna(df["c2020"])
    df["latest_year"] = df["p2025"].notna().map({True: 2025, False: 2020})

    decline = df["peak_pop"] - df["trough_pop"]
    recovery = df["latest"] - df["trough_pop"]
    df["pct_decline"] = 100.0 * decline / df["peak_pop"]
    df["pct_recovered"] = 100.0 * recovery / decline.where(decline > 0)

    # Turnaround: peak precedes trough, declined into an interior/recent trough,
    # then recovered meaningfully and is at/above its 2020 level.
    is_turn = (
        (df["peak_year"] < df["trough_year"])
        & (df["trough_year"].isin([2010, 2020]))
        & (df["pct_decline"] >= 5.0)
        & (df["pct_recovered"] >= 25.0)
        & (df["latest"] >= df["c2020"])
    )
    df["turnaround"] = is_turn
    df["region"] = df["county_fips"].map(REGION).fillna("other upstate")
    return df


def _place_county_map() -> pd.Series:
    """geoid (state+place) -> primary county_fips, from sub-est SUMLEV 157."""
    from popfc.paths import CENSUS_DIR
    se = pd.read_csv(CENSUS_DIR / "2020-plus" / "sub-est2025.csv",
                     dtype=str, encoding_errors="replace")
    se = se[(se["STATE"] == "36") & (se["SUMLEV"] == "157")].copy()
    se["pop"] = pd.to_numeric(se["POPESTIMATE2025"], errors="coerce")
    prim = se.sort_values("pop").groupby("PLACE").tail(1)
    prim["geoid"] = "36" + prim["PLACE"].str.zfill(5)
    return prim.set_index("geoid")["COUNTY"].str.zfill(3)


def classify_villages(rural_only: bool = True) -> pd.DataFrame:
    dec = pd.read_parquet(DATA_INTERIM / "subcounty_decennial_history.parquet")
    vil = dec[(dec["geo_level"] == "place") & (dec["geo_kind"] == "village")].copy()
    wide = vil.pivot_table(index="geoid", columns="year",
                           values="population", aggfunc="first").rename(
        columns={2000: "c2000", 2010: "c2010", 2020: "c2020"})
    names = vil.groupby("geoid")["geography"].first().map(
        lambda s: s.split(",")[0].strip())
    df = wide.reset_index().merge(names.rename("name"), on="geoid")
    df["county_fips"] = df["geoid"].map(_place_county_map())
    df["region"] = df["county_fips"].map(REGION).fillna("other upstate")
    if rural_only:
        df = df[~df["county_fips"].isin(EXCLUDE_COUNTIES)]
    df = df.dropna(subset=["c2000", "c2010", "c2020"])
    df = df[df["c2020"].between(200, 8000)]
    # V-shape: declined 2000->2010, rebounded 2010->2020.
    df["pct_decline"] = 100.0 * (df["c2000"] - df["c2010"]) / df["c2000"]
    df["pct_rebound"] = 100.0 * (df["c2020"] - df["c2010"]) / df["c2010"]
    df["pct_recovered"] = 100.0 * (df["c2020"] - df["c2010"]) / (
        (df["c2000"] - df["c2010"]).where(df["c2000"] > df["c2010"]))
    df["turnaround"] = (df["pct_decline"] >= 3.0) & (df["pct_rebound"] >= 2.0)
    return df


def main() -> None:
    wide = load_town_backbone()
    towns = classify_towns(wide)
    turn = towns[towns["turnaround"]].sort_values("pct_recovered", ascending=False)

    cols = ["geoid", "name", "county_fips", "region", "c2000", "c2010", "c2020",
            "p2025", "latest", "peak_year", "trough_year", "pct_decline",
            "pct_recovered"]
    out = turn[cols].copy()
    for c in ["pct_decline", "pct_recovered"]:
        out[c] = out[c].round(1)
    out.to_csv("/tmp/turnaround_towns_v2.csv", index=False)
    towns.to_csv("/tmp/turnaround_towns_v2_all.csv", index=False)

    print(f"TOWNS: {len(towns)} rural towns analyzed (census backbone). "
          f"{int(towns['turnaround'].sum())} turnarounds.")
    print("\nTrajectory mix (census 2000->2010->2020 direction):")
    def traj(r):
        d1 = r["c2010"] - r["c2000"]; d2 = r["c2020"] - r["c2010"]
        if d1 < 0 and d2 < 0: return "steady decline"
        if d1 > 0 and d2 > 0: return "steady growth"
        if d1 < 0 and d2 > 0: return "turnaround (V)"
        if d1 > 0 and d2 < 0: return "peak-and-fall"
        return "flat"
    print(towns.apply(traj, axis=1).value_counts().to_string())

    print("\nTop 25 rural TOWN turnarounds (census-anchored):")
    show = out.head(25).copy()
    show["name"] = show["name"].str.replace(" town", "", regex=False)
    print(show.to_string(index=False))

    print("\nTurnaround towns by region:")
    print(turn["region"].value_counts().to_string())

    # Villages
    vil = classify_villages()
    vturn = vil[vil["turnaround"]].sort_values("pct_rebound", ascending=False)
    vil.to_csv("/tmp/turnaround_villages_v2_all.csv", index=False)
    vturn.to_csv("/tmp/turnaround_villages_v2.csv", index=False)
    print(f"\n\nVILLAGES (upstate/rural only): {len(vil)} analyzed (decennial only). "
          f"{len(vturn)} V-shape turnarounds (declined 2000->2010, rebounded 2010->2020).")
    print("\nUpstate village turnarounds by region:")
    print(vturn["region"].value_counts().to_string())
    vshow = vturn.head(20)[["geoid", "name", "county_fips", "region",
                            "c2000", "c2010", "c2020",
                            "pct_decline", "pct_rebound"]].copy()
    for c in ["pct_decline", "pct_rebound"]:
        vshow[c] = vshow[c].round(1)
    vshow["name"] = vshow["name"].str.replace(" village", "", regex=False)
    print(vshow.to_string(index=False))


if __name__ == "__main__":
    main()
