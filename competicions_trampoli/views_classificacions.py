"""Compatibility facade for split classificacions entrypoints.

This module intentionally keeps only stable reexports while the repo finishes
moving remaining legacy imports to the split `views_classificacions_*` modules
and service helpers under `services.classificacions`.
"""

from .services.classificacio_templates import (
    normalize_particions_schema as _normalize_particions_schema,
    schema_to_template_schema as _schema_to_template_schema,
    template_schema_to_competicio_schema as _template_schema_to_competicio_schema_service,
)
from .services.classificacions.builder import scoreable_codes_by_app_id as _scoreable_codes_by_app_id
from .services.classificacions.export import _normalize_excel_cell
from .services.classificacions.validation import (
    build_metric_meta_for_comp_aparell as _build_metric_meta_for_comp_aparell,
    build_scoreable_meta_for_schema as _build_scoreable_meta_for_schema,
    validate_particions_schema as _validate_particions_schema,
    validate_schema_for_competicio as _validate_schema_for_competicio,
)
from .views_classificacions_builder import (
    ClassificacionsHome,
    classificacio_delete,
    classificacio_preview,
    classificacio_reorder,
    classificacio_save,
)
from .views_classificacions_export import classificacions_live_export_excel
from .views_classificacions_live import (
    ClassificacionsLive,
    ClassificacionsLoopLive,
    PublicClassificacionsLive,
    PublicClassificacionsLoopLive,
    classificacions_live_data,
    public_classificacions_live_data,
)
from .views_classificacions_templates import (
    classificacio_template_apply,
    classificacio_template_list,
    classificacio_template_save,
    classificacio_template_validate,
)


def _template_schema_to_competicio_schema(*args, **kwargs):
    schema_local, mapping_warnings, mapping, _compat_meta = _template_schema_to_competicio_schema_service(*args, **kwargs)
    return schema_local, mapping_warnings, mapping

__all__ = [
    "ClassificacionsHome",
    "ClassificacionsLive",
    "ClassificacionsLoopLive",
    "PublicClassificacionsLive",
    "PublicClassificacionsLoopLive",
    "_build_metric_meta_for_comp_aparell",
    "_build_scoreable_meta_for_schema",
    "_normalize_excel_cell",
    "_normalize_particions_schema",
    "_schema_to_template_schema",
    "_scoreable_codes_by_app_id",
    "_template_schema_to_competicio_schema",
    "_validate_particions_schema",
    "_validate_schema_for_competicio",
    "classificacio_delete",
    "classificacio_preview",
    "classificacio_reorder",
    "classificacio_save",
    "classificacio_template_apply",
    "classificacio_template_list",
    "classificacio_template_save",
    "classificacio_template_validate",
    "classificacions_live_data",
    "classificacions_live_export_excel",
    "public_classificacions_live_data",
]
