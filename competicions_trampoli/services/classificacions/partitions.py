"""Compatibility boundary for classification partition helpers."""

from ..services_classificacions_2 import (
    BIRTH_YEAR_RANGE_PARTITION_CODE as _BIRTH_YEAR_RANGE_PARTITION_CODE,
)
from ..services_classificacions_2 import (
    normalize_birth_year_range_partition_config as _normalize_birth_year_range_partition_config,
)
from ..services_classificacions_2 import normalize_particions_config as _normalize_particions_config
from ..services_classificacions_2 import normalize_particions_v2_entries as _normalize_particions_v2_entries
from ..services_classificacions_2 import (
    normalize_schema_legacy_team_birth_partition as _normalize_schema_legacy_team_birth_partition,
)
from ..services_classificacions_2 import particio_codes_from_entries as _particio_codes_from_entries


BIRTH_YEAR_RANGE_PARTITION_CODE = _BIRTH_YEAR_RANGE_PARTITION_CODE


def normalize_birth_year_range_partition_config(*args, **kwargs):
    return _normalize_birth_year_range_partition_config(*args, **kwargs)


def normalize_particions_config(*args, **kwargs):
    return _normalize_particions_config(*args, **kwargs)


def normalize_particions_v2_entries(*args, **kwargs):
    return _normalize_particions_v2_entries(*args, **kwargs)


def normalize_schema_legacy_team_birth_partition(*args, **kwargs):
    return _normalize_schema_legacy_team_birth_partition(*args, **kwargs)


def particio_codes_from_entries(*args, **kwargs):
    return _particio_codes_from_entries(*args, **kwargs)

__all__ = [
    "BIRTH_YEAR_RANGE_PARTITION_CODE",
    "normalize_birth_year_range_partition_config",
    "normalize_particions_config",
    "normalize_particions_v2_entries",
    "normalize_schema_legacy_team_birth_partition",
    "particio_codes_from_entries",
]
