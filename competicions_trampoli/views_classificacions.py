# views_classificacions.py
import json
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST
from django.db import transaction

from .models import Competicio, Inscripcio
from .models_trampoli import CompeticioAparell, Aparell
from .models_classificacions import ClassificacioConfig
from .services.services_classificacions import compute_classificacio, DEFAULT_SCHEMA, ALLOWED_SCORE_FIELDS
from django.db import models
from collections import OrderedDict
# views_classificacions.py
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_aware
from django.utils import timezone
from django.shortcuts import get_object_or_404
from .models_trampoli import TrampoliNota


class ClassificacionsLive(TemplateView):
    template_name = "competicio/classificacions_live.html"

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        competicio = self.competicio

        cfgs = (
            ClassificacioConfig.objects
            .filter(competicio=competicio, activa=True)
            .order_by("ordre", "id")
        )
        ctx.update({
            "competicio": competicio,
            "cfgs": list(cfgs.values("id", "nom", "tipus", "ordre")),
            # interval suggerit (ms) perquè el JS el pugui usar
            "poll_ms": 4000,
        })
        return ctx


def classificacions_live_data(request, pk):
    """
    GET /competicio/<pk>/classificacions/live/data?since=<iso>
    Retorna:
      - changed: False si no hi ha canvis des de `since`
      - changed: True + dades si hi ha canvis
    """
    competicio = get_object_or_404(Competicio, pk=pk)

    # stamp = max(última nota, última cfg)
    last_note = (
        TrampoliNota.objects
        .filter(competicio=competicio)
        .order_by("-updated_at")
        .values_list("updated_at", flat=True)
        .first()
    )
    last_cfg = (
        ClassificacioConfig.objects
        .filter(competicio=competicio)
        .order_by("-updated_at")
        .values_list("updated_at", flat=True)
        .first()
    )
    stamp = max([d for d in [last_note, last_cfg] if d is not None], default=timezone.now())

    # Si el client passa ?since=..., i no hi ha canvis, no recalculis
    since_raw = request.GET.get("since")
    if since_raw:
        since_dt = parse_datetime(since_raw)
        if since_dt and not is_aware(since_dt):
            since_dt = timezone.make_aware(since_dt, timezone.get_current_timezone())
        if since_dt and stamp <= since_dt:
            return JsonResponse({"ok": True, "changed": False, "stamp": stamp.isoformat()})

    cfgs = (
        ClassificacioConfig.objects
        .filter(competicio=competicio, activa=True)
        .order_by("ordre", "id")
    )

    payload_cfgs = []
    for cfg in cfgs:
        data = compute_classificacio(competicio, cfg)  # {particio_key: [rows]}
        parts = []
        for k in sorted(data.keys()):
            parts.append({"particio": k, "rows": data[k]})
        payload_cfgs.append({
            "id": cfg.id,
            "nom": cfg.nom,
            "tipus": cfg.tipus,
            "parts": parts,
        })

    return JsonResponse({
        "ok": True,
        "changed": True,
        "stamp": stamp.isoformat(),
        "competicio": {"id": competicio.id, "nom": competicio.nom},
        "cfgs": payload_cfgs,
    })


class ClassificacionsHome(TemplateView):
    template_name = "competicio/classificacions_builder.html"

    def get(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        competicio = self.competicio

        # aparells actius (com a notes)
        aparells_cfg = CompeticioAparell.objects.filter(
            competicio=competicio,
            actiu=True,
        ).select_related("aparell").order_by("ordre", "id")

        # si no n'hi ha, crea'n un per defecte (mateix patró que notes)
        if not aparells_cfg.exists():
            a, _ = Aparell.objects.get_or_create(codi="TRAMP", defaults={"nom": "Trampolí"})
            CompeticioAparell.objects.create(
                competicio=competicio,
                aparell=a,
                ordre=1,
                nombre_elements=11,
                te_execucio=True,
                te_dificultat=True,
                te_tof=True,
                te_hd=True,
                te_penalitzacio=True,
                mode_execucio="salts",
                actiu=True,
            )
            aparells_cfg = CompeticioAparell.objects.filter(
                competicio=competicio,
                actiu=True,
            ).select_related("aparell").order_by("ordre", "id")

        cfgs = ClassificacioConfig.objects.filter(competicio=competicio).order_by("ordre", "id")

        # si no hi ha cap configuració, crea'n una de base
        if not cfgs.exists():
            ClassificacioConfig.objects.create(
                competicio=competicio,
                nom="General (total)",
                activa=True,
                ordre=1,
                tipus="individual",
                schema={
                    **DEFAULT_SCHEMA,
                    "particions": [],
                    "puntuacio": {**DEFAULT_SCHEMA["puntuacio"], "camp": "total", "agregacio": "sum"},
                    "presentacio": {"top_n": 0, "mostrar_empats": True},
                },
            )
            cfgs = ClassificacioConfig.objects.filter(competicio=competicio).order_by("ordre", "id")


        # Choices per filtres visuals (entitat/categoria/subcategoria/grup)
        ins_qs = Inscripcio.objects.filter(competicio=competicio)

        filter_choices = {}

        # entitat
        if _is_fk(Inscripcio, "entitat"):
            filter_choices["entitats"] = _distinct_fk(ins_qs, "entitat")
        else:
            filter_choices["entitats"] = [{"value": v, "label": str(v)} for v in _distinct_values(ins_qs, "entitat")]

        # categoria
        if _is_fk(Inscripcio, "categoria"):
            filter_choices["categories"] = _distinct_fk(ins_qs, "categoria")
        else:
            filter_choices["categories"] = [{"value": v, "label": str(v)} for v in _distinct_values(ins_qs, "categoria")]

        # subcategoria
        if _is_fk(Inscripcio, "subcategoria"):
            filter_choices["subcategories"] = _distinct_fk(ins_qs, "subcategoria")
        else:
            filter_choices["subcategories"] = [{"value": v, "label": str(v)} for v in _distinct_values(ins_qs, "subcategoria")]

        # grup (normalment text)
        filter_choices["grups"] = [{"value": v, "label": str(v)} for v in _distinct_values(ins_qs, "grup")]

        ctx["filter_choices"] = filter_choices


        cfg_payload = []
        for c in cfgs:
            cfg_payload.append({
                "id": c.id,
                "nom": c.nom,
                "activa": c.activa,
                "ordre": c.ordre,
                "tipus": c.tipus,
                "schema": c.schema or {},
            })

        aparell_payload = []
        for ca in aparells_cfg:
            aparell_payload.append({
                "id": ca.id,
                "nom": ca.aparell.nom,
                "codi": ca.aparell.codi,
            })

        ctx.update({
            "competicio": competicio,
            "cfgs": cfg_payload,
            "aparells": aparell_payload,
            "score_fields": {k: v["label"] for k, v in ALLOWED_SCORE_FIELDS.items()},
        })

        return ctx


@require_POST
@transaction.atomic
def classificacio_save(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invàlid")

    cid = payload.get("id")
    nom = (payload.get("nom") or "Classificació").strip()
    activa = bool(payload.get("activa", True))
    ordre = int(payload.get("ordre") or 1)
    tipus = (payload.get("tipus") or "individual").strip()
    schema = payload.get("schema") or {}

    if tipus not in ("individual", "entitat"):
        tipus = "individual"

    if cid:
        obj = get_object_or_404(ClassificacioConfig, pk=cid, competicio=competicio)
        obj.nom = nom
        obj.activa = activa
        obj.ordre = ordre
        obj.tipus = tipus
        obj.schema = schema
        obj.save()
    else:
        obj = ClassificacioConfig.objects.create(
            competicio=competicio,
            nom=nom,
            activa=activa,
            ordre=ordre,
            tipus=tipus,
            schema=schema,
        )

    return JsonResponse({"ok": True, "id": obj.id})


@require_POST
@transaction.atomic
def classificacio_delete(request, pk, cid):
    competicio = get_object_or_404(Competicio, pk=pk)
    obj = get_object_or_404(ClassificacioConfig, pk=cid, competicio=competicio)
    obj.delete()
    return JsonResponse({"ok": True})


@require_POST
@transaction.atomic
def classificacio_reorder(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invàlid")

    order = payload.get("order") or []
    # order = [id1, id2, ...]
    for idx, cid in enumerate(order, start=1):
        ClassificacioConfig.objects.filter(competicio=competicio, id=cid).update(ordre=idx)

    return JsonResponse({"ok": True})


@require_POST
def classificacio_preview(request, pk, cid):
    competicio = get_object_or_404(Competicio, pk=pk)
    cfg = get_object_or_404(ClassificacioConfig, pk=cid, competicio=competicio)

    data = compute_classificacio(competicio, cfg)

    # Retorna una estructura fàcil pel front:
    # [
    #   {"particio": "global", "rows":[...]}
    # ]
    out = []
    for k in sorted(data.keys()):
        out.append({"particio": k, "rows": data[k]})

    return JsonResponse({"ok": True, "data": out})


def _is_fk(model_cls, field_name: str) -> bool:
    try:
        f = model_cls._meta.get_field(field_name)
        return isinstance(f, (models.ForeignKey, models.OneToOneField))
    except Exception:
        return False

def _distinct_values(qs, field_name: str):
    # retorna llista de valors (strings) per camps no FK
    return [v for v in qs.values_list(field_name, flat=True).distinct() if v not in (None, "",)]

def _distinct_fk(qs, field_name: str):
    # retorna llista d'objectes {id, label}
    rel = qs.select_related(field_name).values_list(f"{field_name}_id", f"{field_name}__nom").distinct()
    out = []
    seen = set()
    for _id, nom in rel:
        if _id is None or _id in seen:
            continue
        seen.add(_id)
        out.append({"value": _id, "label": nom or str(_id)})
    return out
