from __future__ import annotations

from dataclasses import dataclass

from django.http import JsonResponse

from ...models import Inscripcio
from ...services.shared.competition_groups import group_label


SCOPE_MODE_ALL = "all"
SCOPE_MODE_FILTERS = "filters"


@dataclass(frozen=True)
class SubjectScope:
    mode: str = SCOPE_MODE_ALL
    categoria: tuple[str, ...] = ()
    subcategoria: tuple[str, ...] = ()
    group_ids: tuple[int, ...] = ()

    @property
    def is_restricted(self) -> bool:
        return bool(
            self.mode == SCOPE_MODE_FILTERS
            and (self.categoria or self.subcategoria or self.group_ids)
        )

    def as_dict(self) -> dict:
        if not self.is_restricted:
            return {"mode": SCOPE_MODE_ALL, "categoria": [], "subcategoria": [], "group_ids": []}
        return {
            "mode": SCOPE_MODE_FILTERS,
            "categoria": list(self.categoria),
            "subcategoria": list(self.subcategoria),
            "group_ids": list(self.group_ids),
        }


def _clean_text_list(values) -> tuple[str, ...]:
    if values in (None, ""):
        return ()
    if isinstance(values, str):
        raw_items = [values]
    elif isinstance(values, (list, tuple, set)):
        raw_items = list(values)
    else:
        return ()
    out = []
    seen = set()
    for value in raw_items:
        clean = str(value or "").strip()
        if clean and clean not in seen:
            seen.add(clean)
            out.append(clean)
    return tuple(out)


def _clean_int_list(values) -> tuple[int, ...]:
    if values in (None, ""):
        return ()
    if isinstance(values, (str, int)):
        raw_items = [values]
    elif isinstance(values, (list, tuple, set)):
        raw_items = list(values)
    else:
        return ()
    out = []
    seen = set()
    for value in raw_items:
        try:
            clean = int(value)
        except (TypeError, ValueError):
            continue
        if clean > 0 and clean not in seen:
            seen.add(clean)
            out.append(clean)
    return tuple(out)


def normalize_subject_scope(raw_scope) -> SubjectScope:
    if isinstance(raw_scope, SubjectScope):
        return raw_scope
    if not isinstance(raw_scope, dict):
        return SubjectScope()
    mode = str(raw_scope.get("mode") or SCOPE_MODE_ALL).strip().lower()
    categoria = _clean_text_list(raw_scope.get("categoria") or raw_scope.get("categories"))
    subcategoria = _clean_text_list(raw_scope.get("subcategoria") or raw_scope.get("subcategories"))
    group_ids = _clean_int_list(raw_scope.get("group_ids") or raw_scope.get("groups"))
    if mode != SCOPE_MODE_FILTERS and not (categoria or subcategoria or group_ids):
        return SubjectScope()
    if not (categoria or subcategoria or group_ids):
        return SubjectScope()
    return SubjectScope(
        mode=SCOPE_MODE_FILTERS,
        categoria=categoria,
        subcategoria=subcategoria,
        group_ids=group_ids,
    )


def subject_scope_from_post(post_data) -> dict:
    scope = SubjectScope(
        mode=SCOPE_MODE_FILTERS,
        categoria=_clean_text_list(post_data.getlist("subject_scope_categoria")),
        subcategoria=_clean_text_list(post_data.getlist("subject_scope_subcategoria")),
        group_ids=_clean_int_list(post_data.getlist("subject_scope_group_ids")),
    )
    mode = str(post_data.get("subject_scope_mode") or SCOPE_MODE_ALL).strip().lower()
    if mode != SCOPE_MODE_FILTERS and not (scope.categoria or scope.subcategoria or scope.group_ids):
        return SubjectScope().as_dict()
    return scope.as_dict()


def filter_inscripcions_queryset_by_subject_scope(qs, raw_scope):
    scope = normalize_subject_scope(raw_scope)
    if not scope.is_restricted:
        return qs
    if scope.categoria:
        qs = qs.filter(categoria__in=scope.categoria)
    if scope.subcategoria:
        qs = qs.filter(subcategoria__in=scope.subcategoria)
    if scope.group_ids:
        qs = qs.filter(grup_competicio_id__in=scope.group_ids)
    return qs


def filter_score_entries_queryset_by_subject_scope(qs, raw_scope):
    scope = normalize_subject_scope(raw_scope)
    if not scope.is_restricted:
        return qs
    if scope.categoria:
        qs = qs.filter(inscripcio__categoria__in=scope.categoria)
    if scope.subcategoria:
        qs = qs.filter(inscripcio__subcategoria__in=scope.subcategoria)
    if scope.group_ids:
        qs = qs.filter(inscripcio__grup_competicio_id__in=scope.group_ids)
    return qs


def filter_team_subject_ids_by_subject_scope(subject_map: dict[int, dict], raw_scope, *, competicio) -> list[int]:
    scope = normalize_subject_scope(raw_scope)
    if not scope.is_restricted:
        return [int(subject_id) for subject_id in subject_map.keys()]
    return [
        int(subject_id)
        for subject_id, subject in (subject_map or {}).items()
        if subject_matches_scope(subject, scope.as_dict(), competicio=competicio)
    ]


def _subject_inscripcio(subject):
    if subject is None:
        return None
    if isinstance(subject, Inscripcio):
        return subject
    if isinstance(subject, dict):
        inscripcio = subject.get("inscripcio")
        if isinstance(inscripcio, Inscripcio):
            return inscripcio
    return None


def _subject_member_ids(subject) -> list[int]:
    if not isinstance(subject, dict):
        return []
    raw_ids = []
    team_subject = subject.get("team_subject")
    if team_subject is not None:
        raw_ids = getattr(team_subject, "member_ids", []) or []
    elif subject.get("member_ids") is not None:
        raw_ids = subject.get("member_ids") or []
    elif subject.get("members") is not None:
        raw_ids = [
            item.get("id") if isinstance(item, dict) else getattr(item, "id", None)
            for item in (subject.get("members") or [])
        ]
    return list(_clean_int_list(raw_ids))


def _inscripcio_matches_scope(inscripcio, scope: SubjectScope) -> bool:
    if not scope.is_restricted:
        return True
    if scope.categoria and str(inscripcio.categoria or "").strip() not in scope.categoria:
        return False
    if scope.subcategoria and str(inscripcio.subcategoria or "").strip() not in scope.subcategoria:
        return False
    if scope.group_ids and int(inscripcio.grup_competicio_id or 0) not in scope.group_ids:
        return False
    return True


def subject_matches_scope(subject, raw_scope, *, competicio=None) -> bool:
    scope = normalize_subject_scope(raw_scope)
    if not scope.is_restricted:
        return True

    inscripcio = _subject_inscripcio(subject)
    if inscripcio is not None:
        return _inscripcio_matches_scope(inscripcio, scope)

    if isinstance(subject, dict):
        if str(subject.get("subject_kind") or "").strip().lower() == "inscripcio":
            if scope.categoria and str(subject.get("categoria") or "").strip() not in scope.categoria:
                return False
            if scope.subcategoria and str(subject.get("subcategoria") or "").strip() not in scope.subcategoria:
                return False
            if scope.group_ids and int(subject.get("grup_competicio_id") or subject.get("group") or 0) not in scope.group_ids:
                return False
            return True

        member_ids = _subject_member_ids(subject)
        if member_ids and competicio is not None:
            members = list(Inscripcio.objects.filter(competicio=competicio, id__in=member_ids))
            if not members:
                return False
            return all(_inscripcio_matches_scope(member, scope) for member in members)

    return False


def filter_subject_dicts_by_subject_scope(subjects: list[dict], raw_scope, *, competicio=None) -> list[dict]:
    scope = normalize_subject_scope(raw_scope)
    if not scope.is_restricted:
        return list(subjects or [])
    return [
        subject
        for subject in (subjects or [])
        if subject_matches_scope(subject, scope, competicio=competicio)
    ]


def subject_scope_forbidden_response():
    return JsonResponse(
        {
            "ok": False,
            "error": "Aquest participant no forma part de l'abast assignat a aquest QR.",
            "reason": "subject_outside_assignment_scope",
        },
        status=403,
    )


def ensure_subject_allowed_by_scope(subject, raw_scope, *, competicio=None):
    if subject_matches_scope(subject, raw_scope, competicio=competicio):
        return None
    return subject_scope_forbidden_response()


def subject_scope_summary(raw_scope, *, competicio=None) -> str:
    scope = normalize_subject_scope(raw_scope)
    if not scope.is_restricted:
        return "Tots els participants"
    parts = []
    if scope.categoria:
        parts.append("Categories: " + ", ".join(scope.categoria))
    if scope.subcategoria:
        parts.append("Subcategories: " + ", ".join(scope.subcategoria))
    if scope.group_ids:
        labels = [f"Grup {group_id}" for group_id in scope.group_ids]
        if competicio is not None:
            groups = {
                int(group.id): group
                for group in competicio.grups_competicio.filter(id__in=scope.group_ids)
            }
            labels = [group_label(groups.get(group_id)) for group_id in scope.group_ids]
        parts.append("Grups: " + ", ".join(labels))
    return " | ".join(parts) if parts else "Tots els participants"


def subject_scope_options_for_competicio(competicio) -> dict:
    rows = (
        Inscripcio.objects
        .filter(competicio=competicio)
        .order_by("categoria", "subcategoria")
        .values_list("categoria", "subcategoria")
        .distinct()
    )
    categories = []
    subcategories = []
    for categoria, subcategoria in rows:
        clean_categoria = str(categoria or "").strip()
        clean_subcategoria = str(subcategoria or "").strip()
        if clean_categoria and clean_categoria not in categories:
            categories.append(clean_categoria)
        if clean_subcategoria and clean_subcategoria not in subcategories:
            subcategories.append(clean_subcategoria)
    groups = [
        {"id": int(group.id), "label": group_label(group)}
        for group in competicio.grups_competicio.filter(actiu=True).order_by("display_num", "id")
    ]
    return {
        "categories": categories,
        "subcategories": subcategories,
        "groups": groups,
    }


__all__ = [
    "SCOPE_MODE_ALL",
    "SCOPE_MODE_FILTERS",
    "SubjectScope",
    "ensure_subject_allowed_by_scope",
    "filter_inscripcions_queryset_by_subject_scope",
    "filter_score_entries_queryset_by_subject_scope",
    "filter_subject_dicts_by_subject_scope",
    "filter_team_subject_ids_by_subject_scope",
    "normalize_subject_scope",
    "subject_matches_scope",
    "subject_scope_from_post",
    "subject_scope_options_for_competicio",
    "subject_scope_summary",
]
