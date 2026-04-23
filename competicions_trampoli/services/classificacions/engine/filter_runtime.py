"""Runtime helpers for classificacio filter matching."""

from ....models import Inscripcio
from .._filters_impl import normalize_positive_int, normalized_text_token
from ..filters import normalize_classificacio_filters
from .model_utils import display_value, is_relational_field


def _normalized_group_filter_value(inscripcio) -> str:
    group_obj = getattr(inscripcio, "grup_competicio", None)
    display_num = normalize_positive_int(getattr(group_obj, "display_num", None))
    if display_num is not None:
        return str(display_num)

    legacy_group = normalize_positive_int(getattr(inscripcio, "grup", None))
    if legacy_group is not None:
        return str(legacy_group)

    return str(getattr(inscripcio, "grup", "") or "").strip()


def _inscripcio_matches_filter_field(inscripcio, field_name: str, allowed_values) -> bool:
    if not allowed_values:
        return True

    if is_relational_field(Inscripcio, field_name):
        candidate_id = normalize_positive_int(getattr(inscripcio, f"{field_name}_id", None))
        candidate_text = normalized_text_token(display_value(inscripcio, field_name))
        for raw in allowed_values:
            raw_id = normalize_positive_int(raw)
            if raw_id is not None and candidate_id is not None and raw_id == candidate_id:
                return True
            if candidate_text and candidate_text == normalized_text_token(raw):
                return True
        return False

    candidate_text = normalized_text_token(getattr(inscripcio, field_name, None))
    if not candidate_text:
        return False
    for raw in allowed_values:
        if candidate_text == normalized_text_token(raw):
            return True
    return False


def _inscripcio_matches_classificacio_filters(inscripcio, filtres) -> bool:
    filters = normalize_classificacio_filters(filtres)
    if not filters:
        return True

    if not _inscripcio_matches_filter_field(inscripcio, "entitat", filters.get("entitats_in") or []):
        return False
    if not _inscripcio_matches_filter_field(inscripcio, "categoria", filters.get("categories_in") or []):
        return False
    if not _inscripcio_matches_filter_field(inscripcio, "subcategoria", filters.get("subcategories_in") or []):
        return False

    group_filters = filters.get("grups_in") or []
    if group_filters:
        candidate_group = normalized_text_token(_normalized_group_filter_value(inscripcio))
        if not candidate_group:
            return False
        if all(candidate_group != normalized_text_token(raw) for raw in group_filters):
            return False

    return True


def _native_team_members_match_classificacio_filters(member_rows, filtres) -> bool:
    resolved_members = []
    seen_ids = set()
    for item in member_rows or []:
        if not isinstance(item, (list, tuple)) or not item:
            return False
        member = item[0]
        member_id = normalize_positive_int(getattr(member, "id", None))
        if member_id is None or member_id in seen_ids:
            continue
        seen_ids.add(member_id)
        resolved_members.append(member)

    if not resolved_members:
        return False

    for member in resolved_members:
        if not _inscripcio_matches_classificacio_filters(member, filtres):
            return False
    return True


__all__ = [
    "_normalized_group_filter_value",
    "_inscripcio_matches_filter_field",
    "_inscripcio_matches_classificacio_filters",
    "_native_team_members_match_classificacio_filters",
]
