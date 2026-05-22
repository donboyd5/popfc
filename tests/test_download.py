"""Tests for popfc.data.download."""

from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest

from popfc.data import download as dl
from popfc.data.download import DownloadSpec, REGISTRY, list_specs


class TestRegistry:
    def test_has_canonical_entries(self):
        # Every Phase-2 deliverable file must be registered so refresh-all
        # really refreshes everything.
        expected = {
            "nchs_us_lt_2023_total",
            "nchs_us_lt_2023_male",
            "nchs_us_lt_2023_female",
            "nchs_ny_lt_2022_total",
            "nchs_ny_lt_2022_male",
            "nchs_ny_lt_2022_female",
            "nchs_ny_lt_2022_se",
            "nchs_usaleep_ny_a",
            "nchs_usaleep_ny_b",
            "acs5_2024_B01001_county",
            "acs5_2024_B01001_mcd",
            "acs5_2024_B07001_county",
            "acs5_2024_B07001_mcd",
            "acs5_2024_B06001_county",
            "acs5_2024_B06001_mcd",
        }
        assert expected.issubset(set(REGISTRY))

    def test_no_duplicate_names(self):
        # If somebody re-imports the module or appends in a loop without
        # checking, register() raises. Confirm REGISTRY is clean here.
        assert len(REGISTRY) == len(set(REGISTRY))

    def test_url_specs_have_source_url(self):
        for name, spec in REGISTRY.items():
            if name.startswith("nchs_"):
                assert spec.source_url is not None, f"{name}: no source_url"
                assert spec.source_url.startswith("https://"), f"{name}: bad URL"

    def test_acs_specs_have_no_source_url(self):
        # API-based specs build their URL at fetch time inside acs.py.
        for name, spec in REGISTRY.items():
            if name.startswith("acs5_"):
                assert spec.source_url is None, \
                    f"{name}: ACS specs should not carry a static URL"
                assert spec.fetcher is not None

    def test_targets_are_absolute_paths(self):
        for spec in REGISTRY.values():
            assert spec.target.is_absolute(), \
                f"{spec.name}: target {spec.target} is not absolute"


class TestListSpecs:
    def test_runs_without_error(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            list_specs(stream=buf)
        output = buf.getvalue()
        # Every spec name should appear in the listing.
        for name in REGISTRY:
            assert name in output


class TestRefreshOne:
    def test_unknown_raises_keyerror(self):
        with pytest.raises(KeyError):
            dl.refresh_one("definitely-not-a-source")

    def test_cached_path_skips_fetch(self, tmp_path, monkeypatch):
        # Spin up a fake spec with a target that already exists; refresh
        # without force should not call requests.get.
        target = tmp_path / "fake.bin"
        target.write_bytes(b"hello")

        called: dict[str, bool] = {"requests_get": False}

        def fake_get(*args, **kwargs):  # noqa: ARG001
            called["requests_get"] = True
            raise AssertionError("network should not be called")

        monkeypatch.setattr(dl.requests, "get", fake_get)

        spec = DownloadSpec(
            name="_test_fake",
            target=target,
            description="test",
            source_url="https://example.invalid/x",
            fetcher=dl._http_get_to_file,
        )
        spec.refresh(force=False)
        assert called["requests_get"] is False
