import json

from django.contrib import messages
from django.db import models, transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from .access import user_has_competicio_capability
from .live_cache import mark_live_dirty
from .models import Competicio, Equip, Inscripcio
from .models_classificacions import ClassificacioConfig
from .models_scoring import ScoringSchema
from .models_trampoli import CompeticioAparell
from .services.classificacions.builder import (
    build_cfg_status,
    collect_particio_value_choices,
    distinct_fk,
    distinct_values,
    get_allowed_group_fields,
    get_equip_context_payload,
    get_team_context_capabilities,
    is_fk,
    sanitize_schema_for_builder,
)
from .services.classificacions.compute import DEFAULT_SCHEMA, compute_classificacio
from .services.classificacions.partitions import normalize_schema_legacy_team_birth_partition
from .services.classificacions.runtime import (
    execute_classificacio_runtime,
    prepare_schema_for_persistence,
)
from .services.classificacions.validation import (
    DETAIL_DISPLAY_KIND_NONE,
    build_metric_meta_for_comp_aparell,
)
from .services.competition_groups import get_group_maps, group_label


class ClassificacionsHome(TemplateView):
    template_name = "competicio/classificacions_builder_v2.html"

    def get(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        has_active_aparells = CompeticioAparell.objects.filter(
            competicio=self.competicio,
            actiu=True,
        ).exists()
        if (
            not has_active_aparells
            and user_has_competicio_capability(request.user, self.competicio, "classificacions.edit")
        ):
            messages.warning(
                request,
                "No pots crear classificacions sense aparells de competicio.",
            )
            create_url = reverse("trampoli_aparell_create", kwargs={"pk": self.competicio.id})
            next_query = urlencode({"next": request.get_full_path()})
            return redirect(f"{create_url}?{next_query}")
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        competicio = self.competicio

        aparells_cfg = (
            CompeticioAparell.objects
            .filter(competicio=competicio, actiu=True)
            .select_related("aparell")
            .order_by("ordre", "id")
        )
        aparell_ids = list(aparells_cfg.values_list("aparell_id", flat=True))
        schemas_by_aparell = {
            s.aparell_id: (s.schema or {})
            for s in ScoringSchema.objects.filter(aparell_id__in=aparell_ids).only("aparell_id", "schema")
        }

        aparell_field_options = {}
        for comp_aparell in aparells_cfg:
            schema = schemas_by_aparell.get(comp_aparell.aparell_id, {}) or {}
            opts = []
            field_meta = build_metric_meta_for_comp_aparell(comp_aparell, schema, strict_unknown=False)
            for field in (schema.get("fields") or []):
                if not isinstance(field, dict) or not field.get("code"):
                    continue
                code = str(field["code"])
                info = field_meta.get(code) or {}
                if not (info.get("scoreable", False) or info.get("detail_displayable", False)):
                    continue
                judges_count = 1
                judges = field.get("judges")
                if isinstance(judges, dict):
                    try:
                        judges_count = int(judges.get("count") or 1)
                    except Exception:
                        judges_count = 1
                else:
                    try:
                        judges_count = int(field.get("judges_count") or 1)
                    except Exception:
                        judges_count = 1
                judges_count = max(1, judges_count)
                opts.append(
                    {
                        "code": code,
                        "label": str(field.get("label") or code),
                        "kind": "field",
                        "scoreable": bool(info.get("scoreable", False)),
                        "judges_count": judges_count,
                        "member_dependent": bool(info.get("member_dependent", False)),
                        "detail_displayable": bool(info.get("detail_displayable", False)),
                        "detail_display_kind": str(info.get("detail_display_kind") or DETAIL_DISPLAY_KIND_NONE),
                    }
                )
            for computed in (schema.get("computed") or []):
                if not isinstance(computed, dict) or not computed.get("code"):
                    continue
                code = str(computed["code"])
                info = field_meta.get(code) or {}
                if not (info.get("scoreable", False) or info.get("detail_displayable", False)):
                    continue
                opts.append(
                    {
                        "code": code,
                        "label": str(computed.get("label") or code),
                        "kind": "computed",
                        "scoreable": bool(info.get("scoreable", False)),
                        "judges_count": 1,
                        "member_dependent": bool(info.get("member_dependent", False)),
                        "detail_displayable": bool(info.get("detail_displayable", False)),
                        "detail_display_kind": str(info.get("detail_display_kind") or DETAIL_DISPLAY_KIND_NONE),
                    }
                )
            seen = set()
            dedup = []
            for option in opts:
                if option["code"] in seen:
                    continue
                seen.add(option["code"])
                dedup.append(option)
            aparell_field_options[str(comp_aparell.id)] = dedup

        cfgs = ClassificacioConfig.objects.filter(competicio=competicio).order_by("ordre", "id")
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

        ins_qs = Inscripcio.objects.filter(competicio=competicio)
        filter_choices = {}
        filter_choices["entitats"] = distinct_fk(ins_qs, "entitat") if is_fk(Inscripcio, "entitat") else [
            {"value": value, "label": str(value)} for value in distinct_values(ins_qs, "entitat")
        ]
        filter_choices["categories"] = distinct_fk(ins_qs, "categoria") if is_fk(Inscripcio, "categoria") else [
            {"value": value, "label": str(value)} for value in distinct_values(ins_qs, "categoria")
        ]
        filter_choices["subcategories"] = distinct_fk(ins_qs, "subcategoria") if is_fk(Inscripcio, "subcategoria") else [
            {"value": value, "label": str(value)} for value in distinct_values(ins_qs, "subcategoria")
        ]
        group_choices = []
        seen_group_values = set()
        for group in get_group_maps(competicio).get("groups", []):
            value = str(getattr(group, "display_num", "") or "").strip()
            if not value or value in seen_group_values:
                continue
            seen_group_values.add(value)
            group_choices.append({"value": value, "label": group_label(group)})
        for legacy_value in distinct_values(ins_qs, "grup"):
            value = str(legacy_value).strip()
            if not value or value in seen_group_values:
                continue
            seen_group_values.add(value)
            group_choices.append({"value": value, "label": f"Grup {value}"})
        filter_choices["grups"] = group_choices

        particio_fields = []
        for item in get_allowed_group_fields(competicio):
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "").strip()
            if not code:
                continue
            particio_fields.append(
                {
                    "code": code,
                    "label": str(item.get("label") or code),
                    "ui_label": str(item.get("ui_label") or item.get("label") or code),
                    "kind": str(item.get("kind") or "builtin"),
                    "source": str(item.get("source") or ""),
                }
            )
        ins_list = list(ins_qs)
        particio_value_choices = collect_particio_value_choices(
            ins_list,
            [field["code"] for field in particio_fields],
        )

        cfg_payload = []
        cfg_status_payload = {}
        for cfg in cfgs:
            display_schema, _legacy_info = normalize_schema_legacy_team_birth_partition(
                competicio,
                cfg.schema or {},
                tipus=cfg.tipus,
                persist=False,
            )
            status = build_cfg_status(competicio, cfg.tipus, display_schema)
            builder_schema = sanitize_schema_for_builder(competicio, display_schema, tipus=cfg.tipus)
            cfg_payload.append(
                {
                    "id": cfg.id,
                    "nom": cfg.nom,
                    "activa": cfg.activa,
                    "ordre": cfg.ordre,
                    "tipus": cfg.tipus,
                    "schema": builder_schema,
                }
            )
            cfg_status_payload[str(cfg.id)] = status

        aparell_payload = []
        for comp_aparell in aparells_cfg:
            aparell_payload.append(
                {
                    "id": comp_aparell.id,
                    "nom": comp_aparell.aparell.nom,
                    "codi": comp_aparell.aparell.codi,
                    "nombre_exercicis": int(getattr(comp_aparell, "nombre_exercicis", 1) or 1),
                    "competition_unit": str(getattr(comp_aparell.aparell, "competition_unit", "") or "individual"),
                }
            )

        equips_qs = (
            Equip.objects
            .filter(competicio=competicio)
            .select_related("context")
            .annotate(membres_count=models.Count("assignacions_contextuals"))
            .order_by("nom", "id")
        )
        equips_payload = []
        for equip in equips_qs:
            equips_payload.append(
                {
                    "id": equip.id,
                    "nom": equip.nom,
                    "origen": equip.origen,
                    "membres_count": int(getattr(equip, "membres_count", 0) or 0),
                    "context_id": getattr(equip, "context_id", None),
                    "context_code": str(getattr(getattr(equip, "context", None), "code", "") or ""),
                }
            )

        equip_contexts = get_equip_context_payload(competicio)
        ctx.update(
            {
                "competicio": competicio,
                "cfgs": cfg_payload,
                "cfg_status": cfg_status_payload,
                "cfg_statuses": cfg_status_payload,
                "aparells": aparell_payload,
                "aparell_field_options": aparell_field_options,
                "equips": equips_payload,
                "equip_contexts": equip_contexts,
                "team_context_capabilities": [
                    get_team_context_capabilities(competicio, item.get("code"))
                    for item in equip_contexts
                ],
                "filter_choices": filter_choices,
                "particio_fields": particio_fields,
                "particio_value_choices": particio_value_choices,
                "can_manage_global_templates": bool(
                    user_has_competicio_capability(self.request.user, competicio, "classificacions.edit")
                ),
                "builder_mode": "competition",
                "builder_title": "Classificacions",
                "builder_subtitle": competicio.nom,
                "builder_home_label": "Configuracio",
                "builder_home_url": reverse("trampoli_config", kwargs={"pk": competicio.id}),
                "builder_save_url": reverse("classificacio_save", kwargs={"pk": competicio.id}),
                "builder_delete_url_pattern": reverse("classificacio_delete", kwargs={"pk": competicio.id, "cid": 0}),
                "builder_preview_url_pattern": reverse("classificacio_preview", kwargs={"pk": competicio.id, "cid": 0}),
                "builder_enable_template_library": True,
                "builder_can_preview": True,
                "builder_selected_id": None,
                "builder_auto_add_new": False,
                "is_global_builder": False,
                "global_templates_url": reverse("classificacio_template_global_list"),
            }
        )
        return ctx


@require_POST
@transaction.atomic
def classificacio_save(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    cid = payload.get("id")
    nom = (payload.get("nom") or "Classificacio").strip()
    activa = bool(payload.get("activa", True))
    ordre = int(payload.get("ordre") or 1)
    tipus = (payload.get("tipus") or "individual").strip()
    schema = payload.get("schema") or {}

    if tipus not in ("individual", "entitat", "equips"):
        tipus = "individual"

    prepared = prepare_schema_for_persistence(
        competicio,
        schema,
        tipus=tipus,
    )
    if prepared["errors"]:
        return JsonResponse(
            {
                "ok": False,
                "error": "Configuracio de classificacio invalida.",
                "errors": prepared["errors"],
                "error_details": prepared["error_details"],
            },
            status=400,
        )
    schema = prepared["schema"]

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

    return JsonResponse(
        {
            "ok": True,
            "id": obj.id,
            "cfg": {
                "id": obj.id,
                "nom": obj.nom,
                "tipus": obj.tipus,
                "activa": obj.activa,
                "ordre": obj.ordre,
                "schema": obj.schema,
            },
        }
    )


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
        return HttpResponseBadRequest("JSON invalid")

    order = payload.get("order") or []
    for idx, cid in enumerate(order, start=1):
        ClassificacioConfig.objects.filter(competicio=competicio, id=cid).update(ordre=idx)

    transaction.on_commit(lambda comp_id=competicio.id: mark_live_dirty(comp_id))
    return JsonResponse({"ok": True})


@require_POST
def classificacio_preview(request, pk, cid):
    competicio = get_object_or_404(Competicio, pk=pk)
    cfg = get_object_or_404(ClassificacioConfig, pk=cid, competicio=competicio)

    runtime = execute_classificacio_runtime(
        competicio,
        schema_local=cfg.schema or {},
        tipus=cfg.tipus,
        compute_fn=compute_classificacio,
        invalid_message="Configuracio de classificacio invalida per previsualitzar.",
        runtime_message="No s'ha pogut previsualitzar la classificacio.",
    )
    if runtime["error"]:
        return JsonResponse(
            {
                "ok": False,
                "error": runtime["error"]["message"],
                "errors": runtime["error"]["errors"],
                "error_details": runtime["error"]["error_details"],
            },
            status=400,
        )

    return JsonResponse(
        {
            "ok": True,
            "columns": runtime["columns"],
            "data": runtime["parts"],
        }
    )


__all__ = [
    "ClassificacionsHome",
    "classificacio_delete",
    "classificacio_preview",
    "classificacio_reorder",
    "classificacio_save",
]
