"""Tests for popfc.models.fertility."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from popfc.models.fertility import (
    ASFR_LONG_COLUMNS,
    NCHS_ASFR_2023_TFR,
    NCHS_ASFR_5YR_2023_ALL,
    REPRO_AGE_MAX,
    REPRO_AGE_MIN,
    SEX_RATIO_AT_BIRTH,
    SHARE_FEMALE_AT_BIRTH,
    SHARE_MALE_AT_BIRTH,
    build_county_year_asfr,
    expand_5yr_to_single_year,
    implied_births_from_schedule,
    reference_asfr_schedule,
    reference_tfr,
    scale_asfr_to_observed_births,
)


class TestConstants:
    def test_share_male_plus_female_equals_one(self):
        assert math.isclose(SHARE_MALE_AT_BIRTH + SHARE_FEMALE_AT_BIRTH, 1.0)

    def test_share_male_matches_srb(self):
        assert math.isclose(
            SHARE_MALE_AT_BIRTH / SHARE_FEMALE_AT_BIRTH, SEX_RATIO_AT_BIRTH
        )

    def test_repro_age_range_sensible(self):
        assert 10 <= REPRO_AGE_MIN < REPRO_AGE_MAX <= 54


class TestExpand5yrToSingleYear:
    def test_basic_expansion(self):
        out = expand_5yr_to_single_year({(15, 19): 13.1})
        assert len(out) == 5
        assert set(out["age"]) == {15, 16, 17, 18, 19}
        assert (out["asfr_per_1000"] == 13.1).all()

    def test_sorts_by_age(self):
        out = expand_5yr_to_single_year({(40, 44): 12.5, (10, 14): 0.2})
        assert out["age"].is_monotonic_increasing

    def test_raises_reversed_band(self):
        with pytest.raises(ValueError, match="reversed"):
            expand_5yr_to_single_year({(20, 15): 10.0})


class TestReferenceSchedule:
    def test_age_coverage(self):
        ref = reference_asfr_schedule()
        # Should cover REPRO_AGE_MIN (10) through REPRO_AGE_MAX (49) = 40 ages.
        assert len(ref) == 40
        assert ref["age"].min() == REPRO_AGE_MIN
        assert ref["age"].max() == REPRO_AGE_MAX

    def test_tfr_matches_published(self):
        # The implied TFR from our single-year schedule should equal the
        # published 2023 NCHS value to within rounding.
        tfr = reference_tfr()
        assert abs(tfr - NCHS_ASFR_2023_TFR) < 0.005

    def test_provenance_columns(self):
        ref = reference_asfr_schedule()
        assert (ref["ref_source"] == "nchs_nvsr").all()
        assert ref["ref_vintage"].nunique() == 1

    def test_unknown_vintage_raises(self):
        with pytest.raises(ValueError, match="unknown vintage"):
            reference_asfr_schedule(vintage="fictional")

    def test_published_values_in_schedule(self):
        # Spot-check that the 5-year published rate appears in the
        # corresponding single-year rows.
        ref = reference_asfr_schedule().set_index("age")["asfr_per_1000"]
        for (lo, hi), published in NCHS_ASFR_5YR_2023_ALL.items():
            for age in range(lo, hi + 1):
                assert float(ref.loc[age]) == published


class TestScaling:
    def _ref(self):
        return reference_asfr_schedule()[["age", "asfr_per_1000"]]

    def _fake_pop(self, women_per_age: float = 1000.0):
        # Uniform female pop of 1000 per single year of age, ages 10-49.
        return pd.DataFrame({
            "age": list(range(REPRO_AGE_MIN, REPRO_AGE_MAX + 1)),
            "population": [women_per_age] * (REPRO_AGE_MAX - REPRO_AGE_MIN + 1),
        })

    def test_implied_births_with_uniform_pop(self):
        # 1000 women per age × 40 ages × asfr/1000 summed = total births.
        # The sum of single-year asfr_per_1000 = NCHS_ASFR_2023_TFR * 1000.
        ref = self._ref()
        pop = self._fake_pop(women_per_age=1000)
        births = implied_births_from_schedule(ref, pop)
        # births = sum(asfr * pop / 1000) = sum(asfr) * 1000 / 1000 = sum(asfr)
        expected = float(ref["asfr_per_1000"].sum())
        assert abs(births - expected) < 1e-6

    def test_scaling_recovers_observed_exactly(self):
        ref = self._ref()
        pop = self._fake_pop(women_per_age=500)
        target = 750.0
        scaled, k = scale_asfr_to_observed_births(ref, pop, target)
        # Implied births under scaled schedule should match target.
        implied = implied_births_from_schedule(
            scaled[["age", "asfr_per_1000"]], pop
        )
        assert abs(implied - target) < 1e-6
        # Scaling factor stored on every row.
        assert (scaled["scaling_factor"] == k).all()

    def test_zero_pop_raises(self):
        ref = self._ref()
        pop = pd.DataFrame({"age": [25], "population": [0]})
        with pytest.raises(ValueError, match="non-positive"):
            scale_asfr_to_observed_births(ref, pop, observed_births=100)


class TestBuildCountyYearAsfr:
    def _data(self):
        # Two counties, one year, simple uniform female pop.
        ages = list(range(0, 86))
        rows = []
        for geoid, geog in [("36115", "Washington County"), ("36091", "Saratoga County")]:
            for age in ages:
                rows.append({
                    "geoid": geoid, "geography": geog, "year": 2022,
                    "sex": "F", "age": age, "population": 500.0,
                })
                rows.append({
                    "geoid": geoid, "geography": geog, "year": 2022,
                    "sex": "M", "age": age, "population": 500.0,
                })
        female_pop = pd.DataFrame(rows)
        births = pd.DataFrame([
            {"geoid": "36115", "year": 2022, "value": 500.0},
            {"geoid": "36091", "year": 2022, "value": 1000.0},
        ])
        return female_pop, births

    def test_basic_build(self):
        female_pop, births = self._data()
        out = build_county_year_asfr(female_pop, births)
        assert list(out.columns) == ASFR_LONG_COLUMNS
        # Two counties × 40 reproductive ages.
        assert len(out) == 2 * 40

    def test_implied_births_matches_observed(self):
        female_pop, births = self._data()
        out = build_county_year_asfr(female_pop, births)
        for geoid, group in out.groupby("geoid"):
            obs = float(births.loc[births["geoid"] == geoid, "value"].iloc[0])
            implied = (
                group["asfr_per_1000"].astype(float)
                * 500.0  # uniform pop
                / 1000.0
            ).sum()
            assert abs(implied - obs) < 1e-6, f"{geoid}: implied {implied} vs observed {obs}"

    def test_skips_county_year_without_births(self):
        female_pop, _births = self._data()
        births_partial = pd.DataFrame([
            {"geoid": "36115", "year": 2022, "value": 500.0}
        ])
        out = build_county_year_asfr(female_pop, births_partial)
        # Only Washington should appear.
        assert out["geoid"].unique().tolist() == ["36115"]

    def test_filters_to_female_reproductive_ages(self):
        female_pop, births = self._data()
        out = build_county_year_asfr(female_pop, births)
        # All rows female and in repro age range.
        assert (out["sex"] == "F").all()
        assert out["age"].min() >= REPRO_AGE_MIN
        assert out["age"].max() <= REPRO_AGE_MAX
