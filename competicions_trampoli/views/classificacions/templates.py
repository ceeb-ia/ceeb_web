import json

from django.db import transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from ...access import user_has_competicio_capability
from ...models import Competicio
from ...models.classificacions import ClassificacioConfig, ClassificacioTemplateGlobal
from ...services.classificacions.runtime import prepare_schema_for_persistence
from ...services.classificacions.templates_competicio import (
    build_template_save_payload,
    next_cfg_ordre_for_competicio,
    next_template_slug,
    parse_fallback_mode,
    template_to_payload_row,
    validate_template_for_competicio,
)


def classificacio_template_list(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    can_manage = bool(user_has_competicio_capability(request.user, competicio, "classificacions.edit"))
    include_inactive = str(request.GET.get("all") or "").strip().lower() in {"1", "true", "yes", "on"}

    qs = ClassificacioTemplateGlobal.objects.filter(created_by=request.user).order_by("nom", "id")
    if not (can_manage and include_inactive):
        qs = qs.filter(activa=True)

    data = [template_to_payload_row(template) for template in qs]
    return JsonResponse({"ok": True, "templates": data, "can_manage": can_manage})


@require_POST
@transaction.atomic
def classificacio_template_save(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    owner = request.user
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    cfg_id = payload.get("cfg_id")
    if not cfg_id:
        return JsonResponse({"ok": False, "error": "Falta cfg_id."}, status=400)

    cfg = get_object_or_404(ClassificacioConfig, pk=cfg_id, competicio=competicio)
    template_id = payload.get("template_id")
    nom = str(payload.get("nom") or cfg.nom or "Plantilla classificacio").strip() or "Plantilla classificacio"
    descripcio = str(payload.get("descripcio") or "").strip()
    activa = bool(payload.get("activa", True))
    payload_obj, requirements, export_warnings = build_template_save_payload(competicio, cfg)

    if template_id:
        tpl = get_object_or_404(ClassificacioTemplateGlobal, pk=template_id, created_by=owner)
        requested_slug = str(payload.get("slug") or tpl.slug or "").strip()
        if requested_slug:
            slug_candidate = slugify(requested_slug)
            if not slug_candidate:
                slug_candidate = next_template_slug(nom, owner.id, exclude_template_id=tpl.id)
            exists = (
                ClassificacioTemplateGlobal.objects
                .exclude(id=tpl.id)
                .filter(created_by=owner, slug=slug_candidate)
                .exists()
            )
            if exists:
                return JsonResponse({"ok": False, "error": "Ja existeix una plantilla amb aquest slug."}, status=400)
            tpl.slug = slug_candidate
        else:
            tpl.slug = next_template_slug(nom, owner.id, exclude_template_id=tpl.id)
        tpl.nom = nom
        tpl.descripcio = descripcio
        tpl.tipus = cfg.tipus or "individual"
        tpl.activa = activa
        tpl.payload = payload_obj
        tpl.requirements = requirements
        tpl.version = int(tpl.version or 1) + 1
        tpl.save()
    else:
        requested_slug = str(payload.get("slug") or "").strip()
        if requested_slug:
            slug_candidate = slugify(requested_slug)
            if not slug_candidate:
                slug_candidate = next_template_slug(nom, owner.id)
            if ClassificacioTemplateGlobal.objects.filter(created_by=owner, slug=slug_candidate).exists():
                return JsonResponse({"ok": False, "error": "Ja existeix una plantilla amb aquest slug."}, status=400)
        else:
            slug_candidate = next_template_slug(nom, owner.id)
        tpl = ClassificacioTemplateGlobal.objects.create(
            nom=nom,
            slug=slug_candidate,
            descripcio=descripcio,
            tipus=cfg.tipus or "individual",
            activa=activa,
            payload=payload_obj,
            requirements=requirements,
            created_by=owner,
        )

    return JsonResponse(
        {
            "ok": True,
            "template": template_to_payload_row(tpl),
            "warnings": export_warnings,
        }
    )


@require_POST
def classificacio_template_validate(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    template_id = payload.get("template_id")
    if not template_id:
        return JsonResponse({"ok": False, "error": "Falta template_id."}, status=400)
    fallback_mode = parse_fallback_mode(payload.get("fallback_mode"))
    qs = ClassificacioTemplateGlobal.objects.filter(activa=True, created_by=request.user)
    tpl = get_object_or_404(qs, pk=template_id)
    result = validate_template_for_competicio(competicio, tpl, fallback_mode=fallback_mode)
    return JsonResponse(
        {
            "ok": True,
            "template": template_to_payload_row(tpl),
            **result,
        }
    )


@require_POST
@transaction.atomic
def classificacio_template_apply(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    template_id = payload.get("template_id")
    if not template_id:
        return JsonResponse({"ok": False, "error": "Falta template_id."}, status=400)
    fallback_mode = parse_fallback_mode(payload.get("fallback_mode"))
    ack_warning = bool(payload.get("ack_warning"))
    if fallback_mode != "strict" and not ack_warning:
        return JsonResponse(
            {
                "ok": False,
                "error": "Cal confirmar l'avis per aplicar aquest mode de fallback.",
                "phase": fallback_mode,
            },
            status=400,
        )

    qs = ClassificacioTemplateGlobal.objects.filter(activa=True, created_by=request.user)
    tpl = get_object_or_404(qs, pk=template_id)
    validation = validate_template_for_competicio(competicio, tpl, fallback_mode=fallback_mode)
    if not validation.get("compatible"):
        return JsonResponse(
            {
                "ok": False,
                "error": "La plantilla no es compatible amb la competicio actual.",
                **validation,
            },
            status=400,
        )

    tipus = str(getattr(tpl, "tipus", "individual") or "individual").strip().lower()
    if tipus not in ("individual", "entitat", "equips"):
        tipus = "individual"
    prepared = prepare_schema_for_persistence(
        competicio,
        validation.get("resolved_schema") or {},
        tipus=tipus,
    )
    if prepared["errors"]:
        return JsonResponse(
            {
                "ok": False,
                "error": "La plantilla validada no s'ha pogut persistir amb el contracte actual.",
                "errors": prepared["errors"],
                "error_details": prepared["error_details"],
                **validation,
            },
            status=400,
        )

    nom = str(payload.get("nom") or "").strip() or f"{tpl.nom} (tpl)"
    activa = bool(payload.get("activa", False))

    obj = ClassificacioConfig.objects.create(
        competicio=competicio,
        nom=nom,
        activa=activa,
        publicada=activa,
        ordre=next_cfg_ordre_for_competicio(competicio),
        tipus=tipus,
        schema=prepared["schema"],
    )

    tpl.uses_count = int(tpl.uses_count or 0) + 1
    tpl.last_used_at = timezone.now()
    tpl.save(update_fields=["uses_count", "last_used_at", "updated_at"])

    return JsonResponse(
        {
            "ok": True,
            "cfg": {
                "id": obj.id,
                "nom": obj.nom,
                "tipus": obj.tipus,
                "activa": obj.activa,
                "publicada": obj.publicada,
                "schema": obj.schema,
            },
            "warnings": validation.get("warnings") or [],
            "template": template_to_payload_row(tpl),
        }
    )


__all__ = [
    "classificacio_template_apply",
    "classificacio_template_list",
    "classificacio_template_save",
    "classificacio_template_validate",
]
