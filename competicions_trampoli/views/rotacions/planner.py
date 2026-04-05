import json

from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from ...models import Competicio
from ...models.rotacions import RotacioAssignacio, RotacioEstacio, RotacioFranja
from ...models.scoring import SerieEquip
from ...services.shared.competition_groups import (
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
    get_rotacions_order_modes,
)
from ...services.teams.team_series import get_programmed_series_ids, serie_label
from ._shared import (
    _assignacio_grups,
    _get_export_meta,
    _logo_url_from_path,
    _rotacions_available_participant_fields,
    _sync_estacions_aparells,
)


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
    group_sidebar = [
        {
            "key": f"g:{group.id}",
            "kind": "group",
            "id": group.id,
            "label": group_labels_map[str(group.id)],
            "members_count": int(group_participant_counts.get(group.id, 0) or 0),
            "is_programmed": group.id in programmed_group_ids,
            "is_out_of_program": group.id in out_of_program_group_ids,
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
    programmed_series_ids = set(get_programmed_series_ids(competicio))
    series_sidebar = []
    program_item_labels = {str(group.id): group_labels_map[str(group.id)] for group in groups}
    program_item_labels.update({f"g:{group.id}": group_labels_map[str(group.id)] for group in groups})
    for serie in series_qs:
        label = f"{getattr(serie.comp_aparell.aparell, 'nom', '')} · {serie_label(serie)}"
        program_item_labels[f"s:{serie.id}"] = label
        series_sidebar.append({
            "key": f"s:{serie.id}",
            "kind": "series",
            "id": int(serie.id),
            "app_id": int(serie.comp_aparell_id),
            "label": label,
            "members_count": int(getattr(serie, "subjects_count", 0) or 0),
            "is_programmed": int(serie.id) in programmed_series_ids,
            "is_out_of_program": int(serie.id) not in programmed_series_ids,
        })
    program_sidebar = group_sidebar + series_sidebar

    estacions = list(
        RotacioEstacio.objects
        .filter(competicio=competicio, actiu=True)
        .select_related("comp_aparell__aparell")
        .order_by("ordre", "id")
    )
    franges = list(RotacioFranja.objects.filter(competicio=competicio).order_by("ordre", "id"))
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
            "label": str(getattr(aparell, "nom", "") or ""),
        }

    assigns = (
        RotacioAssignacio.objects
        .filter(competicio=competicio)
        .select_related("franja", "estacio")
        .prefetch_related("grup_links__grup", "serie_links__serie")
    )

    grid = {}  # grid[franja_id][estacio_id] = [grups]
    for a in assigns:
        estacio = getattr(a, "estacio", None)
        is_team_station = bool(
            estacio
            and getattr(estacio, "tipus", "") == "aparell"
            and getattr(getattr(estacio, "comp_aparell", None), "aparell", None)
            and getattr(estacio.comp_aparell.aparell, "competition_unit", "") == "team"
        )
        if is_team_station:
            grid.setdefault(a.franja_id, {})[a.estacio_id] = [f"s:{serie_id}" for serie_id in assignacio_series(a)]
        else:
            grid.setdefault(a.franja_id, {})[a.estacio_id] = [f"g:{group_id}" for group_id in _assignacio_grups(a)]

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
        "station_modes_json": json.dumps(station_modes, ensure_ascii=False),
        "franja_order_modes_json": json.dumps(franja_modes, ensure_ascii=False),
        "export_meta_json": json.dumps(export_meta, ensure_ascii=False),
        "export_participant_fields_json": json.dumps(export_participant_fields, ensure_ascii=False),
        "grups_json": json.dumps(grups, ensure_ascii=False),
        "out_of_program_groups_count": sum(1 for item in program_sidebar if item["members_count"] > 0 and item["is_out_of_program"]),
        "out_of_program_members_total": sum(item["members_count"] for item in program_sidebar if item["members_count"] > 0 and item["is_out_of_program"]),
        "show_out_of_program_in_competition_views": show_out_of_program_in_competition_views(competicio),
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

