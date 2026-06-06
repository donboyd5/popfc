"""Build year-by-year population + components-of-change tables.

Writes two CSVs to data_final/ and prints a 2015-2035 preview:

- county_yearly_components.csv  — Washington, annual history+forecast with
  births/deaths/natural change/net migration (all scenarios).
- town_yearly_totals.csv        — Cambridge / White Creek / Greenwich (and
  all Washington towns), population + change at native 5-year steps.

Run: python scripts/build_yearly_tables.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from popfc.paths import DATA_FINAL, FULL_FIPS  # noqa: E402
from popfc.reporting.yearly_tables import (  # noqa: E402
    build_county_yearly,
    build_town_yearly,
)

SCENARIOS = ["baseline", "low", "high"]
FOCUS_TOWNS = {
    "3611511836": "Cambridge town",
    "3611581578": "White Creek town",
    "3611530686": "Greenwich town",
}


def main() -> None:
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 30)

    # --- County: all scenarios stacked ---
    county = pd.concat(
        [build_county_yearly(FULL_FIPS, sc) for sc in SCENARIOS],
        ignore_index=True,
    )
    county_path = DATA_FINAL / "county_yearly_components.csv"
    county.to_csv(county_path, index=False)

    # Identity check: components sum to pop_change (forecast rows).
    fc = county[county["period"] == "forecast"].copy()
    resid = (
        fc["births"] - fc["deaths"] + fc["net_mig"] - fc["pop_change"]
    ).abs().max()
    assert resid < 1e-6, f"component identity broken, max resid={resid}"

    # --- Towns: all Washington towns; preview focus towns ---
    towns = build_town_yearly(scenario="baseline")
    towns_all = pd.concat(
        [build_town_yearly(scenario=sc) for sc in SCENARIOS], ignore_index=True
    )
    town_path = DATA_FINAL / "town_yearly_totals.csv"
    towns_all.to_csv(town_path, index=False)

    # --- Previews ---
    print(f"\nWrote {county_path}  ({len(county):,} rows, {len(SCENARIOS)} scenarios)")
    print(f"Wrote {town_path}  ({len(towns_all):,} rows)\n")

    show = (
        county[(county["scenario"] == "baseline")
               & county["year"].between(2015, 2035)]
        .copy()
    )
    for c in ["population", "pop_change", "births", "deaths",
              "natural_change", "net_mig"]:
        show[c] = show[c].round(0).astype("Int64")
    print("=" * 92)
    print("WASHINGTON COUNTY — baseline, 2015-2035 (history -> forecast)")
    print("=" * 92)
    print(show[["year", "period", "population", "pop_change", "births",
                "deaths", "natural_change", "net_mig"]].to_string(index=False))

    print("\n" + "=" * 92)
    print("TOWNS — baseline, population + change (native 5-year steps)")
    print("=" * 92)
    tshow = towns[towns["geoid"].isin(FOCUS_TOWNS)].copy()
    tshow["population"] = tshow["population"].round(0).astype("Int64")
    tshow["pop_change"] = tshow["pop_change"].round(0).astype("Int64")
    tshow["pct_change"] = tshow["pct_change"].round(1)
    print(tshow.to_string(index=False))


if __name__ == "__main__":
    main()
