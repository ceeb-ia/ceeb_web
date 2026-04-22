from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

from ..provenance import clone_row, resolve_main_selected_contributors
from .score_values import _apply_simple_agg, _to_float
from .selection import (
    _normalize_candidate_source_cfg,
    _normalize_candidate_source_mode,
    _normalize_exercicis_cfg,
    _normalize_field_mode,
    _normalize_optional_agg,
    _normalize_participants_cfg,
    _pick_exercicis_rows,
)


EXERCISE_SELECTION_SCOPE_PER_MEMBER = "per_member"
EXERCISE_SELECTION_SCOPE_TEAM_POOL = "team_pool"
EXERCISE_SELECTION_SCOPE_INHERIT = "hereta"
ALLOWED_AGGREGATIONS = {"sum", "avg", "median", "max", "min"}


def _normalize_positive_int(value):
    try:
        num = int(value)
    except Exception:
        return None
    return num if num > 0 else None


def _unique_nonempty_strings(raw_values):
    if isinstance(raw_values, str):
        items = [item.strip() for item in raw_values.split(",")]
    elif isinstance(raw_values, (list, tuple)):
        items = [str(item or "").strip() for item in raw_values]
    else:
        items = []

    out = []
    seen = set()
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _lookup_app_cfg_value(mapping, app_id: int):
    if not isinstance(mapping, Mapping):
        return None
    value = mapping.get(str(app_id))
    if value is None:
        value = mapping.get(app_id)
    return value


def _normalize_agg(raw_value, fallback="sum"):
    agg = str(raw_value or fallback or "sum").strip().lower()
    if agg not in ALLOWED_AGGREGATIONS:
        agg = str(fallback or "sum").strip().lower()
    if agg not in ALLOWED_AGGREGATIONS:
        agg = "sum"
    return agg


def _is_team_context_app(comp_aparell) -> bool:
    return bool(comp_aparell and getattr(comp_aparell, "is_team_competition_unit", False))


def _dedupe_int_ids_preserve_order(raw_ids):
    out = []
    seen = set()
    for raw_id in raw_ids or []:
        resolved = _normalize_positive_int(raw_id)
        if resolved is None or resolved in seen:
            continue
        seen.add(resolved)
        out.append(resolved)
    return out


class SelectionRuntime:
    def __init__(
        self,
        *,
        aparells: Iterable[Any] | None = None,
        tipus: str = "individual",
        team_mode: str = "",
        legacy_camp: str = "total",
        agg_camps: str = "sum",
        camps_per_aparell: Mapping[Any, Any] | None = None,
        camps_mode_per_aparell: Mapping[Any, Any] | None = None,
        camps_per_exercici_per_aparell: Mapping[Any, Any] | None = None,
        agregacio_camps_per_aparell: Mapping[Any, Any] | None = None,
        agregacio_camps_per_exercici_per_aparell: Mapping[Any, Any] | None = None,
        mode_seleccio_exercicis: str = "per_aparell_global",
        base_ex_cfg: Mapping[str, Any] | None = None,
        exercicis_per_aparell: Mapping[Any, Any] | None = None,
        agg_exercicis: str = "sum",
        agregacio_exercicis_per_aparell: Mapping[Any, Any] | None = None,
        candidate_source_mode: str = "raw_exercise",
        candidate_source_cfg: Mapping[str, Any] | None = None,
        candidate_source_per_aparell: Mapping[Any, Any] | None = None,
        participants_per_aparell: Mapping[Any, Any] | None = None,
        agregacio_participants_per_aparell: Mapping[Any, Any] | None = None,
        exercise_selection_scope: str = EXERCISE_SELECTION_SCOPE_PER_MEMBER,
        allow_candidate_source: bool | None = None,
        allow_main_participant_selection_step: bool | None = None,
        app_ex_rows_by_ins: Mapping[Any, Mapping[Any, list[dict[str, Any]]]] | None = None,
        team_app_ex_rows_by_equip: Mapping[Any, Mapping[Any, list[dict[str, Any]]]] | None = None,
    ):
        self.aparells = list(aparells or [])
        self.tipus = str(tipus or "individual").strip().lower()
        self.team_mode = str(team_mode or "").strip().lower()
        self.legacy_camp = str(legacy_camp or "total").strip() or "total"
        self.agg_camps = _normalize_agg(agg_camps, "sum")
        self.camps_per_aparell = dict(camps_per_aparell or {})
        self.camps_mode_per_aparell = dict(camps_mode_per_aparell or {})
        self.camps_per_exercici_per_aparell = dict(camps_per_exercici_per_aparell or {})
        self.agregacio_camps_per_aparell = dict(agregacio_camps_per_aparell or {})
        self.agregacio_camps_per_exercici_per_aparell = dict(
            agregacio_camps_per_exercici_per_aparell or {}
        )
        self.mode_seleccio_exercicis = str(mode_seleccio_exercicis or "per_aparell_global").strip().lower()
        self.base_ex_cfg = _normalize_exercicis_cfg(base_ex_cfg or {})
        self.exercicis_per_aparell = dict(exercicis_per_aparell or {})
        self.agg_exercicis = _normalize_agg(agg_exercicis, "sum")
        self.agregacio_exercicis_per_aparell = dict(agregacio_exercicis_per_aparell or {})
        self.candidate_source_mode = _normalize_candidate_source_mode(candidate_source_mode)
        self.candidate_source_cfg = _normalize_candidate_source_cfg(candidate_source_cfg or {})
        self.candidate_source_per_aparell = dict(candidate_source_per_aparell or {})
        self.participants_per_aparell = dict(participants_per_aparell or {})
        self.agregacio_participants_per_aparell = dict(agregacio_participants_per_aparell or {})
        self.exercise_selection_scope = self._normalize_exercise_selection_scope(exercise_selection_scope)
        self.allow_candidate_source = (
            bool(allow_candidate_source)
            if allow_candidate_source is not None
            else (
                self.tipus == "individual"
                or (self.tipus == "equips" and self.team_mode in {"derived_from_individual", "native_team"})
            )
        )
        self.allow_main_participant_selection_step = (
            bool(allow_main_participant_selection_step)
            if allow_main_participant_selection_step is not None
            else (
                self.tipus == "equips"
                and self.team_mode == "derived_from_individual"
                and self.exercise_selection_scope == EXERCISE_SELECTION_SCOPE_PER_MEMBER
                and self.mode_seleccio_exercicis != "global_pool"
            )
        )
        if not self.allow_candidate_source:
            self.candidate_source_mode = "raw_exercise"

        self.app_ex_rows_by_ins = {
            int(app_id): {int(subject_id): list(rows or []) for subject_id, rows in (rows_by_subject or {}).items()}
            for app_id, rows_by_subject in (app_ex_rows_by_ins or {}).items()
            if _normalize_positive_int(app_id) is not None
        }
        self.team_app_ex_rows_by_equip = {
            int(app_id): {int(subject_id): list(rows or []) for subject_id, rows in (rows_by_subject or {}).items()}
            for app_id, rows_by_subject in (team_app_ex_rows_by_equip or {}).items()
            if _normalize_positive_int(app_id) is not None
        }
        self.app_order = {}
        self.aparell_by_id = {}
        for idx, comp_aparell in enumerate(self.aparells, start=1):
            app_id = _normalize_positive_int(getattr(comp_aparell, "id", None))
            if app_id is None or app_id in self.app_order:
                continue
            self.app_order[app_id] = idx
            self.aparell_by_id[app_id] = comp_aparell

        self.selected_rows_agg_cache = {}
        self.selected_rows_field_cache = {}
        self.selected_team_rows_agg_cache = {}
        self.selected_team_rows_field_cache = {}
        self.main_selected_team_rows_agg_cache = {}
        self.main_selected_team_rows_field_cache = {}
        self.main_selected_rows_for_group_cache = {}
        self.main_selected_rows_for_group_field_cache = {}
        self.derived_team_selected_rows_agg_cache = {}
        self.derived_team_selected_rows_field_cache = {}

    @staticmethod
    def _normalize_exercise_selection_scope(raw_scope):
        scope = str(raw_scope or "").strip().lower()
        if scope == EXERCISE_SELECTION_SCOPE_TEAM_POOL:
            return EXERCISE_SELECTION_SCOPE_TEAM_POOL
        return EXERCISE_SELECTION_SCOPE_PER_MEMBER

    def _ordered_app_ids(self, *, team_context: bool | None = None, include_extra_ids: Iterable[Any] | None = None):
        out = []
        seen = set()
        for comp_aparell in self.aparells:
            app_id = _normalize_positive_int(getattr(comp_aparell, "id", None))
            if app_id is None or app_id in seen:
                continue
            if team_context is True and not _is_team_context_app(comp_aparell):
                continue
            if team_context is False and _is_team_context_app(comp_aparell):
                continue
            seen.add(app_id)
            out.append(app_id)
        for raw_app_id in include_extra_ids or []:
            app_id = _normalize_positive_int(raw_app_id)
            if app_id is None or app_id in seen:
                continue
            seen.add(app_id)
            out.append(app_id)
        return out

    def resolve_agregacio_camps_for_app(self, app_id: int):
        raw = _lookup_app_cfg_value(self.agregacio_camps_per_aparell, app_id)
        return _normalize_agg(raw, self.agg_camps)

    def resolve_camps_mode_for_app(self, app_id: int):
        raw = _lookup_app_cfg_value(self.camps_mode_per_aparell, app_id)
        return _normalize_field_mode(raw)

    def resolve_candidate_source_for_app(self, app_id: int):
        fallback_mode = self.candidate_source_mode
        fallback_cfg = dict(self.candidate_source_cfg)
        if not self.allow_candidate_source:
            return "raw_exercise", fallback_cfg

        raw = _lookup_app_cfg_value(self.candidate_source_per_aparell, app_id)
        entry = dict(raw) if isinstance(raw, Mapping) else {}
        mode = _normalize_candidate_source_mode(entry.get("mode") or fallback_mode)
        if self.tipus == "equips" and self.team_mode == "native_team":
            if mode != "team_aggregate":
                return "raw_exercise", fallback_cfg
        elif mode != "participant_aggregate":
            return "raw_exercise", fallback_cfg

        cfg = _normalize_candidate_source_cfg(entry.get("cfg"), fallback=fallback_cfg)
        return mode, cfg

    def resolve_agregacio_exercicis_for_app(self, app_id: int):
        raw = _lookup_app_cfg_value(self.agregacio_exercicis_per_aparell, app_id)
        return _normalize_agg(raw, self.agg_exercicis)

    def resolve_participants_for_app(self, app_id: int):
        raw = _lookup_app_cfg_value(self.participants_per_aparell, app_id)
        cfg = _normalize_participants_cfg(raw if isinstance(raw, Mapping) else {})
        if not cfg:
            cfg = {"mode": "tots"}
        raw_agg = _lookup_app_cfg_value(self.agregacio_participants_per_aparell, app_id)
        return cfg, _normalize_agg(raw_agg, "sum")

    def _score_camps_for_app(self, app_id: int, *, include_per_exercise=False):
        raw = _lookup_app_cfg_value(self.camps_per_aparell, app_id)
        out = _unique_nonempty_strings(raw)
        if not out:
            out = [self.legacy_camp] if self.legacy_camp else ["total"]

        if include_per_exercise and self.resolve_camps_mode_for_app(app_id) == "per_exercici":
            raw_map = _lookup_app_cfg_value(self.camps_per_exercici_per_aparell, app_id)
            for raw_fields in (raw_map.values() if isinstance(raw_map, Mapping) else []):
                for code in _unique_nonempty_strings(raw_fields):
                    if code not in out:
                        out.append(code)
        return out

    def resolve_score_fields_for_app_exercise(self, app_id: int, ex_idx: int):
        common_fields = list(self._score_camps_for_app(app_id))
        common_agg = self.resolve_agregacio_camps_for_app(app_id)
        if self.resolve_camps_mode_for_app(app_id) != "per_exercici":
            return common_fields, common_agg

        raw_fields_by_ex = _lookup_app_cfg_value(self.camps_per_exercici_per_aparell, app_id)
        raw_agg_by_ex = _lookup_app_cfg_value(self.agregacio_camps_per_exercici_per_aparell, app_id)
        try:
            ex_key = str(max(1, int(ex_idx or 1)))
        except Exception:
            ex_key = "1"
        ex_fields = _unique_nonempty_strings(
            (raw_fields_by_ex or {}).get(ex_key) if isinstance(raw_fields_by_ex, Mapping) else []
        )
        ex_agg = _normalize_optional_agg(
            (raw_agg_by_ex or {}).get(ex_key) if isinstance(raw_agg_by_ex, Mapping) else None
        )
        if not ex_fields or not ex_agg:
            return common_fields, common_agg
        return ex_fields, ex_agg

    def _resolve_ex_cfg_for_app(self, app_id: int):
        if self.mode_seleccio_exercicis != "per_aparell_override":
            return dict(self.base_ex_cfg)
        raw = _lookup_app_cfg_value(self.exercicis_per_aparell, app_id)
        return _normalize_exercicis_cfg(raw, fallback=self.base_ex_cfg)

    def _normalized_source_row(self, row):
        source = row or {}
        return {
            "idx": int(source.get("idx", 0) or 0),
            "app_id": int(source.get("app_id", 0) or 0),
            "app_order": int(source.get("app_order", 0) or 0),
            "exercici": int(source.get("exercici", 1) or 1),
            "inscripcio_id": _normalize_positive_int(source.get("inscripcio_id")),
            "equip_id": _normalize_positive_int(source.get("equip_id")),
            "value": _to_float(source.get("value")),
            "by_camp": dict(source.get("by_camp") or {}),
        }

    def _copy_ex_row_with_value(self, row, value):
        item = dict(row or {})
        item["value"] = _to_float(value)
        item["by_camp"] = dict((row or {}).get("by_camp") or {})
        raw_sources = (row or {}).get("source_rows")
        if isinstance(raw_sources, list) and raw_sources:
            item["source_rows"] = [
                self._normalized_source_row(src)
                for src in raw_sources
                if isinstance(src, Mapping)
            ]
        elif isinstance(row, Mapping):
            item["source_rows"] = [self._normalized_source_row(row)]
        return item

    def copy_ex_row_with_value(self, row, value):
        return self._copy_ex_row_with_value(row, value)

    def _merge_source_rows(self, rows):
        merged = []
        seen = set()
        for row in rows or []:
            if not isinstance(row, Mapping):
                continue
            source_rows = row.get("source_rows")
            if not isinstance(source_rows, list) or not source_rows:
                source_rows = [self._copy_ex_row_with_value(row, row.get("value"))]
            for src in source_rows:
                if not isinstance(src, Mapping):
                    continue
                key = (
                    _normalize_positive_int(src.get("inscripcio_id")),
                    _normalize_positive_int(src.get("equip_id")),
                    _normalize_positive_int(src.get("app_id")),
                    _normalize_positive_int(src.get("exercici")),
                )
                if key in seen:
                    continue
                seen.add(key)
                merged.append(self._copy_ex_row_with_value(src, src.get("value")))
        return sorted(
            merged,
            key=lambda src: (
                _normalize_positive_int(src.get("app_order")) or _normalize_positive_int(src.get("app_id")) or 0,
                _normalize_positive_int(src.get("exercici")) or 0,
                _normalize_positive_int(src.get("inscripcio_id")) or 0,
                _normalize_positive_int(src.get("equip_id")) or 0,
            ),
        )

    def _build_candidate_rows_from_source_rows(self, rows_ex, app_id: int, *, participant_key="inscripcio_id"):
        base_rows = [
            self._copy_ex_row_with_value(row, row.get("value"))
            for row in (rows_ex or [])
            if isinstance(row, Mapping)
        ]
        source_mode, source_cfg = self.resolve_candidate_source_for_app(app_id)
        if source_mode not in {"participant_aggregate", "team_aggregate"}:
            return base_rows
        if not base_rows:
            return []

        picked_rows = _pick_exercicis_rows(
            base_rows,
            source_cfg["mode"],
            source_cfg["best_n"],
            index=source_cfg["index"],
            ids=source_cfg["ids"],
            max_per_participant=0,
            participant_key=participant_key,
        )
        if not picked_rows:
            return []

        agg_value = _apply_simple_agg(
            [_to_float(row.get("value")) for row in picked_rows],
            source_cfg["agregacio_exercicis"],
        )
        field_codes = []
        seen_field_codes = set()
        for row in picked_rows:
            for code in dict((row or {}).get("by_camp") or {}).keys():
                code_str = str(code or "").strip()
                if not code_str or code_str in seen_field_codes:
                    continue
                seen_field_codes.add(code_str)
                field_codes.append(code_str)

        by_camp = {}
        for code in field_codes:
            by_camp[code] = _apply_simple_agg(
                [_to_float(dict((row or {}).get("by_camp") or {}).get(code)) for row in picked_rows],
                source_cfg["agregacio_exercicis"],
            )

        first_row = picked_rows[0]
        candidate_row = self._copy_ex_row_with_value(first_row, agg_value)
        candidate_row["idx"] = int(first_row.get("idx", 1) or 1)
        candidate_row["exercici"] = int(first_row.get("exercici", 1) or 1)
        candidate_row["by_camp"] = by_camp
        candidate_row["candidate_source_mode"] = source_mode
        candidate_row["candidate_source_count"] = len(picked_rows)
        candidate_row["source_rows"] = self._merge_source_rows(picked_rows)
        return [candidate_row]

    def _pick_selected_rows_from_rows_by_app(self, rows_by_app, *, participant_key):
        picked_by_app = defaultdict(list)
        app_ids = self._ordered_app_ids(include_extra_ids=(rows_by_app or {}).keys())
        if self.mode_seleccio_exercicis == "global_pool":
            pool_rows = []
            for app_id in app_ids:
                for row in (rows_by_app or {}).get(app_id, []):
                    item = self._copy_ex_row_with_value(row, row.get("value"))
                    item["idx"] = 0
                    pool_rows.append(item)
            if pool_rows:
                pool_rows = sorted(
                    pool_rows,
                    key=lambda row: (row.get("app_order", 0), row.get("exercici", 0), row.get("app_id", 0)),
                )
                for idx, row in enumerate(pool_rows, start=1):
                    row["idx"] = idx
                picked_rows = _pick_exercicis_rows(
                    pool_rows,
                    self.base_ex_cfg["mode"],
                    self.base_ex_cfg["best_n"],
                    index=self.base_ex_cfg["index"],
                    ids=self.base_ex_cfg["ids"],
                    max_per_participant=self.base_ex_cfg.get("max_per_participant", 0),
                    participant_key=participant_key,
                )
                for row in picked_rows:
                    app_id = _normalize_positive_int(row.get("app_id"))
                    if app_id is None:
                        continue
                    picked_by_app[app_id].append(self._copy_ex_row_with_value(row, row.get("value")))
            return dict(picked_by_app)

        for app_id in app_ids:
            rows = (rows_by_app or {}).get(app_id, [])
            ex_cfg = self._resolve_ex_cfg_for_app(app_id)
            picked = _pick_exercicis_rows(
                rows,
                ex_cfg["mode"],
                ex_cfg["best_n"],
                index=ex_cfg["index"],
                ids=ex_cfg["ids"],
                max_per_participant=ex_cfg.get("max_per_participant", 0),
                participant_key=participant_key,
            )
            picked_by_app[app_id] = [
                self._copy_ex_row_with_value(row, row.get("value"))
                for row in picked
            ]
        return dict(picked_by_app)

    def _individual_rows_for_field(self, ins_id: int, app_id: int, field_code: str):
        rows = []
        for row in ((self.app_ex_rows_by_ins.get(int(app_id)) or {}).get(int(ins_id)) or []):
            rows.append(self._copy_ex_row_with_value(row, ((row.get("by_camp") or {}).get(field_code))))
        return rows

    def _team_rows_for_field(self, equip_id: int, app_id: int, field_code: str):
        rows = []
        for row in ((self.team_app_ex_rows_by_equip.get(int(app_id)) or {}).get(int(equip_id)) or []):
            rows.append(self._copy_ex_row_with_value(row, ((row.get("by_camp") or {}).get(field_code))))
        return rows

    def _get_selected_rows_agg_for_ins(self, ins_id: int):
        ins_id = _normalize_positive_int(ins_id)
        if ins_id is None:
            return {}
        if ins_id in self.selected_rows_agg_cache:
            return self.selected_rows_agg_cache[ins_id]

        rows_by_app = {}
        for app_id in self._ordered_app_ids():
            rows_by_app[app_id] = self._build_candidate_rows_from_source_rows(
                ((self.app_ex_rows_by_ins.get(app_id) or {}).get(ins_id)) or [],
                app_id,
                participant_key="inscripcio_id",
            )
        self.selected_rows_agg_cache[ins_id] = self._pick_selected_rows_from_rows_by_app(
            rows_by_app,
            participant_key="inscripcio_id",
        )
        return self.selected_rows_agg_cache[ins_id]

    def get_selected_rows_agg_for_ins(self, ins_id: int):
        return self._get_selected_rows_agg_for_ins(ins_id)

    def _get_selected_rows_agg_for_team(self, equip_id: int):
        equip_id = _normalize_positive_int(equip_id)
        if equip_id is None:
            return {}
        if equip_id in self.selected_team_rows_agg_cache:
            return self.selected_team_rows_agg_cache[equip_id]

        rows_by_app = {}
        for app_id in self._ordered_app_ids(team_context=True):
            rows_by_app[app_id] = list(
                (((self.team_app_ex_rows_by_equip.get(app_id) or {}).get(equip_id)) or [])
            )
        self.selected_team_rows_agg_cache[equip_id] = self._pick_selected_rows_from_rows_by_app(
            rows_by_app,
            participant_key="equip_id",
        )
        return self.selected_team_rows_agg_cache[equip_id]

    def get_selected_rows_agg_for_team(self, equip_id: int):
        return self._get_selected_rows_agg_for_team(equip_id)

    def _get_selected_rows_for_field(self, ins_id: int, field_code: str):
        cache_key = (_normalize_positive_int(ins_id), str(field_code or ""))
        if cache_key in self.selected_rows_field_cache:
            return self.selected_rows_field_cache[cache_key]

        rows_by_app = {}
        for app_id in self._ordered_app_ids():
            rows_by_app[app_id] = self._build_candidate_rows_from_source_rows(
                self._individual_rows_for_field(cache_key[0], app_id, cache_key[1]),
                app_id,
                participant_key="inscripcio_id",
            )
        self.selected_rows_field_cache[cache_key] = self._pick_selected_rows_from_rows_by_app(
            rows_by_app,
            participant_key="inscripcio_id",
        )
        return self.selected_rows_field_cache[cache_key]

    def get_selected_rows_for_field(self, ins_id: int, field_code: str):
        return self._get_selected_rows_for_field(ins_id, field_code)

    def _get_selected_team_rows_for_field(self, equip_id: int, field_code: str):
        cache_key = (_normalize_positive_int(equip_id), str(field_code or ""))
        if cache_key in self.selected_team_rows_field_cache:
            return self.selected_team_rows_field_cache[cache_key]

        rows_by_app = {}
        for app_id in self._ordered_app_ids(team_context=True):
            rows_by_app[app_id] = self._team_rows_for_field(cache_key[0], app_id, cache_key[1])
        self.selected_team_rows_field_cache[cache_key] = self._pick_selected_rows_from_rows_by_app(
            rows_by_app,
            participant_key="equip_id",
        )
        return self.selected_team_rows_field_cache[cache_key]

    def get_selected_team_rows_for_field(self, equip_id: int, field_code: str):
        return self._get_selected_team_rows_for_field(equip_id, field_code)

    def _get_main_selected_rows_agg_for_team(self, equip_id: int):
        equip_id = _normalize_positive_int(equip_id)
        if equip_id is None:
            return {}
        if equip_id in self.main_selected_team_rows_agg_cache:
            return self.main_selected_team_rows_agg_cache[equip_id]

        rows_by_app = {}
        for app_id in self._ordered_app_ids(team_context=True):
            rows_by_app[app_id] = self._build_candidate_rows_from_source_rows(
                (((self.team_app_ex_rows_by_equip.get(app_id) or {}).get(equip_id)) or []),
                app_id,
                participant_key="equip_id",
            )
        self.main_selected_team_rows_agg_cache[equip_id] = self._pick_selected_rows_from_rows_by_app(
            rows_by_app,
            participant_key="equip_id",
        )
        return self.main_selected_team_rows_agg_cache[equip_id]

    def get_main_selected_rows_agg_for_team(self, equip_id: int):
        return self._get_main_selected_rows_agg_for_team(equip_id)

    def _get_main_selected_team_rows_for_field(self, equip_id: int, field_code: str):
        cache_key = (_normalize_positive_int(equip_id), str(field_code or ""))
        if cache_key in self.main_selected_team_rows_field_cache:
            return self.main_selected_team_rows_field_cache[cache_key]

        rows_by_app = {}
        for app_id in self._ordered_app_ids(team_context=True):
            rows_by_app[app_id] = self._build_candidate_rows_from_source_rows(
                self._team_rows_for_field(cache_key[0], app_id, cache_key[1]),
                app_id,
                participant_key="equip_id",
            )
        self.main_selected_team_rows_field_cache[cache_key] = self._pick_selected_rows_from_rows_by_app(
            rows_by_app,
            participant_key="equip_id",
        )
        return self.main_selected_team_rows_field_cache[cache_key]

    def get_main_selected_team_rows_for_field(self, equip_id: int, field_code: str):
        return self._get_main_selected_team_rows_for_field(equip_id, field_code)

    def _derived_team_cache_key(self, equip_id=None, member_ids=None):
        if equip_id not in (None, "", "__sense_equip__"):
            try:
                return f"equip:{int(equip_id)}"
            except Exception:
                pass
        mids = sorted(set(_dedupe_int_ids_preserve_order(member_ids or [])))
        return f"members:{','.join(str(member_id) for member_id in mids)}"

    def _build_derived_team_rows_for_app(self, member_ids, app_id: int, *, field_code=None):
        rows = []
        for member_id in _dedupe_int_ids_preserve_order(member_ids):
            member_rows = ((self.app_ex_rows_by_ins.get(int(app_id)) or {}).get(member_id)) or []
            source_rows = []
            for base_row in member_rows:
                value = (
                    ((base_row.get("by_camp") or {}).get(field_code))
                    if field_code is not None
                    else base_row.get("value")
                )
                source_rows.append(self._copy_ex_row_with_value(base_row, value))
            for item in self._build_candidate_rows_from_source_rows(
                source_rows,
                app_id,
                participant_key="inscripcio_id",
            ):
                item["inscripcio_id"] = member_id
                rows.append(item)
        return rows

    def _resolve_group_call_args(self, team_cache_key, member_ids):
        if member_ids is None:
            member_ids = team_cache_key
            team_cache_key = self._derived_team_cache_key(None, member_ids)
        mids = _dedupe_int_ids_preserve_order(member_ids or [])
        return str(team_cache_key or self._derived_team_cache_key(None, mids)), mids

    def _get_selected_rows_agg_for_derived_team(self, team_cache_key, member_ids=None):
        cache_key, mids = self._resolve_group_call_args(team_cache_key, member_ids)
        if cache_key in self.derived_team_selected_rows_agg_cache:
            return self.derived_team_selected_rows_agg_cache[cache_key]

        rows_by_app = {}
        for app_id in self._ordered_app_ids(team_context=False):
            rows_by_app[app_id] = self._build_derived_team_rows_for_app(mids, app_id)
        self.derived_team_selected_rows_agg_cache[cache_key] = self._pick_selected_rows_from_rows_by_app(
            rows_by_app,
            participant_key="inscripcio_id",
        )
        return self.derived_team_selected_rows_agg_cache[cache_key]

    def get_selected_rows_agg_for_derived_team(self, team_cache_key, member_ids=None):
        return self._get_selected_rows_agg_for_derived_team(team_cache_key, member_ids)

    def _get_main_selected_rows_for_group(self, team_cache_key, member_ids=None):
        cache_key, mids = self._resolve_group_call_args(team_cache_key, member_ids)
        if cache_key in self.main_selected_rows_for_group_cache:
            return self.main_selected_rows_for_group_cache[cache_key]
        if not mids:
            return {}

        if self.exercise_selection_scope == EXERCISE_SELECTION_SCOPE_TEAM_POOL:
            rows = self._get_selected_rows_agg_for_derived_team(cache_key, mids)
            self.main_selected_rows_for_group_cache[cache_key] = rows
            return rows

        picked_by_app = defaultdict(list)
        for member_id in mids:
            for app_id, rows in (self._get_selected_rows_agg_for_ins(member_id) or {}).items():
                app_id_int = _normalize_positive_int(app_id)
                if app_id_int is None:
                    continue
                for row in rows or []:
                    item = self._copy_ex_row_with_value(row, row.get("value"))
                    item["inscripcio_id"] = member_id
                    picked_by_app[app_id_int].append(item)

        for app_id, rows in list(picked_by_app.items()):
            picked_by_app[app_id] = sorted(
                rows,
                key=lambda row: (
                    row.get("app_order", 0),
                    row.get("exercici", 0),
                    row.get("app_id", 0),
                    row.get("inscripcio_id", 0),
                ),
            )

        self.main_selected_rows_for_group_cache[cache_key] = dict(picked_by_app)
        return self.main_selected_rows_for_group_cache[cache_key]

    def get_main_selected_rows_for_group(self, team_cache_key, member_ids=None):
        return self._get_main_selected_rows_for_group(team_cache_key, member_ids)

    def _contributors_by_app_from_selected_rows(self, selected_rows_by_app):
        return {
            int(app_id): [clone_row(row) for row in rows]
            for app_id, rows in resolve_main_selected_contributors(selected_rows_by_app).items()
        }

    def _contributors_by_member_from_selected_rows(self, selected_rows_by_app):
        contributors = defaultdict(lambda: defaultdict(list))
        seen = set()
        for app_id, rows in (selected_rows_by_app or {}).items():
            app_id_int = _normalize_positive_int(app_id)
            if app_id_int is None:
                continue
            for src in self._merge_source_rows(rows):
                member_id = _normalize_positive_int(src.get("inscripcio_id"))
                if member_id is None:
                    continue
                key = (
                    member_id,
                    app_id_int,
                    _normalize_positive_int(src.get("exercici")),
                    _normalize_positive_int(src.get("equip_id")),
                )
                if key in seen:
                    continue
                seen.add(key)
                contributors[member_id][app_id_int].append(
                    self._copy_ex_row_with_value(src, src.get("value"))
                )
        return {member_id: dict(rows_by_app) for member_id, rows_by_app in contributors.items()}

    def _pick_participant_member_ids(self, member_values, mode: str, n: int):
        rows = []
        for idx, item in enumerate(member_values or []):
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            member_id = _normalize_positive_int(item[0])
            if member_id is None:
                continue
            rows.append((member_id, _to_float(item[1]), idx))
        if not rows:
            return []

        normalized_mode = str(mode or "tots").strip().lower()
        if normalized_mode in {"", "hereta", "tots"}:
            return [member_id for member_id, _value, _idx in rows]

        reverse = normalized_mode.startswith("millor_")
        if normalized_mode.endswith("_1"):
            limit = 1
        elif normalized_mode.endswith("_n"):
            try:
                limit = max(1, int(n or 1))
            except Exception:
                limit = 1
        else:
            limit = len(rows)

        ordered = sorted(
            rows,
            key=lambda item: (item[1], -item[2]) if reverse else (item[1], item[2]),
            reverse=reverse,
        )
        return [member_id for member_id, _value, _idx in ordered[:limit]]

    def _get_main_selected_contributors_for_individual(self, ins_id: int):
        return self._contributors_by_app_from_selected_rows(self._get_selected_rows_agg_for_ins(ins_id))

    def get_main_selected_contributors_for_individual(self, ins_id: int):
        return self._get_main_selected_contributors_for_individual(ins_id)

    def _get_main_selected_contributors_for_native_team(self, equip_id: int):
        return self._contributors_by_app_from_selected_rows(self._get_main_selected_rows_agg_for_team(equip_id))

    def get_main_selected_contributors_for_native_team(self, equip_id: int):
        return self._get_main_selected_contributors_for_native_team(equip_id)

    def _get_main_selected_contributors_for_group(self, team_cache_key, member_ids=None):
        cache_key, mids = self._resolve_group_call_args(team_cache_key, member_ids)
        if not mids:
            return {}

        if self.exercise_selection_scope == EXERCISE_SELECTION_SCOPE_TEAM_POOL:
            selected_rows_by_app = self._get_main_selected_rows_for_group(cache_key, mids)
            return self._contributors_by_member_from_selected_rows(selected_rows_by_app)

        selected_members_by_app = {}
        for app_id in self._ordered_app_ids():
            member_values = []
            for member_id in mids:
                member_rows = (self._get_selected_rows_agg_for_ins(member_id) or {}).get(app_id, [])
                if not member_rows:
                    continue
                member_score = _apply_simple_agg(
                    [_to_float(row.get("value")) for row in member_rows],
                    self.resolve_agregacio_exercicis_for_app(app_id),
                )
                member_values.append((member_id, member_score))

            if self.allow_main_participant_selection_step:
                participants_cfg, _agg = self.resolve_participants_for_app(app_id)
                selected_members_by_app[app_id] = set(
                    self._pick_participant_member_ids(
                        member_values,
                        participants_cfg.get("mode"),
                        int(participants_cfg.get("n") or 1),
                    )
                )
            else:
                selected_members_by_app[app_id] = {member_id for member_id, _score in member_values}

        contributors = defaultdict(lambda: defaultdict(list))
        seen = set()
        for member_id in mids:
            selected_rows_by_app = self._get_selected_rows_agg_for_ins(member_id) or {}
            for app_id, rows in selected_rows_by_app.items():
                app_id_int = _normalize_positive_int(app_id)
                if app_id_int is None:
                    continue
                if member_id not in selected_members_by_app.get(app_id_int, set()):
                    continue
                for src in self._merge_source_rows(rows):
                    key = (
                        member_id,
                        app_id_int,
                        _normalize_positive_int(src.get("exercici")),
                        _normalize_positive_int(src.get("equip_id")),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    item = self._copy_ex_row_with_value(src, src.get("value"))
                    item["inscripcio_id"] = member_id
                    contributors[member_id][app_id_int].append(item)

        return {member_id: dict(rows_by_app) for member_id, rows_by_app in contributors.items()}

    def get_main_selected_contributors_for_group(self, team_cache_key, member_ids=None):
        return self._get_main_selected_contributors_for_group(team_cache_key, member_ids)

    def _get_selected_rows_for_derived_team_field(self, team_cache_key, member_ids=None, field_code: str = ""):
        cache_key, mids = self._resolve_group_call_args(team_cache_key, member_ids)
        field_cache_key = (cache_key, str(field_code or ""))
        if field_cache_key in self.derived_team_selected_rows_field_cache:
            return self.derived_team_selected_rows_field_cache[field_cache_key]

        rows_by_app = {}
        for app_id in self._ordered_app_ids(team_context=False):
            rows_by_app[app_id] = self._build_derived_team_rows_for_app(mids, app_id, field_code=field_code)
        self.derived_team_selected_rows_field_cache[field_cache_key] = self._pick_selected_rows_from_rows_by_app(
            rows_by_app,
            participant_key="inscripcio_id",
        )
        return self.derived_team_selected_rows_field_cache[field_cache_key]

    def get_selected_rows_for_derived_team_field(self, team_cache_key, member_ids=None, field_code: str = ""):
        return self._get_selected_rows_for_derived_team_field(team_cache_key, member_ids, field_code)

    def _get_main_selected_rows_for_group_field(self, team_cache_key, member_ids=None, field_code: str = ""):
        cache_key, mids = self._resolve_group_call_args(team_cache_key, member_ids)
        field_cache_key = (cache_key, str(field_code or ""))
        if field_cache_key in self.main_selected_rows_for_group_field_cache:
            return self.main_selected_rows_for_group_field_cache[field_cache_key]
        if not mids:
            return {}

        if self.exercise_selection_scope == EXERCISE_SELECTION_SCOPE_TEAM_POOL:
            rows = self._get_selected_rows_for_derived_team_field(cache_key, mids, field_code)
            self.main_selected_rows_for_group_field_cache[field_cache_key] = rows
            return rows

        picked_by_app = defaultdict(list)
        for member_id in mids:
            for app_id, rows in (self._get_selected_rows_for_field(member_id, field_code) or {}).items():
                app_id_int = _normalize_positive_int(app_id)
                if app_id_int is None:
                    continue
                for row in rows or []:
                    item = self._copy_ex_row_with_value(row, row.get("value"))
                    item["inscripcio_id"] = member_id
                    picked_by_app[app_id_int].append(item)

        for app_id, rows in list(picked_by_app.items()):
            picked_by_app[app_id] = sorted(
                rows,
                key=lambda row: (
                    row.get("app_order", 0),
                    row.get("exercici", 0),
                    row.get("app_id", 0),
                    row.get("inscripcio_id", 0),
                ),
            )

        self.main_selected_rows_for_group_field_cache[field_cache_key] = dict(picked_by_app)
        return self.main_selected_rows_for_group_field_cache[field_cache_key]

    def get_main_selected_rows_for_group_field(self, team_cache_key, member_ids=None, field_code: str = ""):
        return self._get_main_selected_rows_for_group_field(team_cache_key, member_ids, field_code)

    def build_ctx_exports(self):
        return {
            "copy_ex_row_with_value": self.copy_ex_row_with_value,
            "get_main_selected_contributors_for_individual": self.get_main_selected_contributors_for_individual,
            "get_main_selected_contributors_for_native_team": self.get_main_selected_contributors_for_native_team,
            "get_main_selected_contributors_for_group": self.get_main_selected_contributors_for_group,
            "get_main_selected_rows_for_group": self.get_main_selected_rows_for_group,
        }

    def build_orchestrator_exports(self):
        exports = dict(self.build_ctx_exports())
        exports.update(
            {
                "resolve_agregacio_exercicis_for_app": self.resolve_agregacio_exercicis_for_app,
                "resolve_participants_for_app": self.resolve_participants_for_app,
                "get_selected_rows_agg_for_ins": self.get_selected_rows_agg_for_ins,
                "get_selected_rows_agg_for_team": self.get_selected_rows_agg_for_team,
                "get_selected_rows_for_field": self.get_selected_rows_for_field,
                "get_selected_team_rows_for_field": self.get_selected_team_rows_for_field,
                "get_main_selected_rows_agg_for_team": self.get_main_selected_rows_agg_for_team,
                "get_main_selected_team_rows_for_field": self.get_main_selected_team_rows_for_field,
                "get_selected_rows_agg_for_derived_team": self.get_selected_rows_agg_for_derived_team,
                "get_selected_rows_for_derived_team_field": self.get_selected_rows_for_derived_team_field,
                "get_main_selected_rows_for_group_field": self.get_main_selected_rows_for_group_field,
            }
        )
        return exports


def build_selection_runtime(**kwargs):
    return SelectionRuntime(**kwargs)


__all__ = [
    "EXERCISE_SELECTION_SCOPE_INHERIT",
    "EXERCISE_SELECTION_SCOPE_PER_MEMBER",
    "EXERCISE_SELECTION_SCOPE_TEAM_POOL",
    "SelectionRuntime",
    "build_selection_runtime",
]
