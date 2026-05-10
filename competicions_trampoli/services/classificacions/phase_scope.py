from __future__ import annotations

from ...models.competicio import CompeticioAparellFase


PHASE_SCOPE_IMPLICIT = "implicit"
PHASE_SCOPE_PHASE = "phase"
PHASE_SCOPE_PER_APP = "per_app"


def _positive_int_or_none(value):
    try:
        clean = int(value)
    except (TypeError, ValueError):
        return None
    return clean if clean > 0 else None


def _normalize_single_phase_scope(raw_scope) -> dict:
    scope = raw_scope if isinstance(raw_scope, dict) else {}
    raw_phase_id = scope.get("fase_id")
    if raw_phase_id is None and isinstance(scope.get("fase"), dict):
        raw_phase_id = (scope.get("fase") or {}).get("id") or (scope.get("fase") or {}).get("fase_id")
    phase_id = _positive_int_or_none(raw_phase_id)
    if phase_id:
        return {"mode": PHASE_SCOPE_PHASE, "fase_id": phase_id}
    return {"mode": PHASE_SCOPE_IMPLICIT, "fase_id": None}


def normalize_phase_scope_payload(raw_scope) -> dict:
    scope = raw_scope if isinstance(raw_scope, dict) else {}
    raw_mode = str(scope.get("mode") or "").strip().lower()
    raw_apps = scope.get("apps") if isinstance(scope.get("apps"), dict) else {}
    if raw_mode == PHASE_SCOPE_PER_APP or raw_apps:
        apps = {}
        for raw_app_id, raw_app_scope in raw_apps.items():
            app_id = _positive_int_or_none(raw_app_id)
            if app_id is None:
                continue
            apps[str(app_id)] = _normalize_single_phase_scope(raw_app_scope)
        if apps:
            return {"mode": PHASE_SCOPE_PER_APP, "fase_id": None, "apps": apps}
    return _normalize_single_phase_scope(scope)


def normalize_schema_phase_scope(schema_local) -> dict:
    schema = schema_local if isinstance(schema_local, dict) else {}
    out = dict(schema)
    out["scope"] = normalize_phase_scope_payload(out.get("scope") or {})
    return out


def selected_phase_for_schema(competicio, schema_local):
    scope = normalize_phase_scope_payload((schema_local or {}).get("scope") if isinstance(schema_local, dict) else {})
    phase_id = scope.get("fase_id")
    if not phase_id:
        return None
    return (
        CompeticioAparellFase.objects
        .filter(competicio=competicio, id=phase_id)
        .select_related("comp_aparell", "comp_aparell__aparell")
        .first()
    )


def validate_phase_scope_for_competicio(competicio, schema_local, selected_app_ids=None) -> list[str]:
    schema = schema_local if isinstance(schema_local, dict) else {}
    scope = normalize_phase_scope_payload(schema.get("scope") or {})
    selected_ids = {
        int(app_id)
        for app_id in (selected_app_ids or [])
        if _positive_int_or_none(app_id)
    }
    if scope.get("mode") == PHASE_SCOPE_PER_APP:
        errors = []
        for raw_app_id, app_scope in (scope.get("apps") or {}).items():
            app_id = _positive_int_or_none(raw_app_id)
            if app_id is None:
                continue
            if selected_ids and app_id not in selected_ids:
                errors.append(f"scope.apps[{app_id}]: l'aparell no forma part de la classificacio.")
                continue
            phase_id = (app_scope or {}).get("fase_id")
            if not phase_id:
                continue
            phase = (
                CompeticioAparellFase.objects
                .filter(competicio=competicio, id=phase_id)
                .select_related("comp_aparell")
                .first()
            )
            if phase is None:
                errors.append(f"scope.apps[{app_id}].fase_id: fase {phase_id} no existeix en aquesta competicio.")
            elif int(phase.comp_aparell_id) != app_id:
                errors.append(
                    f"scope.apps[{app_id}].fase_id: la fase seleccionada no pertany a aquest aparell."
                )
        return errors

    phase_id = scope.get("fase_id")
    if not phase_id:
        return []
    phase = selected_phase_for_schema(competicio, {"scope": scope})
    if phase is None:
        return [f"scope.fase_id: fase {phase_id} no existeix en aquesta competicio."]
    if selected_ids and int(phase.comp_aparell_id) not in selected_ids:
        return [
            "scope.fase_id: la fase seleccionada pertany a un aparell que no forma part "
            "de la puntuacio de la classificacio."
        ]
    return []


__all__ = [
    "PHASE_SCOPE_IMPLICIT",
    "PHASE_SCOPE_PER_APP",
    "PHASE_SCOPE_PHASE",
    "normalize_phase_scope_payload",
    "normalize_schema_phase_scope",
    "selected_phase_for_schema",
    "validate_phase_scope_for_competicio",
]
