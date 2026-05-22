"""Centralized data-refresh registry.

Every loader in `popfc.data.*` reads from a file on disk under `data_raw/`.
This module documents and (where possible) automates how those files got
there, so refreshing to a newer vintage is a single command.

## Two kinds of sources

1. **URL-based** (NCHS NVSR life tables, NCHS USALEEP, possibly NYSDOL CSV
   updates): a known stable URL we can `curl` into place. The spec carries
   the URL + the target path.

2. **API-based** (Census ACS via `popfc.data.acs.load_acs5_group()`): the
   "URL" is constructed per call. The spec carries a callable that invokes
   the loader with `refresh=True`.

## Usage

    # From Python:
    from popfc.data.download import refresh_one, refresh_all, list_specs

    list_specs()                          # print the registry
    refresh_one("nchs_us_lt_2023_total")  # one file
    refresh_all()                         # everything

    # From the shell:
    python -m popfc.data.download --list
    python -m popfc.data.download --source nchs_us_lt_2023_total
    python -m popfc.data.download                # all

## Adding a new source

Append a `DownloadSpec` to `REGISTRY` (or register at import time from a
loader module). Each spec must have a stable `name` — that is the user-facing
identifier and should not change once published.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

# Note: `LATEST_ACS5_YEAR` lives in `popfc.data.acs`, not in `paths.py`. We
# import it lazily inside the ACS registration callables so this module stays
# importable even if acs.py changes its public surface.
from popfc.paths import ACS_DIR, NCHS_DIR, PROJECT_ROOT


# ---------------------------------------------------------------------------
# Spec dataclass
# ---------------------------------------------------------------------------

@dataclass
class DownloadSpec:
    """One refreshable data file or loader call."""

    name: str
    target: Path                # absolute path of the file (or, for API
                                # specs, the cache file inside data_raw/<source>/)
    description: str
    source_url: str | None = None
    fetcher: Callable[["DownloadSpec", bool], None] | None = None

    def exists(self) -> bool:
        return self.target.exists()

    def refresh(self, force: bool = False) -> None:
        if self.fetcher is None:
            raise RuntimeError(f"{self.name}: no fetcher configured")
        self.fetcher(self, force)


# ---------------------------------------------------------------------------
# Generic URL fetcher
# ---------------------------------------------------------------------------

def _display_path(p: Path) -> str:
    """Format a path relative to PROJECT_ROOT when possible, else absolute."""
    try:
        return str(p.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(p)


def _http_get_to_file(
    spec: DownloadSpec,
    force: bool,
    *,
    timeout: int = 120,
) -> None:
    """Default fetcher: HTTP GET `spec.source_url` → `spec.target`."""
    if spec.exists() and not force:
        print(f"  [cached] {_display_path(spec.target)}")
        return
    if spec.source_url is None:
        raise RuntimeError(f"{spec.name}: HTTP fetcher requires a source_url")
    spec.target.parent.mkdir(parents=True, exist_ok=True)
    resp = requests.get(spec.source_url, stream=True, timeout=timeout)
    resp.raise_for_status()
    with open(spec.target, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            if chunk:
                f.write(chunk)
    print(f"  [fetched] {_display_path(spec.target)}  "
          f"({spec.target.stat().st_size:,} bytes)")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

REGISTRY: dict[str, DownloadSpec] = {}


def register(spec: DownloadSpec) -> DownloadSpec:
    if spec.name in REGISTRY:
        raise ValueError(f"Duplicate DownloadSpec name: {spec.name}")
    REGISTRY[spec.name] = spec
    return spec


# ---------------------------------------------------------------------------
# NCHS NVSR life tables (URL-based, static)
# ---------------------------------------------------------------------------

_NVSR_BASE = "https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Publications/NVSR"

# US 2023 (NVSR 74-06)
for tbl_no, sex_tag in [("01", "total"), ("02", "male"), ("03", "female")]:
    register(DownloadSpec(
        name=f"nchs_us_lt_2023_{sex_tag}",
        target=NCHS_DIR / "life_tables" / f"us_2023_Table{tbl_no}.xlsx",
        description=f"NCHS US life table 2023, {sex_tag} (NVSR 74-06 Table {int(tbl_no)})",
        source_url=f"{_NVSR_BASE}/74-06/Table{tbl_no}.xlsx",
        fetcher=_http_get_to_file,
    ))

# NY 2022 state (NVSR 74-12)
for tbl_no, sex_tag in [("1", "total"), ("2", "male"), ("3", "female"), ("4", "se")]:
    register(DownloadSpec(
        name=f"nchs_ny_lt_2022_{sex_tag}",
        target=NCHS_DIR / "life_tables" / f"ny_2022_NY{tbl_no}.xlsx",
        description=(
            f"NCHS NY state life table 2022, {sex_tag} (NVSR 74-12 Table NY-{tbl_no})"
        ),
        source_url=f"{_NVSR_BASE}/74-12/NY{tbl_no}.xlsx",
        fetcher=_http_get_to_file,
    ))

# NCHS USALEEP NY (2010-2015 period)
_USALEEP_BASE = "https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Datasets/NVSS/USALEEP/CSV"
for letter, descr in [
    ("A", "life expectancy at birth by tract"),
    ("B", "abridged life table by tract"),
]:
    register(DownloadSpec(
        name=f"nchs_usaleep_ny_{letter.lower()}",
        target=NCHS_DIR / "usaleep" / f"NY_{letter}.csv",
        description=f"NCHS USALEEP NY File {letter} ({descr})",
        source_url=f"{_USALEEP_BASE}/NY_{letter}.CSV",
        fetcher=_http_get_to_file,
    ))


# ---------------------------------------------------------------------------
# ACS (API-based, via popfc.data.acs)
# ---------------------------------------------------------------------------

def _acs_fetcher_factory(
    group: str,
    geography: str,
    *,
    state_fips: str = "36",
    county_fips: str | None = None,
):
    """Build a fetcher that calls `load_acs5_group(...)` with refresh=True."""
    def fetch(spec: DownloadSpec, force: bool) -> None:
        # Late import to avoid the acs ↔ download module cycle.
        from popfc.data.acs import LATEST_ACS5_YEAR, load_acs5_group
        if spec.exists() and not force:
            print(f"  [cached] {_display_path(spec.target)}")
            return
        # refresh=True always re-pulls; load_acs5_group writes the JSON cache.
        load_acs5_group(
            group,
            year=LATEST_ACS5_YEAR,
            geography=geography,
            state_fips=state_fips,
            county_fips=county_fips,
            refresh=True,
        )
        print(f"  [fetched] {_display_path(spec.target)}")
    return fetch


# Register the canonical Phase-2 ACS tables. The target path mirrors what
# `load_acs5_group()` writes via its internal cache rule.
def _register_acs():
    from popfc.data.acs import LATEST_ACS5_YEAR
    year = LATEST_ACS5_YEAR
    base = ACS_DIR / str(year)
    for group in ("B01001", "B07001", "B06001"):
        # County-level (all NY counties)
        register(DownloadSpec(
            name=f"acs5_{year}_{group}_county",
            target=base / f"{group}_state36_county.json",
            description=f"ACS 5-yr {year-4}-{year} {group} at county level (NY)",
            fetcher=_acs_fetcher_factory(group, "county"),
        ))
        # MCD-level (statewide)
        register(DownloadSpec(
            name=f"acs5_{year}_{group}_mcd",
            target=base / f"{group}_state36_in_county_all_county_subdivision.json",
            description=f"ACS 5-yr {year-4}-{year} {group} at MCD level (NY)",
            fetcher=_acs_fetcher_factory(
                group, "county subdivision", county_fips="*",
            ),
        ))


_register_acs()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_specs(stream=sys.stdout) -> None:
    """Print every registered DownloadSpec, grouped by source prefix."""
    name_w = max(len(s.name) for s in REGISTRY.values())
    for name in sorted(REGISTRY):
        spec = REGISTRY[name]
        present = "✓" if spec.exists() else " "
        print(f"  [{present}] {name:<{name_w}}  {spec.description}", file=stream)


def refresh_one(name: str, *, force: bool = False) -> None:
    if name not in REGISTRY:
        raise KeyError(f"Unknown source {name!r}. Try `list_specs()`.")
    print(f"refresh: {name}")
    REGISTRY[name].refresh(force=force)


def refresh_all(*, force: bool = False) -> None:
    for name in sorted(REGISTRY):
        try:
            refresh_one(name, force=force)
        except Exception as e:  # noqa: BLE001
            print(f"  FAILED: {name}: {e}", file=sys.stderr)


def _main() -> int:
    p = argparse.ArgumentParser(prog="popfc.data.download",
                                description=__doc__.splitlines()[0])
    p.add_argument("--list", action="store_true",
                   help="list registered sources and exit")
    p.add_argument("--source", action="append", default=[],
                   help="refresh a specific source by name (repeatable)")
    p.add_argument("--force", action="store_true",
                   help="re-fetch even if the target already exists")
    args = p.parse_args()

    if args.list:
        list_specs()
        return 0
    if args.source:
        for name in args.source:
            refresh_one(name, force=args.force)
        return 0
    refresh_all(force=args.force)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
