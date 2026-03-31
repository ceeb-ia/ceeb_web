import json
import mimetypes
import os
from decimal import Decimal
from collections import defaultdict

from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import Count
from django.urls import reverse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from .models import Competicio, Equip, Inscripcio, InscripcioMedia
from .models_trampoli import CompeticioAparell, InscripcioAparellExclusio
from .access import user_has_competicio_capability
from .services.competition_groups import (
    clear_inscripcions_group,
    get_competicio_groups,
    get_group_card_payload,
    get_group_detail_payload,
    get_group_for_display_num,
    get_group_maps,
    get_group_member_preview,
    get_group_summary_counts,
    get_programmed_group_ids,
    get_programmed_groups_emptied_by_ids,
    move_inscripcions_to_group,
    next_group_display_num,
    normalize_inscripcio_ids,
    safe_deactivate_empty_group,
    sync_competicio_group_names_view,
    ensure_group_for_display_num,
    group_label,
)
from .services.equip_contexts import (
    NATIVE_EQUIP_CONTEXT_CODE,
    get_equip_context_summary,
    get_equip_context_payload,
    get_equips_for_context,
    normalize_equip_context_code,
)
from .services.media_matching import (
    build_inscripcio_media_match_candidates,
    match_media_files_to_inscripcions,
    normalize_media_matching_config,
)
from .services.birth_year_ranges import (
    BIRTH_YEAR_RANGE_PARTITION_CODE,
    clear_inscripcions_derived_group_config_cache,
    get_inscripcions_derived_group_config,
    normalize_birth_year_range_partition_config_for_inscripcions,
    validate_birth_year_range_partition_config,
)
from .views import (
    InscripcionsListView,
    annotate_inscripcions_queryset_for_group_codes,
    _build_inscripcions_filtered_qs,
    _normalize_sort_filters,
    _normalize_sort_group_by,
    _normalize_sort_criterion,
    _parse_fallback_mode,
    _message_for_emptied_programmed_groups,
    get_available_column_filter_fields,
    get_available_sort_fields,
    get_allowed_group_fields,
    get_competicio_custom_sort_codes,
    get_inscripcions_sort_context_state,
    get_request_inscripcio_filters,
    build_inscripcions_sort_context_key,
    reconcile_inscripcions_sort_context_state,
    _extract_sort_partition_codes,
    _build_sort_partition_buckets,
    _resolve_group_creation_buckets,
    capture_inscripcions_history_snapshot,
    competicio_has_rotacions,
    get_inscripcions_history_state,
    record_inscripcions_history_entry,
    with_inscripcions_history_payload,
)

MEDIA_MAX_SIZE_BYTES = 250 * 1024 * 1024
MEDIA_ALLOWED_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".ogg",
    ".mp4",
    ".mov",
    ".m4v",
    ".webm",
    ".jpg",
    ".jpeg",
    ".png",
}


BUILTIN_TABLE_FIELDS = [
    {"code": "nom_i_cognoms", "label": "Nom i cognoms", "kind": "builtin"},
    {"code": "document", "label": "DNI/Document", "kind": "builtin"},
    {"code": "sexe", "label": "Sexe", "kind": "builtin"},
    {"code": "data_naixement", "label": "Data naixement", "kind": "builtin"},
    {"code": "entitat", "label": "Entitat", "kind": "builtin"},
    {"code": "categoria", "label": "Categoria", "kind": "builtin"},
    {"code": "subcategoria", "label": "Subcategoria", "kind": "builtin"},
    {"code": "grup", "label": "Grup", "kind": "builtin"},
    {"code": "equip", "label": "Equip", "kind": "builtin"},
    {"code": "__aparells__", "label": "Aparells", "kind": "ui"},
    {"code": "__media__", "label": "Media", "kind": "ui"},
    {"code": "ordre_sortida", "label": "Ordre", "kind": "builtin"},
]

SYSTEM_NATIVE_TABLE_CODES = {"grup", "equip", "ordre_sortida", "__aparells__", "__media__", "__actions__"}


def _reserved_inscripcio_codes():
    out = set()
    for f in Inscripcio._meta.concrete_fields:
        name = str(getattr(f, "name", "") or "").strip()
        attname = str(getattr(f, "attname", "") or "").strip()
        if name:
            out.add(name)
        if attname:
            out.add(attname)
    return out


def _normalize_schema_extra_code(code: str, reserved_codes):
    code = (code or "").strip()
    if not code:
        return code
    if code.startswith("excel__"):
        return code
    if code in reserved_codes:
        return f"excel__{code}"
    return code


def _label_with_source(label: str, source: str):
    suffix = "Excel" if source == "excel" else "Nativa"
    return f"{label} ({suffix})"


def _get_media_matching_config(competicio):
    view_cfg = competicio.inscripcions_view or {}
    raw_cfg = view_cfg.get("media_matching")
    return normalize_media_matching_config(raw_cfg)


def _guess_media_tipus(*, mime_type: str, filename: str) -> str:
    mime_l = str(mime_type or "").strip().lower()
    if mime_l.startswith("audio/"):
        return InscripcioMedia.Tipus.AUDIO
    if mime_l.startswith("video/"):
        return InscripcioMedia.Tipus.VIDEO
    if mime_l.startswith("image/"):
        return InscripcioMedia.Tipus.IMAGE

    ext = os.path.splitext(str(filename or ""))[1].lower()
    if ext in {".mp3", ".wav", ".m4a", ".aac", ".ogg"}:
        return InscripcioMedia.Tipus.AUDIO
    if ext in {".mp4", ".mov", ".m4v", ".webm"}:
        return InscripcioMedia.Tipus.VIDEO
    if ext in {".jpg", ".jpeg", ".png"}:
        return InscripcioMedia.Tipus.IMAGE
    return InscripcioMedia.Tipus.OTHER


def _validate_uploaded_media_file(uploaded):
    if uploaded is None:
        raise ValueError("Falta fitxer multimèdia.")

    size = int(getattr(uploaded, "size", 0) or 0)
    if size <= 0:
        raise ValueError("Fitxer buit.")
    if size > MEDIA_MAX_SIZE_BYTES:
        raise ValueError(f"El fitxer supera el limit de {MEDIA_MAX_SIZE_BYTES} bytes.")

    filename = str(getattr(uploaded, "name", "") or "").strip()
    ext = os.path.splitext(filename)[1].lower()
    if ext not in MEDIA_ALLOWED_EXTENSIONS:
        raise ValueError("Extensio de fitxer no permesa.")

    mime_type = str(getattr(uploaded, "content_type", "") or "").strip().lower()
    if not mime_type:
        mime_type = str(mimetypes.guess_type(filename)[0] or "").strip().lower()
    return {
        "filename": filename,
        "size": size,
        "mime_type": mime_type,
        "tipus": _guess_media_tipus(mime_type=mime_type, filename=filename),
    }


def _serialize_media_item(item):
    return {
        "id": item.id,
        "inscripcio_id": item.inscripcio_id,
        "tipus": item.tipus,
        "mime_type": item.mime_type or "",
        "original_filename": item.original_filename or "",
        "file_size_bytes": int(item.file_size_bytes or 0),
        "is_primary": bool(item.is_primary),
        "source": item.source or "",
        "match_score": float(item.match_score) if item.match_score is not None else None,
        "url": reverse("inscripcions_media_file", kwargs={"pk": item.competicio_id, "media_id": item.id}),
    }


def get_available_table_columns(competicio):
    """
    Retorna llista [{code, label, kind}] amb builtins + extras detectats + accions.
    """
    out = []
    seen = set()
    reserved = _reserved_inscripcio_codes()

    schema = competicio.inscripcions_schema or {}
    columns = schema.get("columns") or []
    excel_codes = set()
    if isinstance(columns, list):
        for col in columns:
            if not isinstance(col, dict):
                continue
            code = col.get("code")
            if not code:
                continue
            kind = col.get("kind") or "extra"
            if kind == "extra":
                code = _normalize_schema_extra_code(code, reserved)
            excel_codes.add(code)

    for field in BUILTIN_TABLE_FIELDS:
        if field["code"] not in seen:
            source = "native" if field["code"] in SYSTEM_NATIVE_TABLE_CODES else ("excel" if field["code"] in excel_codes else "native")
            out.append(
                {
                    **field,
                    "source": source,
                    "ui_label": _label_with_source(field["label"], source),
                }
            )
            seen.add(field["code"])

    if isinstance(columns, list):
        for col in columns:
            if not isinstance(col, dict):
                continue
            code = col.get("code")
            if not code:
                continue
            kind = col.get("kind") or "extra"
            if kind == "extra":
                code = _normalize_schema_extra_code(code, reserved)
            if code in seen:
                continue
            label = col.get("label") or code
            out.append(
                {
                    "code": code,
                    "label": label,
                    "kind": kind,
                    "source": "excel",
                    "ui_label": _label_with_source(label, "excel"),
                }
            )
            seen.add(code)

    out.append(
        {
            "code": "__actions__",
            "label": "Accions",
            "kind": "ui",
            "source": "native",
            "ui_label": _label_with_source("Accions", "native"),
        }
    )
    return out


def get_selected_table_columns(competicio, available_cols):
    """
    Retorna columnes seleccionades i ordenades segons competicio.inscripcions_view["table_columns"].
    """
    view_cfg = competicio.inscripcions_view or {}
    selected_codes = view_cfg.get("table_columns")
    if not isinstance(selected_codes, list) or not selected_codes:
        selected_codes = [
            "nom_i_cognoms",
            "document",
            "sexe",
            "data_naixement",
            "entitat",
            "categoria",
            "subcategoria",
            "grup",
            "equip",
            "__aparells__",
            "__media__",
            "ordre_sortida",
            "__actions__",
        ]

    by_code = {c["code"]: c for c in available_cols}
    selected = [by_code[c] for c in selected_codes if c in by_code]
    if not selected and "nom_i_cognoms" in by_code:
        selected = [by_code["nom_i_cognoms"]]
    return selected


class InscripcionsListNewView(InscripcionsListView):
    """
    Merge proposat:
    - Manté la logica robusta de views.InscripcionsListView
    - Afegeix la capa UI del borrador (columnes configurables + noms de grup)
    """

    template_name = "competicio/inscricpions_list_new.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["can_edit_inscripcions"] = user_has_competicio_capability(
            self.request.user,
            self.competicio,
            "inscripcions.edit",
        )
        filtered_qs = self.get_queryset_base_filtrada()
        ctx["inscrits_filtered_count"] = filtered_qs.count()
        ctx["inscrits_total_count"] = Inscripcio.objects.filter(
            competicio=self.competicio
        ).count()
        ctx["existing_groups_count"] = (
            filtered_qs.exclude(grup__isnull=True)
            .values("grup")
            .distinct()
            .count()
        )

        available_table_columns = get_available_table_columns(self.competicio)
        selected_table_columns = get_selected_table_columns(
            self.competicio, available_table_columns
        )
        active_filters = get_request_inscripcio_filters(
            self.request,
            competicio=self.competicio,
        )
        column_filter_fields = get_available_column_filter_fields(self.competicio)
        filterable_codes = {f["code"] for f in column_filter_fields}
        active_column_filters = dict(active_filters.get("column_filters") or {})

        ctx["available_table_columns"] = available_table_columns
        ctx["selected_table_columns"] = selected_table_columns
        ctx["table_colspan"] = len(selected_table_columns) if selected_table_columns else 1
        sort_options = ctx.get("sort_field_options") or []
        ctx["sortable_table_column_codes"] = [
            s.get("code")
            for s in sort_options
            if isinstance(s, dict) and s.get("code")
        ]
        sortable_codes = set(ctx["sortable_table_column_codes"])
        ctx["filterable_table_column_codes"] = sorted(filterable_codes)
        ctx["column_menu_codes"] = sorted(sortable_codes | filterable_codes)
        custom_sort_codes = set(
            get_competicio_custom_sort_codes(
                self.competicio,
                allowed_sort_codes=sortable_codes,
            )
        )

        active_group_by = list(ctx.get("selected_group_fields") or [])
        sort_context_key = build_inscripcions_sort_context_key(
            self.competicio.id,
            filters=active_filters,
            group_by=active_group_by,
        )
        current_ids = list(
            filtered_qs.order_by("ordre_sortida", "id").values_list("id", flat=True)
        )
        sort_state = reconcile_inscripcions_sort_context_state(
            self.request,
            sort_context_key,
            current_ids,
        )
        sort_stack = [
            entry
            for entry in (sort_state.get("stack") or [])
            if isinstance(entry, dict) and entry.get("sort_key") in sortable_codes
        ]
        competition_order_tail_active = bool(sort_stack) and bool(
            sort_state.get("competition_order_tail")
        )

        sort_label_by_code = {}
        for s in sort_options:
            if not isinstance(s, dict):
                continue
            code = s.get("code")
            if not code:
                continue
            sort_label_by_code[code] = s.get("ui_label") or s.get("label") or code

        dir_to_symbol = {
            "asc": "↑",
            "desc": "↓",
            "arrow_asc": "↕↑",
            "arrow_desc": "↕↓",
            "custom": "C",
        }
        dir_to_label = {
            "asc": "Ascendent",
            "desc": "Descendent",
            "arrow_asc": "Fletxa ascendent",
            "arrow_desc": "Fletxa descendent",
            "custom": "Custom",
        }

        sort_entries = []
        for priority, entry in enumerate(sort_stack, start=1):
            sort_code = str(entry.get("sort_key") or "")
            if not sort_code:
                continue
            sort_dir = str(entry.get("sort_dir") or "asc")
            scope = str(entry.get("scope") or "all")
            scope_short = "TF"
            scope_label = "Totes les inscripcions filtrades"
            if scope == "tab":
                scope_short = "P"
                scope_label = "Dins de cada pestanya activa"
            elif scope == "all_groups":
                scope_short = "TG"
                scope_label = "Dins de cada grup numeric complet"
            elif scope == "group":
                group_num = entry.get("group_num")
                scope_short = f"G{group_num}" if group_num else "G"
                scope_label = (
                    f"Nomes grup numeric {group_num} complet"
                    if group_num else
                    "Nomes un grup numeric concret"
                )

            symbol = dir_to_symbol.get(sort_dir, "↑")
            sort_entries.append(
                {
                    "priority": priority,
                    "remove_priority": priority,
                    "code": sort_code,
                    "label": sort_label_by_code.get(sort_code, sort_code),
                    "symbol": symbol,
                    "sort_dir": sort_dir,
                    "sort_dir_label": dir_to_label.get(sort_dir, sort_dir),
                    "scope": scope,
                    "scope_short": scope_short,
                    "scope_label": scope_label,
                    "custom_active": sort_dir == "custom",
                    "title": f"#{priority} - {dir_to_label.get(sort_dir, sort_dir)} - {scope_label}",
                }
            )

        indicator_by_code = {}
        for item in sort_entries:
            sort_code = item["code"]
            if sort_code in indicator_by_code:
                continue
            indicator_by_code[sort_code] = {
                "priority": item["priority"],
                "remove_priority": item["remove_priority"],
                "symbol": item["symbol"],
                "scope_short": item["scope_short"],
                "title": item["title"],
            }

        ctx["column_sort_context_key"] = sort_context_key
        ctx["column_sort_stack"] = sort_stack
        ctx["column_sort_has_stack"] = bool(sort_stack)
        ctx["column_sort_stack_count"] = len(sort_stack)
        ctx["column_sort_effective_count"] = len(sort_stack) + (
            1 if competition_order_tail_active else 0
        )
        ctx["column_sort_competition_tail_active"] = competition_order_tail_active
        ctx["column_sort_competition_tail_priority"] = len(sort_stack) + 1
        ctx["column_sort_entries"] = sort_entries
        ctx["column_sort_indicator_by_code"] = indicator_by_code
        ctx["custom_sort_enabled_by_code"] = {code: True for code in custom_sort_codes}
        ctx["column_filter_indicator_by_code"] = {
            code: {
                "count": len(tokens),
                "title": f"{len(tokens)} valor(s) filtrat(s)",
            }
            for code, tokens in active_column_filters.items()
            if tokens
        }
        ctx["column_filter_tokens_by_code"] = active_column_filters
        ctx["active_column_filter_items"] = [
            {
                "param": f"cf_{code}",
                "token": token,
            }
            for code, tokens in active_column_filters.items()
            for token in tokens
        ]

        partition_codes = _extract_sort_partition_codes(sort_stack)
        partition_fields = []
        for priority, code in enumerate(partition_codes, start=1):
            partition_fields.append(
                {
                    "priority": priority,
                    "code": code,
                    "label": sort_label_by_code.get(code, code),
                }
            )

        partition_buckets = []
        if partition_codes:
            partition_builtin_fields = [c for c in partition_codes if hasattr(Inscripcio, c)]
            records_for_partition_qs = annotate_inscripcions_queryset_for_group_codes(
                filtered_qs,
                self.competicio,
                partition_codes,
            )
            records_for_partition = list(
                records_for_partition_qs.order_by("ordre_sortida", "id").only("id", "extra", "data_naixement", *partition_builtin_fields)
            )
            buckets_raw = _build_sort_partition_buckets(records_for_partition, partition_codes)
            partition_buckets = [
                {
                    "key": b["key"],
                    "label": b["label"],
                    "count": b["count"],
                }
                for b in buckets_raw
            ]

        ctx["sort_partition_fields"] = partition_fields
        ctx["sort_partition_has_fields"] = bool(partition_fields)
        ctx["sort_partition_buckets"] = partition_buckets
        ctx["sort_partition_bucket_count"] = len(partition_buckets)

        group_field_options = get_allowed_group_fields(self.competicio)
        group_field_label_by_code = {
            f["code"]: f.get("ui_label") or f.get("label") or f["code"]
            for f in group_field_options
            if isinstance(f, dict) and f.get("code")
        }
        ctx["group_creation_group_fields"] = [
            {
                "code": code,
                "label": group_field_label_by_code.get(code, code),
            }
            for code in active_group_by
        ]
        group_resolution_codes = list(dict.fromkeys(list(active_group_by) + list(partition_codes)))
        group_resolution_builtin_fields = [
            code for code in group_resolution_codes if hasattr(Inscripcio, code)
        ]
        records_for_group_resolution_qs = annotate_inscripcions_queryset_for_group_codes(
            filtered_qs,
            self.competicio,
            group_resolution_codes,
        )
        records_for_group_resolution = list(
            records_for_group_resolution_qs.order_by("ordre_sortida", "id").only(
                "id",
                "extra",
                "data_naixement",
                *group_resolution_builtin_fields,
            )
        )
        auto_group_resolution = _resolve_group_creation_buckets(
            self.competicio,
            records_for_group_resolution,
            group_codes=active_group_by,
            partition_codes=partition_codes,
            fallback_mode="all_filtered",
        )
        auto_group_buckets_raw = (
            auto_group_resolution.get("buckets") if auto_group_resolution.get("ok") else []
        ) or []
        auto_group_layers_used = list(auto_group_resolution.get("layers_used") or [])
        if auto_group_layers_used == ["tabs", "sort"]:
            auto_group_resolution_label = "Agrupacions x ordenacions"
        elif auto_group_layers_used == ["tabs"]:
            auto_group_resolution_label = "Agrupacions actives"
        elif auto_group_layers_used == ["sort"]:
            auto_group_resolution_label = "Ordenacions segmentadores"
        else:
            auto_group_resolution_label = "Fallback sobre les filtrades"
        ctx["group_creation_resolution_mode"] = "auto"
        ctx["group_creation_resolution_layers_used"] = auto_group_layers_used
        ctx["group_creation_resolution_label"] = auto_group_resolution_label
        ctx["group_creation_has_resolvable_criteria"] = bool(auto_group_layers_used)
        ctx["group_creation_auto_buckets"] = [
            {
                "key": bucket.get("key"),
                "label": bucket.get("label"),
                "count": bucket.get("count"),
                "sources": bucket.get("sources") or [],
                "kinds": [
                    str(source.get("kind") or "").strip().lower()
                    for source in (bucket.get("sources") or [])
                    if str(source.get("kind") or "").strip()
                ],
            }
            for bucket in auto_group_buckets_raw
        ]
        ctx["group_creation_auto_bucket_count"] = len(ctx["group_creation_auto_buckets"])
        derived_group_cfg = get_inscripcions_derived_group_config(self.competicio.inscripcions_view or {})
        ctx["birth_year_range_group_config"] = (
            derived_group_cfg.get(BIRTH_YEAR_RANGE_PARTITION_CODE) or {"ranges": []}
        )

        ctx["group_names"] = get_group_maps(self.competicio).get("name_map") or {}
        ctx["group_member_totals"] = {
            str(row["grup"]): int(row["total"] or 0)
            for row in (
                Inscripcio.objects
                .filter(competicio=self.competicio)
                .exclude(grup__isnull=True)
                .values("grup")
                .annotate(total=Count("id"))
            )
            if row.get("grup") is not None
        }

        team_context_code = normalize_equip_context_code(self.request.GET.get("team_context"))
        valid_team_context_codes = {item["code"] for item in get_equip_context_payload(self.competicio)}
        if team_context_code not in valid_team_context_codes:
            team_context_code = NATIVE_EQUIP_CONTEXT_CODE
        team_fields = group_field_options
        team_field_codes = {f["code"] for f in team_fields}
        default_team_fields = [c for c in ("entitat", "subcategoria", "sexe") if c in team_field_codes]
        teams_list = list(get_equips_for_context(self.competicio, team_context_code))
        base_teams_list = list(get_equips_for_context(self.competicio, NATIVE_EQUIP_CONTEXT_CODE))
        ctx["team_partition_fields"] = team_fields
        ctx["team_partition_default_fields"] = default_team_fields
        ctx["equips_existing"] = teams_list
        ctx["equip_name_map"] = {str(e.id): e.nom for e in base_teams_list}
        ctx["team_contexts"] = get_equip_context_payload(self.competicio)
        ctx["team_context_selected_code"] = team_context_code
        ctx["team_context_summary"] = get_equip_context_summary(self.competicio, team_context_code)
        ctx["series_team_aparells"] = list(
            CompeticioAparell.objects
            .filter(
                competicio=self.competicio,
                actiu=True,
                aparell__competition_unit="team",
            )
            .select_related("aparell")
            .order_by("ordre", "id")
        )

        # Pas 8 del pla: dades necessàries per a la columna "Aparells".
        aparells_cfg = list(
            CompeticioAparell.objects
            .filter(competicio=self.competicio, actiu=True)
            .select_related("aparell")
            .order_by("ordre", "id")
        )
        active_app_ids = [a.id for a in aparells_cfg]
        ctx["inscripcio_aparells_cfg"] = aparells_cfg
        ctx["inscripcio_aparells_active_ids"] = active_app_ids

        visible_ins_ids = set()
        records_grouped = ctx.get("records_grouped")
        if records_grouped:
            for _label, rows, _group_key in records_grouped:
                for r in rows:
                    base_equip_id = getattr(r, "_base_equip_id_cache", None)
                    setattr(r, "base_equip_id", base_equip_id)
                    if getattr(r, "id", None):
                        visible_ins_ids.add(r.id)
        else:
            for r in (ctx.get("records") or []):
                base_equip_id = getattr(r, "_base_equip_id_cache", None)
                setattr(r, "base_equip_id", base_equip_id)
                if getattr(r, "id", None):
                    visible_ins_ids.add(r.id)

        excluded_map = {str(ins_id): [] for ins_id in visible_ins_ids}
        if visible_ins_ids and active_app_ids:
            excl_pairs = (
                InscripcioAparellExclusio.objects
                .filter(
                    inscripcio_id__in=visible_ins_ids,
                    comp_aparell_id__in=active_app_ids,
                )
                .values_list("inscripcio_id", "comp_aparell_id")
            )
            for ins_id, app_id in excl_pairs:
                excluded_map.setdefault(str(ins_id), []).append(app_id)
            for ins_id in excluded_map.keys():
                excluded_map[ins_id].sort()

        ctx["inscripcio_aparells_excluded_map"] = excluded_map
        media_map = {str(ins_id): [] for ins_id in visible_ins_ids}
        if visible_ins_ids:
            media_qs = (
                InscripcioMedia.objects
                .filter(competicio=self.competicio, inscripcio_id__in=visible_ins_ids)
                .order_by("inscripcio_id", "-is_primary", "-created_at", "id")
            )
            for media in media_qs:
                media_map.setdefault(str(media.inscripcio_id), []).append(_serialize_media_item(media))
        ctx["inscripcio_media_map"] = media_map

        all_ins_qs = (
            Inscripcio.objects
            .filter(competicio=self.competicio)
            .order_by("ordre_sortida", "id")
            .only("id", "nom_i_cognoms", "entitat", "subcategoria", "sexe")
        )
        media_match_options = []
        for ins in all_ins_qs:
            ent = str(getattr(ins, "entitat", "") or "").strip()
            sub = str(getattr(ins, "subcategoria", "") or "").strip()
            sexe = str(getattr(ins, "sexe", "") or "").strip()
            extra = [x for x in [ent, sub, sexe] if x]
            label = str(getattr(ins, "nom_i_cognoms", "") or "").strip()
            if extra:
                label = f"{label} ({' · '.join(extra)})"
            media_match_options.append({"id": ins.id, "label": label})

        ctx["media_match_inscripcions_options"] = media_match_options
        ctx["media_matching_config"] = _get_media_matching_config(self.competicio)
        ctx["history_state"] = get_inscripcions_history_state(self.request, self.competicio.id)

        return ctx


@require_POST
@csrf_protect
def inscripcions_save_table_columns(request, pk):
    """
    Desa columnes seleccionades + ordre de la taula d'inscripcions.
    """
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    cols = payload.get("table_columns") or payload.get("columns") or []
    if not isinstance(cols, list):
        return HttpResponseBadRequest("table_columns ha de ser una llista")

    available = get_available_table_columns(competicio)
    allowed_codes = {item["code"] for item in available}

    cleaned = []
    for value in cols:
        if not isinstance(value, str):
            continue
        if value in allowed_codes and value not in cleaned:
            cleaned.append(value)

    if not cleaned:
        return HttpResponseBadRequest("No hi ha cap columna valida")

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    view_cfg = competicio.inscripcions_view or {}
    view_cfg["table_columns"] = cleaned
    competicio.inscripcions_view = view_cfg
    competicio.save(update_fields=["inscripcions_view"])
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="save_table_columns",
        action_label="Desar columnes de taula",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    return JsonResponse(
        with_inscripcions_history_payload(
            {"ok": True, "table_columns": cleaned},
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def inscripcions_set_group_name(request, pk):
    """
    Desa el nom d'un grup numeric (Inscripcio.grup).
    """
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    group = payload.get("group")
    name = (payload.get("name") or "").strip()
    try:
        group_int = int(group)
    except Exception:
        return HttpResponseBadRequest("group invalid")

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    group = get_group_for_display_num(competicio, group_int)
    if group is None:
        return HttpResponseBadRequest("group invalid")

    if group.nom != name:
        group.nom = name
        group.save(update_fields=["nom"])
    sync_competicio_group_names_view(competicio)
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="set_group_name",
        action_label="Desar nom de grup",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    return JsonResponse(
        with_inscripcions_history_payload(
            {"ok": True, "group": group_int, "name": name},
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def inscripcions_save_birth_year_range_config(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    raw_cfg = payload.get("config") if isinstance(payload, dict) else {}
    cfg, errors = validate_birth_year_range_partition_config(raw_cfg, require_ranges=True)
    if errors:
        return HttpResponseBadRequest("\n".join(errors))
    storage_cfg = normalize_birth_year_range_partition_config_for_inscripcions(cfg)

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    view_cfg = dict(competicio.inscripcions_view or {})
    derived_group_cfg = view_cfg.get("derived_group_config")
    if not isinstance(derived_group_cfg, dict):
        derived_group_cfg = {}
    else:
        derived_group_cfg = dict(derived_group_cfg)
    derived_group_cfg[BIRTH_YEAR_RANGE_PARTITION_CODE] = storage_cfg
    view_cfg["derived_group_config"] = derived_group_cfg
    competicio.inscripcions_view = view_cfg
    competicio.save(update_fields=["inscripcions_view"])
    clear_inscripcions_derived_group_config_cache()
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="save_birth_year_range_group_config",
        action_label="Desar forquilles de data de naixement",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    return JsonResponse(
        with_inscripcions_history_payload(
            {"ok": True, "config": storage_cfg},
            request,
            competicio.id,
        )
    )


def _normalize_group_workspace_filters(raw_filters):
    filters = raw_filters if isinstance(raw_filters, dict) else {}
    def _normalize_positive_int_list(raw_values):
        out = []
        values = raw_values if isinstance(raw_values, list) else []
        for value in values:
            try:
                clean = int(value)
            except Exception:
                continue
            if clean > 0 and clean not in out:
                out.append(clean)
        return out

    out = {
        **_normalize_sort_filters(filters),
        "group_state": str(filters.get("group_state") or "all").strip().lower(),
        "group_ids": _normalize_positive_int_list(filters.get("group_ids")),
        "group_id": None,
        "group_num": None,
    }
    if out["group_state"] not in {"all", "assigned", "unassigned"}:
        out["group_state"] = "all"
    try:
        group_id = int(filters.get("group_id"))
    except Exception:
        group_id = None
    try:
        group_num = int(filters.get("group_num"))
    except Exception:
        group_num = None
    if out.get("categoria") and out["categoria"] not in out["categories"]:
        out["categories"].append(out["categoria"])
    if out.get("subcategoria") and out["subcategoria"] not in out["subcategories"]:
        out["subcategories"].append(out["subcategoria"])
    if out.get("entitat") and out["entitat"] not in out["entitats"]:
        out["entitats"].append(out["entitat"])
    out["group_id"] = group_id if group_id and group_id > 0 else None
    out["group_num"] = group_num if group_num and group_num > 0 else None
    if out["group_id"] and out["group_id"] not in out["group_ids"]:
        out["group_ids"].append(out["group_id"])
    return out


def _build_group_workspace_candidates_qs(competicio, filters):
    filters = _normalize_group_workspace_filters(filters)
    qs = _build_inscripcions_filtered_qs(competicio, filters)
    group_ids = list(filters.get("group_ids") or [])
    group_id = filters.get("group_id")
    group_num = filters.get("group_num")
    if group_ids:
        qs = qs.filter(grup_competicio_id__in=group_ids)
    elif group_id:
        qs = qs.filter(grup_competicio_id=group_id)
    elif group_num:
        qs = qs.filter(grup=group_num)
    if filters["group_state"] == "assigned":
        qs = qs.filter(grup_competicio__isnull=False)
    elif filters["group_state"] == "unassigned":
        qs = qs.filter(grup_competicio__isnull=True)
    return qs


def _resolve_group_workspace_filtered_target_ids(competicio, filters):
    normalized_filters = _normalize_group_workspace_filters(filters)
    target_ids = list(
        _build_group_workspace_candidates_qs(competicio, normalized_filters)
        .order_by("ordre_sortida", "id")
        .values_list("id", flat=True)
    )
    return {
        "filters": normalized_filters,
        "target_ids": normalize_inscripcio_ids(target_ids),
    }


def _resolve_group_workspace_target_ids(competicio, payload):
    filters = _normalize_group_workspace_filters(payload.get("filters"))
    selected_ids = normalize_inscripcio_ids(payload.get("selected_ids") or payload.get("ids") or [])
    if selected_ids:
        target_ids = list(selected_ids)
    elif str(payload.get("scope") or "").strip().lower() == "filtered":
        target_ids = _resolve_group_workspace_filtered_target_ids(competicio, filters)["target_ids"]
    else:
        target_ids = []

    return {
        "filters": filters,
        "selected_ids": selected_ids,
        "target_ids": normalize_inscripcio_ids(target_ids),
    }


def _resolve_group_workspace_group(competicio, payload, include_inactive=True):
    group_id = None
    raw_group_id = payload.get("group_id")
    raw_group_num = payload.get("group_num")
    if str(raw_group_id or "").strip().isdigit():
        group_id = int(raw_group_id)

    group_maps = get_group_maps(competicio, include_inactive=include_inactive)
    group = None
    if group_id:
        group = group_maps["by_id"].get(group_id)
    if group is None and str(raw_group_num or "").strip().isdigit():
        group = get_group_for_display_num(competicio, int(raw_group_num))
    return group


def _serialize_group_workspace_candidate(ins, selected_ids=None):
    group = getattr(ins, "grup_competicio", None)
    selected_ids = set(selected_ids or [])
    group_label_value = group_label(group) if group is not None else "Sense grup"
    return {
        "id": ins.id,
        "label": str(getattr(ins, "nom_i_cognoms", "") or "").strip() or f"Inscripcio {ins.id}",
        "secondary_label": str(getattr(ins, "entitat", "") or "").strip(),
        "group_id": getattr(ins, "grup_competicio_id", None),
        "group_num": int(group.display_num) if group is not None and getattr(group, "display_num", None) else getattr(ins, "grup", None),
        "group_label": group_label_value,
        "group_state": "unassigned" if group is None else ("assigned" if not getattr(group, "actiu", True) else "assigned"),
        "ordre_competicio": int(ins.ordre_competicio) if getattr(ins, "ordre_competicio", None) is not None else None,
        "ordre_sortida": int(ins.ordre_sortida) if getattr(ins, "ordre_sortida", None) is not None else None,
        "is_selected": ins.id in selected_ids,
    }


def _build_group_workspace_filter_options(records, groups):
    categories = sorted({
        str(getattr(ins, "categoria", "") or "").strip()
        for ins in records
        if str(getattr(ins, "categoria", "") or "").strip()
    })
    subcategories = sorted({
        str(getattr(ins, "subcategoria", "") or "").strip()
        for ins in records
        if str(getattr(ins, "subcategoria", "") or "").strip()
    })
    entitats = sorted({
        str(getattr(ins, "entitat", "") or "").strip()
        for ins in records
        if str(getattr(ins, "entitat", "") or "").strip()
    })
    return {
        "categories": categories,
        "subcategories": subcategories,
        "entitats": entitats,
        "group_states": [
            {"id": "all", "label": "Totes"},
            {"id": "assigned", "label": "Amb grup"},
            {"id": "unassigned", "label": "Sense grup"},
        ],
        "groups": [
            {
                "id": int(group.id),
                "display_num": int(group.display_num),
                "label": group_label(group),
            }
            for group in groups
        ],
    }


def _build_group_workspace_filter_option_source_qs(competicio, filters):
    option_filters = {
        **_normalize_sort_filters(filters),
        "categoria": "",
        "subcategoria": "",
        "entitat": "",
        "categories": [],
        "subcategories": [],
        "entitats": [],
    }
    return _build_inscripcions_filtered_qs(competicio, option_filters)


def _build_group_workspace_selection_summary(competicio, selected_ids):
    selected_ids = normalize_inscripcio_ids(selected_ids)
    if not selected_ids:
        return {
            "count": 0,
            "assigned_count": 0,
            "unassigned_count": 0,
            "group_count": 0,
            "group_ids": [],
            "group_labels": [],
            "member_names_preview": [],
        }

    rows = list(
        Inscripcio.objects
        .filter(competicio=competicio, id__in=selected_ids)
        .select_related("grup_competicio")
        .order_by("ordre_sortida", "id")
        .only("id", "nom_i_cognoms", "grup_competicio_id", "grup", "ordre_sortida")
    )
    group_ids = []
    group_labels = []
    seen_group_ids = set()
    member_names = []
    assigned_count = 0
    for ins in rows:
        group = getattr(ins, "grup_competicio", None)
        if group is not None:
            assigned_count += 1
            if group.id not in seen_group_ids:
                seen_group_ids.add(group.id)
                group_ids.append(group.id)
                group_labels.append(group_label(group))
        member_name = str(getattr(ins, "nom_i_cognoms", "") or "").strip()
        if member_name:
            member_names.append(member_name)

    return {
        "count": len(rows),
        "assigned_count": assigned_count,
        "unassigned_count": max(0, len(rows) - assigned_count),
        "group_count": len(group_ids),
        "group_ids": group_ids,
        "group_labels": group_labels,
        "member_names_preview": member_names[:5],
        "member_names_remaining": max(0, len(member_names) - min(len(member_names), 5)),
    }


def _build_group_workspace_payload(competicio, payload):
    filtered_target_bundle = _resolve_group_workspace_filtered_target_ids(
        competicio,
        payload.get("filters"),
    )
    filters = filtered_target_bundle["filters"]
    selected_ids = normalize_inscripcio_ids(payload.get("selected_ids") or payload.get("ids") or [])
    page = 1
    page_size = 40
    try:
        page = int(payload.get("page") or 1)
    except Exception:
        page = 1
    try:
        page_size = int(payload.get("page_size") or 40)
    except Exception:
        page_size = 40
    page = max(1, page)
    page_size = max(1, min(200, page_size))

    filter_option_records = list(
        _build_group_workspace_filter_option_source_qs(competicio, filters)
        .order_by("ordre_sortida", "id")
        .only("id", "categoria", "subcategoria", "entitat")
    )

    candidates_qs = _build_group_workspace_candidates_qs(competicio, filters)

    candidate_records = list(
        candidates_qs
        .select_related("grup_competicio")
        .order_by("ordre_sortida", "id")
        .only(
            "id",
            "nom_i_cognoms",
            "entitat",
            "categoria",
            "subcategoria",
            "grup",
            "grup_competicio_id",
            "ordre_competicio",
            "ordre_sortida",
        )
    )
    total_candidates = len(candidate_records)
    start = (page - 1) * page_size
    stop = start + page_size
    page_rows = candidate_records[start:stop]

    summary = get_group_summary_counts(competicio, include_inactive=False)
    groups = list(get_competicio_groups(competicio, include_inactive=False))
    group_cards = []
    for group in groups:
        group_cards.append(
            get_group_card_payload(
                group,
                members_count=None,
                member_limit=5,
            )
        )

    return {
        "summary": summary,
        "rotacions_active": bool(competicio_has_rotacions(competicio)),
        "selection": _build_group_workspace_selection_summary(competicio, selected_ids),
        "filters": filters,
        "filter_options": _build_group_workspace_filter_options(filter_option_records, groups),
        "selected_ids": selected_ids,
        "paging": {
            "page": page,
            "page_size": page_size,
            "total": total_candidates,
            "pages": max(1, (total_candidates + page_size - 1) // page_size) if total_candidates else 1,
        },
        "candidates": [_serialize_group_workspace_candidate(ins, selected_ids=selected_ids) for ins in page_rows],
        "groups": group_cards,
    }


def _build_group_workspace_auto_context(competicio, request, payload):
    filters = _normalize_group_workspace_filters(payload.get("filters"))
    selected_ids = normalize_inscripcio_ids(payload.get("selected_ids") or payload.get("ids") or [])
    fallback_mode = _parse_fallback_mode(payload.get("fallback_mode"))

    allowed_group_fields = get_allowed_group_fields(competicio)
    allowed_group_codes = {field["code"] for field in allowed_group_fields}
    selected_group_codes = _normalize_sort_group_by(
        payload.get("group_by"),
        allowed_group_codes,
        fallback_group_by=competicio.group_by_default or [],
    )

    sort_fields = get_available_sort_fields(competicio)
    sort_codes = {field["code"] for field in sort_fields}
    context_key = build_inscripcions_sort_context_key(
        competicio.id,
        filters=filters,
        group_by=selected_group_codes,
    )
    sort_state = get_inscripcions_sort_context_state(request, context_key)
    stack_raw = sort_state.get("stack") if isinstance(sort_state.get("stack"), list) else []
    stack = []
    for item in stack_raw:
        normalized = _normalize_sort_criterion(
            item,
            sort_codes=sort_codes,
            allowed_group_codes=allowed_group_codes,
            fallback_group_by=selected_group_codes,
        )
        if normalized is not None:
            stack.append(normalized)
    partition_codes = _extract_sort_partition_codes(stack)

    if not selected_ids:
        return {
            "selection_count": 0,
            "buckets": [],
            "buckets_total": 0,
            "layers_used": [],
            "used_fallback": False,
            "fallback_reason": "",
            "default_bucket_keys": [],
        }

    resolution_codes = list(dict.fromkeys(list(selected_group_codes) + list(partition_codes)))
    resolution_builtin_fields = [
        code for code in resolution_codes if hasattr(Inscripcio, code)
    ]
    records_qs = Inscripcio.objects.filter(competicio=competicio, id__in=selected_ids)
    if resolution_codes:
        records_qs = annotate_inscripcions_queryset_for_group_codes(
            records_qs,
            competicio,
            resolution_codes,
        )
    records = list(
        records_qs.order_by("ordre_sortida", "id").only(
            "id",
            "extra",
            "data_naixement",
            *resolution_builtin_fields,
        )
    )
    if not records:
        return {
            "selection_count": 0,
            "buckets": [],
            "buckets_total": 0,
            "layers_used": [],
            "used_fallback": False,
            "fallback_reason": "",
            "default_bucket_keys": [],
        }

    resolution = _resolve_group_creation_buckets(
        competicio,
        records,
        group_codes=selected_group_codes,
        partition_codes=partition_codes,
        fallback_mode=fallback_mode,
    )
    buckets_raw = (resolution.get("buckets") if resolution.get("ok") else []) or []
    buckets = [
        {
            "key": bucket.get("key"),
            "label": bucket.get("label"),
            "count": int(bucket.get("count") or 0),
            "sources": bucket.get("sources") or [],
            "kinds": [
                str(source.get("kind") or "").strip().lower()
                for source in (bucket.get("sources") or [])
                if str(source.get("kind") or "").strip()
            ],
        }
        for bucket in buckets_raw
        if str(bucket.get("key") or "").strip()
    ]
    return {
        "selection_count": len(records),
        "buckets": buckets,
        "buckets_total": len(buckets),
        "layers_used": list(resolution.get("layers_used") or []),
        "used_fallback": bool(resolution.get("used_fallback")),
        "fallback_reason": str(resolution.get("fallback_reason") or ""),
        "default_bucket_keys": [bucket["key"] for bucket in buckets],
    }


def _get_programmed_groups_warned_by_ids(competicio, inscripcio_ids, exclude_group_id=None):
    clean_ids = normalize_inscripcio_ids(inscripcio_ids)
    if not clean_ids:
        return []

    programmed_group_ids = set(get_programmed_group_ids(competicio) or [])
    if not programmed_group_ids:
        return []

    blocked_groups = get_programmed_groups_emptied_by_ids(
        competicio,
        clean_ids,
        exclude_group_id=exclude_group_id,
    )
    blocked_ids = {int(group.id) for group in blocked_groups}
    touched_group_ids = {
        int(group_id)
        for group_id in (
            Inscripcio.objects
            .filter(competicio=competicio, id__in=clean_ids)
            .values_list("grup_competicio_id", flat=True)
        )
        if group_id and int(group_id) in programmed_group_ids and int(group_id) not in blocked_ids
    }
    if exclude_group_id:
        touched_group_ids.discard(int(exclude_group_id))
    if not touched_group_ids:
        return []

    groups_by_id = get_group_maps(competicio, include_inactive=True)["by_id"]
    return [
        groups_by_id[group_id]
        for group_id in sorted(touched_group_ids)
        if group_id in groups_by_id
    ]


def _group_workspace_action_preview(competicio, payload):
    action = str(payload.get("action") or "create").strip().lower()
    target_bundle = _resolve_group_workspace_target_ids(competicio, payload)
    filters = target_bundle["filters"]
    selected_ids = target_bundle["selected_ids"]
    target_ids = target_bundle["target_ids"]
    records = list(
        Inscripcio.objects
        .filter(competicio=competicio, id__in=target_ids)
        .select_related("grup_competicio")
        .order_by("ordre_sortida", "id")
        .only("id", "nom_i_cognoms", "entitat", "grup", "grup_competicio_id", "ordre_sortida", "ordre_competicio")
    )
    selection_summary = _build_group_workspace_selection_summary(competicio, selected_ids or target_ids)
    summary = get_group_summary_counts(competicio, include_inactive=False)
    blocked_groups = []
    moving_records = list(records)
    if action in {"create", "assign", "unassign"}:
        if action == "assign":
            group = _resolve_group_workspace_group(competicio, payload, include_inactive=True)
            moving_records = [
                ins for ins in records
                if getattr(ins, "grup_competicio_id", None) != getattr(group, "id", None)
            ] if group is not None else list(records)
            blocked_groups = get_programmed_groups_emptied_by_ids(
                competicio,
                [ins.id for ins in moving_records],
                exclude_group_id=getattr(group, "id", None),
            )
        else:
            blocked_groups = get_programmed_groups_emptied_by_ids(competicio, target_ids)
    warning_groups = []
    if action in {"create", "assign", "unassign"}:
        warning_groups = _get_programmed_groups_warned_by_ids(
            competicio,
            [ins.id for ins in moving_records] if action == "assign" else target_ids,
            exclude_group_id=getattr(_resolve_group_workspace_group(competicio, payload, include_inactive=True), "id", None) if action == "assign" else None,
        )

    existing_groups_preview = []
    if records:
        from .views import _build_existing_groups_preview

        existing_groups_preview = _build_existing_groups_preview(
            competicio,
            records,
            moving_ids=[ins.id for ins in moving_records] if action == "assign" else target_ids,
        )

    preview = {
        "action": action,
        "selection": selection_summary,
        "summary": summary,
        "rotacions_active": bool(competicio_has_rotacions(competicio)),
        "blocked": bool(blocked_groups),
        "blocked_groups": [get_group_card_payload(group, member_limit=5) for group in blocked_groups],
        "warning_groups": [get_group_card_payload(group, member_limit=5) for group in warning_groups],
        "existing_groups": existing_groups_preview,
        "planned_groups": [],
        "target_ids_count": len(moving_records if action == "assign" else target_ids),
        "target_member_names_preview": [
            str(getattr(ins, "nom_i_cognoms", "") or "").strip()
            for ins in (moving_records if action == "assign" else records)[:5]
            if str(getattr(ins, "nom_i_cognoms", "") or "").strip()
        ],
    }

    if action == "create":
        next_group_num = next_group_display_num(competicio)
        preview["planned_groups"] = [
            {
                "preview_kind": "created",
                "impact_kind": "created",
                "group_num": next_group_num,
                "label": f"Grup {next_group_num}",
                "members_count": len(target_ids),
                "member_names_preview": preview["target_member_names_preview"],
                "member_names_remaining": max(0, len(target_ids) - len(preview["target_member_names_preview"])),
            }
        ]
    elif action == "assign":
        group = _resolve_group_workspace_group(competicio, payload, include_inactive=True)
        if group is not None:
            group_count = int(
                Inscripcio.objects.filter(grup_competicio=group).count()
            )
            preview["planned_groups"] = [
                {
                    "preview_kind": "existing",
                    "impact_kind": "updated",
                    "group_num": group.display_num,
                    "group_id": group.id,
                    "label": group_label(group),
                    "members_count": group_count + len(moving_records),
                    "member_names_preview": get_group_member_preview(group, limit=5),
                    "member_names_remaining": max(0, group_count + len(moving_records) - 5),
                }
            ]
            preview["target_group"] = get_group_detail_payload(group, member_limit=5)
    elif action == "unassign":
        preview["planned_groups"] = []
    elif action == "delete":
        group = _resolve_group_workspace_group(competicio, payload, include_inactive=True)
        preview["target_group"] = get_group_detail_payload(group, member_limit=5) if group is not None else None
        preview["can_delete"] = bool(preview["target_group"] and preview["target_group"].get("can_delete"))

    return preview


@require_POST
@csrf_protect
def groups_workspace(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}
    operation = str(payload.get("operation") or "").strip().lower()
    if operation == "resolve_filtered_ids":
        resolved = _resolve_group_workspace_filtered_target_ids(
            competicio,
            payload.get("filters"),
        )
        return JsonResponse(
            with_inscripcions_history_payload(
                {
                    "ok": True,
                    "operation": "resolve_filtered_ids",
                    "filters": resolved["filters"],
                    "target_ids": resolved["target_ids"],
                    "total": len(resolved["target_ids"]),
                },
                request,
                competicio.id,
            )
        )
    if operation == "resolve_auto_context":
        auto_context = _build_group_workspace_auto_context(
            competicio,
            request,
            payload,
        )
        return JsonResponse(
            with_inscripcions_history_payload(
                {
                    "ok": True,
                    "operation": "resolve_auto_context",
                    **auto_context,
                },
                request,
                competicio.id,
            )
        )
    workspace = _build_group_workspace_payload(competicio, payload)
    return JsonResponse(
        with_inscripcions_history_payload(
            {"ok": True, "workspace": workspace, **workspace},
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def groups_detail(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}
    group = _resolve_group_workspace_group(competicio, payload, include_inactive=True)
    if group is None:
        return HttpResponseBadRequest("group invalid")
    detail = get_group_detail_payload(group, member_limit=50)
    return JsonResponse(
        with_inscripcions_history_payload(
            {"ok": True, "group": detail, "members": detail.get("members") or []},
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def groups_preview(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}
    preview = _group_workspace_action_preview(competicio, payload)
    return JsonResponse(
        with_inscripcions_history_payload(
            {"ok": True, "preview": preview},
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def groups_create(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}

    resolved = _resolve_group_workspace_target_ids(competicio, payload)
    target_ids = resolved["target_ids"]
    name = str(payload.get("name") or "").strip()

    blocked_groups = get_programmed_groups_emptied_by_ids(competicio, target_ids)
    if blocked_groups:
        return HttpResponseBadRequest(_message_for_emptied_programmed_groups(blocked_groups))
    warning_groups = _get_programmed_groups_warned_by_ids(competicio, target_ids)

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    group = ensure_group_for_display_num(competicio, next_group_display_num(competicio), name=name)
    result = {"updated": 0, "moved_ids": [], "skipped_ids": [], "compacted_group_ids": []}
    if target_ids:
        result = move_inscripcions_to_group(group, target_ids)
    if name and group.nom != name:
        group.nom = name
        group.save(update_fields=["nom"])
    sync_competicio_group_names_view(competicio)
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="groups_create_manual",
        action_label="Crear grup manual",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    return JsonResponse(
        with_inscripcions_history_payload(
            {
                "ok": True,
                "created": True,
                "updated": int(result.get("updated") or 0),
                "moved_ids": list(result.get("moved_ids") or []),
                "skipped_ids": list(result.get("skipped_ids") or []),
                "group": get_group_detail_payload(group, member_limit=5),
                "selection": _build_group_workspace_selection_summary(competicio, target_ids),
                "warnings": [group_label(row) for row in warning_groups],
                "notice": (
                    f"S'ha modificat un grup programat: {', '.join(group_label(row) for row in warning_groups)}."
                    if warning_groups else ""
                ),
            },
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def groups_assign(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}

    group = _resolve_group_workspace_group(competicio, payload, include_inactive=True)
    if group is None:
        return HttpResponseBadRequest("group invalid")

    resolved = _resolve_group_workspace_target_ids(competicio, payload)
    target_ids = resolved["target_ids"]
    blocked_groups = get_programmed_groups_emptied_by_ids(competicio, target_ids, exclude_group_id=group.id)
    if blocked_groups:
        return HttpResponseBadRequest(_message_for_emptied_programmed_groups(blocked_groups))
    warning_groups = _get_programmed_groups_warned_by_ids(competicio, target_ids, exclude_group_id=group.id)

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    result = move_inscripcions_to_group(group, target_ids)
    sync_competicio_group_names_view(competicio)
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="groups_assign_manual",
        action_label="Assignar seleccio a grup",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    return JsonResponse(
        with_inscripcions_history_payload(
            {
                "ok": True,
                "updated": int(result.get("updated") or 0),
                "moved_ids": list(result.get("moved_ids") or []),
                "skipped_ids": list(result.get("skipped_ids") or []),
                "group": get_group_detail_payload(group, member_limit=5),
                "selection": _build_group_workspace_selection_summary(competicio, target_ids),
                "warnings": [group_label(row) for row in warning_groups],
                "notice": (
                    f"S'ha modificat un grup programat: {', '.join(group_label(row) for row in warning_groups)}."
                    if warning_groups else ""
                ),
            },
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def groups_unassign(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}

    resolved = _resolve_group_workspace_target_ids(competicio, payload)
    target_ids = resolved["target_ids"]
    blocked_groups = get_programmed_groups_emptied_by_ids(competicio, target_ids)
    if blocked_groups:
        return HttpResponseBadRequest(_message_for_emptied_programmed_groups(blocked_groups))
    warning_groups = _get_programmed_groups_warned_by_ids(competicio, target_ids)

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    result = clear_inscripcions_group(competicio, target_ids)
    sync_competicio_group_names_view(competicio)
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="groups_unassign_manual",
        action_label="Treure seleccio del grup",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    return JsonResponse(
        with_inscripcions_history_payload(
            {
                "ok": True,
                "updated": int(result.get("updated") or 0),
                "cleared_ids": list(result.get("cleared_ids") or []),
                "selection": _build_group_workspace_selection_summary(competicio, target_ids),
                "warnings": [group_label(row) for row in warning_groups],
                "notice": (
                    f"S'ha modificat un grup programat: {', '.join(group_label(row) for row in warning_groups)}."
                    if warning_groups else ""
                ),
            },
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def groups_delete(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}

    group = _resolve_group_workspace_group(competicio, payload, include_inactive=True)
    if group is None:
        return HttpResponseBadRequest("group invalid")

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    ok, reason = safe_deactivate_empty_group(group)
    if not ok:
        if reason == "group_not_empty":
            return HttpResponseBadRequest("group not empty")
        return HttpResponseBadRequest("group invalid")

    sync_competicio_group_names_view(competicio)
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="groups_delete_manual",
        action_label="Desactivar grup buit",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    return JsonResponse(
        with_inscripcions_history_payload(
            {
                "ok": True,
                "deleted": True,
                "group": get_group_detail_payload(group, member_limit=5),
            },
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def groups_delete_empty(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    groups = list(get_competicio_groups(competicio, include_inactive=False))
    deleted_ids = []
    skipped_ids = []

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    for group in groups:
        payload = get_group_card_payload(group, member_limit=1)
        if int((payload or {}).get("members_count") or 0) > 0:
            continue
        ok, _reason = safe_deactivate_empty_group(group)
        if ok:
            deleted_ids.append(int(group.id))
        else:
            skipped_ids.append(int(group.id))

    sync_competicio_group_names_view(competicio)
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="groups_delete_empty",
        action_label="Desactivar grups buits",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    return JsonResponse(
        with_inscripcions_history_payload(
            {
                "ok": True,
                "deleted": len(deleted_ids),
                "deleted_ids": deleted_ids,
                "skipped_ids": skipped_ids,
            },
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
@transaction.atomic
def groups_delete_all(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    groups = list(get_competicio_groups(competicio, include_inactive=False))
    programmed_group_ids = set(get_programmed_group_ids(competicio) or [])
    protected_groups = []
    deleted_groups = []

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)

    for group in groups:
        if int(group.id) in programmed_group_ids:
            protected_groups.append({
                "id": int(group.id),
                "display_num": int(group.display_num or 0),
                "label": group_label(group),
            })
            continue

        member_ids = list(
            Inscripcio.objects
            .filter(grup_competicio=group)
            .values_list("id", flat=True)
        )
        if member_ids:
            clear_inscripcions_group(competicio, member_ids)
        ok, reason = safe_deactivate_empty_group(group)
        if ok:
            deleted_groups.append({
                "id": int(group.id),
                "display_num": int(group.display_num or 0),
                "label": group_label(group),
            })
        elif reason == "group_not_empty":
            return HttpResponseBadRequest("group not empty after clearing")

    sync_competicio_group_names_view(competicio)
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="groups_delete_all",
        action_label="Desactivar tots els grups no programats",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    return JsonResponse(
        with_inscripcions_history_payload(
            {
                "ok": True,
                "deleted": len(deleted_groups),
                "deleted_groups": deleted_groups,
                "protected": len(protected_groups),
                "protected_groups": protected_groups,
            },
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def inscripcions_group_competition_order_preview(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    try:
        group_num = int(payload.get("group_num"))
    except Exception:
        return HttpResponseBadRequest("group_num invalid")
    if group_num <= 0:
        return HttpResponseBadRequest("group_num invalid")

    group = get_group_for_display_num(competicio, group_num)
    if group is None:
        return HttpResponseBadRequest("group_num invalid")

    rows = []
    group_rows = (
        Inscripcio.objects
        .filter(competicio=competicio, grup_competicio=group)
        .order_by("ordre_competicio", "ordre_sortida", "id")
        .only("id", "nom_i_cognoms", "entitat", "ordre_competicio", "ordre_sortida")
    )
    for idx, inscripcio in enumerate(group_rows, start=1):
        label = str(getattr(inscripcio, "nom_i_cognoms", "") or "").strip() or f"Inscripcio {inscripcio.id}"
        secondary = str(getattr(inscripcio, "entitat", "") or "").strip()
        saved_order = getattr(inscripcio, "ordre_competicio", None)
        rows.append(
            {
                "id": inscripcio.id,
                "label": label,
                "secondary_label": secondary,
                "saved_order": int(saved_order) if saved_order is not None else idx,
            }
        )

    group_label = str(getattr(group, "nom", "") or "").strip() or f"Grup {group.display_num}"
    return JsonResponse(
        {
            "ok": True,
            "group_num": group_num,
            "group_label": group_label,
            "total_count": len(rows),
            "can_edit": bool(
                user_has_competicio_capability(
                    request.user,
                    competicio,
                    "inscripcions.edit",
                )
            ),
            "rows": rows,
        }
    )


@require_POST
@csrf_protect
def inscripcions_set_aparells(request, pk):
    """
    Desa els aparells on competeix una inscripció.
    Semàntica:
    - selected_comp_aparell_ids = aparells actius on SI competeix
    - la resta d'aparells actius queden exclosos (InscripcioAparellExclusio)
    """
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    inscripcio_id = payload.get("inscripcio_id")
    selected_ids_raw = payload.get("selected_comp_aparell_ids") or []

    try:
        inscripcio_id = int(inscripcio_id)
    except Exception:
        return HttpResponseBadRequest("inscripcio_id invalid")

    if not isinstance(selected_ids_raw, list):
        return HttpResponseBadRequest("selected_comp_aparell_ids ha de ser una llista")

    inscripcio = get_object_or_404(Inscripcio, pk=inscripcio_id, competicio=competicio)

    active_ids = list(
        CompeticioAparell.objects
        .filter(competicio=competicio, actiu=True)
        .values_list("id", flat=True)
    )
    active_set = set(active_ids)

    selected_set = set()
    for value in selected_ids_raw:
        try:
            v = int(value)
        except Exception:
            return HttpResponseBadRequest("selected_comp_aparell_ids conte valors invalids")
        if v not in active_set:
            return HttpResponseBadRequest("selected_comp_aparell_ids conte aparells no valids per la competicio")
        selected_set.add(v)

    excluded_ids = [app_id for app_id in active_ids if app_id not in selected_set]
    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)

    with transaction.atomic():
        # Reemplaça només exclusions dels aparells actius de la competició.
        InscripcioAparellExclusio.objects.filter(
            inscripcio=inscripcio,
            comp_aparell_id__in=active_ids,
        ).delete()

        if excluded_ids:
            InscripcioAparellExclusio.objects.bulk_create(
                [
                    InscripcioAparellExclusio(
                        inscripcio_id=inscripcio.id,
                        comp_aparell_id=app_id,
                    )
                    for app_id in excluded_ids
                ]
            )

    selected_ids = [app_id for app_id in active_ids if app_id in selected_set]
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="set_aparells",
        action_label="Desar aparells de la inscripcio",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    return JsonResponse(
        with_inscripcions_history_payload(
            {
                "ok": True,
                "inscripcio_id": inscripcio.id,
                "active_comp_aparell_ids": active_ids,
                "selected_comp_aparell_ids": selected_ids,
                "excluded_comp_aparell_ids": excluded_ids,
            },
            request,
            competicio.id,
        )
    )


def _create_inscripcio_media_record(
    *,
    competicio,
    inscripcio,
    uploaded,
    source: str,
    match_score=None,
    force_primary: bool = False,
):
    meta = _validate_uploaded_media_file(uploaded)
    match_decimal = None
    if match_score not in (None, ""):
        try:
            match_decimal = Decimal(str(match_score))
        except Exception:
            match_decimal = None

    tipus = meta["tipus"]
    with transaction.atomic():
        existing_qs = InscripcioMedia.objects.filter(
            competicio=competicio,
            inscripcio=inscripcio,
            tipus=tipus,
        )
        will_be_primary = bool(force_primary) or (not existing_qs.filter(is_primary=True).exists())
        if will_be_primary:
            existing_qs.update(is_primary=False)

        item = InscripcioMedia.objects.create(
            competicio=competicio,
            inscripcio=inscripcio,
            fitxer=uploaded,
            tipus=tipus,
            mime_type=meta["mime_type"],
            original_filename=meta["filename"],
            file_size_bytes=meta["size"],
            is_primary=will_be_primary,
            source=source,
            match_score=match_decimal,
        )
    return item


@require_POST
@csrf_protect
def inscripcions_media_upload(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    raw_ins_id = request.POST.get("inscripcio_id")
    try:
        inscripcio_id = int(raw_ins_id)
    except Exception:
        return HttpResponseBadRequest("inscripcio_id invalid")

    inscripcio = get_object_or_404(Inscripcio, pk=inscripcio_id, competicio=competicio)
    uploaded = request.FILES.get("media_file") or request.FILES.get("file")
    set_primary = str(request.POST.get("set_primary") or "").strip().lower() in {"1", "true", "yes", "on"}

    try:
        item = _create_inscripcio_media_record(
            competicio=competicio,
            inscripcio=inscripcio,
            uploaded=uploaded,
            source=InscripcioMedia.Source.MANUAL,
            force_primary=set_primary,
        )
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    payload = {
        "ok": True,
        "item": _serialize_media_item(item),
        "inscripcio_id": inscripcio.id,
    }
    return JsonResponse(with_inscripcions_history_payload(payload, request, competicio.id))


@require_POST
@csrf_protect
def inscripcions_media_delete(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    try:
        media_id = int(payload.get("media_id"))
    except Exception:
        return HttpResponseBadRequest("media_id invalid")

    item = get_object_or_404(InscripcioMedia, pk=media_id, competicio=competicio)
    was_primary = bool(item.is_primary)
    inscripcio_id = item.inscripcio_id
    tipus = item.tipus
    if item.fitxer:
        item.fitxer.delete(save=False)
    item.delete()

    if was_primary:
        next_item = (
            InscripcioMedia.objects
            .filter(competicio=competicio, inscripcio_id=inscripcio_id, tipus=tipus)
            .order_by("-created_at", "id")
            .first()
        )
        if next_item:
            next_item.is_primary = True
            next_item.save(update_fields=["is_primary"])

    response = {
        "ok": True,
        "deleted_media_id": media_id,
        "inscripcio_id": inscripcio_id,
    }
    return JsonResponse(with_inscripcions_history_payload(response, request, competicio.id))


@require_POST
@csrf_protect
def inscripcions_media_set_primary(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    try:
        media_id = int(payload.get("media_id"))
    except Exception:
        return HttpResponseBadRequest("media_id invalid")

    item = get_object_or_404(InscripcioMedia, pk=media_id, competicio=competicio)
    with transaction.atomic():
        InscripcioMedia.objects.filter(
            competicio=competicio,
            inscripcio_id=item.inscripcio_id,
            tipus=item.tipus,
        ).update(is_primary=False)
        item.is_primary = True
        item.save(update_fields=["is_primary"])

    response = {
        "ok": True,
        "item": _serialize_media_item(item),
    }
    return JsonResponse(with_inscripcions_history_payload(response, request, competicio.id))


@require_POST
@csrf_protect
def inscripcions_media_match_preview(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    files = payload.get("files") or []
    if not isinstance(files, list):
        return HttpResponseBadRequest("files ha de ser una llista")
    if len(files) > 3000:
        return HttpResponseBadRequest("Massa fitxers al preview")

    inscripcions = (
        Inscripcio.objects
        .filter(competicio=competicio)
        .only("id", "nom_i_cognoms", "entitat", "subcategoria", "sexe")
    )
    candidates = build_inscripcio_media_match_candidates(inscripcions)
    cfg = _get_media_matching_config(competicio)
    rows = match_media_files_to_inscripcions(files, candidates, config=cfg, top_k=3)

    auto_count = len([r for r in rows if r.get("status") == "auto"])
    review_count = len([r for r in rows if r.get("status") == "review"])
    unmatched_count = len([r for r in rows if r.get("status") == "unmatched"])
    return JsonResponse(
        {
            "ok": True,
            "rows": rows,
            "counts": {
                "total": len(rows),
                "auto": auto_count,
                "review": review_count,
                "unmatched": unmatched_count,
            },
            "config": cfg,
        }
    )


@require_POST
@csrf_protect
def inscripcions_media_match_apply(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    raw = request.POST.get("mapping_json") or "[]"
    try:
        mapping = json.loads(raw)
    except Exception:
        return HttpResponseBadRequest("mapping_json invalid")
    if not isinstance(mapping, list):
        return HttpResponseBadRequest("mapping_json ha de ser una llista")

    key_to_row = {}
    target_ids = set()
    for row in mapping:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip()
        if not key:
            continue
        try:
            ins_id = int(row.get("inscripcio_id"))
        except Exception:
            continue
        score = row.get("score")
        key_to_row[key] = {"inscripcio_id": ins_id, "score": score}
        target_ids.add(ins_id)

    if not key_to_row:
        return HttpResponseBadRequest("No hi ha assignacions valides")

    inscripcions = {
        ins.id: ins
        for ins in Inscripcio.objects.filter(competicio=competicio, id__in=target_ids)
    }

    created = []
    errors = []
    for key, row in key_to_row.items():
        uploaded = request.FILES.get(f"file_{key}")
        if uploaded is None:
            errors.append({"key": key, "error": "Fitxer no trobat al POST"})
            continue

        inscripcio = inscripcions.get(row["inscripcio_id"])
        if inscripcio is None:
            errors.append({"key": key, "error": "Inscripcio no valida"})
            continue

        try:
            item = _create_inscripcio_media_record(
                competicio=competicio,
                inscripcio=inscripcio,
                uploaded=uploaded,
                source=InscripcioMedia.Source.ASSISTED,
                match_score=row.get("score"),
            )
            created.append(_serialize_media_item(item))
        except ValueError as exc:
            errors.append({"key": key, "error": str(exc)})

    return JsonResponse(
        with_inscripcions_history_payload(
            {
                "ok": True,
                "created_count": len(created),
                "error_count": len(errors),
                "created": created[:25],
                "errors": errors[:25],
            },
            request,
            competicio.id,
        )
    )
