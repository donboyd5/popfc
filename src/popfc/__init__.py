"""popfc — Population forecasts for Washington County, NY and its towns."""

__version__ = "0.1.0"

from popfc.paths import (
    DATA_FINAL,
    DATA_INTERIM,
    DATA_RAW,
    PROJECT_ROOT,
)

__all__ = [
    "__version__",
    "PROJECT_ROOT",
    "DATA_RAW",
    "DATA_INTERIM",
    "DATA_FINAL",
]
