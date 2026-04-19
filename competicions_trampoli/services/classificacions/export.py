import json
import re

from django.utils import timezone
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .live import default_live_columns, extract_export_value, format_partition_title


def excel_safe_text(raw) -> str:
    txt = "" if raw is None else str(raw)
    if txt[:1] in ("=", "+", "-", "@"):
        return "'" + txt
    return txt


def try_float(value):
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


def format_scalar_text(value, decimals=None):
    if value is None:
        return ""
    number = try_float(value)
    if number is not None and decimals is not None:
        return f"{number:.{decimals}f}"
    if number is not None and isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def normalize_excel_cell(value, col):
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
            vals = [format_scalar_text(item, decimals) for item in items]
            lines.append(f"{judge_label}: " + " | ".join(vals))
        return excel_safe_text("\n".join([line for line in lines if line])), None, True

    if isinstance(value, dict) and value.get("_kind") == "team_raw_detail":
        lines = []
        summary = value.get("summary")
        if summary not in (None, ""):
            lines.append(format_scalar_text(summary, decimals))
        for row in value.get("rows") or []:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label") or "").strip()
            if not label:
                continue
            judge_rows = row.get("judge_rows")
            if isinstance(judge_rows, dict) and judge_rows.get("_kind") == "judge_rows":
                lines.append(f"{label}:")
                for judge_row in judge_rows.get("rows") or []:
                    judge_num = judge_row.get("judge")
                    try:
                        judge_num = int(judge_num)
                    except Exception:
                        judge_num = None
                    judge_label = f"J{judge_num}" if judge_num and judge_num > 0 else "J?"
                    items = judge_row.get("items") or []
                    if not isinstance(items, list):
                        items = [items]
                    vals = [format_scalar_text(item, decimals) for item in items]
                    lines.append(f"  {judge_label}: " + " | ".join(vals))
                continue
            lines.append(f"{label}: {format_scalar_text(row.get('value'), decimals)}")
        return excel_safe_text("\n".join([line for line in lines if line])), None, True

    if isinstance(value, (dict, list)):
        return excel_safe_text(json.dumps(value, ensure_ascii=False)), None, True
    if isinstance(value, bool):
        return value, None, False

    number = try_float(value)
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
            number = try_float(txt)
            if number is not None:
                rounded = round(number, decimals)
                num_fmt = "0" if decimals == 0 else ("0." + ("0" * decimals))
                return rounded, num_fmt, False
        return excel_safe_text(value), None, ("\n" in value)

    if value is None:
        return "", None, False
    return excel_safe_text(value), None, False


def build_excel_sheet_name(raw_name, used_names):
    base = str(raw_name or "").strip() or "Classificacio"
    base = re.sub(r"[\[\]\*:/\\?]", " ", base)
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


def detail_sections_for_row(row: dict):
    detail = row.get("detail") if isinstance(row, dict) else None
    sections = detail.get("sections") if isinstance(detail, dict) else None
    return sections if isinstance(sections, list) else []


def max_detail_table_columns(parts):
    max_cols = 0
    for part in parts if isinstance(parts, list) else []:
        for row in (part or {}).get("rows") or []:
            for section in detail_sections_for_row(row):
                columns = section.get("columns") if isinstance(section, dict) else None
                if isinstance(columns, list):
                    max_cols = max(max_cols, len(columns))
    return max_cols


def has_detail_sections(parts):
    for part in parts if isinstance(parts, list) else []:
        for row in (part or {}).get("rows") or []:
            if detail_sections_for_row(row):
                return True
    return False


def write_cfg_excel_sheet(ws, competicio, cfg_nom, columns, parts):
    cols = columns if isinstance(columns, list) and columns else default_live_columns()
    detail_cols = max_detail_table_columns(parts)
    total_cols = max(2 if has_detail_sections(parts) else 1, len(cols), detail_cols + 1)

    fill_title = PatternFill("solid", fgColor="1F4E79")
    fill_subtitle = PatternFill("solid", fgColor="D9E1F2")
    fill_partition = PatternFill("solid", fgColor="DDE7FF")
    fill_header = PatternFill("solid", fgColor="E9EEF7")
    fill_zebra = PatternFill("solid", fgColor="F7F9FC")
    fill_detail_title = PatternFill("solid", fgColor="F4F7FB")
    fill_detail_section = PatternFill("solid", fgColor="EEF3FA")
    fill_detail_header = PatternFill("solid", fgColor="F8FAFD")
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

    def merge_range_if_needed(*, start_row, start_column, end_row, end_column):
        if start_row == end_row and start_column == end_column:
            return
        ws.merge_cells(
            start_row=start_row,
            start_column=start_column,
            end_row=end_row,
            end_column=end_column,
        )

    def write_detail_block(start_row_idx, row):
        sections = detail_sections_for_row(row)
        if not sections:
            return start_row_idx

        participant_label = str((row or {}).get("participant") or (row or {}).get("nom") or "").strip()
        title = f"Detall: {participant_label}" if participant_label else "Detall"
        merge_range_if_needed(start_row=start_row_idx, start_column=1, end_row=start_row_idx, end_column=total_cols)
        title_cell = ws.cell(row=start_row_idx, column=1, value=title)
        title_cell.fill = fill_detail_title
        title_cell.font = Font(bold=True)
        title_cell.alignment = align_left
        title_cell.border = border
        update_col_width(1, title)
        start_row_idx += 1

        for section in sections:
            section_type = str((section or {}).get("type") or "").strip().lower()
            section_label = str((section or {}).get("label") or "Detall").strip()

            merge_range_if_needed(start_row=start_row_idx, start_column=1, end_row=start_row_idx, end_column=total_cols)
            section_cell = ws.cell(row=start_row_idx, column=1, value=section_label)
            section_cell.fill = fill_detail_section
            section_cell.font = Font(bold=True)
            section_cell.alignment = align_left
            section_cell.border = border
            update_col_width(1, section_label)
            start_row_idx += 1

            if section_type == "members_list":
                items = section.get("items") if isinstance(section, dict) else None
                members = [
                    str(item.get("participant") or "").strip()
                    for item in (items or [])
                    if isinstance(item, dict) and str(item.get("participant") or "").strip()
                ]
                members_text = " · ".join(members) if members else "Sense detalls."
                merge_range_if_needed(start_row=start_row_idx, start_column=2, end_row=start_row_idx, end_column=total_cols)
                members_cell = ws.cell(row=start_row_idx, column=2, value=excel_safe_text(members_text))
                members_cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
                members_cell.border = border
                update_col_width(2, members_text)
                start_row_idx += 1
                continue

            section_columns = section.get("columns") if isinstance(section, dict) else None
            section_rows = section.get("rows") if isinstance(section, dict) else None
            section_columns = section_columns if isinstance(section_columns, list) else []
            section_rows = section_rows if isinstance(section_rows, list) else []
            if not section_columns:
                merge_range_if_needed(start_row=start_row_idx, start_column=2, end_row=start_row_idx, end_column=total_cols)
                empty_cell = ws.cell(row=start_row_idx, column=2, value="Sense detall exportable.")
                empty_cell.alignment = align_left
                empty_cell.font = Font(italic=True)
                empty_cell.border = border
                update_col_width(2, empty_cell.value)
                start_row_idx += 1
                continue

            for col_pos, col in enumerate(section_columns, start=2):
                label = str((col or {}).get("label") or (col or {}).get("key") or "")
                header_cell = ws.cell(row=start_row_idx, column=col_pos, value=label)
                header_cell.fill = fill_detail_header
                header_cell.font = header_font
                header_cell.alignment = align_center
                header_cell.border = border
                update_col_width(col_pos, label)
            start_row_idx += 1

            if not section_rows:
                merge_range_if_needed(start_row=start_row_idx, start_column=2, end_row=start_row_idx, end_column=total_cols)
                empty_cell = ws.cell(row=start_row_idx, column=2, value="Sense resultats en aquesta seccio.")
                empty_cell.alignment = align_left
                empty_cell.font = Font(italic=True)
                empty_cell.border = border
                update_col_width(2, empty_cell.value)
                start_row_idx += 1
                continue

            for detail_pos, detail_row in enumerate(section_rows):
                max_lines = 1
                for col_pos, col in enumerate(section_columns, start=2):
                    raw_value = extract_export_value(detail_row or {}, col or {})
                    value, number_format, wrap_text = normalize_excel_cell(raw_value, col or {})
                    cell = ws.cell(row=start_row_idx, column=col_pos, value=value)
                    cell.border = border
                    if number_format:
                        cell.number_format = number_format
                    align = str((col or {}).get("align") or "").strip().lower()
                    horizontal = "right" if align == "right" else ("center" if align == "center" else "left")
                    vertical = "top" if wrap_text else "center"
                    cell.alignment = Alignment(horizontal=horizontal, vertical=vertical, wrap_text=wrap_text)
                    if detail_pos % 2 == 1:
                        cell.fill = fill_zebra
                    value_txt = "" if value is None else str(value)
                    max_lines = max(max_lines, len(value_txt.splitlines()) if value_txt else 1)
                    update_col_width(col_pos, value)
                if max_lines > 1:
                    ws.row_dimensions[start_row_idx].height = min(120, max(18, max_lines * 14))
                start_row_idx += 1
            start_row_idx += 1

        return start_row_idx

    merge_range_if_needed(start_row=1, start_column=1, end_row=1, end_column=total_cols)
    c_title = ws.cell(row=1, column=1, value=f"{competicio.nom} - {cfg_nom}")
    c_title.fill = fill_title
    c_title.font = title_font
    c_title.alignment = align_center

    merge_range_if_needed(start_row=2, start_column=1, end_row=2, end_column=total_cols)
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
        merge_range_if_needed(start_row=row_idx, start_column=1, end_row=row_idx, end_column=total_cols)
        empty = ws.cell(row=row_idx, column=1, value="Sense resultats.")
        empty.alignment = align_left
        empty.font = Font(italic=True)
        return

    for part in parts_list:
        part_rows = (part or {}).get("rows") or []
        part_name = format_partition_title((part or {}).get("particio"))

        merge_range_if_needed(start_row=row_idx, start_column=1, end_row=row_idx, end_column=total_cols)
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
            merge_range_if_needed(start_row=row_idx, start_column=1, end_row=row_idx, end_column=total_cols)
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
                raw_value = extract_export_value(row or {}, col or {})
                value, number_format, wrap_text = normalize_excel_cell(raw_value, col or {})
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
            row_idx = write_detail_block(row_idx, row)
        row_idx += 1

    if first_data_row:
        ws.freeze_panes = ws[f"A{first_data_row}"]
    for idx, width in enumerate(col_widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = max(10, width)


def sanitize_filename_component(raw):
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(raw or "").strip()).strip("._")
    return cleaned or "classificacions"


_normalize_excel_cell = normalize_excel_cell


__all__ = [
    "_normalize_excel_cell",
    "build_excel_sheet_name",
    "excel_safe_text",
    "format_scalar_text",
    "normalize_excel_cell",
    "sanitize_filename_component",
    "try_float",
    "write_cfg_excel_sheet",
]
