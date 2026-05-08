"""Excel formatting helpers extracted from the legacy pipeline."""

from __future__ import annotations

try:
    from xlsxwriter.utility import xl_col_to_name as _xl_col_to_name
    def _col_letter(idx: int) -> str:
        return _xl_col_to_name(idx)
except Exception:
    def _col_letter(idx: int) -> str:
        # Conversió manual 0-based -> 'A', 'B', ..., 'Z', 'AA', ...
        if idx < 0:
            return "A"
        letters = ""
        n = idx
        while n >= 0:
            n, rem = divmod(n, 26)
            letters = chr(65 + rem) + letters
            n -= 1
        return letters


def _format_diffs_excel(diffs) -> str:
    """
    Converteix una llista de diferències de jornades a text multi-línia per Excel.
    Accepta formats:
      - [(jornada, casa_fora, rival), ...]
      - [jornada1, jornada2, ...]
      - str ja formatat
    Retorna "—" si no hi ha diferències.
    """
    if diffs is None:
        return "—"
    if isinstance(diffs, str):
        s = diffs.strip()
        return s if s else "—"
    if not isinstance(diffs, (list, tuple)):
        try:
            return str(diffs)
        except Exception:
            return "—"
    if len(diffs) == 0:
        return "—"
    lines = []
    for item in diffs:
        try:
            if isinstance(item, (list, tuple)) and len(item) >= 3:
                j = item[0]
                side = item[1]
                opp = item[2]
                try:
                    j_int = int(j)
                    j_txt = f"J{j_int}"
                except Exception:
                    j_txt = str(j)
                side_s = str(side).strip().lower()
                if side_s in ("c", "casa", "home", "local"):
                    side_txt = "Casa"
                elif side_s in ("f", "fora", "away", "visitant"):
                    side_txt = "Fora"
                else:
                    side_txt = str(side)
                lines.append(f"• {j_txt}: {side_txt} vs {opp}")
            else:
                try:
                    j_int = int(item)
                    lines.append(f"• J{j_int}")
                except Exception:
                    lines.append(f"• {item}")
        except Exception:
            lines.append(f"• {item}")
    return "\n".join(lines)


def _auto_fit_worksheet_columns(ws, df, extra_width=2, min_width=10, max_width=45, wrap_cols=None):
    wrap_cols = set(wrap_cols or [])
    for col_idx, col_name in enumerate(df.columns):
        values = [str(col_name)]
        if not df.empty:
            values.extend(str(x) for x in df[col_name].fillna("").astype(str).tolist())
        width = min(max(max(len(v) for v in values) + extra_width, min_width), max_width)
        ws.set_column(col_idx, col_idx, width)
        if col_name in wrap_cols:
            ws.set_column(col_idx, col_idx, max(width, 20))


def _write_df_block(writer, workbook, sheet_name, start_row, title, df, fmt_title, fmt_header, auto_filter=True, wrap_cols=None):
    if sheet_name not in writer.sheets:
        writer.sheets[sheet_name] = workbook.add_worksheet(sheet_name)
    ws = writer.sheets[sheet_name]
    ws.write(start_row, 0, title, fmt_title)
    if df is None or df.empty:
        ws.write(start_row + 1, 0, "Sense dades")
        return start_row + 3

    df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=start_row + 1)
    for col_idx, col_name in enumerate(df.columns):
        ws.write(start_row + 1, col_idx, col_name, fmt_header)
    if auto_filter:
        ws.autofilter(start_row + 1, 0, start_row + 1 + len(df), max(0, len(df.columns) - 1))
    _auto_fit_worksheet_columns(ws, df, wrap_cols=wrap_cols)
    return start_row + len(df) + 4
