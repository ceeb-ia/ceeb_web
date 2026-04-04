from django.utils import timezone
from django.utils.text import slugify

from ...models_classificacions import ClassificacioTemplateGlobal
from ...services.classificacio_templates import (
    build_template_requirements,
    collect_required_app_codes_from_template,
    extract_template_schema,
    get_comp_aparell_maps,
    schema_to_template_schema,
    template_schema_to_competicio_schema,
)
from ...services.classificacions.builder import (
    autofix_schema_for_competicio,
    build_force_minimal_schema,
    next_cfg_ordre_for_competicio,
)
from ...services.classificacions.validation import validate_schema_for_competicio


def parse_fallback_mode(raw) -> str:
    mode = str(raw or "strict").strip().lower()
    if mode not in {"strict", "assistit", "force"}:
        return "strict"
    return mode


def next_fallback_mode(mode: str):
    mode = parse_fallback_mode(mode)
    if mode == "strict":
        return "assistit"
    if mode == "assistit":
        return "force"
    return None


def template_to_payload_row(obj):
    payload = getattr(obj, "payload", {}) or {}
    schema = extract_template_schema(payload)
    requirements = getattr(obj, "requirements", {}) or {}
    computed_req = build_template_requirements(schema, tipus=getattr(obj, "tipus", "individual"))
    if not isinstance(requirements, dict):
        requirements = {}
    requirements = {**requirements, **computed_req}
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
        "updated_at": obj.updated_at.isoformat() if getattr(obj, "updated_at", None) else None,
    }


def next_template_slug(base_name: str, owner_id: int, exclude_template_id=None):
    base = slugify(base_name or "") or "classificacio-template"
    slug = base
    idx = 2
    qs = ClassificacioTemplateGlobal.objects.filter(created_by_id=owner_id)
    if exclude_template_id:
        qs = qs.exclude(id=exclude_template_id)
    existing = set(qs.values_list("slug", flat=True))
    while slug in existing:
        slug = f"{base}-{idx}"
        idx += 1
    return slug


def validate_template_for_competicio(competicio, template_obj, fallback_mode="strict"):
    fallback_mode = parse_fallback_mode(fallback_mode)
    schema_tpl = extract_template_schema(getattr(template_obj, "payload", {}) or {})
    schema_local, mapping_warnings, mapping, compat_meta = template_schema_to_competicio_schema(
        competicio,
        schema_tpl,
    )
    required_codes = collect_required_app_codes_from_template(schema_tpl)
    _, _by_id_active, by_code_active = get_comp_aparell_maps(competicio, active_only=True)

    blocking = []
    warnings = list(mapping_warnings or [])
    dropped = []
    compat_meta = compat_meta if isinstance(compat_meta, dict) else {}
    for code in sorted(required_codes):
        if code and code not in by_code_active:
            message = f"Aparell requerit per la plantilla no disponible a la competicio: {code}"
            if fallback_mode == "strict":
                blocking.append(message)
            else:
                warnings.append(message)

    for item in compat_meta.get("unresolved_manual_team_partitions") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or f"Particio {int(item.get('index', 0)) + 1}").strip()
        missing_names = [str(name or "").strip() for name in (item.get("missing_names") or []) if str(name or "").strip()]
        context_code = str(item.get("context_code") or "").strip()
        if not missing_names:
            continue
        message = (
            f"equips.particions_manuals: la particio '{label}' no pot resoldre els equips "
            f"{', '.join(missing_names)} al context {context_code}."
        )
        if fallback_mode == "strict":
            blocking.append(message)
        else:
            warnings.append(message)

    tpl_tipus = str(getattr(template_obj, "tipus", "individual") or "individual").strip().lower()
    schema_local, strict_errors = validate_schema_for_competicio(competicio, schema_local, tipus=tpl_tipus)
    blocking.extend(strict_errors)

    if fallback_mode in {"assistit", "force"}:
        schema_local, autofix_warnings, autofix_dropped = autofix_schema_for_competicio(
            competicio,
            schema_local,
            mode=fallback_mode,
            tipus=tpl_tipus,
        )
        warnings.extend(autofix_warnings)
        dropped.extend(autofix_dropped)
        schema_local, blocking = validate_schema_for_competicio(competicio, schema_local, tipus=tpl_tipus)

    if fallback_mode == "force" and blocking:
        forced_schema = build_force_minimal_schema(competicio, schema_local)
        forced_schema, force_errors = validate_schema_for_competicio(competicio, forced_schema, tipus=tpl_tipus)
        if len(force_errors) <= len(blocking):
            schema_local = forced_schema
            dropped.append("FORCE: aplicat schema minim per garantir compatibilitat.")
            warnings.append("FORCE: s'ha aplicat un schema minim (particions/desempat simplificats).")
            blocking = force_errors

    next_mode = next_fallback_mode(fallback_mode) if blocking else None
    return {
        "portable": bool(compat_meta.get("portable", True)),
        "adaptable": bool(compat_meta.get("adaptable")) or bool(next_mode),
        "compatible": not blocking,
        "blocking_errors": blocking,
        "warnings": warnings,
        "dropped_rules": dropped,
        "mapping": mapping,
        "resolved_schema": schema_local,
        "phase": fallback_mode,
        "next_fallback": next_mode,
        "can_try_next": bool(next_mode and blocking),
    }


def build_template_save_payload(competicio, cfg):
    schema_tpl, export_warnings = schema_to_template_schema(competicio, cfg.schema or {})
    requirements = build_template_requirements(schema_tpl, tipus=cfg.tipus)
    payload_obj = {
        "schema": schema_tpl,
        "source": {
            "competicio_id": competicio.id,
            "cfg_id": cfg.id,
            "cfg_nom": cfg.nom,
            "exported_at": timezone.now().isoformat(),
        },
    }
    return payload_obj, requirements, export_warnings


__all__ = [
    "build_template_save_payload",
    "next_cfg_ordre_for_competicio",
    "next_template_slug",
    "parse_fallback_mode",
    "template_to_payload_row",
    "validate_template_for_competicio",
]
