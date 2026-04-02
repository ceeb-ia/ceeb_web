import json

from django.contrib import messages
from django.db import transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.text import slugify
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import ListView, TemplateView

from .models_classificacions import ClassificacioTemplateGlobal
from .models_scoring import ScoringSchema
from .services.classificacio_templates import (
    build_global_aparell_field_options,
    collect_global_builder_legacy_keys,
    build_global_native_particio_fields,
    build_template_requirements,
    extract_template_schema,
    get_global_aparell_maps,
    GLOBAL_FILTER_KEYS,
    global_ui_schema_to_template_schema,
    merge_global_builder_schema,
    next_template_slug,
    template_schema_to_global_ui_schema,
    validate_template_schema_global,
)
from .views_classificacions import (
    _build_metric_meta_for_schema_owner,
    _build_validation_error_details,
)


def _is_global_templates_admin(user) -> bool:
    return bool(
        getattr(user, "is_superuser", False)
        or user.groups.filter(name="platform_admin").exists()
    )


def _template_to_builder_row(obj, *, by_id, by_code, ordre):
    schema_tpl = extract_template_schema(getattr(obj, "payload", {}) or {})
    schema_ui, _warnings = template_schema_to_global_ui_schema(schema_tpl, by_id, by_code)
    return {
        "id": obj.id,
        "nom": obj.nom,
        "slug": obj.slug,
        "activa": bool(obj.activa),
        "ordre": ordre,
        "tipus": obj.tipus,
        "schema": schema_ui or {},
    }


def _template_to_list_row(obj):
    payload = getattr(obj, "payload", {}) or {}
    schema = extract_template_schema(payload)
    requirements = {
        **(getattr(obj, "requirements", {}) or {}),
        **build_template_requirements(schema, tipus=getattr(obj, "tipus", "individual")),
    }
    return {
        "id": obj.id,
        "nom": obj.nom,
        "slug": obj.slug,
        "descripcio": obj.descripcio or "",
        "tipus": obj.tipus,
        "activa": bool(obj.activa),
        "version": int(obj.version or 1),
        "uses_count": int(obj.uses_count or 0),
        "requirements": requirements,
        "updated_at": obj.updated_at,
        "created_by": getattr(obj, "created_by", None),
    }


def _collect_filter_choices(templates):
    out = {"entitats": [], "categories": [], "subcategories": [], "grups": []}
    key_map = {
        "entitats_in": "entitats",
        "categories_in": "categories",
        "subcategories_in": "subcategories",
        "grups_in": "grups",
    }
    seen = {name: set() for name in out}
    for tpl in templates:
        schema = extract_template_schema(getattr(tpl, "payload", {}) or {})
        filtres = schema.get("filtres") or {}
        if not isinstance(filtres, dict):
            continue
        for raw_key, target in key_map.items():
            values = filtres.get(raw_key) or []
            if not isinstance(values, list):
                continue
            for raw in values:
                value = str(raw).strip()
                if not value:
                    continue
                marker = value.casefold()
                if marker in seen[target]:
                    continue
                seen[target].add(marker)
                out[target].append({"value": value, "label": value})
    return out


def _collect_template_equip_contexts(templates):
    seen = set()
    out = []

    def _append(code, label):
        normalized = str(code or "").strip() or "native"
        if normalized in seen:
            return
        seen.add(normalized)
        out.append(
            {
                "code": normalized,
                "nom": str(label or normalized).strip() or normalized,
                "description": "",
                "is_native": normalized == "native",
            }
        )

    _append("native", "Base")
    for tpl in templates:
        schema = extract_template_schema(getattr(tpl, "payload", {}) or {})
        equips_cfg = schema.get("equips") or {}
        if not isinstance(equips_cfg, dict):
            continue
        assignment_source = equips_cfg.get("assignment_source") if isinstance(equips_cfg.get("assignment_source"), dict) else {}
        context_code = str(equips_cfg.get("context_code") or assignment_source.get("context_code") or "").strip()
        if not context_code:
            continue
        _append(context_code, "Base" if context_code == "native" else context_code)
    return out


def _collect_particio_value_choices(templates):
    out = {}
    for tpl in templates:
        schema = extract_template_schema(getattr(tpl, "payload", {}) or {})
        custom_map = schema.get("particions_custom") or {}
        if not isinstance(custom_map, dict):
            continue
        for code, cfg in custom_map.items():
            groups = cfg.get("grups") or [] if isinstance(cfg, dict) else []
            bucket = out.setdefault(str(code), [])
            seen = {str(item.get("value") or "").strip().casefold() for item in bucket}
            for group in groups:
                if not isinstance(group, dict):
                    continue
                for raw_value in group.get("values") or []:
                    value = str(raw_value).strip()
                    if not value:
                        continue
                    marker = value.casefold()
                    if marker in seen:
                        continue
                    seen.add(marker)
                    bucket.append({"value": value, "label": value, "count": 0})
    return out


class ClassificacioTemplateGlobalList(ListView):
    template_name = "competicio/classificacio_templates_list.html"
    context_object_name = "templates"

    def get_queryset(self):
        qs = ClassificacioTemplateGlobal.objects.select_related("created_by").order_by("nom", "id")
        if _is_global_templates_admin(self.request.user):
            return qs
        return qs.filter(created_by=self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["show_owner"] = _is_global_templates_admin(self.request.user)
        return ctx


class ClassificacioTemplateGlobalBuilder(TemplateView):
    template_name = "competicio/classificacions_builder_v2.html"

    def dispatch(self, request, *args, **kwargs):
        self.is_admin = _is_global_templates_admin(request.user)
        base_qs = ClassificacioTemplateGlobal.objects.select_related("created_by").order_by("nom", "id")
        editable_qs = base_qs if self.is_admin else base_qs.filter(created_by=request.user)
        self.selected_template = None
        pk = kwargs.get("pk")
        if pk:
            self.selected_template = get_object_or_404(editable_qs, pk=pk)
        self.catalog_owner = getattr(self.selected_template, "created_by", None) or request.user
        self.templates_qs = base_qs.filter(created_by=self.catalog_owner)
        self.aparells, self.aparells_by_id, self.aparells_by_code = get_global_aparell_maps(
            self.catalog_owner,
            include_inactive=False,
            include_all_owners=False,
        )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        templates = list(self.templates_qs)
        cfgs = [
            _template_to_builder_row(
                tpl,
                by_id=self.aparells_by_id,
                by_code=self.aparells_by_code,
                ordre=idx + 1,
            )
            for idx, tpl in enumerate(templates)
        ]
        ctx.update(
            {
                "builder_mode": "global",
                "builder_title": "Plantilles de classificacio",
                "builder_subtitle": "Gestio global per usuari",
                "builder_home_label": "Plantilles",
                "builder_home_url": reverse("classificacio_template_global_list"),
                "builder_save_url": reverse("classificacio_template_global_save"),
                "builder_delete_url_pattern": reverse("classificacio_template_global_delete", kwargs={"pk": 0}),
                "builder_preview_url_pattern": "",
                "builder_enable_template_library": False,
                "builder_can_preview": False,
                "builder_global_manager_url": reverse("classificacio_template_global_list"),
                "builder_selected_id": getattr(self.selected_template, "id", None),
                "builder_auto_add_new": self.kwargs.get("pk") is None and self.request.path.endswith("/nou/"),
                "is_global_builder": True,
                "cfgs": cfgs,
                "aparells": [
                    {
                        "id": app.id,
                        "nom": app.nom,
                        "codi": app.codi,
                        "nombre_exercicis": 4,
                        "competition_unit": str(getattr(app, "competition_unit", "") or "individual"),
                    }
                    for app in self.aparells
                ],
                "equips": [],
                "equip_contexts": _collect_template_equip_contexts(templates),
                "particio_fields": build_global_native_particio_fields(),
                "particio_value_choices": _collect_particio_value_choices(templates),
                "filter_choices": _collect_filter_choices(templates),
                "aparell_field_options": build_global_aparell_field_options(
                    self.aparells,
                    _build_metric_meta_for_schema_owner,
                ),
                "can_manage_global_templates": False,
            }
        )
        return ctx


@require_POST
@transaction.atomic
def classificacio_template_global_save(request):
    is_admin = _is_global_templates_admin(request.user)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    tpl_id = payload.get("id")
    nom = str(payload.get("nom") or "Plantilla classificacio").strip() or "Plantilla classificacio"
    slug_raw = str(payload.get("slug") or "").strip()
    activa = bool(payload.get("activa", True))
    tipus = str(payload.get("tipus") or "individual").strip().lower()
    if tipus not in ("individual", "entitat", "equips"):
        tipus = "individual"

    owner = request.user
    if tpl_id:
        qs = ClassificacioTemplateGlobal.objects.all()
        if not is_admin:
            qs = qs.filter(created_by=request.user)
        tpl = get_object_or_404(qs, pk=tpl_id)
        owner = tpl.created_by
    apps, by_id, by_code = get_global_aparell_maps(
        owner,
        include_inactive=False,
        include_all_owners=False,
    )
    field_meta_by_code = {}
    app_units_by_code = {}
    schemas_by_aparell = {
        s.aparell_id: (s.schema or {})
        for s in ScoringSchema.objects.filter(aparell_id__in=[app.id for app in apps]).only("aparell_id", "schema")
    }
    for app in apps:
        sch = schemas_by_aparell.get(app.id, {}) or {}
        meta = _build_metric_meta_for_schema_owner(app, sch, strict_unknown=True)
        field_meta_by_code[app.codi.upper()] = meta
        app_units_by_code[app.codi.upper()] = str(getattr(app, "competition_unit", "") or "").strip().lower()

    allowed_particio_codes = {item["code"] for item in build_global_native_particio_fields()}
    preserved_particio_codes = set()
    preserved_filter_keys = set()
    existing_schema_tpl = {}
    if tpl_id:
        existing_schema_tpl = extract_template_schema(getattr(tpl, "payload", {}) or {})
        preserved_particio_codes, preserved_filter_keys = collect_global_builder_legacy_keys(
            existing_schema_tpl,
            allowed_particio_codes=allowed_particio_codes,
            allowed_filter_keys=GLOBAL_FILTER_KEYS,
        )

    schema_ui = payload.get("schema") or {}
    schema_tpl, _warnings = global_ui_schema_to_template_schema(schema_ui, by_id, by_code)
    if tpl_id:
        schema_tpl = merge_global_builder_schema(
            existing_schema_tpl,
            schema_tpl,
            allowed_particio_codes=allowed_particio_codes,
            allowed_filter_keys=GLOBAL_FILTER_KEYS,
        )
    schema_tpl, validation_errors, validation_details = validate_template_schema_global(
        schema_tpl,
        available_app_codes={app.codi.upper() for app in apps},
        field_meta_by_code=field_meta_by_code,
        app_units_by_code=app_units_by_code,
        allowed_particio_codes=allowed_particio_codes,
        allowed_filter_keys=GLOBAL_FILTER_KEYS,
        preserved_particio_codes=preserved_particio_codes,
        preserved_filter_keys=preserved_filter_keys,
        tipus=tipus,
    )
    if validation_errors:
        return JsonResponse(
            {
                "ok": False,
                "error": "Plantilla global invalida.",
                "errors": validation_errors,
                "error_details": _build_validation_error_details(validation_details or validation_errors),
            },
            status=400,
        )

    if tpl_id:
        slug_candidate = slugify(slug_raw) if slug_raw else tpl.slug
        if not slug_candidate:
            slug_candidate = next_template_slug(nom, owner.id, exclude_template_id=tpl.id)
        exists = (
            ClassificacioTemplateGlobal.objects.exclude(id=tpl.id)
            .filter(created_by=owner, slug=slug_candidate)
            .exists()
        )
        if exists:
            return JsonResponse({"ok": False, "error": "Ja existeix una plantilla amb aquest slug."}, status=400)
        tpl.nom = nom
        tpl.slug = slug_candidate
        tpl.tipus = tipus
        tpl.activa = activa
        tpl.payload = {"schema": schema_tpl, "source": {"mode": "global_builder"}}
        tpl.requirements = build_template_requirements(schema_tpl, tipus=tipus)
        tpl.version = int(tpl.version or 1) + 1
        tpl.save()
    else:
        slug_candidate = slugify(slug_raw) if slug_raw else next_template_slug(nom, owner.id)
        if not slug_candidate:
            slug_candidate = next_template_slug(nom, owner.id)
        if ClassificacioTemplateGlobal.objects.filter(created_by=owner, slug=slug_candidate).exists():
            return JsonResponse({"ok": False, "error": "Ja existeix una plantilla amb aquest slug."}, status=400)
        tpl = ClassificacioTemplateGlobal.objects.create(
            nom=nom,
            slug=slug_candidate,
            tipus=tipus,
            activa=activa,
            payload={"schema": schema_tpl, "source": {"mode": "global_builder"}},
            requirements=build_template_requirements(schema_tpl, tipus=tipus),
            created_by=owner,
        )

    cfg = _template_to_builder_row(
        tpl,
        by_id=by_id,
        by_code=by_code,
        ordre=int(payload.get("ordre") or 1),
    )
    return JsonResponse({"ok": True, "cfg": cfg})


class ClassificacioTemplateGlobalDeleteView(View):
    def post(self, request, pk):
        qs = ClassificacioTemplateGlobal.objects.all()
        if not _is_global_templates_admin(request.user):
            qs = qs.filter(created_by=request.user)
        tpl = get_object_or_404(qs, pk=pk)
        nom = tpl.nom
        tpl.delete()

        wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in str(
            request.headers.get("Accept") or ""
        )
        if wants_json:
            return JsonResponse({"ok": True})
        messages.success(request, f"Plantilla '{nom}' eliminada.")
        return redirect(reverse("classificacio_template_global_list"))
