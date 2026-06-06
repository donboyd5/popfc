"""Town annual population + change (history) and average-annual change per
5-year forecast period, for Cambridge / White Creek / Greenwich.

History: annual town population from data_interim/town_total_pop_history.parquet
(whatever annual coverage exists, from 2015 onward) with year-over-year change.

Forecast: the town forecast is produced at 5-year steps only (Hamilton-Perry).
For each 5-year period we report the total change and the AVERAGE ANNUAL change
(= period change / number of years in the period). No births/deaths/migration
split exists at the town level.

Writes:
  data_final/town_annual_history.csv
  data_final/town_period_avg_annual.csv
and prints a preview. Robust to the exact history schema.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from popfc.paths import DATA_FINAL, DATA_INTERIM  # noqa: E402

FOCUS = {
    "3611511836": "Cambridge town",
    "3611581578": "White Creek town",
    "3611530686": "Greenwich town",
}
START = 2015


def _pick(cols, *cands):
    for c in cands:
        if c in cols:
            return c
    return None


def main() -> None:
    log = []

    # ---------- HISTORY ----------
    hist_src = pd.read_parquet(DATA_INTERIM / "town_total_pop_history.parquet")
    cols = list(hist_src.columns)
    log.append(f"history schema: {cols}")

    gcol = _pick(cols, "geoid", "mcd_fips")
    ncol = _pick(cols, "geography", "name", "mcd_name")
    ycol = _pick(cols, "year")
    pcol = _pick(cols, "population", "pop", "value")
    log.append(f"using geoid={gcol} name={ncol} year={ycol} pop={pcol}")

    h = hist_src.copy()
    h[gcol] = h[gcol].astype(str)
    h = h[h[gcol].isin(FOCUS)].copy()
    log.append(f"all years present for focus towns: "
               f"{sorted(h[ycol].unique().tolist())}")

    # If multiple rows per (geoid, year) (e.g. several sources/vintages),
    # collapse to one. Prefer the largest year-coverage source; otherwise mean.
    scol = _pick(cols, "source")
    vcol = _pick(cols, "vintage")
    dup = h.groupby([gcol, ycol]).size().max()
    log.append(f"max rows per (geoid, year) before collapse: {int(dup)}")
    if dup > 1:
        sort_cols = [c for c in [vcol, scol] if c]
        if sort_cols:
            h = h.sort_values([gcol, ycol, *sort_cols]).drop_duplicates(
                [gcol, ycol], keep="last")
        else:
            h = (h.groupby([gcol, ycol], as_index=False)[pcol].mean())
            ncol = None

    keep = {gcol: "geoid", ycol: "year", pcol: "population"}
    if ncol:
        keep[ncol] = "geography"
    h = h[list(keep)].rename(columns=keep)
    h["geography"] = h["geoid"].map(FOCUS)
    h = h[h["year"] >= START].sort_values(["geoid", "year"]).reset_index(drop=True)
    h["pop_change"] = h.groupby("geoid")["population"].diff()
    h["pct_change"] = 100.0 * h.groupby("geoid")["population"].pct_change()
    h = h[["geoid", "geography", "year", "population", "pop_change", "pct_change"]]
    h.to_csv(DATA_FINAL / "town_annual_history.csv", index=False)

    # ---------- FORECAST: avg annual per 5-year period ----------
    fc = pd.read_parquet(DATA_INTERIM / "town_forecasts.parquet")
    fc["geoid"] = fc["geoid"].astype(str)
    fc = fc[fc["geoid"].isin(FOCUS)]
    tot = (fc.groupby(["geoid", "geography", "year", "scenario"])["population"]
           .sum().reset_index()
           .sort_values(["geoid", "scenario", "year"]))
    tot["prev_year"] = tot.groupby(["geoid", "scenario"])["year"].shift()
    tot["prev_pop"] = tot.groupby(["geoid", "scenario"])["population"].shift()
    tot["period"] = (tot["prev_year"].astype("Int64").astype(str)
                     + "-" + tot["year"].astype(str))
    tot["n_years"] = tot["year"] - tot["prev_year"]
    tot["period_change"] = tot["population"] - tot["prev_pop"]
    tot["avg_annual_change"] = tot["period_change"] / tot["n_years"]
    tot["avg_annual_pct"] = (
        100.0 * ((tot["population"] / tot["prev_pop"]) ** (1.0 / tot["n_years"]) - 1.0)
    )
    per = tot.dropna(subset=["prev_pop"]).copy()
    per = per[["geoid", "geography", "scenario", "period", "n_years",
               "prev_pop", "population", "period_change",
               "avg_annual_change", "avg_annual_pct"]]
    per.to_csv(DATA_FINAL / "town_period_avg_annual.csv", index=False)

    # ---------- preview ----------
    out = ["\n".join(log), ""]
    out.append("=== ANNUAL HISTORY (focus towns, 2015+) ===")
    hp = h.copy()
    hp["population"] = hp["population"].round(0).astype("Int64")
    hp["pop_change"] = hp["pop_change"].round(0).astype("Int64")
    hp["pct_change"] = hp["pct_change"].round(2)
    out.append(hp.to_string(index=False))
    out.append("")
    out.append("=== FORECAST: avg annual change per 5-yr period (baseline) ===")
    pp = per[per["scenario"] == "baseline"].copy()
    for c in ["prev_pop", "population", "period_change", "avg_annual_change"]:
        pp[c] = pp[c].round(0).astype("Int64")
    pp["avg_annual_pct"] = pp["avg_annual_pct"].round(2)
    out.append(pp.to_string(index=False))

    text = "\n".join(out)
    (Path("/tmp") / "town_annual_preview.txt").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
