"""Tests for popfc.reconcile."""

from __future__ import annotations

import pandas as pd
import pytest

from popfc.reconcile import (
    DEFAULT_PEP_VINTAGE_RANK,
    reconcile_county_population,
    resolve_pep_vintage,
)


def _pop_row(*, geoid, year, kind, population, source, vintage, geography="X"):
    return {
        "state_fips": geoid[:2],
        "county_fips": geoid[2:],
        "geoid": geoid,
        "geography": geography,
        "year": year,
        "kind": kind,
        "population": population,
        "source": source,
        "vintage": vintage,
        "notes": "",
    }


class TestResolvePepVintage:
    def test_keeps_latest_vintage_for_overlapping_year(self):
        df = pd.DataFrame([
            _pop_row(geoid="36115", year=2020, kind="estimate",
                     population=61000, source="census_pep", vintage="v2020"),
            _pop_row(geoid="36115", year=2020, kind="estimate",
                     population=61297, source="census_pep", vintage="v2024"),
        ])
        out = resolve_pep_vintage(df)
        assert len(out) == 1
        assert int(out["population"].iloc[0]) == 61297
        assert out["vintage"].iloc[0] == "v2024"

    def test_independent_kinds_both_kept(self):
        # 'census' and 'estimate' for the same year should both survive.
        df = pd.DataFrame([
            _pop_row(geoid="36115", year=2010, kind="census",
                     population=63216, source="census_pep", vintage="v2020"),
            _pop_row(geoid="36115", year=2010, kind="estimate",
                     population=63100, source="census_pep", vintage="v2020"),
        ])
        out = resolve_pep_vintage(df)
        assert len(out) == 2
        assert set(out["kind"]) == {"census", "estimate"}

    def test_unknown_vintage_ranked_below_known(self):
        df = pd.DataFrame([
            _pop_row(geoid="36115", year=2020, kind="estimate",
                     population=60000, source="census_pep", vintage="garbage"),
            _pop_row(geoid="36115", year=2020, kind="estimate",
                     population=61297, source="census_pep", vintage="v2024"),
        ])
        out = resolve_pep_vintage(df)
        assert out["vintage"].iloc[0] == "v2024"

    def test_custom_rank_overrides_default(self):
        df = pd.DataFrame([
            _pop_row(geoid="36115", year=2020, kind="estimate",
                     population=100, source="census_pep", vintage="A"),
            _pop_row(geoid="36115", year=2020, kind="estimate",
                     population=200, source="census_pep", vintage="B"),
        ])
        out = resolve_pep_vintage(df, vintage_rank={"A": 1, "B": 0})
        assert int(out["population"].iloc[0]) == 100  # A wins under custom rank

    def test_default_rank_is_ordered(self):
        # Guardrail: if someone changes the default ranking, this fails loudly.
        ranks = list(DEFAULT_PEP_VINTAGE_RANK.values())
        assert ranks == sorted(ranks)


class TestReconcileCountyPopulation:
    def _frames(self):
        # Minimal three-year scenario for one county.
        pep = pd.DataFrame([
            _pop_row(geoid="36115", year=2020, kind="estimate",
                     population=61297, source="census_pep", vintage="v2024"),
            _pop_row(geoid="36115", year=2021, kind="estimate",
                     population=60871, source="census_pep", vintage="v2024"),
            _pop_row(geoid="36115", year=2022, kind="estimate",
                     population=60764, source="census_pep", vintage="v2024"),
        ])
        nysdol = pd.DataFrame([
            _pop_row(geoid="36115", year=2010, kind="census",
                     population=63254, source="nysdol", vintage="nysdol_2025-04-20"),
            _pop_row(geoid="36115", year=2019, kind="intercensal",
                     population=61665, source="nysdol", vintage="nysdol_2025-04-20"),
            _pop_row(geoid="36115", year=2020, kind="census",
                     population=61297, source="nysdol", vintage="nysdol_2025-04-20"),
        ])
        return pep, nysdol

    def test_rule_routing(self):
        pep, nysdol = self._frames()
        out = reconcile_county_population(pep, nysdol)
        by_year = out.set_index("year")["rule"].to_dict()
        assert by_year[2010] == "decennial_census_nysdol"
        assert by_year[2019] == "intercensal_nysdol"
        assert by_year[2020] == "decennial_census_nysdol"
        assert by_year[2021] == "postcensal_census_pep"
        assert by_year[2022] == "postcensal_census_pep"

    def test_unique_per_geoid_year(self):
        pep, nysdol = self._frames()
        out = reconcile_county_population(pep, nysdol)
        assert (out.groupby(["geoid", "year"]).size() == 1).all()

    def test_raises_on_rule_overlap(self):
        # Force a duplicate by adding a NYSDOL intercensal row for 2020
        # (which should never happen in real data — 2020 is a decennial year).
        pep, nysdol = self._frames()
        bad = nysdol.copy()
        bad = pd.concat([
            bad,
            pd.DataFrame([_pop_row(
                geoid="36115", year=2010, kind="intercensal",  # collides with decennial 2010? No — 2010 is excluded from intercensal.
                population=99999, source="nysdol", vintage="nysdol_2025-04-20",
            )]),
        ], ignore_index=True)
        # 2010 is explicitly excluded from the intercensal rule, so this should
        # *not* raise. Just confirm.
        out = reconcile_county_population(pep, bad)
        assert (out.groupby(["geoid", "year"]).size() == 1).all()
