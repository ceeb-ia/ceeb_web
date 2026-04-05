import json
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import F, Max
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_time
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from ...models import Competicio
from ...models.rotacions import RotacioAssignacio, RotacioEstacio, RotacioFranja
from ...models.scoring import SerieEquip
from ...services.competition_groups import get_group_maps
from ...services.rotacions_ordering import set_rotacio_order_mode
from ._shared import (
    _assignacio_program_keys,
    _split_program_keys,
    _sync_assignacio_groups,
    _sync_assignacio_series,
)


@require_POST
@csrf_protect
def franges_auto_create(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invàlid")

    hi = parse_time(payload.get("hora_inici") or "")
    hf = parse_time(payload.get("hora_fi") or "")
    interval = payload.get("interval_min", None)
    clear_existing = bool(payload.get("clear_existing", False))
    titol_base = (payload.get("titol_base") or "Franja").strip()

    try:
        interval = int(interval)
    except Exception:
        return HttpResponseBadRequest("interval_min ha de ser un enter (minuts)")

    if not hi or not hf:
        return HttpResponseBadRequest("Hora inici/fi obligatòries")
    if interval <= 0:
        return HttpResponseBadRequest("interval_min ha de ser > 0")

    # Convertim TimeField a datetime “dummy” per sumar minuts
    day = datetime(2000, 1, 1)
    start = datetime.combine(day.date(), hi)
    end = datetime.combine(day.date(), hf)

    if end <= start:
        return HttpResponseBadRequest("hora_fi ha de ser posterior a hora_inici")

    with transaction.atomic():
        if clear_existing:
            # Esborrem assignacions i franges (mantindrem estacions)
            franges = RotacioFranja.objects.filter(competicio=competicio)
            RotacioAssignacio.objects.filter(competicio=competicio, franja__in=franges).delete()
            franges.delete()

        # ordre a partir del màxim actual
        base_ord = (RotacioFranja.objects.filter(competicio=competicio).aggregate(Max("ordre"))["ordre__max"] or 0)

        to_create = []
        cur = start
        idx = 1
        while cur < end:
            nxt = cur + timedelta(minutes=interval)
            if nxt > end:
                break  # no creem una franja “mig buida” (si vols que la creï igualment, t'ho canvio)
            base_ord += 1
            to_create.append(RotacioFranja(
                competicio=competicio,
                hora_inici=cur.time(),
                hora_fi=nxt.time(),
                ordre=base_ord,
                titol=f"{titol_base} {idx}",
            ))
            cur = nxt
            idx += 1

        RotacioFranja.objects.bulk_create(to_create)

    return JsonResponse({"ok": True, "created": len(to_create)})


@require_POST
@csrf_protect
def franja_create(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invàlid")

    hi = parse_time(payload.get("hora_inici") or "")
    hf = parse_time(payload.get("hora_fi") or "")
    titol = (payload.get("titol") or "").strip()

    if not hi or not hf:
        return HttpResponseBadRequest("Hora inici/fi obligatòries")

    max_ord = (RotacioFranja.objects.filter(competicio=competicio).aggregate(Max("ordre"))["ordre__max"] or 0) + 1

    f = RotacioFranja(competicio=competicio, hora_inici=hi, hora_fi=hf, ordre=max_ord, titol=titol)
    try:
        f.full_clean()
    except Exception as e:
        return HttpResponseBadRequest(str(e))

    f.save()
    return JsonResponse({"ok": True, "id": f.id})


@require_POST
@csrf_protect
def franja_delete(request, pk, franja_id):
    competicio = get_object_or_404(Competicio, pk=pk)
    f = get_object_or_404(RotacioFranja, pk=franja_id, competicio=competicio)

    day = datetime(2000, 1, 1).date()

    with transaction.atomic():
        anchor_ord = f.ordre

        # 🔑 Tanquem el forat: enganxem la cadena a l'hora d'inici de la franja eliminada
        anchor_time = datetime.combine(day, f.hora_inici)

        # 1) Esborrem assignacions i franja
        RotacioAssignacio.objects.filter(competicio=competicio, franja=f).delete()
        f.delete()

        # 2) Recalculem les franges de sota mantenint la durada original de cadascuna
        below = list(
            RotacioFranja.objects
            .filter(competicio=competicio, ordre__gt=anchor_ord)
            .order_by("ordre", "id")
        )

        prev_end = anchor_time
        for fr in below:
            s0 = datetime.combine(day, fr.hora_inici)
            e0 = datetime.combine(day, fr.hora_fi)
            if e0 <= s0:
                raise ValueError("Hi ha una franja amb durada no positiva")

            dur = e0 - s0
            new_start = prev_end
            new_end = new_start + dur

            fr.hora_inici = new_start.time()
            fr.hora_fi = new_end.time()
            prev_end = new_end

        if below:
            RotacioFranja.objects.bulk_update(below, ["hora_inici", "hora_fi"], batch_size=200)

        # 3) Reordenem 'ordre' perquè no quedin forats (recomanat)
        rest = list(RotacioFranja.objects.filter(competicio=competicio).order_by("ordre", "id"))
        for i, fr in enumerate(rest, start=1):
            fr.ordre = i
        if rest:
            RotacioFranja.objects.bulk_update(rest, ["ordre"], batch_size=200)

    return JsonResponse({"ok": True})


@require_POST
@csrf_protect
def franja_insert_after(request, pk, franja_id):
    competicio = get_object_or_404(Competicio, pk=pk)
    fr_prev = get_object_or_404(RotacioFranja, pk=franja_id, competicio=competicio)

    # Durada = durada de la franja anterior
    day = datetime(2000, 1, 1).date()
    prev_start = datetime.combine(day, fr_prev.hora_inici)
    prev_end = datetime.combine(day, fr_prev.hora_fi)

    if prev_end <= prev_start:
        return HttpResponseBadRequest("La franja base té hores invàlides.")

    delta = prev_end - prev_start  # timedelta
    new_start = prev_end
    new_end = new_start + delta

    # (Opcional) títol personalitzat
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}
    titol = (payload.get("titol") or "").strip()

    with transaction.atomic():
        # 1) Apliquem un offset temporal gran per evitar col·lisions amb el unique (competicio, ordre)
        qs = RotacioFranja.objects.filter(
            competicio=competicio,
            ordre__gt=fr_prev.ordre
        )

        OFFSET = 1000  # prou gran per sortir de la zona de valors reals
        qs.update(ordre=F("ordre") + OFFSET)

        # 2) Ara ja podem deixar-ho en el valor final (+1) sense col·lisions
        qs.update(ordre=F("ordre") - OFFSET + 1)

        # 3) Crear franja nova
        f_new = RotacioFranja.objects.create(
            competicio=competicio,
            hora_inici=new_start.time(),
            hora_fi=new_end.time(),
            ordre=fr_prev.ordre + 1,
            titol=titol or "",
        )

        # 4) Desplacem horaris de totes les franges que queden per sota (ara tenen ordre > fr_prev.ordre+1)
        to_shift = list(
            RotacioFranja.objects.filter(
                competicio=competicio,
                ordre__gt=f_new.ordre
            ).order_by("ordre", "id")
        )

        for f in to_shift:
            s = datetime.combine(day, f.hora_inici) + delta
            e = datetime.combine(day, f.hora_fi) + delta
            f.hora_inici = s.time()
            f.hora_fi = e.time()

        if to_shift:
            RotacioFranja.objects.bulk_update(to_shift, ["hora_inici", "hora_fi"], batch_size=200)

    return JsonResponse({"ok": True, "id": f_new.id})



@require_POST
@csrf_protect
def franja_update_inline(request, pk, franja_id):
    competicio = get_object_or_404(Competicio, pk=pk)
    fr = get_object_or_404(RotacioFranja, pk=franja_id, competicio=competicio)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invàlid")

    titol = (payload.get("titol") or "").strip()
    hora_inici = payload.get("hora_inici")
    hora_fi = payload.get("hora_fi")

    if not hora_inici or not hora_fi:
        return HttpResponseBadRequest("Falten hores")

    try:
        # esperem "HH:MM" (input type="time")
        hi = datetime.strptime(hora_inici, "%H:%M").time()
        hf = datetime.strptime(hora_fi, "%H:%M").time()
    except ValueError:
        return HttpResponseBadRequest("Format d'hora incorrecte (HH:MM)")

    day = datetime(2000, 1, 1).date()
    d_hi = datetime.combine(day, hi)
    d_hf = datetime.combine(day, hf)
    if d_hf <= d_hi:
        return HttpResponseBadRequest("L'hora de fi ha de ser posterior a l'hora d'inici")

    with transaction.atomic():
        # 1) Actualitza franja editada
        fr.titol = titol
        fr.hora_inici = hi
        fr.hora_fi = hf
        fr.save(update_fields=["titol", "hora_inici", "hora_fi"])

        # 2) Reajusta totes les franges per sota perquè quedin encadenades
        below = list(
            RotacioFranja.objects.filter(
                competicio=competicio,
                ordre__gt=fr.ordre
            ).order_by("ordre", "id")
        )

        prev_end = d_hf
        for f in below:
            # mantenim la durada original de cada franja
            s0 = datetime.combine(day, f.hora_inici)
            e0 = datetime.combine(day, f.hora_fi)
            if e0 <= s0:
                # si alguna té hores dolentes, parem per evitar fer més mal
                raise ValueError("Hi ha una franja amb durada no positiva")

            dur = e0 - s0
            new_start = prev_end
            new_end = new_start + dur

            f.hora_inici = new_start.time()
            f.hora_fi = new_end.time()
            prev_end = new_end

        if below:
            RotacioFranja.objects.bulk_update(below, ["hora_inici", "hora_fi"], batch_size=200)

    return JsonResponse({"ok": True})


@require_POST
@csrf_protect
def franja_order_mode_set(request, pk, franja_id):
    competicio = get_object_or_404(Competicio, pk=pk)
    get_object_or_404(RotacioFranja, pk=franja_id, competicio=competicio)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    mode = payload.get("mode")
    clean_mode = set_rotacio_order_mode(competicio, franja_id=franja_id, mode=mode)
    return JsonResponse({"ok": True, "franja_id": int(franja_id), "mode": clean_mode})


@require_POST
@csrf_protect
def rotacions_extrapolar(request, pk, franja_id):
    competicio = get_object_or_404(Competicio, pk=pk)
    fr_base = get_object_or_404(RotacioFranja, pk=franja_id, competicio=competicio)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}

    # quantes franges vols omplir a partir de la base
    count = payload.get("count", None)

    estacions = list(
        RotacioEstacio.objects.filter(competicio=competicio, actiu=True)
        .order_by("ordre", "id")
    )
    if not estacions:
        return HttpResponseBadRequest("No hi ha estacions actives.")

    if count is None:
        count = max(0, len(estacions) - 1)

    try:
        count = int(count)
    except Exception:
        return HttpResponseBadRequest("count ha de ser un enter.")
    if count <= 0:
        return JsonResponse({"ok": True, "created_franges": 0, "filled": 0})

    # 1) Llegim assignació de la franja base segons ordre d'estacions
    base_map = {}
    for a in (
        RotacioAssignacio.objects
        .filter(competicio=competicio, franja=fr_base)
        .select_related("estacio__comp_aparell__aparell")
        .prefetch_related("grup_links__grup", "serie_links__serie")
    ):
        base_map[a.estacio_id] = _assignacio_program_keys(a)

    base_groups = []
    for e in estacions:
        base_groups.append(base_map.get(e.id, []))

    # Si no hi ha cap grup definit, no té sentit extrapolar
    if all(len(gs) == 0 for gs in base_groups):
        return HttpResponseBadRequest("La franja base no té cap grup assignat.")

    # 2) Aconseguim/creem franges següents
    franges = list(RotacioFranja.objects.filter(competicio=competicio).order_by("ordre", "id"))
    idx_base = next((i for i, f in enumerate(franges) if f.id == fr_base.id), None)
    if idx_base is None:
        return HttpResponseBadRequest("Franja base no trobada al llistat.")

    # Interval per crear franges: preferim interval de la base; si no es pot, del veí anterior
    def _delta_minutes(f):
        # retorna minuts entre inici i fi, o None
        try:
            day = datetime(2000, 1, 1)
            s = datetime.combine(day.date(), f.hora_inici)
            t = datetime.combine(day.date(), f.hora_fi)
            if t <= s:
                return None
            return int((t - s).total_seconds() // 60)
        except Exception:
            return None

    interval_min = _delta_minutes(fr_base)
    if not interval_min:
        if idx_base > 0:
            interval_min = _delta_minutes(franges[idx_base - 1])
    if not interval_min:
        return HttpResponseBadRequest("No puc deduir l'interval (minuts) per crear franges noves.")

    # Ens assegurem que existeixen idx_base+1 ... idx_base+count
    created = 0
    groups_by_id = get_group_maps(competicio)["by_id"]
    series_by_id = {
        int(serie.id): serie
        for serie in SerieEquip.objects.filter(competicio=competicio, actiu=True).select_related("comp_aparell")
    }
    with transaction.atomic():
        # refresquem per evitar desajustos
        franges = list(RotacioFranja.objects.filter(competicio=competicio).order_by("ordre", "id"))
        idx_base = next((i for i, f in enumerate(franges) if f.id == fr_base.id), None)

        max_ord = (RotacioFranja.objects.filter(competicio=competicio).aggregate(Max("ordre"))["ordre__max"] or 0)

        target_franges = []
        for k in range(1, count + 1):
            idx = idx_base + k
            if idx < len(franges):
                target_franges.append(franges[idx])
            else:
                # crear franja nova a continuació temporalment
                # start = fi de l'última franja existent
                last = franges[-1] if franges else fr_base
                day = datetime(2000, 1, 1).date()
                last_end = datetime.combine(day, last.hora_fi)
                new_start = last_end
                new_end = new_start + timedelta(minutes=interval_min)

                max_ord += 1
                nf = RotacioFranja.objects.create(
                    competicio=competicio,
                    hora_inici=new_start.time(),
                    hora_fi=new_end.time(),
                    ordre=max_ord,
                    titol=f"{fr_base.titol or 'Franja'} +{k}",
                )
                created += 1
                franges.append(nf)
                target_franges.append(nf)

        # 3) Omplim les franges fent shift circular
        filled_cells = 0
        n = len(estacions)

        for k, fr_t in enumerate(target_franges, start=1):
            shifted = [list(base_groups[(i - k) % n]) for i in range(n)]  # shift cap a la dreta

            for e, gs in zip(estacions, shifted):
                group_ids, serie_ids = _split_program_keys(gs)
                assignacio, _created = RotacioAssignacio.objects.update_or_create(
                    competicio=competicio,
                    franja=fr_t,
                    estacio=e,
                    defaults={
                        "grups": [],
                        "grup": None,
                    },
                )
                is_team_station = bool(
                    getattr(e, "tipus", "") == "aparell"
                    and getattr(getattr(e, "comp_aparell", None), "aparell", None)
                    and getattr(e.comp_aparell.aparell, "competition_unit", "") == "team"
                )
                if is_team_station:
                    group_ids = []
                    serie_ids = [
                        serie_id
                        for serie_id in serie_ids
                        if serie_id in series_by_id and int(series_by_id[serie_id].comp_aparell_id or 0) == int(getattr(e, "comp_aparell_id", 0) or 0)
                    ]
                else:
                    serie_ids = []
                _sync_assignacio_groups(assignacio, group_ids, groups_by_id)
                _sync_assignacio_series(assignacio, serie_ids, series_by_id)
                filled_cells += 1

    return JsonResponse({
        "ok": True,
        "created_franges": created,
        "filled": filled_cells,
    })


@require_POST
@csrf_protect
def rotacions_clear_all(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    with transaction.atomic():
        RotacioAssignacio.objects.filter(competicio=competicio).delete()
        # opcional:
        RotacioFranja.objects.filter(competicio=competicio).delete()
    return JsonResponse({"ok": True})


__all__ = [
    "franges_auto_create",
    "franja_create",
    "franja_delete",
    "franja_insert_after",
    "franja_order_mode_set",
    "franja_update_inline",
    "rotacions_clear_all",
    "rotacions_extrapolar",
]

