"""Smoke tests — verify the package installs and paths resolve."""

from pathlib import Path

import popfc


def test_version():
    assert popfc.__version__ == "0.1.0"


def test_project_root_exists():
    assert popfc.PROJECT_ROOT.is_dir()
    assert (popfc.PROJECT_ROOT / "pyproject.toml").is_file()


def test_paths_are_path_objects():
    assert isinstance(popfc.DATA_RAW, Path)
    assert isinstance(popfc.DATA_INTERIM, Path)
    assert isinstance(popfc.DATA_FINAL, Path)


def test_fips_codes():
    from popfc.paths import COUNTY_FIPS, FULL_FIPS, STATE_FIPS
    assert STATE_FIPS == "36"
    assert COUNTY_FIPS == "115"
    assert FULL_FIPS == "36115"
