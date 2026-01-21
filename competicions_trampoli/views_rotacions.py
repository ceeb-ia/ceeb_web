import json
from django.utils.dateparse import parse_time
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_protect
from django.http import JsonResponse, HttpResponseBadRequest
from django.db import transaction
from django.shortcuts import render, get_object_or_404
from django.db.models import Q, Max, Min, Case, When, IntegerField, F
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from django.http import HttpResponse
from ceeb_web import models
from .models import Competicio, Inscripcio
from .models_trampoli import CompeticioAparell
from .models_rotacions import RotacioFranja, RotacioAssignacio, RotacioEstacio
from django.db import transaction
from datetime import date, datetime, timedelta
from django.utils.dateparse import parse_time
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

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

def _sync_estacions_aparells(competicio):
    comp_aps = list(CompeticioAparell.objects.filter(competicio=competicio, actiu=True).order_by("ordre", "id"))
    existents = set(
        RotacioEstacio.objects.filter(competicio=competicio, tipus="aparell", comp_aparell__isnull=False)
        .values_list("comp_aparell_id", flat=True)
    )
    to_create = []
    for ca in comp_aps:
        if ca.id not in existents:
            to_create.append(RotacioEstacio(
                competicio=competicio,
                tipus="aparell",
                comp_aparell=ca,
                ordre=int(getattr(ca, "ordre", 1) or 1),
                actiu=True
            ))
    if to_create:
        RotacioEstacio.objects.bulk_create(to_create)


def rotacions_planner(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)

    _sync_estacions_aparells(competicio)

    grups = list(
        Inscripcio.objects.filter(competicio=competicio, grup__isnull=False)
        .order_by("grup").values_list("grup", flat=True).distinct()
    )

    estacions = list(RotacioEstacio.objects.filter(competicio=competicio, actiu=True).order_by("ordre", "id"))
    franges = list(RotacioFranja.objects.filter(competicio=competicio).order_by("ordre", "id"))

    assigns = (
        RotacioAssignacio.objects
        .filter(competicio=competicio)
        .select_related("franja", "estacio")
    )

    grid = {}  # grid[franja_id][estacio_id] = grup
    for a in assigns:
        grid.setdefault(a.franja_id, {})[a.estacio_id] = a.grup

    ctx = {
        "competicio": competicio,
        "grups": grups,
        "estacions": estacions,
        "franges": franges,
        "grid_json": json.dumps(grid, ensure_ascii=False),
        "grups_json": json.dumps(grups, ensure_ascii=False),
    }
    return render(request, "competicio/rotacions_planner.html", ctx)


@require_POST
@csrf_protect
def rotacions_save(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invàlid")

    # Esperem: { "cells": [ {"franja":1,"estacio":2,"grup":3}, ... ] }
    cells = payload.get("cells", [])
    if not isinstance(cells, list):
        return HttpResponseBadRequest("Format incorrecte")

    franja_ids = set(RotacioFranja.objects.filter(competicio=competicio).values_list("id", flat=True))
    estacio_ids = set(RotacioEstacio.objects.filter(competicio=competicio).values_list("id", flat=True))

    with transaction.atomic():
        for c in cells:
            try:
                fr_id = int(c.get("franja"))
                es_id = int(c.get("estacio"))
                g = c.get("grup", None)
                g = None if (g in ("", None)) else int(g)
            except Exception:
                continue

            if fr_id not in franja_ids or es_id not in estacio_ids:
                continue

            RotacioAssignacio.objects.update_or_create(
                competicio=competicio,
                franja_id=fr_id,
                estacio_id=es_id,
                defaults={"grup": g},
            )

    return JsonResponse({"ok": True})


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
def estacio_descans_create(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    max_ord = (RotacioEstacio.objects.filter(competicio=competicio).aggregate(Max("ordre"))["ordre__max"] or 0) + 1
    e = RotacioEstacio.objects.create(competicio=competicio, tipus="descans", ordre=max_ord, actiu=True)
    return JsonResponse({"ok": True, "id": e.id})

@require_POST
@csrf_protect
def estacio_delete(request, pk, estacio_id):
    competicio = get_object_or_404(Competicio, pk=pk)
    e = get_object_or_404(RotacioEstacio, pk=estacio_id, competicio=competicio)
    with transaction.atomic():
        RotacioAssignacio.objects.filter(competicio=competicio, estacio=e).delete()
        e.delete()  # o e.actiu=False si prefereixes no perdre històric
    return JsonResponse({"ok": True})


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
    base_map = {
        a.estacio_id: a.grup
        for a in RotacioAssignacio.objects.filter(competicio=competicio, franja=fr_base)
    }

    base_groups = []
    for e in estacions:
        base_groups.append(base_map.get(e.id, None))  # pot ser None

    # Si no hi ha cap grup definit, no té sentit extrapolar
    if all(g is None for g in base_groups):
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
            shifted = [base_groups[(i - k) % n] for i in range(n)]  # shift cap a la dreta

            for e, g in zip(estacions, shifted):
                RotacioAssignacio.objects.update_or_create(
                    competicio=competicio,
                    franja=fr_t,
                    estacio=e,
                    defaults={"grup": g},
                )
                filled_cells += 1

    return JsonResponse({
        "ok": True,
        "created_franges": created,
        "filled": filled_cells,
    })


@require_POST
@csrf_protect
def estacions_reorder(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invàlid")

    order = payload.get("order", [])
    if not isinstance(order, list) or not order:
        return HttpResponseBadRequest("order ha de ser una llista d'IDs")

    # validació: totes les estacions han de ser de la competició
    estacions = RotacioEstacio.objects.filter(competicio=competicio, id__in=order)
    found = set(estacions.values_list("id", flat=True))
    wanted = []
    for x in order:
        try:
            wanted.append(int(x))
        except Exception:
            pass

    if set(wanted) != found:
        return HttpResponseBadRequest("IDs d'estació invàlids per aquesta competició.")

    with transaction.atomic():
        for idx, estacio_id in enumerate(wanted, start=1):
            RotacioEstacio.objects.filter(competicio=competicio, id=estacio_id).update(ordre=idx)

    return JsonResponse({"ok": True})


@require_POST
@csrf_protect
def rotacions_clear_all(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    with transaction.atomic():
        RotacioAssignacio.objects.filter(competicio=competicio).delete()
        # opcional:
        RotacioFranja.objects.filter(competicio=competicio).delete()
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



def franges_export_excel(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)

    # --- Dades base ---
    estacions = list(RotacioEstacio.objects.filter(competicio=competicio, actiu=True).order_by("ordre", "id"))
    franges = list(RotacioFranja.objects.filter(competicio=competicio).order_by("ordre", "id"))

    # assignacions: (franja_id, estacio_id) -> grup
    assigns = RotacioAssignacio.objects.filter(competicio=competicio).values("franja_id", "estacio_id", "grup")
    cell_group = {(a["franja_id"], a["estacio_id"]): a["grup"] for a in assigns}

    # grup -> [noms inscripcions]
    grups = sorted({g for g in cell_group.values() if g is not None})
    ins_by_grup = {}
    if grups:
        qs = (
            Inscripcio.objects
            .filter(competicio=competicio, grup__in=grups)
            .order_by("ordre_sortida", "id")
        )
        for ins in qs:
            ins_by_grup.setdefault(ins.grup, []).append(getattr(ins, "nom_i_cognoms", None) or str(ins))

    # --- Header (competició + seu) ---
    titol_competicio = getattr(competicio, "nom", f"Competició {competicio.id}")
    seu = getattr(competicio, "seu", "") or "—"
    data_comp = getattr(competicio, "data", None)
    data_txt = data_comp.strftime("%d/%m/%Y") if data_comp else ""

    wb = Workbook()
    ws = wb.active
    ws.title = "Rotacions"

    # --- Estils ---
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    center_no_wrap = Alignment(horizontal="center", vertical="center")
    bold = Font(bold=True)

    fill_title = PatternFill("solid", fgColor="1F4E79")    # blau fosc
    fill_sub = PatternFill("solid", fgColor="D9E1F2")      # blau clar
    fill_hdr = PatternFill("solid", fgColor="E9EEF7")      # capçalera taula
    fill_zebra = PatternFill("solid", fgColor="F6F8FC")    # zebra suau

    thin = Side(style="thin", color="9AA7B2")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    # Columnes: 1a col = "Franja", resta = estacions
    total_cols = 1 + len(estacions)

    # Títol
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total_cols)
    c = ws.cell(row=1, column=1, value=titol_competicio)
    c.font = Font(bold=True, size=16, color="FFFFFF")
    c.fill = fill_title
    c.alignment = center_no_wrap

    # Subcapçalera
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=total_cols)
    c = ws.cell(row=2, column=1, value=f"Seu: {seu}    {data_txt}")
    c.font = Font(bold=True)
    c.fill = fill_sub
    c.alignment = center_no_wrap

    # línia en blanc
    ws.append([])

    # Capçalera de la matriu (fila 4)
    header_row = ws.max_row + 1
    ws.cell(row=header_row, column=1, value="Franja").font = bold
    ws.cell(row=header_row, column=1).fill = fill_hdr
    ws.cell(row=header_row, column=1).alignment = center_no_wrap
    ws.cell(row=header_row, column=1).border = border

    for j, e in enumerate(estacions, start=2):
        cell = ws.cell(row=header_row, column=j, value=e.nom)
        cell.font = bold
        cell.fill = fill_hdr
        cell.alignment = center_no_wrap
        cell.border = border

    # Files: una per franja
    for i, f in enumerate(franges, start=1):
        r = header_row + i

        label = (f.titol.strip() or "Franja")
        fr_txt = f"{label}\n{f.hora_inici.strftime('%H:%M')}–{f.hora_fi.strftime('%H:%M')}"

        c0 = ws.cell(row=r, column=1, value=fr_txt)
        c0.alignment = center
        c0.border = border

        # zebra a tota la fila (inclosa la 1a col)
        if i % 2 == 0:
            for col in range(1, total_cols + 1):
                ws.cell(row=r, column=col).fill = fill_zebra

        # cel·les per estació
        for j, e in enumerate(estacions, start=2):
            g = cell_group.get((f.id, e.id), None)
            noms = ins_by_grup.get(g, []) if g is not None else []
            txt = "\n".join(noms) if noms else ("—" if g is not None else "")

            cell = ws.cell(row=r, column=j, value=txt)
            cell.alignment = center
            cell.border = border

    # Amplades i alçades (perquè es vegi “maco”)
    ws.column_dimensions[get_column_letter(1)].width = 22
    for j in range(2, total_cols + 1):
        ws.column_dimensions[get_column_letter(j)].width = 24

    # Alçada mín. per veure llistes
    for r in range(header_row + 1, header_row + 1 + len(franges)):
        ws.row_dimensions[r].height = 60

    ws.row_dimensions[1].height = 28
    ws.row_dimensions[2].height = 20
    ws.row_dimensions[header_row].height = 22

    # Freeze panes: manté capçaleres visibles
    ws.freeze_panes = ws["B" + str(header_row + 1)]  # bloqueja fila capçalera i col 1

    # Response
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="rotacions_{competicio.id}.xlsx"'
    wb.save(response)
    return response