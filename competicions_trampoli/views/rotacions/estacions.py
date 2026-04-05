import json

from django.db import transaction
from django.db.models import Max
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from ...models import Competicio
from ...models.rotacions import RotacioAssignacio, RotacioEstacio


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


__all__ = [
    "estacio_delete",
    "estacio_descans_create",
    "estacions_reorder",
]

