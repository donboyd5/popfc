"""IRS SOI county-to-county migration data loader.

Loads the annual IRS Statistics of Income (SOI) county migration files,
which report year-over-year address changes from individual tax returns.
Each "vintage" of the data covers a single pair of consecutive tax years
(e.g., the `2223` vintage covers movements from 2022 to 2023).

## File schema (per the 2022-2023 Users Guide)

Two files per vintage live under `data_raw/irs/`:

- ``countyinflow<YYZZ>.csv`` — anchored on the **destination** county.
  One row per (origin-county → destination-county) pair, plus several
  summary rows per destination.
- ``countyoutflow<YYZZ>.csv`` — anchored on the **origin** county.
  One row per (origin-county → destination-county) pair, plus summary
  rows per origin.

Both files have the same value columns: `n1` (returns ≈ households),
`n2` (exemptions ≈ individuals), `agi` (total AGI in thousands of $).
No age or sex breakdown is available at the county level.

## Summary-row sentinels

Each anchor county has several summary rows aggregating its flows:

| Sentinel FIPS         | Meaning                                  |
|-----------------------|------------------------------------------|
| ``96 / 000``          | Total migration — US and Foreign         |
| ``97 / 000``          | Total migration — US (domestic only)     |
| ``97 / 001``          | Total migration — Same State             |
| ``97 / 003``          | Total migration — Different State        |
| ``98 / 000``          | Total migration — Foreign                |

We expose these as separate ``partner_kind`` values so the caller can
slice cleanly (e.g., to compute net domestic = `total_us` inflow minus
`total_us` outflow).

## Output schema

A single long-format DataFrame (``IRS_MIGRATION_COLUMNS``) with one row
per (anchor county × direction × partner_kind × partner). The
``partner_*`` columns describe the *other* end of the flow:

- For ``partner_kind == "specific_county"`` rows, the partner is a real
  county and ``partner_geoid`` / ``partner_geography`` carry its
  identifiers.
- For ``partner_kind == "total_*"`` summary rows, ``partner_geoid`` is
  ``None`` and ``partner_geography`` carries the raw IRS label.

## Vintage

The two-character vintage tag is the four-digit calendar-year pair
written without separator (``"2223"`` = 2022-2023). The output uses
the human-readable form ``"irs_soi_2022-2023"`` in the ``vintage``
column. The ``year_start`` / ``year_end`` columns hold the two
calendar years that bookend the move (2022 and 2023 for vintage 2223).
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from popfc.data._common import (
    coerce_numeric,
    make_geoid,
    pad_county_fips,
    pad_state_fips,
    read_csv_strings,
)
from popfc.paths import IRS_DIR

# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

IRS_MIGRATION_COLUMNS: list[str] = [
    "state_fips",        # 2-char anchor state FIPS
    "county_fips",       # 3-char anchor county FIPS
    "geoid",             # 5-char anchor county FIPS
    "geography",         # anchor county human-readable name
    "year_start",        # first tax year of the move (e.g., 2022 for 2223)
    "year_end",          # second tax year of the move (e.g., 2023 for 2223)
    "direction",         # "in" (anchor = destination) | "out" (anchor = origin)
    "partner_kind",      # see below
    "partner_geoid",     # 5-char partner FIPS for specific_county, None otherwise
    "partner_geography", # partner county name OR the raw IRS summary-row label
    "returns",           # nullable Int64 — n1 (≈ households)
    "exemptions",        # nullable Int64 — n2 (≈ individuals)
    "agi_thousands",     # nullable Int64 — total AGI in thousands of $
    "source",            # "irs_soi_migration"
    "vintage",           # "irs_soi_2022-2023" style
    "notes",
]

# `partner_kind` enum values.
PARTNER_KIND_SPECIFIC = "specific_county"
PARTNER_KIND_NON_MIGRANTS = "non_migrants"
PARTNER_KIND_TOTAL_US_AND_FOREIGN = "total_us_and_foreign"
PARTNER_KIND_TOTAL_US = "total_us"
PARTNER_KIND_TOTAL_SAME_STATE = "total_same_state"
PARTNER_KIND_TOTAL_DIFFERENT_STATE = "total_different_state"
PARTNER_KIND_TOTAL_FOREIGN = "total_foreign"
PARTNER_KIND_OTHER_SAME_STATE = "other_same_state"
PARTNER_KIND_OTHER_DIFFERENT_STATE = "other_different_state"
PARTNER_KIND_OTHER_REGION = "other_region"
PARTNER_KIND_FOREIGN_SUBREGION = "foreign_subregion"

# Sentinel state-FIPS codes that mark non-county rows in the IRS migration
# files. Counties have FIPS 01-56; everything 57+ is an aggregate row.
_SENTINEL_STATEFIPS: set[str] = {"57", "58", "59", "96", "97", "98"}

# Exact (statefips, countyfips) pairs for grand-total summary rows.
_SENTINEL_KIND: dict[tuple[str, str], str] = {
    ("96", "000"): PARTNER_KIND_TOTAL_US_AND_FOREIGN,
    ("97", "000"): PARTNER_KIND_TOTAL_US,
    ("97", "001"): PARTNER_KIND_TOTAL_SAME_STATE,
    ("97", "003"): PARTNER_KIND_TOTAL_DIFFERENT_STATE,
    ("98", "000"): PARTNER_KIND_TOTAL_FOREIGN,
    ("58", "000"): PARTNER_KIND_OTHER_SAME_STATE,
    ("59", "000"): PARTNER_KIND_OTHER_DIFFERENT_STATE,
}


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_VINTAGE_TAG = "2223"


def _default_inflow_path(vintage_tag: str) -> Path:
    return IRS_DIR / f"countyinflow{vintage_tag}.csv"


def _default_outflow_path(vintage_tag: str) -> Path:
    return IRS_DIR / f"countyoutflow{vintage_tag}.csv"


def _vintage_from_tag(tag: str) -> tuple[int, int, str]:
    """Turn a `2223`-style tag into (year_start=2022, year_end=2023, label)."""
    m = re.fullmatch(r"(\d{2})(\d{2})", tag)
    if not m:
        raise ValueError(f"vintage tag must be YYZZ (e.g., '2223'); got {tag!r}")
    y1 = 2000 + int(m.group(1))  # works through 2099; IRS uses 2-digit years
    y2 = 2000 + int(m.group(2))
    return y1, y2, f"irs_soi_{y1}-{y2}"


# ---------------------------------------------------------------------------
# One-file loader
# ---------------------------------------------------------------------------

def _load_one_file(
    path: Path,
    *,
    direction: str,
    year_start: int,
    year_end: int,
    vintage_label: str,
    state_filter: str | None,
) -> pd.DataFrame:
    """Load one inflow or outflow CSV and emit IRS_MIGRATION_COLUMNS rows."""
    assert direction in ("in", "out"), direction
    raw = read_csv_strings(path)

    # Identify which side of each row is the anchor and which is the partner.
    # Inflow file: anchor = destination = y2; partner = origin = y1.
    # Outflow file: anchor = origin = y1; partner = destination = y2.
    if direction == "in":
        anchor_state_col, anchor_county_col = "y2_statefips", "y2_countyfips"
        partner_state_col, partner_county_col = "y1_statefips", "y1_countyfips"
        partner_name_col = "y1_countyname"
    else:
        anchor_state_col, anchor_county_col = "y1_statefips", "y1_countyfips"
        partner_state_col, partner_county_col = "y2_statefips", "y2_countyfips"
        partner_name_col = "y2_countyname"

    required = {anchor_state_col, anchor_county_col,
                partner_state_col, partner_county_col,
                partner_name_col, "n1", "n2", "agi"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(
            f"{path.name}: missing expected columns {sorted(missing)}; "
            f"got {sorted(raw.columns)}"
        )

    # Apply state filter on the anchor side, if requested.
    if state_filter is not None:
        raw = raw[raw[anchor_state_col].astype(str).str.zfill(2) == state_filter].copy()

    # Pad FIPS codes.
    raw[anchor_state_col] = raw[anchor_state_col].apply(
        lambda s: pad_state_fips(int(s)) if str(s).strip().isdigit() else str(s)
    )
    raw[anchor_county_col] = raw[anchor_county_col].apply(
        lambda s: pad_county_fips(int(s)) if str(s).strip().isdigit() else str(s)
    )
    raw[partner_state_col] = raw[partner_state_col].apply(
        lambda s: str(s).strip().zfill(2)
    )
    raw[partner_county_col] = raw[partner_county_col].apply(
        lambda s: str(s).strip().zfill(3)
    )

    # Classify partner_kind. Sentinel state codes 57-59 and 96-98 mark
    # aggregate / non-county rows; codes 01-56 mark real counties. Within
    # the real-county set, when partner_geoid == anchor_geoid the row is
    # the "Non-migrants" count (people who stayed in the same county).
    anchor_geoids_lookup = raw[anchor_state_col].astype(str) + raw[anchor_county_col].astype(str)

    def classify(row: pd.Series) -> tuple[str, str | None, str]:
        ps, pc = str(row[partner_state_col]), str(row[partner_county_col])
        name = str(row[partner_name_col])
        if (ps, pc) in _SENTINEL_KIND:
            return _SENTINEL_KIND[(ps, pc)], None, name
        if ps in _SENTINEL_STATEFIPS:
            # 57/xxx = foreign sub-regions; 59/xxx (xxx ∈ {001,003,005,007}) = region buckets.
            if ps == "57":
                return PARTNER_KIND_FOREIGN_SUBREGION, None, name
            if ps == "59":
                return PARTNER_KIND_OTHER_REGION, None, name
            # 58/xxx with xxx != 000 unlikely; fall through to a labeled generic.
            return PARTNER_KIND_OTHER_SAME_STATE, None, name
        # Real-county pair. Distinguish the anchor's own non-migrant count
        # from a true origin/destination flow.
        pgeoid = make_geoid(int(ps), int(pc))
        anchor_geoid = make_geoid(int(row[anchor_state_col]), int(row[anchor_county_col]))
        if pgeoid == anchor_geoid:
            return PARTNER_KIND_NON_MIGRANTS, pgeoid, name
        return PARTNER_KIND_SPECIFIC, pgeoid, name

    classified = raw.apply(classify, axis=1, result_type="expand")
    classified.columns = ["partner_kind", "partner_geoid", "partner_geography"]
    raw = pd.concat([raw, classified], axis=1)

    # Anchor county name: not in the raw row (only state code present); the
    # caller can join to a roster if needed. For now we leave geography blank
    # for anchors and populate it best-effort from any partner_kind=='specific_county'
    # row that names the anchor.
    raw["state_fips"] = raw[anchor_state_col]
    raw["county_fips"] = raw[anchor_county_col]
    raw["geoid"] = raw.apply(
        lambda r: make_geoid(int(r["state_fips"]), int(r["county_fips"])),
        axis=1,
    )

    # Coerce numerics. IRS uses -1 to mark "value suppressed for disclosure
    # avoidance"; we map those to <NA>.
    def _to_int_with_suppress(s: pd.Series, label: str) -> pd.Series:
        out = coerce_numeric(s, label=label, dtype="Int64")
        return out.mask(out < 0)

    returns = _to_int_with_suppress(raw["n1"], label=f"irs/n1/{direction}")
    exemptions = _to_int_with_suppress(raw["n2"], label=f"irs/n2/{direction}")
    agi = _to_int_with_suppress(raw["agi"], label=f"irs/agi/{direction}")

    out = pd.DataFrame({
        "state_fips": raw["state_fips"].astype(str),
        "county_fips": raw["county_fips"].astype(str),
        "geoid": raw["geoid"].astype(str),
        "geography": "",  # filled below from sentinel rows
        "year_start": year_start,
        "year_end": year_end,
        "direction": direction,
        "partner_kind": raw["partner_kind"].astype(str),
        "partner_geoid": raw["partner_geoid"],
        "partner_geography": raw["partner_geography"].astype(str),
        "returns": returns,
        "exemptions": exemptions,
        "agi_thousands": agi,
        "source": "irs_soi_migration",
        "vintage": vintage_label,
        "notes": "",
    })

    # Fill the anchor `geography` from any sentinel row that names it. The
    # IRS summary labels have the form "Washington County Total Migration-US",
    # so we strip the trailing suffix to recover a clean county name.
    suffix_re = re.compile(r"\s+Total Migration[-\s].*$")
    def _extract_anchor_name(label: str) -> str:
        return suffix_re.sub("", str(label)).strip()
    sentinel_mask = out["partner_kind"] != PARTNER_KIND_SPECIFIC
    by_geoid_name = (
        out.loc[sentinel_mask, ["geoid", "partner_geography"]]
        .assign(extracted=lambda d: d["partner_geography"].map(_extract_anchor_name))
        .drop_duplicates(subset="geoid", keep="first")
        .set_index("geoid")["extracted"]
    )
    out["geography"] = out["geoid"].map(by_geoid_name).fillna("")

    return out[IRS_MIGRATION_COLUMNS]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_irs_county_migration(
    vintage_tag: str = DEFAULT_VINTAGE_TAG,
    *,
    inflow_path: Path | str | None = None,
    outflow_path: Path | str | None = None,
    state_filter: str | None = "36",
    direction: str = "both",
) -> pd.DataFrame:
    """Load IRS SOI county migration data for one vintage.

    Parameters
    ----------
    vintage_tag
        Four-digit calendar-year pair without separator (e.g., ``"2223"``
        for 2022-2023). Determines the default file paths.
    inflow_path, outflow_path
        Optional path overrides for the two CSVs.
    state_filter
        Restrict to anchor counties in this state FIPS (default ``"36"`` =
        NY). Pass ``None`` for nationwide.
    direction
        ``"in"``, ``"out"``, or ``"both"`` (default). When ``"both"``,
        the result stacks the two files.

    Returns
    -------
    DataFrame conforming to ``IRS_MIGRATION_COLUMNS``.
    """
    year_start, year_end, vintage_label = _vintage_from_tag(vintage_tag)

    if direction not in ("in", "out", "both"):
        raise ValueError(f"direction must be 'in', 'out', or 'both'; got {direction!r}")

    frames: list[pd.DataFrame] = []
    if direction in ("in", "both"):
        p = Path(inflow_path) if inflow_path is not None else _default_inflow_path(vintage_tag)
        frames.append(_load_one_file(
            p, direction="in",
            year_start=year_start, year_end=year_end,
            vintage_label=vintage_label,
            state_filter=state_filter,
        ))
    if direction in ("out", "both"):
        p = Path(outflow_path) if outflow_path is not None else _default_outflow_path(vintage_tag)
        frames.append(_load_one_file(
            p, direction="out",
            year_start=year_start, year_end=year_end,
            vintage_label=vintage_label,
            state_filter=state_filter,
        ))

    out = pd.concat(frames, ignore_index=True)
    return out[IRS_MIGRATION_COLUMNS]
