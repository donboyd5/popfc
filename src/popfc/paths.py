"""Central path constants for the popfc project.

Analog of `setup.R` in the R project. All modules and notebooks should import
paths from here rather than constructing them ad-hoc.
"""

from pathlib import Path

# PROJECT_ROOT resolves to the repo root regardless of where this is imported
# from, because this file lives at src/popfc/paths.py (3 parents up = root).
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

# Data directories
DATA_RAW: Path = PROJECT_ROOT / "data_raw"
DATA_INTERIM: Path = PROJECT_ROOT / "data_interim"
DATA_FINAL: Path = PROJECT_ROOT / "data_final"

# Raw-data subdirectories (mirrors popfc_R/data_raw/ structure)
CENSUS_DIR: Path = DATA_RAW / "census"
CDC_DIR: Path = DATA_RAW / "cdc"
NYSDOL_DIR: Path = DATA_RAW / "nysdol"
NYSDOH_DIR: Path = DATA_RAW / "nysdoh"
IRS_DIR: Path = DATA_RAW / "irs"
CORNELL_DIR: Path = DATA_RAW / "cornell"
ACS_DIR: Path = DATA_RAW / "acs"

# Notebook and output locations
NOTEBOOKS_DIR: Path = PROJECT_ROOT / "notebooks"

# Washington County, NY identifiers
STATE_FIPS: str = "36"
COUNTY_FIPS: str = "115"
FULL_FIPS: str = STATE_FIPS + COUNTY_FIPS  # "36115"
