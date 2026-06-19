from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from ...scoring.team_scoring import is_team_context_app, member_runtime_code
from .common import json_clone_value, normalize_positive_int, normalized_text_token
from .ranking import _normalize_tie_camps
from .score_values import _field_value_from_entry, _numeric_scalar_or_1x1, _to_float
from .teams import _derived_team_cache_key


DISPLAY_BUILTIN_KEYS = ("posicio", "participant", "nom", "entitat_nom", "participants", "punts")
DETAIL_DISPLAY_BUILTIN_KEYS = ("participant", "entitat_nom")
DETAIL_EXERCISE_BUILTIN_KEYS = ("exercise_index", "aparell_nom", "participant", "entitat_nom")
DETAIL_SECTION_TYPES = (
    "members_list",
    "members_table",
    "team_members_table",
    "team_metrics",
    "exercise_table",
    "entity_members_table",
)


def _normalize_display_columns(raw_cols, *, detail_mode=False, allowed_builtin_keys=None, default_cols=None):
    cols = raw_cols if isinstance(raw_cols, list) else []
    if default_cols is None:
        default_cols = (
            [{"type": "builtin", "key": "participant", "label": "Participant", "align": "left"}]
            if detail_mode
            else [
                {"type": "builtin", "key": "posicio", "label": "#", "align": "left"},
                {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                {"type": "builtin", "key": "punts", "label": "Punts", "align": "right", "decimals": 3},
            ]
        )
    if allowed_builtin_keys is None:
        allowed_builtin_keys = DETAIL_DISPLAY_BUILTIN_KEYS if detail_mode else DISPLAY_BUILTIN_KEYS
    if not cols:
        return json_clone_value(default_cols)

    out = []
    seen_keys = set()
    metric_idx = 1
    for item in cols:
        if not isinstance(item, dict):
            continue

        ctype = str(item.get("type") or "builtin").strip().lower()
        label = str(item.get("label") or "").strip()
        align = str(item.get("align") or "").strip().lower()
        if align not in ("left", "right", "center"):
            align = "left" if ctype == "builtin" else "right"

        decimals = item.get("decimals", None)
        try:
            decimals = int(decimals) if decimals is not None else None
        except Exception:
            decimals = None
        if decimals is not None:
            decimals = max(0, min(6, decimals))

        if ctype == "raw":
            key = str(item.get("key") or "").strip() or f"raw_{metric_idx}"
            metric_idx += 1

            source = item.get("source") if isinstance(item.get("source"), dict) else {}
            app_id = source.get("aparell_id")
            exercici = source.get("exercici", item.get("exercici"))
            exercise_mode = str(source.get("exercise_mode", item.get("exercise_mode")) or "").strip().lower()
            if exercise_mode not in ("selected", "fixed"):
                exercise_mode = ""
            camp = str(source.get("camp") or "").strip()

            if app_id in (None, "", 0, "0"):
                app_id = item.get("aparell_id", item.get("app_id"))
            try:
                app_id = int(app_id)
            except Exception:
                app_id = None

            try:
                exercici = int(exercici)
            except Exception:
                exercici = 1
            exercici = max(1, exercici)

            if not camp:
                camp = str(item.get("camp") or "").strip() or "total"

            raw_jutges = source.get("jutges") if isinstance(source.get("jutges"), dict) else {}
            ids = raw_jutges.get("ids")
            if not isinstance(ids, list):
                ids = source.get("jutges_ids")
            if not isinstance(ids, list):
                ids = []
            jutges_ids = []
            for raw_id in ids:
                try:
                    judge_id = int(raw_id)
                except Exception:
                    continue
                if judge_id > 0 and judge_id not in jutges_ids:
                    jutges_ids.append(judge_id)

            if not label:
                label = camp
            if decimals is None:
                decimals = 3
            out_item = {
                "type": "raw",
                "key": key,
                "label": label,
                "align": align,
                "decimals": decimals,
                "source": {
                    "aparell_id": app_id,
                    "exercici": exercici,
                    "camp": camp,
                    "jutges": {"ids": jutges_ids},
                },
            }
            if exercise_mode:
                out_item["source"]["exercise_mode"] = exercise_mode
        elif ctype == "metric":
            key = str(item.get("key") or "").strip() or f"raw_{metric_idx}"
            metric_idx += 1
            crit = item.get("criteri") if isinstance(item.get("criteri"), dict) else {}
            camps = _normalize_tie_camps(crit)
            camp = camps[0] if camps else "total"
            scope = crit.get("scope") or {}
            apps = scope.get("aparells") or {}
            app_mode = str(apps.get("mode") or "").lower().strip()
            app_id = None
            if app_mode == "seleccionar":
                ids = apps.get("ids") or []
                if ids:
                    try:
                        app_id = int(ids[0])
                    except Exception:
                        app_id = None
            elif item.get("aparell_id") not in (None, "", 0, "0"):
                try:
                    app_id = int(item.get("aparell_id"))
                except Exception:
                    app_id = None

            ex_cfg = scope.get("exercicis") or {}
            exercici = 1
            if str(ex_cfg.get("mode") or "").lower().strip() == "index":
                try:
                    exercici = max(1, int(ex_cfg.get("index") or 1))
                except Exception:
                    exercici = 1
            if not label:
                label = camp
            if decimals is None:
                decimals = 3
            out_item = {
                "type": "raw",
                "key": key,
                "label": label,
                "align": align,
                "decimals": decimals,
                "source": {
                    "aparell_id": app_id,
                    "exercici": exercici,
                    "camp": camp,
                    "jutges": {"ids": []},
                },
            }
        else:
            key = str(item.get("key") or "").strip()
            if key not in allowed_builtin_keys:
                continue
            if not label:
                label = {
                    "posicio": "#",
                    "participant": "Nom",
                    "nom": "Nom",
                    "entitat_nom": "Entitat",
                    "participants": "Participants",
                    "punts": "Punts",
                }.get(key, key)
            if decimals is None and key == "punts":
                decimals = 3
            out_item = {
                "type": "builtin",
                "key": key,
                "label": label,
                "align": align,
            }
            if decimals is not None:
                out_item["decimals"] = decimals

        if key in seen_keys:
            continue
        seen_keys.add(key)
        out.append(out_item)

    return out or json_clone_value(default_cols)


def _detail_section_builtin_keys(section_type: str):
    stype = str(section_type or "").strip().lower()
    if stype == "exercise_table":
        return DETAIL_EXERCISE_BUILTIN_KEYS
    if stype in ("members_table", "team_members_table", "entity_members_table", "team_metrics"):
        return DETAIL_DISPLAY_BUILTIN_KEYS
    return ()


def _detail_section_default(section_type: str):
    stype = str(section_type or "").strip().lower()
    if stype == "members_list":
        return {"type": "members_list", "label": "Participants"}
    if stype == "team_metrics":
        return {
            "type": "team_metrics",
            "label": "Notes equip",
            "aparell_id": None,
            "columns": [
                {
                    "type": "raw",
                    "key": "team_raw_1",
                    "label": "Total",
                    "align": "right",
                    "decimals": 3,
                    "source": {"aparell_id": None, "exercici": 1, "camp": "total", "jutges": {"ids": []}},
                }
            ],
        }
    if stype == "exercise_table":
        return {
            "type": "exercise_table",
            "label": "Exercicis",
            "aparell_id": None,
            "columns": [
                {"type": "builtin", "key": "aparell_nom", "label": "Aparell", "align": "left"},
                {"type": "builtin", "key": "exercise_index", "label": "Ex.", "align": "left"},
                {
                    "type": "raw",
                    "key": "exercise_raw_1",
                    "label": "Total",
                    "align": "right",
                    "decimals": 3,
                    "source": {"aparell_id": None, "exercici": 1, "camp": "total", "jutges": {"ids": []}},
                },
            ],
        }
    if stype == "entity_members_table":
        return {
            "type": "entity_members_table",
            "label": "Participants",
            "aparell_id": None,
            "columns": [{"type": "builtin", "key": "participant", "label": "Participant", "align": "left"}],
        }
    if stype == "team_members_table":
        return {
            "type": "team_members_table",
            "label": "Notes per membre",
            "aparell_id": None,
            "columns": [{"type": "builtin", "key": "participant", "label": "Participant", "align": "left"}],
        }
    return {
        "type": "members_table",
        "label": "Detall",
        "aparell_id": None,
        "columns": [{"type": "builtin", "key": "participant", "label": "Participant", "align": "left"}],
    }


def _normalize_detail_section(section):
    if not isinstance(section, dict):
        return None
    stype = str(section.get("type") or "").strip().lower()
    if stype not in DETAIL_SECTION_TYPES:
        return None

    base = _detail_section_default(stype)
    out = {**base, **section, "type": stype}
    out["label"] = str(out.get("label") or base.get("label") or "").strip() or str(base.get("label") or "").strip()
    section_app_id = normalize_positive_int(out.get("aparell_id"))
    raw_app_ids = set()
    if "columns" in base or isinstance(section.get("columns"), list):
        out["columns"] = _normalize_display_columns(
            section.get("columns") if isinstance(section.get("columns"), list) else base.get("columns"),
            detail_mode=True,
            allowed_builtin_keys=_detail_section_builtin_keys(stype),
            default_cols=base.get("columns") or [],
        )
        for col in out.get("columns") or []:
            if str(col.get("type") or "").strip().lower() != "raw":
                continue
            src = col.get("source") if isinstance(col.get("source"), dict) else {}
            app_id = normalize_positive_int(src.get("aparell_id"))
            if app_id is not None:
                raw_app_ids.add(app_id)
        if section_app_id is None and len(raw_app_ids) == 1:
            section_app_id = next(iter(raw_app_ids))
        if section_app_id is not None:
            for col in out.get("columns") or []:
                if str(col.get("type") or "").strip().lower() != "raw":
                    continue
                src = col.get("source") if isinstance(col.get("source"), dict) else {}
                if normalize_positive_int(src.get("aparell_id")) is None:
                    col["source"] = {**src, "aparell_id": section_app_id}
    else:
        out.pop("columns", None)

    if stype == "members_list":
        out.pop("aparell_id", None)
    else:
        out["aparell_id"] = section_app_id
    return out


def get_display_columns(schema_or_presentacio=None):
    if not isinstance(schema_or_presentacio, dict):
        presentacio = {}
    elif "presentacio" in schema_or_presentacio:
        presentacio = schema_or_presentacio.get("presentacio") or {}
    else:
        presentacio = schema_or_presentacio or {}
    return _normalize_display_columns(presentacio.get("columnes"), detail_mode=False)


def get_detail_display_config(schema_or_presentacio=None, *, tipus="individual", team_mode=""):
    if not isinstance(schema_or_presentacio, dict):
        presentacio = {}
    elif "presentacio" in schema_or_presentacio:
        presentacio = schema_or_presentacio.get("presentacio") or {}
    else:
        presentacio = schema_or_presentacio or {}

    raw_detail = presentacio.get("detall") if isinstance(presentacio.get("detall"), dict) else {}
    raw_sections = raw_detail.get("sections") if isinstance(raw_detail.get("sections"), list) else []
    sections = []
    for item in raw_sections:
        normalized = _normalize_detail_section(item)
        if normalized is not None:
            sections.append(normalized)
    if not sections and isinstance(raw_detail.get("columnes"), list):
        sections = [
            _normalize_detail_section(
                {"type": "members_table", "label": "Detall", "columns": raw_detail.get("columnes") or []}
            )
        ]
    return {
        "enabled": bool(raw_detail.get("enabled", False)),
        "default_open": bool(raw_detail.get("default_open", False)),
        "sections_layout": "stacked" if str(raw_detail.get("sections_layout") or "").strip().lower() == "stacked" else "tabs",
        "sections": [section for section in sections if section],
    }


class DetailPayloadRuntime:
    def __init__(
        self,
        *,
        notes_by_key,
        team_notes_by_key,
        all_ins_by_id,
        aparells,
        display_columns,
        detail_enabled,
        detail_config,
        get_main_selected_rows_agg_for_team,
        get_main_selected_team_rows_for_field,
        get_main_selected_rows_for_group_field,
    ):
        self.notes_by_key = notes_by_key or {}
        self.team_notes_by_key = team_notes_by_key or {}
        self.all_ins_by_id = all_ins_by_id or {}
        self.aparells = list(aparells or [])
        self.display_columns = list(display_columns or [])
        self.detail_enabled = bool(detail_enabled)
        self.detail_config = detail_config or {}
        self.get_main_selected_rows_agg_for_team = get_main_selected_rows_agg_for_team
        self.get_main_selected_team_rows_for_field = get_main_selected_team_rows_for_field
        self.get_main_selected_rows_for_group_field = get_main_selected_rows_for_group_field

    def _apply_decimals_if_numeric(self, value, decimals):
        if decimals is None:
            return value
        try:
            dv = int(decimals)
        except Exception:
            return value
        if isinstance(value, (int, float, Decimal)):
            return round(_to_float(value), max(0, min(6, dv)))
        return value

    def _value_from_entry(self, entry, camp: str):
        raw = _field_value_from_entry(entry, camp)
        if raw is None:
            return ""
        num = _numeric_scalar_or_1x1(raw)
        if num is not None:
            return num
        return raw

    def _normalize_judge_item(self, value):
        if isinstance(value, Decimal):
            return _to_float(value)
        if isinstance(value, list):
            out = []
            for item in value:
                out.append(_to_float(item) if isinstance(item, Decimal) else item)
            return out
        return value

    def _apply_judge_selection(self, raw_value, judge_ids):
        ids = []
        for raw_id in judge_ids or []:
            try:
                judge_id = int(raw_id)
            except Exception:
                continue
            if judge_id > 0 and judge_id not in ids:
                ids.append(judge_id)
        if not isinstance(raw_value, list):
            return raw_value
        if not ids:
            ids = list(range(1, len(raw_value) + 1))

        picked = []
        for judge_id in ids:
            idx = judge_id - 1
            if 0 <= idx < len(raw_value) and raw_value[idx] is not None:
                picked.append((judge_id, raw_value[idx]))
        if not picked:
            return ""

        rows = []
        for judge_id, value in picked:
            normalized = self._normalize_judge_item(value)
            items = normalized if isinstance(normalized, list) else [normalized]
            rows.append({"judge": judge_id, "items": items})
        return {"_kind": "judge_rows", "rows": rows}

    def _raw_col_value_for_ins(self, ins_id, col):
        src = col.get("source") or {}
        app_id = src.get("aparell_id")
        ex_idx = src.get("exercici", 1)
        camp = str(src.get("camp") or "total").strip() or "total"
        try:
            app_id = int(app_id)
        except Exception:
            return ""
        try:
            ex_idx = max(1, int(ex_idx))
        except Exception:
            ex_idx = 1

        entry = self.notes_by_key.get((ins_id, app_id, ex_idx))
        if not entry:
            return ""
        raw = self._value_from_entry(entry, camp)
        jcfg = src.get("jutges") if isinstance(src.get("jutges"), dict) else {}
        jids = jcfg.get("ids") if isinstance(jcfg.get("ids"), list) else []
        return self._apply_judge_selection(raw, jids)

    def _is_scalar_team_raw_value(self, value):
        if value in (None, ""):
            return False
        if isinstance(value, bool):
            return True
        if isinstance(value, (int, float, Decimal)):
            return True
        return isinstance(value, str)

    def _build_team_raw_detail(self, rows):
        detail_rows = []
        numeric_values = []
        for item in rows or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            value = item.get("value")
            judge_rows = item.get("judge_rows")
            if not label:
                continue
            row_out = {"label": label}
            if judge_rows and isinstance(judge_rows, dict) and judge_rows.get("_kind") == "judge_rows":
                row_out["judge_rows"] = judge_rows
            else:
                row_out["value"] = value
                if self._is_scalar_team_raw_value(value) and not isinstance(value, bool):
                    num = _numeric_scalar_or_1x1(value)
                    if num is not None:
                        numeric_values.append(num)
            detail_rows.append(row_out)
        if not detail_rows:
            return ""

        summary = ""
        if len(detail_rows) == 1:
            only = detail_rows[0]
            if "judge_rows" not in only:
                summary = only.get("value", "")
        elif numeric_values and len(numeric_values) == len(detail_rows):
            summary = float(sum(numeric_values))
        return {"_kind": "team_raw_detail", "summary": summary, "rows": detail_rows}

    @staticmethod
    def _collapse_redundant_native_team_metric_detail(value):
        if not isinstance(value, dict) or value.get("_kind") != "team_raw_detail":
            return value
        rows = value.get("rows")
        if not isinstance(rows, list) or len(rows) != 1:
            return value
        only = rows[0]
        if not isinstance(only, dict) or "judge_rows" in only:
            return value
        summary = value.get("summary")
        if summary in (None, "") or only.get("value") != summary:
            return value
        compact = dict(value)
        compact["rows"] = []
        return compact

    def _merge_judge_rows_payloads(self, payloads):
        merged = {}
        order = []
        for payload in payloads or []:
            if not isinstance(payload, dict) or payload.get("_kind") != "judge_rows":
                continue
            for row in payload.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                judge = row.get("judge")
                key = str(judge)
                if key not in merged:
                    merged[key] = {"judge": judge, "items": []}
                    order.append(key)
                items = row.get("items") or []
                if not isinstance(items, list):
                    items = [items]
                merged[key]["items"].extend(items)
        out_rows = [merged[key] for key in order if merged[key]["items"]]
        if not out_rows:
            return ""
        return {"_kind": "judge_rows", "rows": out_rows}

    def _aggregate_selected_raw_values(self, raw_values):
        values = [value for value in (raw_values or []) if value not in (None, "")]
        if not values:
            return ""

        judge_payloads = [
            value for value in values if isinstance(value, dict) and value.get("_kind") == "judge_rows"
        ]
        if judge_payloads:
            if len(judge_payloads) != len(values):
                return ""
            return self._merge_judge_rows_payloads(judge_payloads)

        if len(values) == 1:
            return values[0]

        numeric_values = []
        for value in values:
            if isinstance(value, bool):
                return ""
            num = _numeric_scalar_or_1x1(value)
            if num is None:
                return ""
            numeric_values.append(num)
        return float(sum(numeric_values))

    def _raw_value_for_selected_member_row(self, row, field_code: str, judge_ids):
        try:
            member_id = int(row.get("inscripcio_id"))
            app_id = int(row.get("app_id"))
            ex_idx = int(row.get("exercici"))
        except Exception:
            return ""
        entry = self.notes_by_key.get((member_id, app_id, ex_idx))
        if not entry:
            return ""
        raw = self._value_from_entry(entry, field_code)
        return self._apply_judge_selection(raw, judge_ids)

    def _raw_value_for_selected_team_row(self, row, field_code: str, judge_ids):
        try:
            equip_id = int(row.get("equip_id"))
            app_id = int(row.get("app_id"))
            ex_idx = int(row.get("exercici"))
        except Exception:
            return ""
        entry = self.team_notes_by_key.get((equip_id, app_id, ex_idx))
        if not entry:
            return ""
        raw = self._value_from_entry(entry, field_code)
        return self._apply_judge_selection(raw, judge_ids)

    def _team_member_raw_value(self, raw_value, member_id):
        if not isinstance(raw_value, dict):
            return ""
        return raw_value.get(str(int(member_id)), "")

    def _ordered_member_ids_for_team_entry(self, entry, fallback_member_ids):
        fallback_ids = []
        seen = set()
        for raw_member_id in fallback_member_ids or []:
            member_id = normalize_positive_int(raw_member_id)
            if member_id is None or member_id in seen:
                continue
            seen.add(member_id)
            fallback_ids.append(member_id)
        subject = getattr(entry, "team_subject", None)
        raw_subject_ids = getattr(subject, "member_ids", []) or [] if subject is not None else []
        subject_ids = []
        seen = set()
        normalized_subject_ids = []
        for raw_member_id in raw_subject_ids:
            member_id = normalize_positive_int(raw_member_id)
            normalized_subject_ids.append(member_id)
            if member_id is None or member_id in seen:
                continue
            seen.add(member_id)
            subject_ids.append(member_id)
        subject_ids_consistent = bool(subject_ids) and len(subject_ids) == len(
            [value for value in normalized_subject_ids if value is not None]
        )
        if fallback_ids and (not subject_ids_consistent or any(member_id not in subject_ids for member_id in fallback_ids)):
            return fallback_ids
        if subject_ids_consistent:
            return subject_ids
        return fallback_ids

    def _team_member_slot_for_entry(self, entry, member_id, fallback_member_ids):
        member_pk = normalize_positive_int(member_id)
        if member_pk is None:
            return None
        ordered_member_ids = self._ordered_member_ids_for_team_entry(entry, fallback_member_ids)
        try:
            return ordered_member_ids.index(member_pk) + 1
        except ValueError:
            return None

    def _member_raw_value_from_container(self, container, field_code, member_id):
        if not isinstance(container, dict):
            return None
        member_raw = self._team_member_raw_value(container.get(str(field_code or "").strip()), member_id)
        if member_raw in (None, ""):
            return None
        return member_raw

    def _raw_value_for_team_member_entry(self, entry, field_code: str, judge_ids, member_id, fallback_member_ids):
        member_pk = normalize_positive_int(member_id)
        if entry is None or member_pk is None:
            return ""

        field_code = str(field_code or "").strip()
        inputs = entry.inputs if isinstance(entry.inputs, dict) else {}
        outputs = entry.outputs if isinstance(entry.outputs, dict) else {}

        member_raw = self._member_raw_value_from_container(inputs, field_code, member_pk)
        if member_raw is None:
            member_raw = self._member_raw_value_from_container(outputs, field_code, member_pk)

        slot = self._team_member_slot_for_entry(entry, member_pk, fallback_member_ids)
        if member_raw is None and slot is not None:
            runtime_code = member_runtime_code(field_code, slot)
            if runtime_code in outputs and outputs.get(runtime_code) not in (None, ""):
                member_raw = outputs.get(runtime_code)
            elif runtime_code in inputs and inputs.get(runtime_code) not in (None, ""):
                member_raw = inputs.get(runtime_code)

        if member_raw in (None, ""):
            return ""
        return self._apply_judge_selection(member_raw, judge_ids)

    def _raw_col_value_for_team_row(self, row, col, *, honor_fixed_exercise=False):
        team_mode_value = str(row.get("_team_mode") or "").strip().lower()
        equip_id = row.get("equip_id")
        member_ids = row.get("_member_ids") or []
        src = col.get("source") or {}
        camp = str(src.get("camp") or "total").strip() or "total"
        fixed_exercici = normalize_positive_int(src.get("exercici"))
        jcfg = src.get("jutges") if isinstance(src.get("jutges"), dict) else {}
        jids = jcfg.get("ids") if isinstance(jcfg.get("ids"), list) else []
        try:
            app_id = int(src.get("aparell_id"))
        except Exception:
            return ""

        if team_mode_value == "native_team":
            if equip_id in (None, "", "__sense_equip__"):
                return ""
            comp_aparell = next((item for item in self.aparells if int(item.id) == app_id), None)
            if not comp_aparell or not is_team_context_app(comp_aparell):
                return ""
            if honor_fixed_exercise and fixed_exercici is not None:
                selected_rows = [{"equip_id": int(equip_id), "app_id": int(app_id), "exercici": int(fixed_exercici)}]
            else:
                selected_rows = self.get_main_selected_team_rows_for_field(int(equip_id), camp).get(app_id, [])
            raw_value = self._aggregate_selected_raw_values(
                [self._raw_value_for_selected_team_row(selected_row, camp, jids) for selected_row in selected_rows]
            )
            if raw_value in (None, ""):
                return ""
            if isinstance(raw_value, dict) and raw_value.get("_kind") == "judge_rows":
                return self._build_team_raw_detail(
                    [{"label": row.get("participant") or row.get("nom") or "Equip", "judge_rows": raw_value}]
                )
            return self._build_team_raw_detail(
                [{"label": row.get("participant") or row.get("nom") or "Equip", "value": raw_value}]
            )

        team_cache_key = _derived_team_cache_key(equip_id, member_ids)
        selected_rows_by_app = self.get_main_selected_rows_for_group_field(team_cache_key, member_ids, camp)
        selected_rows = selected_rows_by_app.get(app_id, [])
        rows_by_member = defaultdict(list)
        for selected_row in selected_rows:
            try:
                member_id = int(selected_row.get("inscripcio_id"))
            except Exception:
                continue
            rows_by_member[member_id].append(selected_row)

        detail_rows = []
        for member_id in member_ids:
            member = self.all_ins_by_id.get(member_id)
            if member is None:
                continue
            label = (
                getattr(member, "nom_complet", None)
                or getattr(member, "nom_i_cognoms", None)
                or getattr(member, "nom", None)
                or str(member)
            )
            raw_value = self._aggregate_selected_raw_values(
                [
                    self._raw_value_for_selected_member_row(selected_row, camp, jids)
                    for selected_row in rows_by_member.get(member_id, [])
                ]
            )
            if raw_value in (None, ""):
                continue
            if isinstance(raw_value, dict) and raw_value.get("_kind") == "judge_rows":
                detail_rows.append({"label": label, "judge_rows": raw_value})
            else:
                detail_rows.append({"label": label, "value": raw_value})
        return self._build_team_raw_detail(detail_rows)

    def _builtin_col_value(self, row: dict, key: str):
        if key == "nom":
            key = "participant"
        if key == "participant":
            return row.get("participant") or row.get("nom") or row.get("entitat_nom") or ""
        if key == "punts":
            return row.get("punts", 0.0)
        if key == "posicio":
            return row.get("posicio")
        if key == "entitat_nom":
            return row.get("entitat_nom") or ""
        if key == "participants":
            return row.get("participants", 0)
        return row.get(key)

    def _detail_builtin_value_for_member(self, member, key: str):
        if key == "participant":
            return (
                getattr(member, "nom_complet", None)
                or getattr(member, "nom_i_cognoms", None)
                or getattr(member, "nom", None)
                or str(member)
            )
        if key == "entitat_nom":
            return getattr(getattr(member, "entitat", None), "nom", None) or ""
        return ""

    def _detail_builtin_value_for_row(self, row, key: str):
        if key == "participant":
            return row.get("participant") or row.get("nom") or row.get("entitat_nom") or ""
        if key == "entitat_nom":
            return row.get("entitat_nom") or ""
        return row.get(key) or ""

    def _detail_builtin_value_for_exercise_row(self, row, key: str):
        if key == "exercise_index":
            return row.get("exercise_index")
        if key == "aparell_nom":
            return row.get("aparell_nom") or ""
        if key == "participant":
            return row.get("participant") or ""
        if key == "entitat_nom":
            return row.get("entitat_nom") or ""
        return row.get(key) or ""

    def _detail_type_for_row(self, row: dict):
        team_mode_row = str(row.get("_team_mode") or "").strip().lower()
        if team_mode_row == "derived_from_individual":
            return "derived_team"
        if team_mode_row == "native_team":
            return "native_team"
        if normalize_positive_int(row.get("inscripcio_id")) is not None:
            return "individual"
        if "entitat_nom" in row and (row.get("_member_ids") or []):
            return "entity"
        return ""

    def _comp_aparell_label(self, app_id):
        try:
            app_id = int(app_id)
        except Exception:
            return ""
        comp_aparell = next(
            (item for item in self.aparells if int(getattr(item, "id", 0) or 0) == app_id),
            None,
        )
        if comp_aparell is None:
            return ""
        return getattr(getattr(comp_aparell, "aparell", None), "nom", None) or str(comp_aparell)

    def _comp_aparell_exercise_count(self, app_id):
        try:
            app_id = int(app_id)
        except Exception:
            return 1
        comp_aparell = next(
            (item for item in self.aparells if int(getattr(item, "id", 0) or 0) == app_id),
            None,
        )
        if comp_aparell is None:
            return 1
        try:
            return max(1, int(getattr(comp_aparell, "nombre_exercicis", 1) or 1))
        except Exception:
            return 1

    def _detail_row_id(self, row: dict):
        if row.get("_team_mode"):
            equip_marker = row.get("equip_id")
            if equip_marker in (None, ""):
                equip_marker = "none"
            member_part = "-".join(
                str(int(member_id))
                for member_id in (row.get("_member_ids") or [])
                if normalize_positive_int(member_id)
            )
            return f"team:{equip_marker}:{member_part}"
        if "entitat_nom" in row and (row.get("_member_ids") or []):
            member_part = "-".join(
                str(int(member_id))
                for member_id in (row.get("_member_ids") or [])
                if normalize_positive_int(member_id)
            )
            ent_part = normalized_text_token(row.get("entitat_nom") or "sense-entitat") or "sense-entitat"
            return f"entity:{ent_part}:{member_part}"
        ins_id = normalize_positive_int(row.get("inscripcio_id"))
        return f"row:{ins_id}" if ins_id is not None else ""

    def _ordered_member_ids(self, row):
        return sorted(
            row.get("_member_ids") or [],
            key=lambda raw_member_id: (
                getattr(self.all_ins_by_id.get(normalize_positive_int(raw_member_id) or -1), "ordre_competicio", None)
                or getattr(self.all_ins_by_id.get(normalize_positive_int(raw_member_id) or -1), "ordre_sortida", None)
                or 10**9,
                normalize_positive_int(raw_member_id) or 10**9,
            ),
        )

    def _build_members_list_section(self, row: dict, section: dict):
        items = []
        seen = set()
        for member_id in self._ordered_member_ids(row):
            member_pk = normalize_positive_int(member_id)
            if member_pk is None or member_pk in seen:
                continue
            seen.add(member_pk)
            member = self.all_ins_by_id.get(member_pk)
            if member is None:
                continue
            items.append(
                {
                    "member_id": member_pk,
                    "participant": self._detail_builtin_value_for_member(member, "participant"),
                    "entitat_nom": self._detail_builtin_value_for_member(member, "entitat_nom"),
                }
            )
        if not items:
            return None
        return {"type": "members_list", "label": str(section.get("label") or "Participants"), "items": items}

    def _build_members_table_section(self, row: dict, section: dict):
        detail_rows = []
        detail_columns = section.get("columns") or []
        for member_id in self._ordered_member_ids(row):
            member_pk = normalize_positive_int(member_id)
            if member_pk is None:
                continue
            member = self.all_ins_by_id.get(member_pk)
            if member is None:
                continue

            cells = {}
            for col in detail_columns:
                ctype = str(col.get("type") or "builtin").strip().lower()
                ckey = str(col.get("key") or "").strip()
                if not ckey:
                    continue
                if ctype == "raw":
                    value = self._raw_col_value_for_ins(member_pk, col)
                    if not (isinstance(value, dict) and value.get("_kind") == "judge_rows"):
                        value = self._apply_decimals_if_numeric(value, col.get("decimals"))
                else:
                    value = self._detail_builtin_value_for_member(member, ckey)
                    value = self._apply_decimals_if_numeric(value, col.get("decimals"))
                cells[ckey] = value

            detail_rows.append(
                {
                    "member_id": member_pk,
                    "participant": self._detail_builtin_value_for_member(member, "participant"),
                    "entitat_nom": self._detail_builtin_value_for_member(member, "entitat_nom"),
                    "cells": cells,
                    "display": cells,
                }
            )
        if not detail_rows:
            return None
        return {
            "type": str(section.get("type") or "members_table"),
            "label": str(section.get("label") or "Detall"),
            "aparell_id": normalize_positive_int(section.get("aparell_id")),
            "columns": json_clone_value(detail_columns),
            "rows": detail_rows,
        }

    def _build_team_metrics_section(self, row: dict, section: dict):
        detail_columns = section.get("columns") or []
        cells = {}
        for col in detail_columns:
            ctype = str(col.get("type") or "builtin").strip().lower()
            ckey = str(col.get("key") or "").strip()
            if not ckey:
                continue
            if ctype == "raw":
                value = self._raw_col_value_for_team_row(row, col, honor_fixed_exercise=True)
                value = self._collapse_redundant_native_team_metric_detail(value)
                if not (isinstance(value, dict) and value.get("_kind") == "team_raw_detail"):
                    value = self._apply_decimals_if_numeric(value, col.get("decimals"))
            else:
                value = self._detail_builtin_value_for_row(row, ckey)
                value = self._apply_decimals_if_numeric(value, col.get("decimals"))
            cells[ckey] = value
        if not cells:
            return None
        return {
            "type": "team_metrics",
            "label": str(section.get("label") or "Notes equip"),
            "aparell_id": normalize_positive_int(section.get("aparell_id")),
            "columns": json_clone_value(detail_columns),
            "rows": [
                {
                    "participant": self._detail_builtin_value_for_row(row, "participant"),
                    "entitat_nom": self._detail_builtin_value_for_row(row, "entitat_nom"),
                    "cells": cells,
                    "display": cells,
                }
            ],
        }

    def _build_native_team_members_table_section(self, row: dict, section: dict):
        equip_id = normalize_positive_int(row.get("equip_id"))
        member_ids = row.get("_member_ids") or []
        if equip_id is None or not member_ids:
            return None

        detail_columns = section.get("columns") or []
        detail_rows = []
        team_entries_cache = {}

        def team_entries_for(app_id, exercici):
            cache_key = (int(app_id), normalize_positive_int(exercici) or 0)
            if cache_key in team_entries_cache:
                return team_entries_cache[cache_key]
            if normalize_positive_int(exercici) is not None:
                entry = self.team_notes_by_key.get((equip_id, int(app_id), int(exercici)))
                team_entries_cache[cache_key] = [entry] if entry is not None else []
                return team_entries_cache[cache_key]

            entries = []
            seen = set()
            for selected_row in self.get_main_selected_rows_agg_for_team(equip_id).get(int(app_id), []):
                try:
                    entry_key = (
                        int(selected_row.get("equip_id")),
                        int(selected_row.get("app_id")),
                        int(selected_row.get("exercici")),
                    )
                except Exception:
                    continue
                if entry_key in seen:
                    continue
                seen.add(entry_key)
                entry = self.team_notes_by_key.get(entry_key)
                if entry is not None:
                    entries.append(entry)
            team_entries_cache[cache_key] = entries
            return team_entries_cache[cache_key]

        for member_id in member_ids:
            member_pk = normalize_positive_int(member_id)
            if member_pk is None:
                continue
            member = self.all_ins_by_id.get(member_pk)
            if member is None:
                continue

            cells = {}
            for col in detail_columns:
                ctype = str(col.get("type") or "builtin").strip().lower()
                ckey = str(col.get("key") or "").strip()
                if not ckey:
                    continue
                if ctype == "raw":
                    src = col.get("source") if isinstance(col.get("source"), dict) else {}
                    app_id = normalize_positive_int(src.get("aparell_id"))
                    exercise_mode = str(src.get("exercise_mode") or "").strip().lower()
                    exercici = normalize_positive_int(src.get("exercici")) if exercise_mode == "fixed" else None
                    camp = str(src.get("camp") or "").strip()
                    jcfg = src.get("jutges") if isinstance(src.get("jutges"), dict) else {}
                    jids = jcfg.get("ids") if isinstance(jcfg.get("ids"), list) else []
                    if app_id is None or not camp:
                        value = ""
                    else:
                        value = self._aggregate_selected_raw_values(
                            [
                                self._raw_value_for_team_member_entry(entry, camp, jids, member_pk, member_ids)
                                for entry in team_entries_for(app_id, exercici)
                            ]
                        )
                    if not (isinstance(value, dict) and value.get("_kind") == "judge_rows"):
                        value = self._apply_decimals_if_numeric(value, col.get("decimals"))
                else:
                    value = self._detail_builtin_value_for_member(member, ckey)
                    value = self._apply_decimals_if_numeric(value, col.get("decimals"))
                cells[ckey] = value

            detail_rows.append(
                {
                    "member_id": member_pk,
                    "participant": self._detail_builtin_value_for_member(member, "participant"),
                    "entitat_nom": self._detail_builtin_value_for_member(member, "entitat_nom"),
                    "cells": cells,
                    "display": cells,
                }
            )
        if not detail_rows:
            return None
        return {
            "type": "team_members_table",
            "label": str(section.get("label") or "Notes per membre"),
            "aparell_id": normalize_positive_int(section.get("aparell_id")),
            "columns": json_clone_value(detail_columns),
            "rows": detail_rows,
        }

    def _build_exercise_table_section(self, row: dict, section: dict):
        ins_id = normalize_positive_int(row.get("inscripcio_id"))
        if ins_id is None:
            return None
        detail_columns = section.get("columns") or []
        section_app_id = normalize_positive_int(section.get("aparell_id"))
        row_defs = []
        seen_defs = set()
        for col in detail_columns:
            if str(col.get("type") or "").strip().lower() != "raw":
                continue
            src = col.get("source") if isinstance(col.get("source"), dict) else {}
            app_id = normalize_positive_int(src.get("aparell_id"))
            ex_idx = normalize_positive_int(src.get("exercici")) or 1
            if app_id is None:
                continue
            key = (app_id, ex_idx)
            if key in seen_defs:
                continue
            seen_defs.add(key)
            row_defs.append(key)
        if not row_defs and section_app_id is not None:
            for ex_idx in range(1, self._comp_aparell_exercise_count(section_app_id) + 1):
                row_defs.append((section_app_id, ex_idx))
        if not row_defs:
            return None

        rows_out = []
        for app_id, ex_idx in row_defs:
            cells = {}
            for col in detail_columns:
                ctype = str(col.get("type") or "builtin").strip().lower()
                ckey = str(col.get("key") or "").strip()
                if not ckey:
                    continue
                if ctype == "raw":
                    src = col.get("source") if isinstance(col.get("source"), dict) else {}
                    if normalize_positive_int(src.get("aparell_id")) != app_id:
                        cells[ckey] = ""
                        continue
                    if (normalize_positive_int(src.get("exercici")) or 1) != ex_idx:
                        cells[ckey] = ""
                        continue
                    value = self._raw_col_value_for_ins(ins_id, col)
                    if not (isinstance(value, dict) and value.get("_kind") == "judge_rows"):
                        value = self._apply_decimals_if_numeric(value, col.get("decimals"))
                else:
                    value = self._detail_builtin_value_for_exercise_row(
                        {
                            "exercise_index": ex_idx,
                            "aparell_nom": self._comp_aparell_label(app_id),
                            "participant": self._detail_builtin_value_for_row(row, "participant"),
                            "entitat_nom": self._detail_builtin_value_for_row(row, "entitat_nom"),
                        },
                        ckey,
                    )
                    value = self._apply_decimals_if_numeric(value, col.get("decimals"))
                cells[ckey] = value
            rows_out.append(
                {
                    "app_id": app_id,
                    "exercise_index": ex_idx,
                    "aparell_nom": self._comp_aparell_label(app_id),
                    "participant": self._detail_builtin_value_for_row(row, "participant"),
                    "entitat_nom": self._detail_builtin_value_for_row(row, "entitat_nom"),
                    "cells": cells,
                    "display": cells,
                }
            )
        if not rows_out:
            return None
        return {
            "type": "exercise_table",
            "label": str(section.get("label") or "Exercicis"),
            "aparell_id": section_app_id,
            "columns": json_clone_value(detail_columns),
            "rows": rows_out,
        }

    def _build_detail_payload(self, row: dict):
        if not self.detail_enabled:
            return None
        sections = []
        detail_type = self._detail_type_for_row(row)
        for section in self.detail_config.get("sections") or []:
            stype = str(section.get("type") or "").strip().lower()
            section_payload = None
            if stype == "members_list" and detail_type in ("derived_team", "native_team"):
                section_payload = self._build_members_list_section(row, section)
            elif stype == "members_table" and detail_type == "derived_team":
                section_payload = self._build_members_table_section(row, section)
            elif stype == "team_members_table" and detail_type == "native_team":
                section_payload = self._build_native_team_members_table_section(row, section)
            elif stype == "entity_members_table" and detail_type == "entity":
                section_payload = self._build_members_table_section(row, section)
            elif stype == "team_metrics" and detail_type == "native_team":
                section_payload = self._build_team_metrics_section(row, section)
            elif stype == "exercise_table" and detail_type == "individual":
                section_payload = self._build_exercise_table_section(row, section)
            if section_payload is not None:
                sections.append(section_payload)
        if not sections:
            return None
        return {
            "default_open": bool(self.detail_config.get("default_open", False)),
            "sections_layout": "stacked" if str(self.detail_config.get("sections_layout") or "").strip().lower() == "stacked" else "tabs",
            "sections": sections,
        }

    def attach_display_cells(self, rows, *, entity_mode=False):
        for row in rows:
            cells = {}
            member_ids = row.get("_member_ids") or []
            for col in self.display_columns:
                ctype = col.get("type")
                ckey = col.get("key")
                if not ckey:
                    continue

                if ctype == "raw":
                    if entity_mode:
                        if row.get("_team_mode"):
                            value = self._raw_col_value_for_team_row(row, col)
                        elif len(member_ids) == 1:
                            value = self._raw_col_value_for_ins(member_ids[0], col)
                        else:
                            value = ""
                    else:
                        value = self._raw_col_value_for_ins(row.get("inscripcio_id"), col)
                    if not (isinstance(value, dict) and value.get("_kind") == "team_raw_detail"):
                        value = self._apply_decimals_if_numeric(value, col.get("decimals"))
                else:
                    value = self._builtin_col_value(row, ckey)
                    value = self._apply_decimals_if_numeric(value, col.get("decimals"))

                cells[ckey] = value

            row["cells"] = cells
            row["display"] = cells
            row["row_id"] = self._detail_row_id(row)
            detail_payload = self._build_detail_payload(row)
            if detail_payload is not None:
                row["detail"] = detail_payload
            else:
                row.pop("detail", None)
            row.pop("_member_ids", None)
            row.pop("_team_mode", None)
        return rows


def build_detail_runtime(**kwargs):
    return DetailPayloadRuntime(**kwargs)


__all__ = [
    "DETAIL_DISPLAY_BUILTIN_KEYS",
    "DETAIL_EXERCISE_BUILTIN_KEYS",
    "DETAIL_SECTION_TYPES",
    "DISPLAY_BUILTIN_KEYS",
    "DetailPayloadRuntime",
    "build_detail_runtime",
    "get_detail_display_config",
    "get_display_columns",
]
