import json
import unicodedata
from pathlib import Path

from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from ...models import Competicio, Inscripcio
from ...models.competicio import ProgramUnit, ProgramUnitSlot
from ...models.rotacions import RotacioAssignacio, RotacioAssignacioProgramUnit, RotacioEstacio, RotacioFranja
from ...models.scoring import SerieEquip, SerieEquipItem, TeamCompetitiveSubject
from ...services.avatar.rotacions.messages import AVATAR_MESSAGES as ROTACIONS_AVATAR_MESSAGES
from ...services.shared.competition_groups import (
    get_group_board_filter_facets,
    get_group_maps,
    get_group_participant_counts,
    get_out_of_program_group_ids,
    get_programmed_group_ids,
    group_label,
    set_show_out_of_program_in_competition_views,
    show_out_of_program_in_competition_views,
)
from ...services.rotacions.rotacions_ordering import (
    ORDER_MODE_CHOICES,
    ORDER_MODE_LABELS,
    assignacio_series,
    assignacio_program_units,
    get_rotacions_order_modes,
)
from ...services.fases.logos import selected_logo_path_for_app
from ...services.teams.team_series import get_programmed_series_ids, serie_label
from ._shared import (
    _assignacio_grups,
    _get_export_meta,
    _logo_url_from_path,
    _rotacions_available_participant_fields,
    _sync_estacions_aparells,
)


def _is_competitive_franja(franja):
    return getattr(franja, "tipus", RotacioFranja.TIPUS_COMPETITION) == RotacioFranja.TIPUS_COMPETITION


def _logo_key(value):
    text = unicodedata.normalize("NFD", str(value or "").strip().lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return "".join(ch if ch.isalnum() else " " for ch in text).strip()


def _rotacions_logo_candidates(competicio):
    root = Path(__file__).resolve().parents[2] / "static" / "rotacions" / "aparells"
    discipline = str(getattr(competicio, "tipus", "") or "").strip().lower()
    if discipline not in {"artistica", "ritmica", "trampoli"}:
        discipline = "trampoli"
    dirs = []
    dirs.append(root / discipline)
    dirs.append(root)
    out = []
    seen = set()
    for directory in dirs:
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
                rel = path.relative_to(root.parents[1]).as_posix()
                if rel in seen:
                    continue
                seen.add(rel)
                out.append({"path": rel, "key": _logo_key(path.stem)})
    return out


def _rotacions_logo_path_for_app(comp_aparell):
    if not comp_aparell:
        return ""
    candidates = _rotacions_logo_candidates(comp_aparell.competicio)
    if not candidates:
        return ""
    selected = selected_logo_path_for_app(comp_aparell)
    selected_key = _logo_key(Path(selected).stem)
    if selected_key:
        for candidate in candidates:
            if candidate["key"] == selected_key:
                return candidate["path"]
    code = _logo_key(getattr(comp_aparell, "display_codi", ""))
    name = _logo_key(getattr(comp_aparell, "display_nom", ""))
    haystack = f"{code} {name}".strip()
    for candidate in candidates:
        if candidate["key"] and candidate["key"] in haystack:
            return candidate["path"]
    for candidate in candidates:
        key_parts = [part for part in candidate["key"].split() if part]
        if any(part in haystack for part in key_parts):
            return candidate["path"]
    return candidates[0]["path"]


def _clean_filter_values(values):
    return sorted({
        str(value or "").strip()
        for value in (values or [])
        if str(value or "").strip()
    })


def _clean_int_list(values):
    out = []
    seen = set()
    for raw in values or []:
        try:
            value = int(raw)
        except Exception:
            continue
        if value <= 0 or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _inscripcio_facet_rows(competicio, inscripcio_ids):
    clean_ids = _clean_int_list(inscripcio_ids)
    if not clean_ids:
        return {}
    rows = (
        Inscripcio.objects
        .filter(competicio=competicio, id__in=clean_ids)
        .only("id", "nom_i_cognoms", "categoria", "subcategoria", "entitat")
    )
    out = {}
    for ins in rows:
        parts = [
            getattr(ins, "nom_i_cognoms", ""),
            getattr(ins, "categoria", ""),
            getattr(ins, "subcategoria", ""),
            getattr(ins, "entitat", ""),
        ]
        out[int(ins.id)] = {
            "categories": _clean_filter_values([getattr(ins, "categoria", "")]),
            "subcategories": _clean_filter_values([getattr(ins, "subcategoria", "")]),
            "entitats": _clean_filter_values([getattr(ins, "entitat", "")]),
            "search_text": " ".join(str(part or "").strip() for part in parts if str(part or "").strip()),
        }
    return out


def _facets_from_member_ids(member_ids, inscripcio_facets):
    categories = set()
    subcategories = set()
    entitats = set()
    search_parts = []
    for member_id in _clean_int_list(member_ids):
        row = inscripcio_facets.get(member_id)
        if not row:
            continue
        categories.update(row.get("categories") or [])
        subcategories.update(row.get("subcategories") or [])
        entitats.update(row.get("entitats") or [])
        search = str(row.get("search_text") or "").strip()
        if search:
            search_parts.append(search)
    return {
        "categories": sorted(categories),
        "subcategories": sorted(subcategories),
        "entitats": sorted(entitats),
        "search_text": " ".join(search_parts).strip(),
    }


def _build_series_filter_facets(competicio, series_ids):
    clean_ids = _clean_int_list(series_ids)
    if not clean_ids:
        return {}
    member_ids_by_serie = {serie_id: [] for serie_id in clean_ids}
    subject_ids = set()
    for item in (
        SerieEquipItem.objects
        .filter(serie_id__in=clean_ids)
        .select_related("team_subject")
    ):
        subject = getattr(item, "team_subject", None)
        subject_ids.update(_clean_int_list(getattr(subject, "member_ids", []) if subject else []))
        member_ids_by_serie.setdefault(int(item.serie_id), []).extend(
            _clean_int_list(getattr(subject, "member_ids", []) if subject else [])
        )
    inscripcio_facets = _inscripcio_facet_rows(competicio, subject_ids)
    return {
        serie_id: _facets_from_member_ids(member_ids, inscripcio_facets)
        for serie_id, member_ids in member_ids_by_serie.items()
    }


def _build_program_unit_filter_facets(competicio, unit_ids):
    clean_ids = _clean_int_list(unit_ids)
    if not clean_ids:
        return {}
    member_ids_by_unit = {unit_id: [] for unit_id in clean_ids}
    team_subject_ids = set()
    for slot in (
        ProgramUnitSlot.objects
        .filter(unit_id__in=clean_ids, subject_id__isnull=False)
        .only("unit_id", "subject_kind", "subject_id")
    ):
        kind = str(getattr(slot, "subject_kind", "") or "").strip().lower()
        subject_id = int(getattr(slot, "subject_id", 0) or 0)
        if subject_id <= 0:
            continue
        if kind == "inscripcio":
            member_ids_by_unit.setdefault(int(slot.unit_id), []).append(subject_id)
        elif kind == "team_unit":
            team_subject_ids.add(subject_id)

    team_subject_members = {
        int(subject.id): _clean_int_list(subject.member_ids)
        for subject in TeamCompetitiveSubject.objects.filter(id__in=team_subject_ids).only("id", "member_ids")
    }
    for slot in (
        ProgramUnitSlot.objects
        .filter(unit_id__in=clean_ids, subject_kind="team_unit", subject_id__in=team_subject_ids)
        .only("unit_id", "subject_id")
    ):
        member_ids_by_unit.setdefault(int(slot.unit_id), []).extend(
            team_subject_members.get(int(slot.subject_id or 0), [])
        )

    all_member_ids = set()
    for member_ids in member_ids_by_unit.values():
        all_member_ids.update(_clean_int_list(member_ids))
    inscripcio_facets = _inscripcio_facet_rows(competicio, all_member_ids)
    return {
        unit_id: _facets_from_member_ids(member_ids, inscripcio_facets)
        for unit_id, member_ids in member_ids_by_unit.items()
    }


def _filter_option_payload(values):
    return [
        {"value": value, "label": value}
        for value in _clean_filter_values(values)
    ]


def _program_filter_options(program_sidebar):
    categories = []
    subcategories = []
    entitats = []
    for item in program_sidebar:
        categories.extend(item.get("categories") or [])
        subcategories.extend(item.get("subcategories") or [])
        entitats.extend(item.get("entitats") or [])
    return {
        "categories": _filter_option_payload(categories),
        "subcategories": _filter_option_payload(subcategories),
        "entitats": _filter_option_payload(entitats),
    }


def rotacions_planner(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)

    _sync_estacions_aparells(competicio)

    group_maps = get_group_maps(competicio, include_inactive=False)
    groups = group_maps["groups"]
    group_labels_map = {
        str(group.id): group_label(group)
        for group in groups
    }
    group_participant_counts = get_group_participant_counts(competicio)
    programmed_group_ids = get_programmed_group_ids(competicio)
    out_of_program_group_ids = get_out_of_program_group_ids(competicio)
    group_filter_facets = get_group_board_filter_facets(competicio, [group.id for group in groups])
    group_sidebar = [
        {
            "key": f"g:{group.id}",
            "kind": "group",
            "id": group.id,
            "label": group_labels_map[str(group.id)],
            "members_count": int(group_participant_counts.get(group.id, 0) or 0),
            "is_programmed": group.id in programmed_group_ids,
            "is_out_of_program": group.id in out_of_program_group_ids,
            **(group_filter_facets.get(group.id) or {}),
        }
        for group in groups
    ]
    grups = [group.id for group in groups]
    grups_display = [{"id": group.id, "label": group_labels_map[str(group.id)]} for group in groups]

    series_qs = (
        SerieEquip.objects
        .filter(competicio=competicio, actiu=True, comp_aparell__actiu=True)
        .select_related("comp_aparell__aparell")
        .annotate(subjects_count=Count("items"))
        .order_by("comp_aparell__ordre", "comp_aparell_id", "display_num", "id")
    )
    series_rows = list(series_qs)
    series_filter_facets = _build_series_filter_facets(competicio, [serie.id for serie in series_rows])
    programmed_series_ids = set(get_programmed_series_ids(competicio))
    series_sidebar = []
    program_item_labels = {str(group.id): group_labels_map[str(group.id)] for group in groups}
    program_item_labels.update({f"g:{group.id}": group_labels_map[str(group.id)] for group in groups})
    for serie in series_rows:
        app_label = getattr(serie.comp_aparell, "display_nom", "") or getattr(serie.comp_aparell.aparell, "nom", "")
        label = f"{app_label} · {serie_label(serie)}"
        program_item_labels[f"s:{serie.id}"] = label
        facets = series_filter_facets.get(int(serie.id), {})
        series_sidebar.append({
            "key": f"s:{serie.id}",
            "kind": "series",
            "id": int(serie.id),
            "app_id": int(serie.comp_aparell_id),
            "label": label,
            "members_count": int(getattr(serie, "subjects_count", 0) or 0),
            "is_programmed": int(serie.id) in programmed_series_ids,
            "is_out_of_program": int(serie.id) not in programmed_series_ids,
            **facets,
        })

    programmed_program_unit_ids = set(
        RotacioAssignacioProgramUnit.objects
        .filter(assignacio__competicio=competicio)
        .values_list("program_unit_id", flat=True)
        .distinct()
    )
    program_units_qs = (
        ProgramUnit.objects
        .filter(fase__competicio=competicio)
        .select_related("fase", "fase__comp_aparell", "fase__comp_aparell__aparell")
        .annotate(slots_count=Count("slots"))
        .order_by("fase__comp_aparell__ordre", "fase__ordre", "ordre", "id")
    )
    program_unit_rows = list(program_units_qs)
    program_unit_filter_facets = _build_program_unit_filter_facets(competicio, [unit.id for unit in program_unit_rows])
    program_unit_sidebar = []
    for unit in program_unit_rows:
        fase = unit.fase
        comp_aparell = fase.comp_aparell
        app_label = getattr(comp_aparell, "display_nom", "") or getattr(comp_aparell.aparell, "nom", "")
        label = f"{app_label} · {fase.nom} · {unit.nom}"
        program_item_labels[f"pu:{unit.id}"] = label
        facets = program_unit_filter_facets.get(int(unit.id), {})
        program_unit_sidebar.append({
            "key": f"pu:{unit.id}",
            "kind": "program_unit",
            "id": int(unit.id),
            "app_id": int(fase.comp_aparell_id),
            "phase_id": int(fase.id),
            "phase_label": fase.nom,
            "label": label,
            "members_count": int(getattr(unit, "slots_count", 0) or unit.capacity or 0),
            "is_programmed": int(unit.id) in programmed_program_unit_ids,
            "is_out_of_program": int(unit.id) not in programmed_program_unit_ids,
            **facets,
        })
    program_sidebar = group_sidebar + series_sidebar + program_unit_sidebar
    program_filter_options = _program_filter_options(program_sidebar)

    estacions = list(
        RotacioEstacio.objects
        .filter(competicio=competicio, actiu=True)
        .select_related("comp_aparell__aparell")
        .order_by("ordre", "id")
    )
    for estacio in estacions:
        estacio.ui_logo_path = _rotacions_logo_path_for_app(getattr(estacio, "comp_aparell", None))
    franges = list(RotacioFranja.objects.filter(competicio=competicio).order_by("ordre_visual", "id"))
    franja_notes = [
        {
            "franja_id": int(franja.id),
            "label": franja.display_label,
            "hora_inici": franja.hora_inici.strftime("%H:%M"),
            "hora_fi": franja.hora_fi.strftime("%H:%M"),
            "nota_interna": franja.nota_interna,
        }
        for franja in franges
        if str(getattr(franja, "nota_interna", "") or "").strip()
    ]
    franja_type_options = [
        {"value": value, "label": label}
        for value, label in RotacioFranja.TIPUS_CHOICES
    ]
    franja_modes = get_rotacions_order_modes(competicio)
    export_meta = _get_export_meta(competicio)
    export_meta["logo_url"] = _logo_url_from_path(export_meta.get("logo_path", ""))
    export_participant_fields = _rotacions_available_participant_fields(competicio)
    station_modes = {}
    for estacio in estacions:
        mode = "none"
        comp_aparell_id = getattr(estacio, "comp_aparell_id", None)
        comp_aparell = getattr(estacio, "comp_aparell", None)
        aparell = getattr(comp_aparell, "aparell", None)
        if getattr(estacio, "tipus", "") == "aparell" and comp_aparell_id:
            if aparell is not None and getattr(aparell, "competition_unit", "") == "team":
                mode = "series"
            else:
                mode = "group"
        station_modes[str(estacio.id)] = {
            "mode": mode,
            "comp_aparell_id": int(comp_aparell_id or 0) or None,
            "label": str(getattr(comp_aparell, "display_nom", "") or getattr(aparell, "nom", "") or ""),
        }

    assigns = (
        RotacioAssignacio.objects
        .filter(competicio=competicio)
        .select_related("franja", "estacio")
        .prefetch_related("grup_links__grup", "serie_links__serie", "program_unit_links__program_unit__fase")
    )
    competition_franja_ids = {fr.id for fr in franges if _is_competitive_franja(fr)}

    grid = {}  # grid[franja_id][estacio_id] = [grups]
    for a in assigns:
        if a.franja_id not in competition_franja_ids:
            continue
        estacio = getattr(a, "estacio", None)
        is_team_station = bool(
            estacio
            and getattr(estacio, "tipus", "") == "aparell"
            and getattr(getattr(estacio, "comp_aparell", None), "aparell", None)
            and getattr(estacio.comp_aparell.aparell, "competition_unit", "") == "team"
        )
        if is_team_station:
            base_keys = [f"s:{serie_id}" for serie_id in assignacio_series(a)]
        else:
            base_keys = [f"g:{group_id}" for group_id in _assignacio_grups(a)]
        grid.setdefault(a.franja_id, {})[a.estacio_id] = base_keys + [
            f"pu:{unit_id}" for unit_id in assignacio_program_units(a)
        ]

    ctx = {
        "competicio": competicio,
        "grups": grups,
        "grups_display": grups_display,
        "estacions": estacions,
        "franges": franges,
        "order_mode_options": [
            {"value": m, "label": ORDER_MODE_LABELS.get(m, m)}
            for m in ORDER_MODE_CHOICES
        ],
        "grid_json": json.dumps(grid, ensure_ascii=False),
        "group_labels_json": json.dumps(program_item_labels, ensure_ascii=False),
        "group_sidebar_json": json.dumps(program_sidebar, ensure_ascii=False),
        "program_filter_options_json": json.dumps(program_filter_options, ensure_ascii=False),
        "station_modes_json": json.dumps(station_modes, ensure_ascii=False),
        "franja_order_modes_json": json.dumps(franja_modes, ensure_ascii=False),
        "franja_type_options": franja_type_options,
        "franja_type_options_json": json.dumps(franja_type_options, ensure_ascii=False),
        "franja_default_colors_json": json.dumps(RotacioFranja.DEFAULT_BACKGROUND_COLORS, ensure_ascii=False),
        "franja_notes_json": json.dumps(franja_notes, ensure_ascii=False),
        "export_meta_json": json.dumps(export_meta, ensure_ascii=False),
        "export_participant_fields_json": json.dumps(export_participant_fields, ensure_ascii=False),
        "grups_json": json.dumps(grups, ensure_ascii=False),
        "out_of_program_groups_count": sum(1 for item in program_sidebar if item["members_count"] > 0 and item["is_out_of_program"]),
        "out_of_program_members_total": sum(item["members_count"] for item in program_sidebar if item["members_count"] > 0 and item["is_out_of_program"]),
        "show_out_of_program_in_competition_views": show_out_of_program_in_competition_views(competicio),
        "avatar_messages": ROTACIONS_AVATAR_MESSAGES,
        "avatar_initial_topic": "competition_rotations",
    }
    return render(request, "competicio/rotacions_planner.html", ctx)



@require_POST
@csrf_protect
def rotacions_out_of_program_visibility_save(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}

    value = bool(payload.get("value"))
    saved_value = set_show_out_of_program_in_competition_views(competicio, value)
    return JsonResponse({"ok": True, "value": saved_value})


__all__ = [
    "rotacions_out_of_program_visibility_save",
    "rotacions_planner",
]

