from __future__ import annotations

import copy
from typing import Iterable, Optional, Tuple

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


def ensure_local_scoring_schema_for_comp_aparell(comp_aparell: CompeticioAparell) -> ScoringSchema:
    schema_obj = (
        ScoringSchema.objects
        .filter(comp_aparell=comp_aparell)
        .select_related("aparell", "comp_aparell")
        .first()
    )
    if schema_obj is not None:
        return schema_obj

    _global_obj, global_schema = resolve_scoring_schema_for_comp_aparell(comp_aparell)
    return ScoringSchema.objects.create(
        comp_aparell=comp_aparell,
        schema=copy.deepcopy(global_schema if isinstance(global_schema, dict) else {}),
    )


def copy_global_scoring_schema_to_comp_aparell_if_missing(
    comp_aparell: CompeticioAparell,
) -> Optional[ScoringSchema]:
    if comp_aparell is None or not getattr(comp_aparell, "id", None) or not getattr(comp_aparell, "aparell_id", None):
        return None

    existing = (
        ScoringSchema.objects
        .filter(comp_aparell=comp_aparell)
        .select_related("aparell", "comp_aparell")
        .first()
    )
    if existing is not None:
        return existing

    global_schema = (
        ScoringSchema.objects
        .filter(aparell_id=comp_aparell.aparell_id, comp_aparell__isnull=True)
        .only("schema")
        .first()
    )
    if global_schema is None:
        return None

    return ScoringSchema.objects.create(
        comp_aparell=comp_aparell,
        schema=copy.deepcopy(global_schema.schema if isinstance(global_schema.schema, dict) else {}),
    )


def schema_by_comp_aparell_id(comp_aparells: Iterable[CompeticioAparell]) -> dict[int, dict]:
    apps = [app for app in comp_aparells if app is not None and getattr(app, "id", None)]
    if not apps:
        return {}

    by_id = {int(app.id): {} for app in apps}
    app_ids = list(by_id.keys())
    aparell_ids = {int(app.aparell_id) for app in apps if getattr(app, "aparell_id", None)}

    global_by_aparell = {
        int(schema.aparell_id): (schema.schema if isinstance(schema.schema, dict) else {})
        for schema in ScoringSchema.objects
        .filter(comp_aparell__isnull=True, aparell_id__in=aparell_ids)
        .only("aparell_id", "schema")
    }
    for app in apps:
        by_id[int(app.id)] = global_by_aparell.get(int(app.aparell_id), {}) or {}

    for schema in ScoringSchema.objects.filter(comp_aparell_id__in=app_ids).only("comp_aparell_id", "schema"):
        by_id[int(schema.comp_aparell_id)] = schema.schema if isinstance(schema.schema, dict) else {}

    return by_id
