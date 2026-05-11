import json

from django.db import transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from ...models import Competicio
from ...models.competicio import ProgramUnit
from ...models.rotacions import RotacioAssignacio, RotacioEstacio, RotacioFranja
from ...models.scoring import SerieEquip
from ...services.shared.competition_groups import get_group_maps
from ._shared import (
    _normalize_grups,
    _split_program_keys,
    _sync_assignacio_groups,
    _sync_assignacio_program_units,
    _sync_assignacio_series,
)


@require_POST
@csrf_protect
def rotacions_save(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invàlid")

    # Esperem:
    # { "cells": [ {"franja":1,"estacio":2,"grups":[3,5]}, ... ] }
    # Compat legacy: {"grup": 3}
    cells = payload.get("cells", [])
    if not isinstance(cells, list):
        return HttpResponseBadRequest("Format incorrecte")

    franges_by_id = {
        fr.id: fr
        for fr in RotacioFranja.objects.filter(competicio=competicio)
    }
    franja_ids = set(franges_by_id.keys())
    estacions = list(
        RotacioEstacio.objects
        .filter(competicio=competicio)
        .select_related("comp_aparell__aparell")
    )
    estacio_ids = {int(estacio.id) for estacio in estacions}
    estacions_by_id = {int(estacio.id): estacio for estacio in estacions}
    groups_by_id = get_group_maps(competicio)["by_id"]
    series_by_id = {
        int(serie.id): serie
        for serie in SerieEquip.objects.filter(competicio=competicio, actiu=True).select_related("comp_aparell")
    }
    program_units_by_id = {
        int(unit.id): unit
        for unit in (
            ProgramUnit.objects
            .filter(fase__competicio=competicio)
            .select_related("fase", "fase__comp_aparell")
        )
    }
    seen_groups_by_franja = {}
    seen_series_by_franja = {}
    seen_program_units_by_franja = {}
    validation_errors = []
    normalized_cells = []

    for c in cells:
        if not isinstance(c, dict):
            continue
        try:
            fr_id = int(c.get("franja"))
            es_id = int(c.get("estacio"))
        except Exception:
            continue

        if fr_id not in franja_ids or es_id not in estacio_ids:
            continue

        franja = franges_by_id.get(fr_id)
        if franja is None or not getattr(franja, "is_competitive", False):
            continue

        if "items" in c:
            groups, series, program_units = _split_program_keys(c.get("items"))
        elif "grups" in c:
            groups = _normalize_grups(c.get("grups"))
            series = []
            program_units = []
        else:
            groups = _normalize_grups(c.get("grup", None))
            series = []
            program_units = []

        estacio = estacions_by_id.get(es_id)
        is_team_station = bool(
            estacio
            and getattr(estacio, "tipus", "") == "aparell"
            and getattr(getattr(estacio, "comp_aparell", None), "aparell", None)
            and getattr(estacio.comp_aparell.aparell, "competition_unit", "") == "team"
        )
        if is_team_station:
            groups = []
            series = [
                serie_id
                for serie_id in series
                if serie_id in series_by_id and int(series_by_id[serie_id].comp_aparell_id or 0) == int(getattr(estacio, "comp_aparell_id", 0) or 0)
            ]
        else:
            series = []
        program_units = [
            unit_id
            for unit_id in program_units
            if unit_id in program_units_by_id
            and int(getattr(getattr(program_units_by_id[unit_id], "fase", None), "comp_aparell_id", 0) or 0)
            == int(getattr(estacio, "comp_aparell_id", 0) or 0)
        ]

        for group_id in groups:
            owner_map = seen_groups_by_franja.setdefault(fr_id, {})
            previous_estacio = owner_map.setdefault(group_id, es_id)
            if previous_estacio != es_id:
                validation_errors.append(
                    f"El grup {group_id} no pot estar assignat a dues estacions dins la mateixa franja."
                )
        for serie_id in series:
            owner_map = seen_series_by_franja.setdefault(fr_id, {})
            previous_estacio = owner_map.setdefault(serie_id, es_id)
            if previous_estacio != es_id:
                validation_errors.append(
                    f"La serie {serie_id} no pot estar assignada a dues estacions dins la mateixa franja."
                )
        for unit_id in program_units:
            owner_map = seen_program_units_by_franja.setdefault(fr_id, {})
            previous_estacio = owner_map.setdefault(unit_id, es_id)
            if previous_estacio != es_id:
                validation_errors.append(
                    f"La unitat programable {unit_id} no pot estar assignada a dues estacions dins la mateixa franja."
                )

        normalized_cells.append(
            {
                "franja_id": fr_id,
                "estacio_id": es_id,
                "groups": groups,
                "series": series,
                "program_units": program_units,
            }
        )

    if validation_errors:
        return JsonResponse({"ok": False, "errors": validation_errors}, status=400)

    with transaction.atomic():
        for cell in normalized_cells:
            fr_id = cell["franja_id"]
            es_id = cell["estacio_id"]
            assignacio, _created = RotacioAssignacio.objects.update_or_create(
                competicio=competicio,
                franja_id=fr_id,
                estacio_id=es_id,
                defaults={
                    "grups": [],
                    "grup": None,
                },
            )
            _sync_assignacio_groups(assignacio, cell["groups"], groups_by_id)
            _sync_assignacio_series(assignacio, cell["series"], series_by_id)
            _sync_assignacio_program_units(assignacio, cell["program_units"], program_units_by_id)

    return JsonResponse({"ok": True})


__all__ = ["rotacions_save"]

