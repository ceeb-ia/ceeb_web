# views_classificacions.py
import json
import re
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST
from django.db import transaction
from django.urls import reverse
from .models_scoring import ScoreEntry, ScoringSchema  
from .models import Competicio, Inscripcio, Equip
from .models_trampoli import CompeticioAparell, Aparell
from .models_classificacions import ClassificacioConfig
from .models_judging import PublicLiveToken
from .services.services_classificacions_2 import compute_classificacio, DEFAULT_SCHEMA, get_display_columns
from .views import get_allowed_group_fields, get_inscripcio_value
from .services.scoring_schema_validation import (
    _field_shape,
    _build_alias_map,
    _resolve_name,
    _topo_sort,
    _ast_parse,
    _extract_names,
    DryRunEval,
    TMat,
    Shape,
    RESERVED_NAMES,
    ALLOWED_FUNCTIONS,
)
from django.db import models
# views_classificacions.py
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_aware
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


def _active_cfg_values(competicio):
    cfgs = (
        ClassificacioConfig.objects
        .filter(competicio=competicio, activa=True)
        .order_by("ordre", "id")
    )
    return list(cfgs.values("id", "nom", "tipus", "ordre"))


def _live_data_payload(competicio, since_raw=None):
    last_note = (
        ScoreEntry.objects
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

    if since_raw:
        since_dt = parse_datetime(since_raw)
        if since_dt and not is_aware(since_dt):
            since_dt = timezone.make_aware(since_dt, timezone.get_current_timezone())
        if since_dt and stamp <= since_dt:
            return {"ok": True, "changed": False, "stamp": stamp.isoformat()}

    cfgs = (
        ClassificacioConfig.objects
        .filter(competicio=competicio, activa=True)
        .order_by("ordre", "id")
    )

    payload_cfgs = []
    for cfg in cfgs:
        data = compute_classificacio(competicio, cfg)
        parts = []
        for k in sorted(data.keys()):
            parts.append({"particio": k, "rows": data[k]})
        payload_cfgs.append({
            "id": cfg.id,
            "nom": cfg.nom,
            "tipus": cfg.tipus,
            "columns": get_display_columns(cfg.schema or {}),
            "parts": parts,
        })

    return {
        "ok": True,
        "changed": True,
        "stamp": stamp.isoformat(),
        "competicio": {"id": competicio.id, "nom": competicio.nom},
        "cfgs": payload_cfgs,
    }


def _default_live_columns():
    return [
        {"type": "builtin", "key": "posicio", "label": "Pos.", "align": "left"},
        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
        {"type": "builtin", "key": "punts", "label": "Punts", "align": "right", "decimals": 3},
    ]


def _format_partition_title(raw):
    source = "global" if raw in (None, "") else str(raw)
    tokens = []
    for part in source.split("|"):
        token = str(part or "").strip()
        if not token:
            continue
        idx = token.find(":")
        tokens.append(token[idx + 1:].strip() if idx >= 0 else token)
    return " / ".join([x for x in tokens if x]) or "global"


def _fallback_export_value(row: dict, key: str):
    if key in ("participant", "nom"):
        return row.get("participant") or row.get("nom") or row.get("entitat_nom") or ""
    if key == "punts":
        return row.get("punts")
    if key == "posicio":
        return row.get("posicio")
    if key == "entitat_nom":
        return row.get("entitat_nom") or ""
    if key == "participants":
        return row.get("participants") if row.get("participants") is not None else ""
    return row.get(key)


def _extract_export_value(row: dict, col: dict):
    key = str((col or {}).get("key") or "")
    cells = row.get("cells") or row.get("display") or {}
    if isinstance(cells, dict) and key in cells:
        return cells.get(key)
    return _fallback_export_value(row, key)


def _excel_safe_text(raw) -> str:
    txt = "" if raw is None else str(raw)
    if txt[:1] in ("=", "+", "-", "@"):
        return "'" + txt
    return txt


def _try_float(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        txt = value.strip()
        if not txt:
            return None
        try:
            return float(txt)
        except Exception:
            return None
    return None


def _format_scalar_text(value, decimals=None):
    if value is None:
        return ""
    number = _try_float(value)
    if number is not None and decimals is not None:
        return f"{number:.{decimals}f}"
    if number is not None and isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _normalize_excel_cell(value, col):
    decimals = (col or {}).get("decimals")
    try:
        decimals = int(decimals) if decimals is not None else None
    except Exception:
        decimals = None
    if decimals is not None:
        decimals = max(0, min(6, decimals))

    if isinstance(value, dict) and value.get("_kind") == "judge_rows":
        lines = []
        for row in value.get("rows") or []:
            judge_num = row.get("judge")
            try:
                judge_num = int(judge_num)
            except Exception:
                judge_num = None
            judge_label = f"J{judge_num}" if judge_num and judge_num > 0 else "J?"
            items = row.get("items") or []
            if not isinstance(items, list):
                items = [items]
            vals = [_format_scalar_text(it, decimals) for it in items]
            lines.append(f"{judge_label}: " + " | ".join(vals))
        return _excel_safe_text("\n".join([ln for ln in lines if ln])), None, True

    if isinstance(value, (dict, list)):
        return _excel_safe_text(json.dumps(value, ensure_ascii=False)), None, True

    if isinstance(value, bool):
        return value, None, False

    number = _try_float(value)
    if number is not None and not isinstance(value, str):
        if decimals is None:
            if isinstance(value, int):
                return int(value), "0", False
            return float(value), "0.###", False
        rounded = round(number, decimals)
        num_fmt = "0" if decimals == 0 else ("0." + ("0" * decimals))
        return rounded, num_fmt, False

    if isinstance(value, str):
        txt = value.strip()
        if decimals is not None:
            number = _try_float(txt)
            if number is not None:
                rounded = round(number, decimals)
                num_fmt = "0" if decimals == 0 else ("0." + ("0" * decimals))
                return rounded, num_fmt, False
        return _excel_safe_text(value), None, ("\n" in value)

    if value is None:
        return "", None, False
    return _excel_safe_text(value), None, False


def _build_excel_sheet_name(raw_name, used_names):
    base = str(raw_name or "").strip() or "Classificacio"
    base = re.sub(r'[\[\]\*:/\\?]', " ", base)
    base = " ".join(base.split())
    if not base:
        base = "Classificacio"
    base = base[:31]

    candidate = base
    idx = 2
    while candidate.casefold() in used_names:
        suffix = f" ({idx})"
        max_len = 31 - len(suffix)
        truncated = (base[:max_len].rstrip() if max_len > 0 else "") or "Sheet"
        candidate = f"{truncated}{suffix}"
        idx += 1
    used_names.add(candidate.casefold())
    return candidate


def _write_cfg_excel_sheet(ws, competicio, cfg_nom, columns, parts):
    cols = columns if isinstance(columns, list) and columns else _default_live_columns()
    total_cols = max(1, len(cols))

    fill_title = PatternFill("solid", fgColor="1F4E79")
    fill_subtitle = PatternFill("solid", fgColor="D9E1F2")
    fill_partition = PatternFill("solid", fgColor="DDE7FF")
    fill_header = PatternFill("solid", fgColor="E9EEF7")
    fill_zebra = PatternFill("solid", fgColor="F7F9FC")
    fill_first = PatternFill("solid", fgColor="F6E27A")
    fill_second = PatternFill("solid", fgColor="E3E8EF")
    fill_third = PatternFill("solid", fgColor="E8C7A3")

    thin = Side(style="thin", color="9AA7B2")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    title_font = Font(bold=True, size=14, color="FFFFFF")
    subtitle_font = Font(bold=True, size=11)
    header_font = Font(bold=True)

    col_widths = [10 for _ in range(total_cols)]

    def update_col_width(col_idx, value):
        txt = "" if value is None else str(value)
        longest = max([len(line) for line in txt.splitlines()] or [0])
        col_widths[col_idx - 1] = min(48, max(col_widths[col_idx - 1], longest + 2))

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total_cols)
    c_title = ws.cell(row=1, column=1, value=f"{competicio.nom} - {cfg_nom}")
    c_title.fill = fill_title
    c_title.font = title_font
    c_title.alignment = align_center

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=total_cols)
    c_sub = ws.cell(
        row=2,
        column=1,
        value=f"Exportat el {timezone.localtime().strftime('%Y-%m-%d %H:%M:%S')}",
    )
    c_sub.fill = fill_subtitle
    c_sub.font = subtitle_font
    c_sub.alignment = align_center

    ws.row_dimensions[1].height = 26
    ws.row_dimensions[2].height = 20

    row_idx = 4
    first_data_row = None
    parts_list = parts if isinstance(parts, list) else []
    if not parts_list:
        ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=total_cols)
        empty = ws.cell(row=row_idx, column=1, value="Sense resultats.")
        empty.alignment = align_left
        empty.font = Font(italic=True)
        return

    for p in parts_list:
        part_rows = (p or {}).get("rows") or []
        part_name = _format_partition_title((p or {}).get("particio"))

        ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=total_cols)
        pc = ws.cell(row=row_idx, column=1, value=f"Particio: {part_name} ({len(part_rows)} files)")
        pc.fill = fill_partition
        pc.font = Font(bold=True)
        pc.alignment = align_left
        pc.border = border
        row_idx += 1

        header_row = row_idx
        if first_data_row is None:
            first_data_row = header_row + 1
        for col_pos, col in enumerate(cols, start=1):
            label = str(col.get("label") or col.get("key") or "")
            hc = ws.cell(row=header_row, column=col_pos, value=label)
            hc.fill = fill_header
            hc.font = header_font
            hc.alignment = align_center
            hc.border = border
            update_col_width(col_pos, label)
        row_idx += 1

        if not part_rows:
            ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=total_cols)
            rc = ws.cell(row=row_idx, column=1, value="Sense resultats en aquesta particio.")
            rc.alignment = align_left
            rc.font = Font(italic=True)
            row_idx += 2
            continue

        for data_pos, row in enumerate(part_rows):
            try:
                posicio = int((row or {}).get("posicio"))
            except Exception:
                posicio = None

            if posicio == 1:
                podium_fill = fill_first
            elif posicio == 2:
                podium_fill = fill_second
            elif posicio == 3:
                podium_fill = fill_third
            else:
                podium_fill = None

            max_lines = 1
            for col_pos, col in enumerate(cols, start=1):
                raw_value = _extract_export_value(row or {}, col or {})
                value, number_format, wrap_text = _normalize_excel_cell(raw_value, col or {})
                cell = ws.cell(row=row_idx, column=col_pos, value=value)
                cell.border = border
                if number_format:
                    cell.number_format = number_format

                align = str((col or {}).get("align") or "").strip().lower()
                horizontal = "right" if align == "right" else ("center" if align == "center" else "left")
                vertical = "top" if wrap_text else "center"
                cell.alignment = Alignment(horizontal=horizontal, vertical=vertical, wrap_text=wrap_text)

                if podium_fill is not None:
                    cell.fill = podium_fill
                elif data_pos % 2 == 1:
                    cell.fill = fill_zebra

                value_txt = "" if value is None else str(value)
                max_lines = max(max_lines, len(value_txt.splitlines()) if value_txt else 1)
                update_col_width(col_pos, value)

            if max_lines > 1:
                ws.row_dimensions[row_idx].height = min(120, max(18, max_lines * 14))
            row_idx += 1

        row_idx += 1

    if first_data_row:
        ws.freeze_panes = ws[f"A{first_data_row}"]

    for idx, width in enumerate(col_widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = max(10, width)


def _sanitize_filename_component(raw):
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(raw or "").strip()).strip("._")
    return cleaned or "classificacions"


def classificacions_live_export_excel(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    cfg_qs = (
        ClassificacioConfig.objects
        .filter(competicio=competicio, activa=True)
        .order_by("ordre", "id")
    )

    cfg_id_raw = (request.GET.get("cfg_id") or "").strip()
    selected_cfg_id = None
    if cfg_id_raw:
        try:
            selected_cfg_id = int(cfg_id_raw)
        except Exception:
            return HttpResponseBadRequest("cfg_id invalid")
        cfg_qs = cfg_qs.filter(id=selected_cfg_id)

    cfgs = list(cfg_qs)
    if not cfgs:
        return HttpResponseBadRequest("No hi ha classificacions actives per exportar.")

    wb = Workbook()
    used_sheet_names = set()

    for idx, cfg in enumerate(cfgs):
        ws = wb.active if idx == 0 else wb.create_sheet()
        ws.title = _build_excel_sheet_name(cfg.nom or f"Classificacio {idx + 1}", used_sheet_names)

        data = compute_classificacio(competicio, cfg)
        parts = [{"particio": k, "rows": data[k]} for k in sorted(data.keys())]
        columns = get_display_columns(cfg.schema or {}) or _default_live_columns()
        _write_cfg_excel_sheet(ws, competicio, cfg.nom or f"Classificacio {idx + 1}", columns, parts)

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    suffix = f"_cfg_{selected_cfg_id}" if selected_cfg_id else ""
    filename = f"classificacions_{_sanitize_filename_component(competicio.nom)}{suffix}.xlsx"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response


class ClassificacionsLive(TemplateView):
    template_name = "competicio/classificacions_live.html"

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        competicio = self.competicio
        public_raw = (self.request.GET.get("public") or "").strip().lower()
        is_public = public_raw in {"1", "true", "yes", "on"}

        cfgs = (
            ClassificacioConfig.objects
            .filter(competicio=competicio, activa=True)
            .order_by("ordre", "id")
        )
        ctx.update({
            "competicio": competicio,
            "cfgs": list(cfgs.values("id", "nom", "tipus", "ordre")),
            "is_public": is_public,
            "hide_base_chrome": is_public,
            # interval suggerit (ms) perquè el JS el pugui usar
            "poll_ms": 4000,
        })
        return ctx


class ClassificacionsLoopLive(TemplateView):
    template_name = "competicio/classificacions_loop_live.html"

    @staticmethod
    def _parse_int_param(raw, default: int, min_value: int, max_value: int) -> int:
        try:
            value = int(raw)
        except Exception:
            value = default
        return max(min_value, min(max_value, value))

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        competicio = self.competicio

        public_raw = (self.request.GET.get("public") or "").strip().lower()
        is_public = public_raw in {"1", "true", "yes", "on"}

        cfgs = (
            ClassificacioConfig.objects
            .filter(competicio=competicio, activa=True)
            .order_by("ordre", "id")
        )

        poll_ms = self._parse_int_param(self.request.GET.get("poll_ms"), 4000, 1000, 60000)
        slide_ms = self._parse_int_param(self.request.GET.get("slide_ms"), 8000, 2000, 120000)
        rows_per_page = self._parse_int_param(self.request.GET.get("rows"), 12, 3, 60)

        transition = (self.request.GET.get("transition") or "fade").strip().lower()
        if transition not in {"fade", "none"}:
            transition = "fade"

        ctx.update({
            "competicio": competicio,
            "cfgs": list(cfgs.values("id", "nom", "tipus", "ordre")),
            "is_public": is_public,
            "hide_base_chrome": is_public,
            "poll_ms": poll_ms,
            "slide_ms": slide_ms,
            "rows_per_page": rows_per_page,
            "transition": transition,
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
        ScoreEntry.objects
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
            "columns": get_display_columns(cfg.schema or {}),
            "parts": parts,
        })

    return JsonResponse({
        "ok": True,
        "changed": True,
        "stamp": stamp.isoformat(),
        "competicio": {"id": competicio.id, "nom": competicio.nom},
        "cfgs": payload_cfgs,
    })


class PublicClassificacionsLive(TemplateView):
    template_name = "competicio/classificacions_live.html"

    def dispatch(self, request, *args, **kwargs):
        self.token_obj = get_object_or_404(PublicLiveToken, pk=kwargs["token"])
        if not self.token_obj.is_valid():
            return JsonResponse({"ok": False, "error": "Token invalid o revocat"}, status=403)
        self.token_obj.touch()
        self.competicio = self.token_obj.competicio
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        cfgs = (
            ClassificacioConfig.objects
            .filter(competicio=self.competicio, activa=True)
            .order_by("ordre", "id")
        )
        ctx.update({
            "competicio": self.competicio,
            "cfgs": list(cfgs.values("id", "nom", "tipus", "ordre")),
            "is_public": True,
            "hide_base_chrome": True,
            "poll_ms": 4000,
            "public_token_can_view_media": bool(self.token_obj.can_view_media),
            "data_url": self.request.build_absolute_uri(
                reverse("public_live_classificacions_data", kwargs={"token": self.token_obj.id})
            ),
        })
        return ctx


class PublicClassificacionsLoopLive(TemplateView):
    template_name = "competicio/classificacions_loop_live.html"

    @staticmethod
    def _parse_int_param(raw, default: int, min_value: int, max_value: int) -> int:
        try:
            value = int(raw)
        except Exception:
            value = default
        return max(min_value, min(max_value, value))

    def dispatch(self, request, *args, **kwargs):
        self.token_obj = get_object_or_404(PublicLiveToken, pk=kwargs["token"])
        if not self.token_obj.is_valid():
            return JsonResponse({"ok": False, "error": "Token invalid o revocat"}, status=403)
        self.token_obj.touch()
        self.competicio = self.token_obj.competicio
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        cfgs = (
            ClassificacioConfig.objects
            .filter(competicio=self.competicio, activa=True)
            .order_by("ordre", "id")
        )
        poll_ms = self._parse_int_param(self.request.GET.get("poll_ms"), 4000, 1000, 60000)
        slide_ms = self._parse_int_param(self.request.GET.get("slide_ms"), 8000, 2000, 120000)
        rows_per_page = self._parse_int_param(self.request.GET.get("rows"), 12, 3, 60)
        transition = (self.request.GET.get("transition") or "fade").strip().lower()
        if transition not in {"fade", "none"}:
            transition = "fade"

        ctx.update({
            "competicio": self.competicio,
            "cfgs": list(cfgs.values("id", "nom", "tipus", "ordre")),
            "is_public": True,
            "hide_base_chrome": True,
            "poll_ms": poll_ms,
            "slide_ms": slide_ms,
            "rows_per_page": rows_per_page,
            "transition": transition,
            "public_token_can_view_media": bool(self.token_obj.can_view_media),
            "data_url": self.request.build_absolute_uri(
                reverse("public_live_classificacions_data", kwargs={"token": self.token_obj.id})
            ),
        })
        return ctx


def public_classificacions_live_data(request, token):
    token_obj = get_object_or_404(PublicLiveToken, pk=token)
    if not token_obj.is_valid():
        return JsonResponse({"ok": False, "error": "Token invalid o revocat"}, status=403)

    competicio = token_obj.competicio
    last_note = (
        ScoreEntry.objects
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

    since_raw = request.GET.get("since")
    if since_raw:
        since_dt = parse_datetime(since_raw)
        if since_dt and not is_aware(since_dt):
            since_dt = timezone.make_aware(since_dt, timezone.get_current_timezone())
        if since_dt and stamp <= since_dt:
            return JsonResponse(
                {
                    "ok": True,
                    "changed": False,
                    "stamp": stamp.isoformat(),
                    "permissions": {"can_view_media": bool(token_obj.can_view_media)},
                }
            )

    cfgs = (
        ClassificacioConfig.objects
        .filter(competicio=competicio, activa=True)
        .order_by("ordre", "id")
    )

    payload_cfgs = []
    for cfg in cfgs:
        data = compute_classificacio(competicio, cfg)
        parts = []
        for k in sorted(data.keys()):
            parts.append({"particio": k, "rows": data[k]})
        payload_cfgs.append({
            "id": cfg.id,
            "nom": cfg.nom,
            "tipus": cfg.tipus,
            "columns": get_display_columns(cfg.schema or {}),
            "parts": parts,
        })

    return JsonResponse({
        "ok": True,
        "changed": True,
        "stamp": stamp.isoformat(),
        "competicio": {"id": competicio.id, "nom": competicio.nom},
        "permissions": {"can_view_media": bool(token_obj.can_view_media)},
        "cfgs": payload_cfgs,
    })


class ClassificacionsHome(TemplateView):
    template_name = "competicio/classificacions_builder_v2.html"

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
            )
            aparells_cfg = CompeticioAparell.objects.filter(
                competicio=competicio,
                actiu=True,
            ).select_related("aparell").order_by("ordre", "id")

        aparell_ids = list(aparells_cfg.values_list("aparell_id", flat=True))

        schemas_by_aparell = {
            s.aparell_id: (s.schema or {})
            for s in ScoringSchema.objects.filter(aparell_id__in=aparell_ids).only("aparell_id", "schema")
        }

        aparell_field_options = {}


        for ca in aparells_cfg:
            sch = schemas_by_aparell.get(ca.aparell_id, {}) or {}
            opts = []
            score_meta = _build_scoreable_meta_for_schema(sch)


            for f in (sch.get("fields") or []):
                if isinstance(f, dict) and f.get("code"):
                    code = str(f["code"])
                    info = score_meta.get(code) or {}
                    if not info.get("scoreable", False):
                        continue
                    judges_count = 1
                    j = f.get("judges")
                    if isinstance(j, dict):
                        try:
                            judges_count = int(j.get("count") or 1)
                        except Exception:
                            judges_count = 1
                    else:
                        try:
                            judges_count = int(f.get("judges_count") or 1)
                        except Exception:
                            judges_count = 1
                    judges_count = max(1, judges_count)
                    opts.append({
                        "code": code,
                        "label": str(f.get("label") or code),
                        "kind": "field",
                        "judges_count": judges_count,
                    })

            for c in (sch.get("computed") or []):
                if isinstance(c, dict) and c.get("code"):
                    code = str(c["code"])
                    info = score_meta.get(code) or {}
                    if not info.get("scoreable", False):
                        continue
                    opts.append({
                        "code": code,
                        "label": str(c.get("label") or code),
                        "kind": "computed",
                        "judges_count": 1,
                    })

            # dedup
            seen = set()
            dedup = []
            for o in opts:
                if o["code"] in seen:
                    continue
                seen.add(o["code"])
                dedup.append(o)

            aparell_field_options[str(ca.id)] = dedup

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
        particio_value_choices = _collect_particio_value_choices(
            ins_list,
            [f["code"] for f in particio_fields],
        )

        ctx["particio_fields"] = particio_fields
        ctx["particio_value_choices"] = particio_value_choices


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
                "nombre_exercicis": int(getattr(ca, "nombre_exercicis", 1) or 1),
            })

        equips_qs = (
            Equip.objects
            .filter(competicio=competicio)
            .annotate(membres_count=models.Count("membres"))
            .order_by("nom", "id")
        )
        equips_payload = []
        for e in equips_qs:
            equips_payload.append({
                "id": e.id,
                "nom": e.nom,
                "origen": e.origen,
                "membres_count": int(getattr(e, "membres_count", 0) or 0),
            })

        ctx.update({
            "competicio": competicio,
            "cfgs": cfg_payload,
            "aparells": aparell_payload,
            "equips": equips_payload,
        })

        ctx.update({
            "aparell_field_options": aparell_field_options,
        })

        return ctx


def _safe_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return default


def _normalize_particio_codes(raw):
    out = []
    seen = set()
    if not isinstance(raw, list):
        return out
    for item in raw:
        code = str(item or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def _split_particio_custom_values(raw):
    if isinstance(raw, list):
        values = [str(x or "").strip() for x in raw]
    elif isinstance(raw, str):
        values = [x.strip() for x in raw.split(",")]
    else:
        values = []

    out = []
    seen = set()
    for txt in values:
        if not txt:
            continue
        key = " ".join(txt.split()).casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(txt)
    return out


def _normalize_particions_custom(raw):
    out = {}
    if not isinstance(raw, dict):
        return out

    for field_code, cfg in raw.items():
        code = str(field_code or "").strip()
        if not code or not isinstance(cfg, dict):
            continue

        mode = str(cfg.get("mode") or "raw").strip().lower()
        if mode not in {"raw", "custom"}:
            mode = "raw"

        fallback_label = str(cfg.get("fallback_label") or "").strip()
        groups = []
        for idx, group in enumerate(cfg.get("grups") or []):
            if not isinstance(group, dict):
                continue
            label = (
                str(group.get("label") or group.get("key") or f"Grup {idx + 1}").strip()
                or f"Grup {idx + 1}"
            )
            values = _split_particio_custom_values(group.get("values"))
            if not values and not label:
                continue
            groups.append(
                {
                    "key": str(group.get("key") or f"grp_{idx + 1}").strip() or f"grp_{idx + 1}",
                    "label": label,
                    "values": values,
                }
            )

        out[code] = {
            "mode": mode,
            "fallback_label": fallback_label,
            "grups": groups,
        }
    return out


def _normalize_particions_schema(schema):
    if not isinstance(schema, dict):
        return {}
    out = dict(schema)
    out["particions"] = _normalize_particio_codes(schema.get("particions") or [])
    out["particions_custom"] = _normalize_particions_custom(schema.get("particions_custom") or {})
    return out


def _validate_particions_schema(competicio, schema: dict):
    schema = schema or {}
    errors = []

    allowed_fields = get_allowed_group_fields(competicio)
    allowed_codes = {str(f.get("code") or "").strip() for f in allowed_fields if str(f.get("code") or "").strip()}

    parts = _normalize_particio_codes(schema.get("particions") or [])
    for code in parts:
        if code not in allowed_codes:
            errors.append(f"particions: camp no permès per aquesta competicio: '{code}'")

    custom_map = _normalize_particions_custom(schema.get("particions_custom") or {})
    for code, cfg in custom_map.items():
        if code not in allowed_codes:
            errors.append(f"particions_custom['{code}']: camp no permès per aquesta competicio.")
            continue
        if code not in parts:
            errors.append(f"particions_custom['{code}']: cal incloure el camp a particions.")

        mode = str(cfg.get("mode") or "raw").strip().lower()
        if mode not in {"raw", "custom"}:
            errors.append(f"particions_custom['{code}'].mode invalid: {mode}")
        if mode != "custom":
            continue

        values_owner = {}
        groups = cfg.get("grups") or []
        if not isinstance(groups, list):
            errors.append(f"particions_custom['{code}'].grups ha de ser una llista.")
            continue
        for gidx, group in enumerate(groups):
            if not isinstance(group, dict):
                errors.append(f"particions_custom['{code}'].grups[{gidx}] ha de ser un objecte.")
                continue
            values = _split_particio_custom_values(group.get("values"))
            for val in values:
                key = " ".join(str(val).split()).casefold()
                owner = values_owner.get(key)
                if owner is not None:
                    errors.append(
                        f"particions_custom['{code}']: valor repetit entre grups ({val}) a indexos {owner} i {gidx}."
                    )
                    continue
                values_owner[key] = gidx

    return errors


def _field_is_direct_scoreable(field_cfg: dict):
    """
    Regla robusta per camps d'input:
    - number -> ok
    - list judge -> només si 1 jutge (equivalent 1x1)
    - matrix judge_x_* -> només 1 jutge i 1 item (1x1)
    """
    if not isinstance(field_cfg, dict):
        return False, "config de camp no valida"

    ftype = str(field_cfg.get("type") or "").strip().lower()
    shape = str(field_cfg.get("shape") or "").strip().lower()

    judges_cfg = field_cfg.get("judges") if isinstance(field_cfg.get("judges"), dict) else {}
    items_cfg = field_cfg.get("items") if isinstance(field_cfg.get("items"), dict) else {}

    n_judges = _safe_int(judges_cfg.get("count") or field_cfg.get("judges_count") or 1, 1)
    n_judges = max(1, min(10, n_judges))
    n_items = _safe_int(items_cfg.get("count") or 0, 0)
    n_items = max(0, min(50, n_items))

    if ftype == "number":
        return True, ""

    if ftype == "list" and shape == "judge":
        if n_judges == 1:
            return True, ""
        return False, "camp tipus llista amb mes d'un jutge"

    if ftype == "matrix" and shape in ("judge_x_item", "judge_x_element"):
        if n_judges == 1 and n_items == 1:
            return True, ""
        return False, "camp tipus matriu; per puntuacio directa nomes s'admet 1x1"

    return False, "tipus de camp no puntuable directament"


def _infer_schema_code_shapes(schema_obj: dict):
    schema_obj = schema_obj or {}

    params = schema_obj.get("params", {})
    if params is None or not isinstance(params, dict):
        params = {}

    fields = schema_obj.get("fields", [])
    computed = schema_obj.get("computed", [])
    if not isinstance(fields, list):
        fields = []
    if not isinstance(computed, list):
        computed = []

    field_codes = []
    comp_codes = []
    for f in fields:
        if isinstance(f, dict) and isinstance(f.get("code"), str):
            field_codes.append(f["code"])
    for c in computed:
        if isinstance(c, dict) and isinstance(c.get("code"), str):
            comp_codes.append(c["code"])

    aliases = _build_alias_map(fields, computed, params)
    allowed_names = set(field_codes) | set(comp_codes) | set(aliases.keys()) | RESERVED_NAMES | ALLOWED_FUNCTIONS

    comp_deps = {cc: set() for cc in comp_codes}
    for i, c in enumerate(computed):
        if not isinstance(c, dict):
            continue
        code = str(c.get("code") or "").strip()
        if not code:
            continue
        formula = c.get("formula")
        if not isinstance(formula, str) or not formula.strip():
            continue

        loc = f"computed[{i}]({code})"
        try:
            tree = _ast_parse(formula, loc)
            names = _extract_names(tree)
        except Exception:
            continue

        # best-effort: ignorem desconeguts i extraiem deps conegudes
        resolved = {_resolve_name(n, aliases) for n in names if n in allowed_names}
        for r in resolved:
            if r in comp_deps and r != code:
                comp_deps[code].add(r)

    try:
        order = _topo_sort(comp_codes, comp_deps)
    except Exception:
        order = list(comp_codes)

    ctx = {}
    for f in fields:
        if not isinstance(f, dict):
            continue
        code = str(f.get("code") or "").strip()
        if not code:
            continue
        ctx[code] = TMat(_field_shape(f), name=code)

    ctx["params"] = TMat(Shape(1, 1), name="params")
    for short, code in aliases.items():
        if code in ctx:
            ctx[short] = ctx[code]

    for code in order:
        cobj = next((x for x in computed if isinstance(x, dict) and x.get("code") == code), None)
        if not cobj:
            continue
        formula = str(cobj.get("formula") or "")
        if not formula:
            continue
        loc = f"computed({code})"
        try:
            tree = _ast_parse(formula, loc)
            val = DryRunEval(ctx).visit(tree)
        except Exception:
            continue
        ctx[code] = val
        var = cobj.get("var")
        if isinstance(var, str) and var in aliases:
            ctx[var] = val

    out = {}
    for code in field_codes + comp_codes:
        tm = ctx.get(code)
        if not isinstance(tm, TMat):
            continue
        out[code] = {"rows": tm.shape.rows, "cols": tm.shape.cols}
    return out


def _shape_desc(shape_info) -> str:
    if not isinstance(shape_info, dict):
        return "?"
    r = shape_info.get("rows")
    c = shape_info.get("cols")
    r_txt = "?" if r is None else str(r)
    c_txt = "?" if c is None else str(c)
    return f"{r_txt}x{c_txt}"


def _is_scalar_shape_info(shape_info) -> bool:
    if not isinstance(shape_info, dict):
        return False
    return shape_info.get("rows") == 1 and shape_info.get("cols") == 1


def _normalize_tie_camps_for_validation(tie_obj) -> list:
    if not isinstance(tie_obj, dict):
        return []
    out = []
    raw = tie_obj.get("camps")
    if isinstance(raw, list):
        out = [str(x).strip() for x in raw if str(x).strip()]
    elif isinstance(raw, str):
        out = [x.strip() for x in raw.split(",") if x and x.strip()]

    if not out:
        legacy = str(tie_obj.get("camp") or "").strip()
        if legacy:
            out = [legacy]

    dedup = []
    seen = set()
    for c in out:
        if c in seen:
            continue
        seen.add(c)
        dedup.append(c)
    return dedup


def _computed_mode_hint(comp_cfg: dict) -> str:
    if not isinstance(comp_cfg, dict):
        return ""
    builder = comp_cfg.get("builder") if isinstance(comp_cfg.get("builder"), dict) else {}
    preset = str(builder.get("preset") or "").strip().lower()
    if preset in {"row_compute", "column_compute", "row_agregation", "exec_trampoli", "select_sum_guided"}:
        return preset

    formula = str(comp_cfg.get("formula") or "").strip().lower()
    if re.match(r"^row_custom_compute\s*\(", formula):
        return "row_compute"
    if re.match(r"^column_custom_compute\s*\(", formula):
        return "column_compute"
    if re.match(r"^row_custom_agregation\s*\(", formula):
        return "row_agregation"
    if re.match(r"^exec_by_judge\s*\(", formula):
        return "exec_trampoli"
    if re.match(r"^select_sum\s*\(", formula):
        return "select_sum_guided"
    return ""


def _formula_forces_vector_return(formula: str) -> bool:
    call_name, args_txt = _parse_formula_root_call(formula)
    fn = str(call_name or "").strip().lower()
    if fn not in {"row_custom_compute", "column_custom_compute"}:
        return False
    rm = _extract_kwarg_str(args_txt, "return_mode").lower()
    return rm in {"by_judge", "by_item"}


def _parse_formula_root_call(formula: str):
    txt = str(formula or "").strip()
    if not txt:
        return "", ""
    m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*$", txt, flags=re.DOTALL)
    if not m:
        return "", ""
    return str(m.group(1) or "").strip(), str(m.group(2) or "")


def _extract_kwarg_int(args_txt: str, key: str):
    txt = str(args_txt or "")
    pat = rf"\b{re.escape(str(key))}\s*=\s*(-?\d+)\b"
    m = re.search(pat, txt)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _extract_kwarg_str(args_txt: str, key: str):
    txt = str(args_txt or "")
    pat = rf"\b{re.escape(str(key))}\s*=\s*(?:(['\"])(.*?)\1|([A-Za-z_][A-Za-z0-9_]*))"
    m = re.search(pat, txt, flags=re.DOTALL)
    if not m:
        return ""
    return str(m.group(2) or m.group(3) or "").strip()


def _extract_first_arg(args_txt: str):
    txt = str(args_txt or "")
    if not txt.strip():
        return ""

    depth = 0
    quote = ""
    escaped = False
    for i, ch in enumerate(txt):
        if quote:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == quote:
                quote = ""
            continue

        if ch in {"'", '"'}:
            quote = ch
            continue
        if ch in {"(", "[", "{"}:
            depth += 1
            continue
        if ch in {")", "]", "}"}:
            depth = max(0, depth - 1)
            continue
        if ch == "," and depth == 0:
            return txt[:i].strip()
    return txt.strip()


def _extract_source_from_call(comp_cfg: dict, call_name: str, args_txt: str):
    if isinstance(comp_cfg, dict):
        b = comp_cfg.get("builder")
        if isinstance(b, dict):
            src = str(b.get("source") or "").strip()
            if src:
                return src

    fn = str(call_name or "").strip().lower()
    if fn not in {
        "row_custom_compute", "column_custom_compute", "row_custom_agregation",
        "exec_by_judge", "items_reduce", "crash",
    }:
        return ""

    tok = _extract_first_arg(args_txt)
    if not tok:
        return ""

    m = re.match(r"""^\s*field\s*\(\s*(?:'([^']+)'|"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*))\s*\)\s*$""", tok)
    if m:
        return str(m.group(1) or m.group(2) or m.group(3) or "").strip()

    m = re.match(r"""^\s*(?:'([^']+)'|"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*))\s*$""", tok)
    if not m:
        return ""
    return str(m.group(1) or m.group(2) or m.group(3) or "").strip()


def _extract_best_n_value(args_txt: str):
    n_kw = _extract_kwarg_int(args_txt, "n")
    if n_kw is not None:
        return n_kw
    txt = str(args_txt or "")
    # best_n(scores, 1)
    m = re.match(r"""^\s*[^,]+,\s*(-?\d+)\b""", txt)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _schema_field_dims_map(schema_obj: dict):
    out = {}
    schema_obj = schema_obj or {}
    for f in (schema_obj.get("fields") or []):
        if not isinstance(f, dict) or not f.get("code"):
            continue
        code = str(f.get("code"))
        sh = _field_shape(f)
        out[code] = {"rows": sh.rows, "cols": sh.cols}
    return out


def _resolve_source_dims(source_code: str, inferred_shapes: dict, field_dims: dict):
    src = str(source_code or "").strip()
    if not src:
        return {"rows": None, "cols": None}
    info = inferred_shapes.get(src)
    if isinstance(info, dict):
        return {"rows": info.get("rows"), "cols": info.get("cols")}
    info = field_dims.get(src)
    if isinstance(info, dict):
        return {"rows": info.get("rows"), "cols": info.get("cols")}
    return {"rows": None, "cols": None}


def _scoreable_from_conditional_vector(comp_cfg: dict, mode_hint: str, call_name: str, args_txt: str, inferred_shapes: dict, field_dims: dict, strict_unknown: bool):
    mode = str(mode_hint or "").strip().lower()
    fn = str(call_name or "").strip().lower()
    args = str(args_txt or "")

    source_code = _extract_source_from_call(comp_cfg, fn, args)
    dims = _resolve_source_dims(source_code, inferred_shapes, field_dims)
    src_rows = dims.get("rows")
    src_cols = dims.get("cols")

    # row/column compute only become vectors with explicit return_mode
    if mode in {"row_compute", "column_compute"} or fn in {"row_custom_compute", "column_custom_compute"}:
        is_row_compute = mode == "row_compute" or fn == "row_custom_compute"
        is_col_compute = mode == "column_compute" or fn == "column_custom_compute"
        rm = _extract_kwarg_str(args, "return_mode").lower()

        if not _formula_forces_vector_return(comp_cfg.get("formula")) or rm in {"", "final"}:
            return True, "", True

        if is_row_compute:
            if rm != "by_judge":
                return True, "", True
            if src_rows == 1:
                return True, "return_mode by_judge amb 1 jutge (llista d'1)", True
            if src_rows is None:
                if strict_unknown:
                    return False, "no es pot inferir longitud de vector by_judge", True
                return True, "longitud by_judge no inferible (UI tolerant)", True
            return False, f"return_mode by_judge amb {src_rows} jutges", True

        if is_col_compute:
            if rm != "by_item":
                return True, "", True
            # by_item: use cols and/or explicit count=1
            cnt = _extract_kwarg_int(args, "count")
            if cnt is not None and cnt == 1:
                return True, "return_mode by_item amb count=1", True
            if src_cols == 1:
                return True, "return_mode by_item amb 1 item", True
            if src_cols is None:
                if strict_unknown:
                    return False, "no es pot inferir longitud de vector by_item", True
                return True, "longitud by_item no inferible (UI tolerant)", True
            return False, f"return_mode by_item amb {src_cols} items", True

    # Vector by judge families
    if mode in {"row_agregation", "exec_trampoli"} or fn in {"row_custom_agregation", "exec_by_judge", "items_reduce", "crash"}:
        if src_rows == 1:
            return True, "vector per jutge de longitud 1", True
        if src_rows is None:
            if strict_unknown:
                return False, "no es pot inferir longitud de vector per jutge", True
            return True, "longitud per jutge no inferible (UI tolerant)", True
        return False, f"vector per jutge de longitud {src_rows}", True

    # best_n -> vector de mida n
    if fn == "best_n":
        n_val = _extract_best_n_value(args)
        if n_val == 1:
            return True, "best_n amb n=1", True
        if n_val is None:
            if strict_unknown:
                return False, "best_n sense n constant no es pot garantir mida 1", True
            return True, "best_n sense n constant (UI tolerant)", True
        return False, f"best_n amb n={n_val}", True

    return False, "", False


def _build_scoreable_meta_for_schema(schema_obj: dict, strict_unknown=False):
    schema_obj = schema_obj or {}
    meta = {
        "total": {"scoreable": True, "reason": ""},
        "TOTAL": {"scoreable": True, "reason": ""},
    }

    inferred_shapes = {}
    infer_error = ""
    field_dims = _schema_field_dims_map(schema_obj)
    try:
        inferred_shapes = _infer_schema_code_shapes(schema_obj)
    except Exception as exc:
        infer_error = str(exc)

    for f in (schema_obj.get("fields") or []):
        if not isinstance(f, dict) or not f.get("code"):
            continue
        code = str(f["code"])
        ok, reason = _field_is_direct_scoreable(f)
        shape_info = inferred_shapes.get(code)
        if shape_info is not None:
            if _is_scalar_shape_info(shape_info):
                ok, reason = True, ""
            else:
                ok, reason = False, f"shape no escalar {_shape_desc(shape_info)}"
        meta[code] = {"scoreable": bool(ok), "reason": str(reason or "")}

    for c in (schema_obj.get("computed") or []):
        if not isinstance(c, dict) or not c.get("code"):
            continue
        code = str(c["code"])
        mode_hint = _computed_mode_hint(c)
        formula_txt = str(c.get("formula") or "")
        call_name, call_args = _parse_formula_root_call(formula_txt)

        cond_ok, cond_reason, cond_handled = _scoreable_from_conditional_vector(
            c,
            mode_hint,
            call_name,
            call_args,
            inferred_shapes,
            field_dims,
            strict_unknown=bool(strict_unknown),
        )
        if cond_handled:
            meta[code] = {"scoreable": bool(cond_ok), "reason": "" if cond_ok else cond_reason}
            continue

        shape_info = inferred_shapes.get(code)
        if shape_info is None:
            if mode_hint in {"row_compute", "column_compute", "select_sum_guided"}:
                meta[code] = {"scoreable": True, "reason": ""}
                continue

            if strict_unknown:
                if infer_error:
                    reason = f"no es pot inferir shape (schema invalid): {infer_error}"
                else:
                    reason = "no es pot inferir shape del computed"
                meta[code] = {"scoreable": False, "reason": reason}
            else:
                meta[code] = {"scoreable": True, "reason": ""}
            continue
        if mode_hint in {"row_compute", "column_compute", "select_sum_guided"} and _is_scalar_shape_info(shape_info):
            meta[code] = {"scoreable": True, "reason": ""}
            continue
        if _is_scalar_shape_info(shape_info):
            meta[code] = {"scoreable": True, "reason": ""}
        else:
            meta[code] = {
                "scoreable": False,
                "reason": f"computed amb shape no escalar {_shape_desc(shape_info)}",
            }

    return meta


def _validate_camps_per_aparell(competicio, schema: dict):
    schema = schema or {}
    punt = (schema.get("puntuacio") or {})
    camps_per_aparell = punt.get("camps_per_aparell") or {}
    if not camps_per_aparell:
        return []
    if not isinstance(camps_per_aparell, dict):
        return ["puntuacio.camps_per_aparell ha de ser un objecte {app_id:[camps]}."]

    active_apps = list(
        CompeticioAparell.objects
        .filter(competicio=competicio, actiu=True)
        .select_related("aparell")
    )
    app_by_id = {ca.id: ca for ca in active_apps}
    if not app_by_id:
        return []

    aparell_ids = [ca.aparell_id for ca in active_apps]
    schemas_by_aparell = {
        s.aparell_id: (s.schema or {})
        for s in ScoringSchema.objects.filter(aparell_id__in=aparell_ids).only("aparell_id", "schema")
    }

    app_mode = ((punt.get("aparells") or {}).get("mode") or "seleccionar").strip().lower()
    app_ids_raw = ((punt.get("aparells") or {}).get("ids") or [])
    selected_app_ids = set()
    if app_mode == "seleccionar":
        for x in app_ids_raw:
            try:
                selected_app_ids.add(int(x))
            except Exception:
                continue
    else:
        selected_app_ids = set(app_by_id.keys())

    errors = []
    for app_key, raw_codes in camps_per_aparell.items():
        try:
            app_id = int(app_key)
        except Exception:
            errors.append(f"app_id invalid a camps_per_aparell: {app_key}")
            continue

        if app_id not in app_by_id:
            errors.append(f"aparell {app_id} no valid o no actiu a la competicio.")
            continue
        if app_id not in selected_app_ids:
            continue

        if isinstance(raw_codes, str):
            codes = [x.strip() for x in raw_codes.split(",") if x and x.strip()]
        elif isinstance(raw_codes, list):
            codes = [str(x).strip() for x in raw_codes if str(x).strip()]
        else:
            errors.append(f"camps_per_aparell[{app_id}] ha de ser llista o string.")
            continue

        sch = schemas_by_aparell.get(app_by_id[app_id].aparell_id, {}) or {}
        meta = _build_scoreable_meta_for_schema(sch, strict_unknown=True)

        for code in codes:
            info = meta.get(code)
            if not info:
                errors.append(f"aparell {app_id}: camp '{code}' no existeix al schema.")
                continue
            if not info.get("scoreable", False):
                errors.append(f"aparell {app_id}: camp '{code}' no es puntuable directament ({info.get('reason')}).")

    return errors


def _parse_positive_int_list(raw):
    if raw is None:
        return []
    if isinstance(raw, str):
        out = []
        for part in raw.split(","):
            p = str(part or "").strip()
            if not p:
                continue
            try:
                iv = int(p)
            except Exception:
                continue
            if iv > 0:
                out.append(iv)
        return out
    if isinstance(raw, (list, tuple)):
        out = []
        for x in raw:
            try:
                iv = int(x)
            except Exception:
                continue
            if iv > 0:
                out.append(iv)
        return out
    return []


def _validate_exercicis_cfg_obj(cfg, prefix: str):
    errors = []
    if not isinstance(cfg, dict):
        errors.append(f"{prefix} ha de ser un objecte.")
        return errors

    allowed_modes = {"tots", "millor_1", "millor_n", "pitjor_1", "pitjor_n", "primer", "ultim", "index", "llista"}
    mode = str(cfg.get("mode") or "tots").strip().lower()
    if mode not in allowed_modes:
        errors.append(f"{prefix}.mode invalid: {mode}")
        return errors

    if mode in {"millor_n", "pitjor_n"}:
        try:
            n = int(cfg.get("best_n") or 1)
        except Exception:
            n = 0
        if n < 1:
            errors.append(f"{prefix}.best_n ha de ser >= 1.")

    if mode == "index":
        try:
            idx = int(cfg.get("index") or 1)
        except Exception:
            idx = 0
        if idx < 1:
            errors.append(f"{prefix}.index ha de ser >= 1.")

    if mode == "llista":
        ids = _parse_positive_int_list(cfg.get("ids"))
        if not ids:
            errors.append(f"{prefix}.ids ha de contenir almenys un index valid (>0).")

    return errors


def _get_active_and_selected_app_ids(competicio, punt: dict):
    active_app_ids = set(
        CompeticioAparell.objects.filter(competicio=competicio, actiu=True).values_list("id", flat=True)
    )
    app_mode = str(((punt or {}).get("aparells") or {}).get("mode") or "seleccionar").strip().lower()
    app_ids_raw = ((punt or {}).get("aparells") or {}).get("ids") or []
    if app_mode != "seleccionar":
        return active_app_ids, set(active_app_ids)

    selected_ids = set()
    for x in app_ids_raw:
        try:
            selected_ids.add(int(x))
        except Exception:
            continue
    return active_app_ids, selected_ids


def _validate_exercicis_selection(competicio, schema: dict):
    schema = schema or {}
    punt = (schema.get("puntuacio") or {})

    mode_sel = str(punt.get("mode_seleccio_exercicis") or "per_aparell_global").strip().lower()
    allowed_sel = {"per_aparell_global", "per_aparell_override", "global_pool"}
    if mode_sel not in allowed_sel:
        return [f"puntuacio.mode_seleccio_exercicis invalid: {mode_sel}"]

    errors = []
    ex_global = punt.get("exercicis") or {}
    errors.extend(_validate_exercicis_cfg_obj(ex_global, "puntuacio.exercicis"))

    if mode_sel != "per_aparell_override":
        return errors

    raw_map = punt.get("exercicis_per_aparell") or {}
    if not isinstance(raw_map, dict):
        errors.append("puntuacio.exercicis_per_aparell ha de ser un objecte {app_id: cfg}.")
        return errors

    active_app_ids, selected_ids = _get_active_and_selected_app_ids(competicio, punt)

    for app_key, ex_cfg in raw_map.items():
        try:
            app_id = int(app_key)
        except Exception:
            errors.append(f"puntuacio.exercicis_per_aparell: app_id invalid {app_key}")
            continue
        if app_id not in active_app_ids:
            errors.append(f"puntuacio.exercicis_per_aparell: aparell {app_id} no valid o no actiu.")
            continue
        if app_id not in selected_ids:
            continue
        errors.extend(_validate_exercicis_cfg_obj(ex_cfg, f"puntuacio.exercicis_per_aparell[{app_id}]"))

    return errors


def _validate_no_tots_mode(schema: dict):
    schema = schema or {}
    errors = []

    punt = schema.get("puntuacio") or {}
    if not isinstance(punt, dict):
        punt = {}
    app_mode = str(((punt.get("aparells") or {}).get("mode") or "seleccionar")).strip().lower()
    if app_mode == "tots":
        errors.append("puntuacio.aparells.mode='tots' no esta permès; cal seleccionar aparells explicitament.")

    desempat = schema.get("desempat") or []
    if not isinstance(desempat, list):
        return errors

    for idx, tie in enumerate(desempat):
        if not isinstance(tie, dict):
            continue
        scope = tie.get("scope") or {}
        if not isinstance(scope, dict):
            continue
        app_scope = scope.get("aparells") or {}
        if not isinstance(app_scope, dict):
            continue
        tie_mode = str(app_scope.get("mode") or "hereta").strip().lower()
        if tie_mode == "tots":
            errors.append(
                f"desempat[{idx}].scope.aparells.mode='tots' no esta permès; usa 'hereta' o seleccio explicita."
            )

    return errors


def _validate_tie_camps_per_aparell(competicio, schema: dict):
    schema = schema or {}
    punt = (schema.get("puntuacio") or {})
    desempat = schema.get("desempat") or []
    if not isinstance(desempat, list):
        return ["desempat ha de ser una llista."]

    active_apps = list(
        CompeticioAparell.objects
        .filter(competicio=competicio, actiu=True)
        .select_related("aparell")
    )
    app_by_id = {ca.id: ca for ca in active_apps}
    if not app_by_id:
        return []

    schemas_by_aparell = {
        s.aparell_id: (s.schema or {})
        for s in ScoringSchema.objects.filter(aparell_id__in=[ca.aparell_id for ca in active_apps]).only("aparell_id", "schema")
    }

    _, selected_ids_main = _get_active_and_selected_app_ids(competicio, punt)
    active_app_ids = set(app_by_id.keys())
    meta_cache = {}
    errors = []

    for idx, tie in enumerate(desempat):
        if not isinstance(tie, dict):
            continue

        camps = _normalize_tie_camps_for_validation(tie)
        if not camps:
            continue

        scope = tie.get("scope") or {}
        if not isinstance(scope, dict):
            scope = {}
        app_scope = scope.get("aparells") or {}
        if not isinstance(app_scope, dict):
            app_scope = {}
        app_mode = str(app_scope.get("mode") or "hereta").strip().lower()

        if app_mode == "seleccionar":
            target_ids = set(_parse_positive_int_list(app_scope.get("ids")))
        elif app_mode == "tots":
            target_ids = set(active_app_ids)
        else:
            target_ids = set(selected_ids_main)

        for app_id in sorted(target_ids):
            if app_id not in active_app_ids:
                errors.append(f"desempat[{idx}]: aparell {app_id} no valid o no actiu.")
                continue

            if app_id not in meta_cache:
                sch = schemas_by_aparell.get(app_by_id[app_id].aparell_id, {}) or {}
                meta_cache[app_id] = _build_scoreable_meta_for_schema(sch, strict_unknown=True)
            meta = meta_cache[app_id]

            for code in camps:
                info = meta.get(code)
                if not info:
                    errors.append(f"desempat[{idx}]: aparell {app_id}: camp '{code}' no existeix al schema.")
                    continue
                if not info.get("scoreable", False):
                    errors.append(
                        f"desempat[{idx}]: aparell {app_id}: camp '{code}' no es puntuable directament "
                        f"({info.get('reason')})."
                    )

    return errors


def _validate_tie_exercicis_selection(competicio, schema: dict):
    schema = schema or {}
    punt = (schema.get("puntuacio") or {})
    desempat = schema.get("desempat") or []
    if not isinstance(desempat, list):
        return ["desempat ha de ser una llista."]

    errors = []
    active_app_ids, selected_ids_main = _get_active_and_selected_app_ids(competicio, punt)

    for idx, tie in enumerate(desempat):
        if not isinstance(tie, dict):
            errors.append(f"desempat[{idx}] ha de ser un objecte.")
            continue

        scope = tie.get("scope") or {}
        if not isinstance(scope, dict):
            errors.append(f"desempat[{idx}].scope ha de ser un objecte.")
            scope = {}
        ex_scope = scope.get("exercicis") or {}
        if scope.get("exercicis") is not None and not isinstance(scope.get("exercicis"), dict):
            errors.append(f"desempat[{idx}].scope.exercicis ha de ser un objecte.")
        if not isinstance(ex_scope, dict):
            ex_scope = {}

        ex_mode = str(ex_scope.get("mode") or "hereta").strip().lower()
        if ex_mode != "hereta":
            errors.extend(
                _validate_exercicis_cfg_obj(ex_scope, f"desempat[{idx}].scope.exercicis")
            )

        mode_sel_raw = (
            tie.get("mode_seleccio_exercicis")
            or ex_scope.get("mode_seleccio_exercicis")
            or "hereta"
        )
        mode_sel = str(mode_sel_raw).strip().lower()
        allowed_sel = {"hereta", "per_aparell_global", "per_aparell_override", "global_pool"}
        if mode_sel not in allowed_sel:
            errors.append(f"desempat[{idx}].mode_seleccio_exercicis invalid: {mode_sel}")
            continue
        if mode_sel != "per_aparell_override":
            continue

        app_scope = scope.get("aparells") or {}
        if not isinstance(app_scope, dict):
            app_scope = {}
        app_mode = str(app_scope.get("mode") or "hereta").strip().lower()

        if app_mode == "seleccionar":
            target_ids = set(_parse_positive_int_list(app_scope.get("ids")))
        elif app_mode == "tots":
            target_ids = set(active_app_ids)
        else:
            target_ids = set(selected_ids_main)

        raw_map = tie.get("exercicis_per_aparell")
        if raw_map is None:
            raw_map = ex_scope.get("exercicis_per_aparell")
        if raw_map is None:
            raw_map = {}
        if not isinstance(raw_map, dict):
            errors.append(f"desempat[{idx}].exercicis_per_aparell ha de ser un objecte {{app_id: cfg}}.")
            continue

        for app_key, ex_cfg in raw_map.items():
            try:
                app_id = int(app_key)
            except Exception:
                errors.append(f"desempat[{idx}].exercicis_per_aparell: app_id invalid {app_key}")
                continue
            if app_id not in active_app_ids:
                errors.append(
                    f"desempat[{idx}].exercicis_per_aparell: aparell {app_id} no valid o no actiu."
                )
                continue
            if target_ids and app_id not in target_ids:
                continue
            errors.extend(
                _validate_exercicis_cfg_obj(
                    ex_cfg,
                    f"desempat[{idx}].exercicis_per_aparell[{app_id}]",
                )
            )

    return errors


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
    schema = _normalize_particions_schema(payload.get("schema") or {})

    if tipus not in ("individual", "entitat", "equips"):
        tipus = "individual"

    validation_errors = []
    validation_errors.extend(_validate_particions_schema(competicio, schema))
    validation_errors.extend(_validate_no_tots_mode(schema))
    validation_errors.extend(_validate_camps_per_aparell(competicio, schema))
    validation_errors.extend(_validate_tie_camps_per_aparell(competicio, schema))
    validation_errors.extend(_validate_exercicis_selection(competicio, schema))
    validation_errors.extend(_validate_tie_exercicis_selection(competicio, schema))
    if validation_errors:
        return JsonResponse(
            {
                "ok": False,
                "error": "Configuracio de classificacio invalida.",
                "errors": validation_errors,
            },
            status=400,
        )

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

    return JsonResponse({
        "ok": True,
        "columns": get_display_columns(cfg.schema or {}),
        "data": out,
    })


def _is_fk(model_cls, field_name: str) -> bool:
    try:
        f = model_cls._meta.get_field(field_name)
        return isinstance(f, (models.ForeignKey, models.OneToOneField))
    except Exception:
        return False


def _particio_value_to_text(raw) -> str:
    if raw is None:
        return ""
    if isinstance(raw, (list, dict)):
        try:
            return json.dumps(raw, ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(raw)
    return str(raw).strip()


def _collect_particio_value_choices(ins_list, field_codes, max_per_field=200):
    out = {}
    for code in field_codes:
        unique_labels = {}
        unique_counts = {}
        for ins in ins_list:
            txt = _particio_value_to_text(get_inscripcio_value(ins, code))
            if not txt:
                continue
            key = " ".join(txt.split()).casefold()
            if key in unique_labels:
                unique_counts[key] = int(unique_counts.get(key, 0) or 0) + 1
                continue
            if len(unique_labels) >= max_per_field:
                continue
            unique_labels[key] = txt
            unique_counts[key] = 1

        entries = []
        for key, value in unique_labels.items():
            entries.append(
                {
                    "value": value,
                    "label": value,
                    "count": int(unique_counts.get(key, 0) or 0),
                }
            )

        entries.sort(key=lambda x: str(x.get("label") or "").casefold())
        out[code] = entries
    return out


def _distinct_values(qs, field_name: str):
    vals = qs.values_list(field_name, flat=True).distinct()
    out = []
    seen = set()
    for v in vals:
        if v is None:
            continue
        label = str(v).strip()
        if not label:
            continue
        key = " ".join(label.split()).casefold()   # treu dobles espais + case-insensitive
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
    return out


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




