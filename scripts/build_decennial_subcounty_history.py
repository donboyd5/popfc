"""Build the decennial sub-county (town + village) population history.

Downloads decennial 2000/2010/2020 total-population counts for NY county
subdivisions (towns/cities) and places (villages/cities/CDPs) from the Census
Data API, then writes a statewide long-format interim parquet.

Output: data_interim/subcounty_decennial_history.parquet

Run:  .venv/bin/python scripts/build_decennial_subcounty_history.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from popfc.data.census_decennial import (  # noqa: E402
    download_decennial_subcounty,
    load_decennial_subcounty,
)
from popfc.paths import DATA_INTERIM  # noqa: E402

OUT = DATA_INTERIM / "subcounty_decennial_history.parquet"


def main() -> None:
    written = download_decennial_subcounty()
    print(f"raw files ready ({len(written)}):")
    for k, p in sorted(written.items()):
        print(f"  {k:14s} {p}")

    df = load_decennial_subcounty()

    # ---- sanity checks ----
    assert set(df["year"].unique()) == {2000, 2010, 2020}, df["year"].unique()
    assert set(df["geo_level"].unique()) == {"cousub", "place"}
    assert (df["state_fips"] == "36").all(), "non-NY rows present"
    # cousub geoids are 10 chars, place geoids are 7 chars
    cousub = df[df["geo_level"] == "cousub"]
    place = df[df["geo_level"] == "place"]
    assert cousub["geoid"].str.len().eq(10).all()
    assert place["geoid"].str.len().eq(7).all()
    neg = int((df["population"] < 0).sum())
    assert neg == 0, f"{neg} negative populations"
    # every (geoid, year) unique
    dups = df.duplicated(["geoid", "year"]).sum()
    assert dups == 0, f"{dups} duplicate (geoid, year) rows"

    df.to_parquet(OUT, index=False)

    # ---- summary ----
    print(f"\nwrote {OUT}  ({len(df):,} rows)")
    by = (
        df.groupby(["geo_level", "geo_kind", "year"])
        .size()
        .unstack("year", fill_value=0)
    )
    print("\nrow counts by geo_level / geo_kind / year:")
    print(by.to_string())

    print("\nNA population by (geo_level, year):")
    print(
        df.assign(na=df["population"].isna())
        .groupby(["geo_level", "year"])["na"]
        .sum()
        .to_string()
    )

    # spot-check: Washington County towns across the three censuses
    wc = (
        df[(df["geo_level"] == "cousub") & (df["county_fips"] == "115")]
        .pivot_table(index=["geoid", "geography"], columns="year",
                     values="population", aggfunc="first")
        .reset_index()
    )
    wc["geography"] = wc["geography"].str.split(",").str[0]
    print("\nWashington County towns, decennial counts:")
    print(wc.sort_values("geography").to_string(index=False))


if __name__ == "__main__":
    main()
