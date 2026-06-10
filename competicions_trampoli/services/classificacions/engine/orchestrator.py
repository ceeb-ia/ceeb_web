"""Classification compute orchestrator."""

import logging
from collections import defaultdict
from ...scoring.team_scoring import is_team_context_app
from ...teams.equip_contexts import get_contextual_assignment_map
from ..partitions import normalize_particions_config, normalize_particions_v2_entries
from .common import (
    EXERCISE_SELECTION_SCOPE_PER_MEMBER,
    get_effective_team_context_code as _get_effective_team_context_code,
    normalize_classificacio_equips_cfg as _normalize_classificacio_equips_cfg,
    normalize_classificacio_filters as _normalize_classificacio_filters,
    normalize_equip_assignment_source as _normalize_equip_assignment_source,
    normalize_exercise_selection_scope as _normalize_exercise_selection_scope,
    normalized_text_token as _normalized_text_token,
)
from .detail_payload import (
    build_detail_runtime,
    get_detail_display_config as engine_get_detail_display_config,
    get_display_columns as engine_get_display_columns,
)
from .loaders import load_engine_orm_data
from .metrics_runtime import (
    _sanitize_desempat_for_tipus as engine_sanitize_desempat_for_tipus,
    build_metrics_runtime,
    build_metrics_runtime_adapters,
    calc_criterion_value as engine_calc_criterion_value,
)
from .model_utils import display_value as _display_value
from .partition_runtime import _build_particions_custom_index, _partition_key_from_entries
from .ranking import (
    _is_pipeline_tie,
    _normalize_tie_camps,
    _rank_v2 as engine_rank_rows,
    _tie_key,
)
from .score_values import (
    _apply_simple_agg,
    _get_score_field,
    _to_float,
)
from .selection import (
    _normalize_candidate_source_cfg,
    _normalize_candidate_source_mode,
    _normalize_exercicis_cfg,
    _normalize_field_mode,
    _normalize_optional_agg,
    _normalize_participants_cfg,
    _pick_exercicis_rows,
    _pick_exercicis_tuples,
    _pick_participants,
)
from .selection_runtime import build_selection_runtime
from .schema import normalize_schema as engine_normalize_schema
from .teams import _build_resolved_team_by_ins_id, _build_team_grouped, _build_team_rows
from .victories import (
    build_victories_adapters,
    _normalize_mode_resultat_aparells as engine_normalize_mode_resultat_aparells,
    _normalize_victories_cfg as engine_normalize_victories_cfg,
)

logger = logging.getLogger(__name__)


def _unique_nonempty_strings(raw_values):
    out = []
    seen = set()
    values = raw_values
    if isinstance(values, str):
        values = values.split(",")
    if not isinstance(values, (list, tuple)):
        return out
    for raw in values:
        txt = str(raw or "").strip()
        if not txt or txt in seen:
            continue
        seen.add(txt)
        out.append(txt)
    return out


def compute_classificacio(competicio, cfg_obj):
    """
    Retorna:
      { "particio_key": [ {row}, ... ] }

    row (individual) mÃ­nim:
      - inscripcio_id, nom, entitat_nom, score, tie{...}
      - posicio/punts els posa _rank()
    """
    tipus = (getattr(cfg_obj, "tipus", "individual") or "individual").lower().strip()
    schema, _legacy_info = engine_normalize_schema(
        competicio,
        getattr(cfg_obj, "schema", {}) or {},
        tipus=tipus,
        persist=False,
    )
    part_entries = schema.get("particions_v2") or normalize_particions_v2_entries(
        schema.get("particions") or []
    )
    part_custom_idx = _build_particions_custom_index(schema.get("particions_custom") or {})
    particions_config = normalize_particions_config(schema.get("particions_config") or {})
    filtres = _normalize_classificacio_filters(schema.get("filtres") or {})
    punt = schema["puntuacio"] or {}
    desempat = schema["desempat"] or []
    presentacio = schema["presentacio"] or {}
    display_columns = engine_get_display_columns(schema)
    equips_cfg = _normalize_classificacio_equips_cfg(schema.get("equips") or {})
    assignment_source = equips_cfg.get("assignment_source") or _normalize_equip_assignment_source({})
    team_context_code = _get_effective_team_context_code(equips_cfg)
    desempat = engine_sanitize_desempat_for_tipus(desempat, tipus)
    mode_resultat_aparells = engine_normalize_mode_resultat_aparells(punt.get("mode_resultat_aparells"))
    victories_cfg = engine_normalize_victories_cfg((punt.get("victories") or {}))
    if tipus != "individual" and mode_resultat_aparells == "victories":
        mode_resultat_aparells = "score"

    # 1) PRETRACTAMENT
    ordre_principal = (punt.get("ordre") or "desc").lower().strip()
    if ordre_principal not in ("asc", "desc"):
        ordre_principal = "desc"

    ex_cfg = punt.get("exercicis") or {}
    base_ex_cfg = _normalize_exercicis_cfg(
        {
            **(ex_cfg if isinstance(ex_cfg, dict) else {}),
            "best_n": (
                (ex_cfg.get("best_n") if isinstance(ex_cfg, dict) else None)
                or punt.get("exercicis_best_n")
                or 1
            ),
        },
        fallback={"mode": "tots", "best_n": 1, "index": 1, "ids": []},
    )
    exerc_mode = base_ex_cfg["mode"]
    ex_best_n = base_ex_cfg["best_n"]
    ex_index = base_ex_cfg["index"]
    ex_ids = base_ex_cfg["ids"]
    mode_seleccio_exercicis = str(punt.get("mode_seleccio_exercicis") or "per_aparell_global").lower().strip()
    if mode_seleccio_exercicis not in ("per_aparell_global", "per_aparell_override", "global_pool"):
        mode_seleccio_exercicis = "per_aparell_global"
    exercicis_per_aparell = punt.get("exercicis_per_aparell") or {}
    if not isinstance(exercicis_per_aparell, dict):
        exercicis_per_aparell = {}
    camps_mode_per_aparell = punt.get("camps_mode_per_aparell") or {}
    if not isinstance(camps_mode_per_aparell, dict):
        camps_mode_per_aparell = {}
    camps_per_exercici_per_aparell = punt.get("camps_per_exercici_per_aparell") or {}
    if not isinstance(camps_per_exercici_per_aparell, dict):
        camps_per_exercici_per_aparell = {}
    agregacio_camps_per_aparell = punt.get("agregacio_camps_per_aparell") or {}
    if not isinstance(agregacio_camps_per_aparell, dict):
        agregacio_camps_per_aparell = {}
    agregacio_camps_per_exercici_per_aparell = punt.get("agregacio_camps_per_exercici_per_aparell") or {}
    if not isinstance(agregacio_camps_per_exercici_per_aparell, dict):
        agregacio_camps_per_exercici_per_aparell = {}
    candidate_source_per_aparell = punt.get("candidate_source_per_aparell") or {}
    if not isinstance(candidate_source_per_aparell, dict):
        candidate_source_per_aparell = {}
    agregacio_exercicis_per_aparell = punt.get("agregacio_exercicis_per_aparell") or {}
    if not isinstance(agregacio_exercicis_per_aparell, dict):
        agregacio_exercicis_per_aparell = {}
    team_pool_mode_per_aparell = punt.get("team_pool_mode_per_aparell") or {}
    if not isinstance(team_pool_mode_per_aparell, dict):
        team_pool_mode_per_aparell = {}
    team_pool_participants_per_exercici_per_aparell = punt.get("team_pool_participants_per_exercici_per_aparell") or {}
    if not isinstance(team_pool_participants_per_exercici_per_aparell, dict):
        team_pool_participants_per_exercici_per_aparell = {}
    team_pool_agregacio_participants_per_exercici_per_aparell = punt.get("team_pool_agregacio_participants_per_exercici_per_aparell") or {}
    if not isinstance(team_pool_agregacio_participants_per_exercici_per_aparell, dict):
        team_pool_agregacio_participants_per_exercici_per_aparell = {}

    agg_camps = (punt.get("agregacio_camps") or "sum").lower().strip()
    candidate_source_mode = _normalize_candidate_source_mode(punt.get("candidate_source_mode"))
    candidate_source_cfg = _normalize_candidate_source_cfg(
        punt.get("candidate_source_cfg"),
        fallback={"mode": "tots", "best_n": 1, "index": 1, "ids": [], "agregacio_exercicis": "sum"},
    )
    agg_exercicis = (punt.get("agregacio_exercicis") or "sum").lower().strip()
    agg_aparells = (punt.get("agregacio_aparells") or "sum").lower().strip()

    orm_data = load_engine_orm_data(
        competicio,
        punt=punt,
        tipus=tipus,
        filtres=filtres,
        equips_cfg=equips_cfg,
        phase_scope=schema.get("scope") or {},
    )
    aparells = orm_data.aparells
    team_mode = orm_data.team_mode if tipus == "equips" else ""
    team_context_code = orm_data.team_context_code or team_context_code
    detail_config = engine_get_detail_display_config(schema, tipus=tipus, team_mode=team_mode)
    detail_enabled = bool(detail_config.get("enabled"))
    exercise_selection_scope = EXERCISE_SELECTION_SCOPE_PER_MEMBER
    if tipus == "equips" and team_mode == "derived_from_individual":
        exercise_selection_scope = _normalize_exercise_selection_scope(
            punt.get("exercise_selection_scope")
        )
    allow_main_participant_selection_step = (
        tipus == "equips"
        and team_mode == "derived_from_individual"
        and exercise_selection_scope == EXERCISE_SELECTION_SCOPE_PER_MEMBER
        and mode_seleccio_exercicis != "global_pool"
    )
    allow_global_participant_selection_step = (
        tipus == "equips"
        and team_mode == "derived_from_individual"
        and exercise_selection_scope == EXERCISE_SELECTION_SCOPE_PER_MEMBER
        and mode_seleccio_exercicis == "global_pool"
    )
    participants_per_aparell = punt.get("participants_per_aparell") if isinstance(punt.get("participants_per_aparell"), dict) else {}
    agregacio_participants_per_aparell = (
        punt.get("agregacio_participants_per_aparell")
        if isinstance(punt.get("agregacio_participants_per_aparell"), dict)
        else {}
    )
    participants_global = _normalize_participants_cfg(
        punt.get("participants_global") if isinstance(punt.get("participants_global"), dict) else {}
    )
    agregacio_participants_global = _normalize_optional_agg(punt.get("agregacio_participants_global")) or "sum"
    allow_candidate_source = (
        tipus == "individual"
        or (tipus == "equips" and team_mode in ("derived_from_individual", "native_team"))
    )
    if not allow_candidate_source:
        candidate_source_mode = "raw_exercise"
    if (
        tipus == "equips"
        and team_mode == "derived_from_individual"
        and exercise_selection_scope == "team_pool"
    ):
        for raw_app_id, raw_mode in list(team_pool_mode_per_aparell.items()):
            try:
                app_id = int(raw_app_id)
            except Exception:
                continue
            if str(raw_mode or "").strip().lower() == "per_exercici":
                candidate_source_per_aparell[str(app_id)] = {"mode": "raw_exercise"}
        if any(str(raw_mode or "").strip().lower() == "per_exercici" for raw_mode in team_pool_mode_per_aparell.values()):
            if str(candidate_source_mode or "").strip().lower() != "raw_exercise":
                candidate_source_mode = "raw_exercise"

    def resolve_agregacio_camps_for_app(app_id: int):
        raw = agregacio_camps_per_aparell.get(str(app_id))
        if raw is None:
            raw = agregacio_camps_per_aparell.get(app_id)
        agg = str(raw or agg_camps or "sum").lower().strip()
        if agg not in ("sum", "avg", "median", "max", "min"):
            agg = str(agg_camps or "sum").lower().strip()
        if agg not in ("sum", "avg", "median", "max", "min"):
            agg = "sum"
        return agg

    def resolve_camps_mode_for_app(app_id: int):
        raw = camps_mode_per_aparell.get(str(app_id))
        if raw is None:
            raw = camps_mode_per_aparell.get(app_id)
        return _normalize_field_mode(raw)

    # si no hi ha aparells seleccionats -> retorn buit
    if not aparells:
        return {"global": []}

    # 3) INSCRIPCIONS per competiciÃ³, agrupades per aparell
    all_ins_list = orm_data.all_ins_list
    all_ins_by_id = orm_data.all_ins_by_id
    filtered_ins_list = orm_data.ins_list
    filtered_ins_by_id = orm_data.ins_by_id
    ins_list = filtered_ins_list
    ins_by_id = filtered_ins_by_id
    team_assignment_map = {}
    if tipus == "equips" and team_mode == "derived_from_individual" and assignment_source.get("mode") == "context":
        team_assignment_map = get_contextual_assignment_map(
            competicio,
            filtered_ins_list,
            team_context_code,
        )

    notes = orm_data.notes
    notes_by_app = orm_data.notes_by_app
    notes_by_key = orm_data.notes_by_key
    ins_ids_by_app = orm_data.ins_ids_by_app
    team_notes = orm_data.team_notes
    team_notes_by_app = orm_data.team_notes_by_app
    team_notes_by_key = orm_data.team_notes_by_key
    team_ids_by_app = orm_data.team_ids_by_app

    # 4) CAMPS per aparell (lliures)
    camps_per_aparell = punt.get("camps_per_aparell") or {}
    # fallback legacy: si no hi ha camps_per_aparell, usem camp legacy per tots els aparells
    legacy_camp = (punt.get("camp") or "total").strip()

    def _score_camps_for_app(app_id: int, *, include_per_exercise=False):
        raw = camps_per_aparell.get(str(app_id)) or camps_per_aparell.get(app_id)
        out = _unique_nonempty_strings(raw)
        if not out:
            # legacy
            out = [legacy_camp] if legacy_camp else ["total"]
        if include_per_exercise and resolve_camps_mode_for_app(app_id) == "per_exercici":
            raw_map = camps_per_exercici_per_aparell.get(str(app_id))
            if raw_map is None:
                raw_map = camps_per_exercici_per_aparell.get(app_id)
            for raw_fields in (raw_map.values() if isinstance(raw_map, dict) else []):
                for code in _unique_nonempty_strings(raw_fields):
                    if code not in out:
                        out.append(code)
        return out

    def resolve_score_fields_for_app_exercise(app_id: int, ex_idx: int):
        common_fields = list(_score_camps_for_app(app_id))
        common_agg = resolve_agregacio_camps_for_app(app_id)
        if resolve_camps_mode_for_app(app_id) != "per_exercici":
            return common_fields, common_agg

        raw_fields_by_ex = camps_per_exercici_per_aparell.get(str(app_id))
        if raw_fields_by_ex is None:
            raw_fields_by_ex = camps_per_exercici_per_aparell.get(app_id)
        raw_agg_by_ex = agregacio_camps_per_exercici_per_aparell.get(str(app_id))
        if raw_agg_by_ex is None:
            raw_agg_by_ex = agregacio_camps_per_exercici_per_aparell.get(app_id)

        ex_key = str(max(1, int(ex_idx or 1)))
        ex_fields = _unique_nonempty_strings(
            (raw_fields_by_ex or {}).get(ex_key) if isinstance(raw_fields_by_ex, dict) else []
        )
        ex_agg = _normalize_optional_agg(
            (raw_agg_by_ex or {}).get(ex_key) if isinstance(raw_agg_by_ex, dict) else None
        )
        if not ex_fields or not ex_agg:
            return common_fields, common_agg
        return ex_fields, ex_agg

    def camps_for_app(app_id: int):
        out = list(_score_camps_for_app(app_id, include_per_exercise=True))
        seen = set()
        for crit in desempat or []:
            if isinstance(crit, dict) and isinstance(crit.get("pipeline"), dict):
                pipeline = crit.get("pipeline") or {}
                app_cfg = pipeline.get("aparells") if isinstance(pipeline.get("aparells"), dict) else {}
                target_ids = []
                for raw_app_id in (app_cfg.get("ids") or []):
                    try:
                        target_ids.append(int(raw_app_id))
                    except Exception:
                        continue
                if not target_ids:
                    target_ids = [int(app_id)]
                if int(app_id) in target_ids:
                    camps_map = pipeline.get("camps_per_aparell") if isinstance(pipeline.get("camps_per_aparell"), dict) else {}
                    raw_camps = camps_map.get(str(app_id))
                    if raw_camps is None:
                        raw_camps = camps_map.get(app_id)
                    if raw_camps is None and len(target_ids) == 1:
                        raw_camps = next(iter(camps_map.values()), [])
                    if isinstance(raw_camps, list):
                        out.extend(str(x).strip() for x in raw_camps if str(x).strip())
                    elif isinstance(raw_camps, str) and raw_camps.strip():
                        out.extend(x.strip() for x in raw_camps.split(",") if x.strip())
                continue

            scope = (crit.get("scope") or {}) if isinstance(crit, dict) else {}
            app_scope = (scope.get("aparells") or {}) if isinstance(scope, dict) else {}
            app_mode = str(app_scope.get("mode") or "").strip().lower()
            target_ids = []
            if app_mode == "seleccionar":
                for raw_app_id in (app_scope.get("ids") or []):
                    try:
                        target_ids.append(int(raw_app_id))
                    except Exception:
                        continue
            elif crit.get("aparell_id") not in (None, "", 0, "0"):
                try:
                    target_ids.append(int(crit.get("aparell_id")))
                except Exception:
                    pass
            if not target_ids:
                target_ids = [int(app_id)]
            if int(app_id) in target_ids:
                out.extend(_normalize_tie_camps(crit))

        def _collect_raw_columns(raw_columns):
            if not isinstance(raw_columns, list):
                return
            for col in raw_columns:
                if not isinstance(col, dict):
                    continue
                if str(col.get("type") or "builtin").strip().lower() != "raw":
                    continue
                src = col.get("source") if isinstance(col.get("source"), dict) else {}
                try:
                    source_app_id = int(src.get("aparell_id"))
                except Exception:
                    continue
                if source_app_id != int(app_id):
                    continue
                camp = str(src.get("camp") or "").strip()
                if camp:
                    out.append(camp)

        presentacio = schema.get("presentacio") if isinstance(schema.get("presentacio"), dict) else {}
        _collect_raw_columns(presentacio.get("columnes"))
        detail_cfg = presentacio.get("detall") if isinstance(presentacio.get("detall"), dict) else {}
        _collect_raw_columns(detail_cfg.get("columnes"))
        for section in (detail_cfg.get("sections") or []):
            if isinstance(section, dict):
                _collect_raw_columns(section.get("columns"))

        dedup = []
        for code in out:
            if code in seen:
                continue
            seen.add(code)
            dedup.append(code)
        return dedup

    # 5) EXERCICIS per aparell segons CompeticioAparell.nombre_exercicis
    # 6) AGREGACIONS + construccio de score final per inscripcio
    per_ins = {}  # ins_id -> {"score":float, "by_app_base":{}, "by_app":{}, "tie":{...}}
    for ins in ins_list:
        per_ins[ins.id] = {"score": 0.0, "by_app_base": {}, "by_app": {}, "tie": {}}

    app_order = {ca.id: idx for idx, ca in enumerate(aparells, start=1)}
    app_fields_by_app = {}
    app_ex_rows_by_ins = defaultdict(dict)  # app_id -> ins_id -> [row]
    team_app_ex_rows_by_equip = defaultdict(dict)  # app_id -> equip_id -> [row]

    for ca in aparells:
        app_id = ca.id
        n_ex = int(getattr(ca, "nombre_exercicis", 1) or 1)
        n_ex = max(1, min(50, n_ex))
        score_fields = _score_camps_for_app(app_id)
        fields = camps_for_app(app_id)
        app_fields_by_app[app_id] = list(score_fields)

        if tipus == "equips" and is_team_context_app(ca):
            app_notes = team_notes_by_app.get(app_id, [])
            by_team_ex = defaultdict(dict)
            for nt in app_notes:
                ex_idx = int(getattr(nt, "exercici", 1) or 1)
                if ex_idx < 1:
                    ex_idx = 1
                if ex_idx > n_ex:
                    continue
                by_team_ex[nt.equip_id][ex_idx] = nt

            for equip_id in list(by_team_ex.keys()):
                vals_rows = []
                for ex_idx in range(1, n_ex + 1):
                    nt = by_team_ex.get(equip_id, {}).get(ex_idx)
                    if not nt:
                        continue
                    score_fields_for_ex, agg_camps_for_ex = resolve_score_fields_for_app_exercise(app_id, ex_idx)
                    fields_map = {f: _get_score_field(nt, f) for f in fields}
                    v_fields = [fields_map.get(f, 0.0) for f in score_fields_for_ex]
                    v_ex = _apply_simple_agg(v_fields, agg_camps_for_ex)
                    vals_rows.append(
                        {
                            "idx": int(ex_idx),
                            "value": _to_float(v_ex),
                            "app_id": app_id,
                            "app_order": app_order.get(app_id, 0),
                            "exercici": int(ex_idx),
                            "equip_id": int(equip_id),
                            "by_camp": fields_map,
                        }
                    )
                team_app_ex_rows_by_equip[app_id][equip_id] = vals_rows
            continue

        # notes d'aquest aparell
        app_notes = notes_by_app.get(app_id, [])
        # index: ins_id -> exercici -> note
        by_ins_ex = defaultdict(dict)
        for nt in app_notes:
            # normalitzem exercici al rang 1..n_ex
            ex_idx = int(getattr(nt, "exercici", 1) or 1)
            if ex_idx < 1:
                ex_idx = 1
            if ex_idx > n_ex:
                # si hi ha notes extra, les ignorem per coherencia amb configuracio d'aparell
                continue
            by_ins_ex[nt.inscripcio_id][ex_idx] = nt

        # calculem valor per exercici (agregant camps)
        for ins_id in list(ins_by_id.keys()):
            if ins_id not in ins_ids_by_app.get(app_id, set()):
                # no competeix en aquest aparell
                continue

            vals_ex = []
            vals_rows = []
            for ex_idx in range(1, n_ex + 1):
                nt = by_ins_ex.get(ins_id, {}).get(ex_idx)
                if not nt:
                    continue
                score_fields_for_ex, agg_camps_for_ex = resolve_score_fields_for_app_exercise(app_id, ex_idx)
                fields_map = {f: _get_score_field(nt, f) for f in fields}
                v_fields = [fields_map.get(f, 0.0) for f in score_fields_for_ex]

                v_ex = _apply_simple_agg(v_fields, agg_camps_for_ex)  # agregacio camps dins exercici
                vals_ex.append((ex_idx, v_ex))
                vals_rows.append(
                    {
                        "idx": int(ex_idx),
                        "value": _to_float(v_ex),
                        "app_id": app_id,
                        "app_order": app_order.get(app_id, 0),
                        "exercici": int(ex_idx),
                        "inscripcio_id": ins_id,
                        "by_camp": fields_map,
                    }
                )

            app_ex_rows_by_ins[app_id][ins_id] = vals_rows

    selection_runtime = build_selection_runtime(
        aparells=aparells,
        tipus=tipus,
        team_mode=team_mode,
        legacy_camp=legacy_camp,
        agg_camps=agg_camps,
        camps_per_aparell=camps_per_aparell,
        camps_mode_per_aparell=camps_mode_per_aparell,
        camps_per_exercici_per_aparell=camps_per_exercici_per_aparell,
        agregacio_camps_per_aparell=agregacio_camps_per_aparell,
        agregacio_camps_per_exercici_per_aparell=agregacio_camps_per_exercici_per_aparell,
        mode_seleccio_exercicis=mode_seleccio_exercicis,
        base_ex_cfg=base_ex_cfg,
        exercicis_per_aparell=exercicis_per_aparell,
        agg_exercicis=agg_exercicis,
        agregacio_exercicis_per_aparell=agregacio_exercicis_per_aparell,
        candidate_source_mode=candidate_source_mode,
        candidate_source_cfg=candidate_source_cfg,
        candidate_source_per_aparell=candidate_source_per_aparell,
        participants_per_aparell=participants_per_aparell,
        agregacio_participants_per_aparell=agregacio_participants_per_aparell,
        team_pool_mode_per_aparell=team_pool_mode_per_aparell,
        team_pool_participants_per_exercici_per_aparell=team_pool_participants_per_exercici_per_aparell,
        team_pool_agregacio_participants_per_exercici_per_aparell=team_pool_agregacio_participants_per_exercici_per_aparell,
        exercise_selection_scope=exercise_selection_scope,
        allow_candidate_source=allow_candidate_source,
        allow_main_participant_selection_step=allow_main_participant_selection_step,
        app_ex_rows_by_ins=app_ex_rows_by_ins,
        team_app_ex_rows_by_equip=team_app_ex_rows_by_equip,
    )
    selection_exports = selection_runtime.build_orchestrator_exports()

    resolve_agregacio_camps_for_app = selection_runtime.resolve_agregacio_camps_for_app
    resolve_camps_mode_for_app = selection_runtime.resolve_camps_mode_for_app
    resolve_candidate_source_for_app = selection_runtime.resolve_candidate_source_for_app
    resolve_agregacio_exercicis_for_app = selection_runtime.resolve_agregacio_exercicis_for_app
    resolve_participants_for_app = selection_runtime.resolve_participants_for_app
    _score_camps_for_app = selection_runtime._score_camps_for_app
    resolve_score_fields_for_app_exercise = selection_runtime.resolve_score_fields_for_app_exercise
    _resolve_ex_cfg_for_app = selection_runtime._resolve_ex_cfg_for_app
    _copy_ex_row_with_value = selection_exports["copy_ex_row_with_value"]
    _merge_source_rows = selection_runtime._merge_source_rows
    _build_candidate_rows_from_source_rows = selection_runtime._build_candidate_rows_from_source_rows
    _get_selected_rows_agg_for_ins = selection_exports["get_selected_rows_agg_for_ins"]
    _get_selected_rows_agg_for_team = selection_exports["get_selected_rows_agg_for_team"]
    _get_selected_rows_for_field = selection_exports["get_selected_rows_for_field"]
    _get_selected_team_rows_for_field = selection_exports["get_selected_team_rows_for_field"]
    _get_main_selected_rows_agg_for_team = selection_exports["get_main_selected_rows_agg_for_team"]
    _get_main_selected_team_rows_for_field = selection_exports["get_main_selected_team_rows_for_field"]
    _derived_team_cache_key = selection_runtime._derived_team_cache_key
    _get_selected_rows_agg_for_derived_team = selection_exports["get_selected_rows_agg_for_derived_team"]
    _get_main_selected_rows_for_group = selection_exports["get_main_selected_rows_for_group"]
    _get_main_selected_contributors_for_individual = selection_exports["get_main_selected_contributors_for_individual"]
    _get_main_selected_contributors_for_native_team = selection_exports["get_main_selected_contributors_for_native_team"]
    _get_main_selected_contributors_for_group = selection_exports["get_main_selected_contributors_for_group"]
    _get_selected_rows_for_derived_team_field = selection_exports["get_selected_rows_for_derived_team_field"]
    _get_main_selected_rows_for_group_field = selection_exports["get_main_selected_rows_for_group_field"]

    def resolve_global_participants():
        return dict(participants_global or {"mode": "tots"}), agregacio_participants_global

    for ins_id, obj in per_ins.items():
        selected_rows_by_app = _get_selected_rows_agg_for_ins(ins_id)
        for ca in aparells:
            app_id = ca.id
            if ins_id not in ins_ids_by_app.get(app_id, set()):
                continue
            agg_exercicis_for_app = resolve_agregacio_exercicis_for_app(app_id)
            score_app = _apply_simple_agg(
                [_to_float(row.get("value")) for row in selected_rows_by_app.get(app_id, [])],
                agg_exercicis_for_app,
            )
            obj["by_app_base"][app_id] = float(score_app)

    # agregacio final entre aparells
    for ins_id, obj in per_ins.items():
        obj["by_app"] = dict(obj.get("by_app_base") or {})
        if mode_resultat_aparells == "score":
            app_vals = list((obj.get("by_app") or {}).values())
            obj["score"] = float(_apply_simple_agg(app_vals, agg_aparells))
        else:
            obj["by_app"] = {}
            obj["score"] = 0.0

    # 7) TIE-BREAKS segons ordre del front
    # suport:
    #  - legacy: {"camp":"execucio_total","ordre":"desc"} -> suma (o avg) sobre aparells/exercicis segons el pipeline
    #  - nou: {"aparell_id": X, "camp": "E_total", "ordre":"desc"} -> recalcula com "score d'aquell aparell perÃ² nomÃ©s amb aquell camp"
    #
    # IMPORTANT: per no duplicar molt codi, fem una funciÃ³ que calcula "valor criteri" reutilitzant el mateix pipeline,
    # perÃ² substituint camps per la llista [camp].
    metrics_runtime = build_metrics_runtime(
        tipus=tipus,
        team_mode=team_mode,
        selected_app_ids=[int(ca.id) for ca in aparells],
        derived_team_cache_key=_derived_team_cache_key,
        app_ex_rows_by_ins=app_ex_rows_by_ins,
        team_app_ex_rows_by_equip=team_app_ex_rows_by_equip,
        app_order=app_order,
        copy_ex_row_with_value=_copy_ex_row_with_value,
        to_float=_to_float,
        apply_simple_agg=_apply_simple_agg,
        pick_exercicis_rows=_pick_exercicis_rows,
        pick_exercicis_tuples=_pick_exercicis_tuples,
        pick_participants=_pick_participants,
        get_main_selected_contributors_for_individual=_get_main_selected_contributors_for_individual,
        get_main_selected_contributors_for_native_team=_get_main_selected_contributors_for_native_team,
        get_main_selected_rows_for_group=_get_main_selected_rows_for_group,
        get_main_selected_contributors_for_group=_get_main_selected_contributors_for_group,
        individual_ids=list(per_ins.keys()),
        per_ins=per_ins,
    )
    metrics_adapters = build_metrics_runtime_adapters(metrics_runtime)
    victories_adapters = build_victories_adapters(metrics_adapters["calc_metric_value_for_ins"])

    calc_criterion_value = lambda ins_id, crit, forced_app_ids=None, forced_exercici_ids=None, forced_camps=None: engine_calc_criterion_value(
        metrics_runtime,
        ins_id,
        crit,
        forced_app_ids=forced_app_ids,
        forced_exercici_ids=forced_exercici_ids,
        forced_camps=forced_camps,
    )
    calc_metric_value_for_ins = metrics_adapters["calc_metric_value_for_ins"]
    calc_metric_value_for_group = metrics_adapters["calc_metric_value_for_group"]
    calc_metric_value_for_native_team = metrics_adapters["calc_metric_value_for_native_team"]
    _pipeline_metric_map_for_crit = metrics_adapters["pipeline_metric_map_for_crit"]
    _apply_victories_per_app_to_rows = victories_adapters["apply_victories_per_app_to_rows"]
    _compute_victory_points_for_entries = victories_adapters["compute_victory_points_for_entries"]

    detail_runtime = build_detail_runtime(
        notes_by_key=notes_by_key,
        team_notes_by_key=team_notes_by_key,
        all_ins_by_id=all_ins_by_id,
        aparells=aparells,
        display_columns=display_columns,
        detail_enabled=detail_enabled,
        detail_config=detail_config,
        get_main_selected_rows_agg_for_team=_get_main_selected_rows_agg_for_team,
        get_main_selected_team_rows_for_field=_get_main_selected_team_rows_for_field,
        get_main_selected_rows_for_group_field=_get_main_selected_rows_for_group_field,
    )

    # guardem tie values (amb clau estable per UI)
    for crit in desempat:
        key = _tie_key(crit)
        if not key:
            continue
        for ins_id in per_ins.keys():
            per_ins[ins_id]["tie"][key] = calc_metric_value_for_ins(ins_id, crit)

    # 8) PARTICIONS + output rows
    per_particio = defaultdict(list)

    for ins in ins_list:
        pkey = _partition_key_from_entries(
            ins,
            part_entries,
            part_custom_idx,
            particions_config=particions_config,
        )
        participant = (
            getattr(ins, "nom_complet", None)
            or getattr(ins, "nom_i_cognoms", None)
            or getattr(ins, "nom", None)
            or str(ins)
        )

        row = {
            "inscripcio_id": ins.id,
            "nom": participant,
            "participant": participant,
            "entitat_nom": _display_value(ins, "entitat"),
            "score": float(per_ins[ins.id]["score"]),
            "tie": per_ins[ins.id]["tie"],
            # extra Ãºtil pel front (si vols mostrar detalls)
            "by_app": dict(per_ins[ins.id]["by_app"]),
            "by_app_base": dict(per_ins[ins.id]["by_app_base"]),
        }
        per_particio[pkey].append(row)

    metrics_runtime["per_particio"] = per_particio

    if tipus == "individual" and mode_resultat_aparells == "victories":
        target_app_ids = [ca.id for ca in aparells]
        mode_vict_camps = str(victories_cfg.get("mode_camps") or "agregat").lower().strip()
        mode_vict_exercicis = str(victories_cfg.get("mode_exercicis") or "agregat").lower().strip()
        camps_sep_ex_selection = str(
            victories_cfg.get("mode_seleccio_exercicis_camps_separats") or "per_camp"
        ).lower().strip()
        agg_victories_camps = str(victories_cfg.get("agregacio_victories_camps") or "sum").lower().strip()
        agg_victories_exercicis = str(
            victories_cfg.get("agregacio_victories_exercicis") or "sum"
        ).lower().strip()

        def _selected_field_rows_for_app(ins_id: int, app_id: int, field_code: str):
            if camps_sep_ex_selection == "per_camp":
                return _get_selected_rows_for_field(ins_id, field_code).get(app_id, [])
            return [
                _copy_ex_row_with_value(row, ((row.get("by_camp") or {}).get(field_code)))
                for row in (_get_selected_rows_agg_for_ins(ins_id).get(app_id, []) or [])
            ]

        for _pkey, rows in per_particio.items():
            for row in rows:
                row["by_app"] = {}

            if mode_vict_camps == "agregat" and mode_vict_exercicis == "agregat":
                _apply_victories_per_app_to_rows(
                    rows,
                    app_ids=target_app_ids,
                    ordre_principal=ordre_principal,
                    agg_aparells=agg_aparells,
                    victories_cfg=victories_cfg,
                )
                continue

            for app_id in target_app_ids:
                if app_id not in app_fields_by_app:
                    continue

                points_by_ins = defaultdict(list)
                points_by_ins_ex = defaultdict(lambda: defaultdict(list))

                if mode_vict_camps == "separat" and mode_vict_exercicis == "agregat":
                    for field_code in app_fields_by_app.get(app_id, []):
                        entries = []
                        for row in rows:
                            ins_id = row.get("inscripcio_id")
                            if ins_id in (None, ""):
                                continue
                            selected_rows = _selected_field_rows_for_app(ins_id, app_id, field_code)
                            if not selected_rows:
                                continue
                            agg_exercicis_for_app = resolve_agregacio_exercicis_for_app(app_id)
                            base_val = _apply_simple_agg(
                                [_to_float(item.get("value")) for item in selected_rows],
                                agg_exercicis_for_app,
                            )
                            entries.append({"row": row, "base": base_val})

                        unit_points = _compute_victory_points_for_entries(
                            entries,
                            ordre_principal,
                            victories_cfg,
                            forced_app_ids=[app_id],
                            forced_camps=[field_code],
                        )
                        for ins_id, pts in unit_points.items():
                            points_by_ins[ins_id].append(pts)

                    for row in rows:
                        ins_id = row.get("inscripcio_id")
                        if ins_id in (None, ""):
                            continue
                        row["by_app"][app_id] = float(
                            _apply_simple_agg(points_by_ins.get(ins_id, []), agg_victories_camps)
                        )
                    continue

                if mode_vict_camps == "agregat" and mode_vict_exercicis == "separat":
                    all_exercicis = set()
                    ex_rows_by_ins = {}
                    for row in rows:
                        ins_id = row.get("inscripcio_id")
                        if ins_id in (None, ""):
                            continue
                        selected_rows = _get_selected_rows_agg_for_ins(ins_id).get(app_id, [])
                        ex_map = {}
                        for item in selected_rows:
                            try:
                                ex_idx = int(item.get("exercici"))
                            except Exception:
                                continue
                            ex_map[ex_idx] = _to_float(item.get("value"))
                            all_exercicis.add(ex_idx)
                        ex_rows_by_ins[ins_id] = ex_map

                    for ex_idx in sorted(all_exercicis):
                        entries = []
                        for row in rows:
                            ins_id = row.get("inscripcio_id")
                            if ins_id in (None, ""):
                                continue
                            if ex_idx not in (ex_rows_by_ins.get(ins_id) or {}):
                                continue
                            entries.append({"row": row, "base": ex_rows_by_ins[ins_id][ex_idx]})

                        unit_points = _compute_victory_points_for_entries(
                            entries,
                            ordre_principal,
                            victories_cfg,
                            forced_app_ids=[app_id],
                            forced_exercici_ids=[ex_idx],
                        )
                        for ins_id, pts in unit_points.items():
                            points_by_ins[ins_id].append(pts)

                    for row in rows:
                        ins_id = row.get("inscripcio_id")
                        if ins_id in (None, ""):
                            continue
                        row["by_app"][app_id] = float(
                            _apply_simple_agg(points_by_ins.get(ins_id, []), agg_victories_exercicis)
                        )
                    continue

                if mode_vict_camps == "separat" and mode_vict_exercicis == "separat":
                    all_exercicis = set()
                    for field_code in app_fields_by_app.get(app_id, []):
                        ex_rows_by_ins = {}
                        for row in rows:
                            ins_id = row.get("inscripcio_id")
                            if ins_id in (None, ""):
                                continue
                            selected_rows = _selected_field_rows_for_app(ins_id, app_id, field_code)
                            ex_map = {}
                            for item in selected_rows:
                                try:
                                    ex_idx = int(item.get("exercici"))
                                except Exception:
                                    continue
                                ex_map[ex_idx] = _to_float(item.get("value"))
                                all_exercicis.add(ex_idx)
                            ex_rows_by_ins[ins_id] = ex_map

                        for ex_idx in sorted(all_exercicis):
                            entries = []
                            for row in rows:
                                ins_id = row.get("inscripcio_id")
                                if ins_id in (None, ""):
                                    continue
                                if ex_idx not in (ex_rows_by_ins.get(ins_id) or {}):
                                    continue
                                entries.append({"row": row, "base": ex_rows_by_ins[ins_id][ex_idx]})

                            unit_points = _compute_victory_points_for_entries(
                                entries,
                                ordre_principal,
                                victories_cfg,
                                forced_app_ids=[app_id],
                                forced_exercici_ids=[ex_idx],
                                forced_camps=[field_code],
                            )
                            for ins_id, pts in unit_points.items():
                                points_by_ins_ex[ins_id][ex_idx].append(pts)

                    for row in rows:
                        ins_id = row.get("inscripcio_id")
                        if ins_id in (None, ""):
                            continue
                        ex_totals = []
                        for ex_idx in sorted((points_by_ins_ex.get(ins_id) or {}).keys()):
                            ex_totals.append(
                                _apply_simple_agg(
                                    (points_by_ins_ex.get(ins_id) or {}).get(ex_idx, []),
                                    agg_victories_camps,
                                )
                            )
                        row["by_app"][app_id] = float(
                            _apply_simple_agg(ex_totals, agg_victories_exercicis)
                        )
                    continue

            for row in rows:
                row["score"] = float(_apply_simple_agg(list((row.get("by_app") or {}).values()), agg_aparells))

    out = {}

    if tipus == "equips":
        resolved_team_by_ins_id = _build_resolved_team_by_ins_id(
            ins_list,
            team_mode=team_mode,
            team_context_code=team_context_code,
            assignment_fallback=assignment_source.get("fallback"),
            team_assignment_map=team_assignment_map,
        )
        grouped = _build_team_grouped(
            ins_list=ins_list,
            team_mode=team_mode,
            equips_cfg=equips_cfg,
            aparells=aparells,
            team_notes_by_app=team_notes_by_app,
            all_ins_by_id=all_ins_by_id,
            filtres=filtres,
            part_entries=part_entries,
            part_custom_idx=part_custom_idx,
            particions_config=particions_config,
            team_context_code=team_context_code,
            assignment_fallback=assignment_source.get("fallback"),
            team_assignment_map=team_assignment_map,
            resolved_team_by_ins_id=resolved_team_by_ins_id,
        )
        metrics_runtime["grouped"] = grouped
        out = _build_team_rows(
            grouped,
            team_mode=team_mode,
            aparells=aparells,
            equips_cfg=equips_cfg,
            competicio=competicio,
            part_entries=part_entries,
            part_custom_idx=part_custom_idx,
            particions_config=particions_config,
            per_ins=per_ins,
            agg_aparells=agg_aparells,
            exercise_selection_scope=exercise_selection_scope,
            allow_main_participant_selection_step=allow_main_participant_selection_step,
            allow_global_participant_selection_step=allow_global_participant_selection_step,
            desempat=desempat,
            get_main_selected_rows_agg_for_team=_get_main_selected_rows_agg_for_team,
            get_selected_rows_agg_for_derived_team=_get_selected_rows_agg_for_derived_team,
            get_selected_rows_agg_for_ins=_get_selected_rows_agg_for_ins,
            resolve_agregacio_exercicis_for_app=resolve_agregacio_exercicis_for_app,
            resolve_participants_for_app=resolve_participants_for_app,
            resolve_global_participants=resolve_global_participants,
            global_member_agg_exercicis=agg_exercicis,
            tie_key_resolver=_tie_key,
            is_pipeline_tie=_is_pipeline_tie,
            pipeline_metric_map_for_crit=_pipeline_metric_map_for_crit,
            calc_metric_value_for_native_team=calc_metric_value_for_native_team,
            calc_metric_value_for_group=calc_metric_value_for_group,
        )

        for pkey, rows in out.items():
            ranked = engine_rank_rows(rows, desempat, presentacio, ordre_principal=ordre_principal, entity_mode=True)
            out[pkey] = detail_runtime.attach_display_cells(ranked, entity_mode=True)
        return out

    if tipus == "entitat":
        for pkey, rows in per_particio.items():
            by_ent = defaultdict(list)
            for r in rows:
                by_ent[r.get("entitat_nom") or ""].append(r)

            ent_rows = []
            for ent_nom, items in by_ent.items():
                ent_score = sum([_to_float(x["score"]) for x in items])
                ent_tie = {}
                for t in desempat or []:
                    tkey = _tie_key(t)
                    if not tkey:
                        continue
                    if _is_pipeline_tie(t):
                        ent_tie[tkey] = float(
                            _pipeline_metric_map_for_crit(t).get(("entitat", _normalized_text_token(ent_nom)), 0.0)
                        )
                    else:
                        ent_tie[tkey] = sum([_to_float((x.get("tie") or {}).get(tkey, 0.0)) for x in items])

                ent_rows.append({
                    "entitat_nom": ent_nom,
                    "score": float(ent_score),
                    "tie": ent_tie,
                    "participants": len(items),
                    "_member_ids": [x.get("inscripcio_id") for x in items if x.get("inscripcio_id") is not None],
                })

            ranked = engine_rank_rows(ent_rows, desempat, presentacio, ordre_principal=ordre_principal, entity_mode=True)
            out[pkey] = detail_runtime.attach_display_cells(ranked, entity_mode=True)
        return out

    for pkey, rows in per_particio.items():
        ranked = engine_rank_rows(rows, desempat, presentacio, ordre_principal=ordre_principal, entity_mode=False)
        out[pkey] = detail_runtime.attach_display_cells(ranked, entity_mode=False)
    return out
