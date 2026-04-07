from __future__ import annotations

from typing import Optional, Tuple

from ...models.competicio import CompeticioAparell
from ...models.scoring import ScoringSchema


def resolve_scoring_schema_for_comp_aparell(
    comp_aparell: Optional[CompeticioAparell],
) -> Tuple[Optional[ScoringSchema], dict]:
    if comp_aparell is None:
        return None, {}

    schema_obj = (
        ScoringSchema.objects
        .filter(comp_aparell=comp_aparell)
        .select_related("aparell", "comp_aparell")
        .first()
    )
    if schema_obj is not None:
        return schema_obj, (schema_obj.schema if isinstance(schema_obj.schema, dict) else {})

    schema_obj = (
        ScoringSchema.objects
        .filter(aparell=comp_aparell.aparell, comp_aparell__isnull=True)
        .select_related("aparell", "comp_aparell")
        .first()
    )
    if schema_obj is not None:
        return schema_obj, (schema_obj.schema if isinstance(schema_obj.schema, dict) else {})

    schema_obj, _ = ScoringSchema.objects.get_or_create(
        aparell=comp_aparell.aparell,
        defaults={"schema": {}},
    )
    return schema_obj, (schema_obj.schema if isinstance(schema_obj.schema, dict) else {})
