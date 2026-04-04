from types import SimpleNamespace

from .builder import with_mode_resolution
from .compute import compute_classificacio
from .display import get_display_columns
from .partitions import normalize_schema_legacy_team_birth_partition
from .validation import (
    build_validation_error_details,
    validate_schema_for_competicio_detailed,
)


def prepare_schema_for_persistence(competicio, schema_local, *, tipus="individual"):
    schema_local, validation_errors, validation_details = validate_schema_for_competicio_detailed(
        competicio,
        schema_local,
        tipus=tipus,
    )
    if validation_errors:
        return {
            "schema": schema_local,
            "errors": validation_errors,
            "error_details": build_validation_error_details(validation_details or validation_errors),
        }

    schema_local, _legacy_info = normalize_schema_legacy_team_birth_partition(
        competicio,
        schema_local,
        tipus=tipus,
        persist=True,
    )
    schema_local = with_mode_resolution(competicio, tipus, schema_local)
    return {
        "schema": schema_local,
        "errors": [],
        "error_details": [],
    }


def execute_classificacio_runtime(
    competicio,
    *,
    schema_local,
    tipus="individual",
    compute_fn=compute_classificacio,
    invalid_message="Configuracio de classificacio invalida.",
    runtime_message="No s'ha pogut renderitzar la classificacio.",
):
    schema_local, validation_errors, validation_details = validate_schema_for_competicio_detailed(
        competicio,
        schema_local,
        tipus=tipus,
    )
    columns = get_display_columns(schema_local if isinstance(schema_local, dict) else (schema_local or {}))
    if validation_errors:
        return {
            "schema": schema_local,
            "columns": columns,
            "parts": [],
            "error": {
                "message": invalid_message,
                "errors": validation_errors,
                "error_details": build_validation_error_details(validation_details or validation_errors),
            },
        }

    try:
        data = compute_fn(
            competicio,
            SimpleNamespace(schema=schema_local, tipus=tipus),
        )
    except Exception as exc:
        errors = [str(exc or "").strip() or runtime_message]
        return {
            "schema": schema_local,
            "columns": columns,
            "parts": [],
            "error": {
                "message": runtime_message,
                "errors": errors,
                "error_details": build_validation_error_details(errors),
            },
        }

    return {
        "schema": schema_local,
        "columns": columns,
        "parts": [{"particio": key, "rows": data[key]} for key in sorted(data.keys())],
        "error": None,
    }


__all__ = [
    "execute_classificacio_runtime",
    "prepare_schema_for_persistence",
]
