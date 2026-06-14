from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace

from django.utils import timezone

from ...scoring.team_scoring import is_team_context_app
from ...teams.equip_contexts import (
    NATIVE_EQUIP_CONTEXT_CODE,
    normalize_equip_context_code,
    resolve_inscripcio_equip,
)
from ..partitions import BIRTH_YEAR_RANGE_PARTITION_CODE
from .common import (
    EXERCISE_SELECTION_SCOPE_TEAM_POOL,
    competition_reference_date,
    normalize_classificacio_equips_cfg,
    normalize_team_mode,
)
from .filter_runtime import _native_team_members_match_classificacio_filters
from .partition_runtime import (
    _bucket_edat,
    _partition_key_from_entries,
    _partition_key_from_entries_for_team,
    _resolve_particio_equip,
    _years_old,
)
from .score_values import _apply_simple_agg, _to_float
from .selection import _pick_participants


def _dedupe_int_ids_preserve_order(raw_ids):
    out = []
    seen = set()
    for raw_id in list(raw_ids or []):
        try:
            value = int(raw_id)
        except Exception:
            continue
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _legacy_native_equip_for_classificacio(inscripcio):
    equip = getattr(inscripcio, "equip", None)
    if equip is not None:
        return equip

    equip_id = getattr(inscripcio, "equip_id", None)
    if not equip_id:
        return None

    return SimpleNamespace(
        id=int(equip_id),
        nom=str(getattr(inscripcio, "equip__nom", "") or "").strip(),
    )


def _resolve_inscripcio_equip_for_classificacio(
    inscripcio,
    *,
    context_code=None,
    fallback=None,
    assignment_map=None,
):
    resolved = resolve_inscripcio_equip(
        inscripcio,
        context_code=context_code,
        fallback=fallback,
        assignment_map=assignment_map,
    )
    if resolved is not None:
        return resolved

    code = normalize_equip_context_code(context_code)
    fallback_code = normalize_equip_context_code(fallback) if fallback not in (None, "") else ""
    if code != NATIVE_EQUIP_CONTEXT_CODE and fallback_code != NATIVE_EQUIP_CONTEXT_CODE:
        return None
    return _legacy_native_equip_for_classificacio(inscripcio)


def _derived_team_cache_key(equip_id, member_ids):
    if equip_id not in (None, "", "__sense_equip__"):
        try:
            return f"equip:{int(equip_id)}"
        except Exception:
            pass

    mids = []
    for raw_member_id in member_ids or []:
        try:
            mids.append(int(raw_member_id))
        except Exception:
            continue
    mids = sorted(set(mids))
    return f"members:{','.join(str(member_id) for member_id in mids)}"


def _mapping_get(mapping, key, default=None):
    if not isinstance(mapping, dict):
        return default
    if key in mapping:
        return mapping.get(key, default)
    return mapping.get(str(key), default)


def _selected_row_value(row):
    if isinstance(row, dict):
        return row.get("value")
    return getattr(row, "value", None)


def _sorted_team_members(members):
    return sorted(
        members or [],
        key=lambda item: (
            int(getattr(item[0], "ordre_competicio", 10**9) or 10**9),
            int(getattr(item[0], "id", 10**9) or 10**9),
        ),
    )


def _build_manual_part_map(manual_defs):
    manual_map = {}
    for idx, item in enumerate(manual_defs or []):
        if not isinstance(item, dict):
            continue
        label = (
            str(item.get("label") or item.get("key") or f"Particio {idx + 1}").strip()
            or f"Particio {idx + 1}"
        )
        team_key = f"manual:{label}"
        for raw_id in item.get("equip_ids") or []:
            try:
                equip_id = int(raw_id)
            except Exception:
                continue
            if equip_id not in manual_map:
                manual_map[equip_id] = team_key
    return manual_map


def _resolve_team_age_partition(members, *, competicio=None, llindars=None, sense_data_label="Sense edat"):
    ref_date = competition_reference_date(competicio) or timezone.localdate()
    ages = []
    for member, _resolved_equip in members or []:
        age = _years_old(getattr(member, "data_naixement", None), ref_date)
        if age is not None:
            ages.append(age)
    age_max = max(ages) if ages else None
    return _bucket_edat(age_max, llindars or [], sense_data_label)


def _resolve_team_partition_runtime(equips_cfg, *, use_native_team_mode):
    cfg = normalize_classificacio_equips_cfg(equips_cfg)
    if use_native_team_mode:
        return {
            "include_sense_equip": False,
            "manual_map": {},
            "age_active": False,
            "age_label_empty": "Sense edat",
            "llindars": [],
            "combine_manual_age": False,
        }

    age_cfg = cfg.get("particio_edat") or {}
    llindars = []
    for raw_value in age_cfg.get("llindars") or []:
        try:
            llindars.append(int(raw_value))
        except Exception:
            continue

    return {
        "include_sense_equip": bool(cfg.get("incloure_sense_equip", False)),
        "manual_map": _build_manual_part_map(cfg.get("particions_manuals") or []),
        "age_active": bool(age_cfg.get("activa", False)),
        "age_label_empty": (age_cfg.get("sense_data_label") or "Sense edat").strip() or "Sense edat",
        "llindars": llindars,
        "combine_manual_age": bool(cfg.get("combinar_manual_i_edat", False)),
    }


def _build_resolved_team_by_ins_id(
    ins_list,
    *,
    team_mode,
    team_context_code=None,
    assignment_fallback=None,
    team_assignment_map=None,
):
    if normalize_team_mode(team_mode) == "native_team":
        return {}

    resolved = {}
    for inscripcio in ins_list or []:
        try:
            ins_id = int(getattr(inscripcio, "id"))
        except Exception:
            continue
        resolved[ins_id] = _resolve_inscripcio_equip_for_classificacio(
            inscripcio,
            context_code=team_context_code,
            fallback=assignment_fallback,
            assignment_map=team_assignment_map,
        )
    return resolved


def _build_team_grouped(
    *,
    ins_list,
    team_mode,
    equips_cfg=None,
    aparells=None,
    team_notes_by_app=None,
    all_ins_by_id=None,
    filtres=None,
    part_entries=None,
    part_custom_idx=None,
    particions_config=None,
    team_context_code=None,
    assignment_fallback=None,
    team_assignment_map=None,
    resolved_team_by_ins_id=None,
):
    use_native_team_mode = normalize_team_mode(team_mode) == "native_team"
    partition_runtime = _resolve_team_partition_runtime(
        equips_cfg,
        use_native_team_mode=use_native_team_mode,
    )
    has_team_birth_partition = any(
        str((entry or {}).get("code") or "").strip() == BIRTH_YEAR_RANGE_PARTITION_CODE
        for entry in (part_entries or [])
    )
    grouped = defaultdict(lambda: defaultdict(list))

    if use_native_team_mode:
        team_app_ids = {
            int(getattr(comp_aparell, "id"))
            for comp_aparell in (aparells or [])
            if is_team_context_app(comp_aparell) and getattr(comp_aparell, "id", None) is not None
        }
        for app_id, rows in (team_notes_by_app or {}).items():
            try:
                app_id_int = int(app_id)
            except Exception:
                continue
            if app_id_int not in team_app_ids:
                continue
            for row in rows or []:
                subject = getattr(row, "team_subject", None)
                equip = getattr(subject, "equip", None)
                if subject is None or equip is None:
                    continue

                member_rows = []
                missing_members = False
                for member_id in _dedupe_int_ids_preserve_order(
                    getattr(subject, "member_ids", []) or []
                ):
                    member = _mapping_get(all_ins_by_id or {}, member_id)
                    if member is None:
                        missing_members = True
                        break
                    member_rows.append((member, equip))

                if missing_members or not _native_team_members_match_classificacio_filters(member_rows, filtres):
                    continue

                base_bucket = "__team_partition__" if has_team_birth_partition else "global"
                grouped[base_bucket].setdefault(int(equip.id), member_rows)
        return grouped

    effective_cfg = normalize_classificacio_equips_cfg(equips_cfg)
    if resolved_team_by_ins_id is None:
        assignment_source = effective_cfg.get("assignment_source") or {}
        resolved_team_by_ins_id = _build_resolved_team_by_ins_id(
            ins_list,
            team_mode=team_mode,
            team_context_code=team_context_code or effective_cfg.get("context_code"),
            assignment_fallback=(
                assignment_fallback
                if assignment_fallback is not None
                else assignment_source.get("fallback")
            ),
            team_assignment_map=team_assignment_map,
        )

    for inscripcio in ins_list or []:
        try:
            ins_id = int(getattr(inscripcio, "id"))
        except Exception:
            continue
        resolved_equip = resolved_team_by_ins_id.get(ins_id)
        if resolved_equip is None and not partition_runtime["include_sense_equip"]:
            continue

        if has_team_birth_partition:
            base_pkey = "__team_partition__"
        else:
            base_pkey = _partition_key_from_entries(
                inscripcio,
                part_entries,
                part_custom_idx,
                particions_config=particions_config,
            )
        team_id_key = getattr(resolved_equip, "id", "__sense_equip__") if resolved_equip is not None else "__sense_equip__"
        grouped[base_pkey][team_id_key].append((inscripcio, resolved_equip))

    return grouped


def _compose_team_tie(
    *,
    equip_id,
    member_ids,
    use_native_team_mode,
    desempat=None,
    tie_key_resolver=None,
    is_pipeline_tie=None,
    pipeline_metric_map_for_crit=None,
    calc_metric_value_for_native_team=None,
    calc_metric_value_for_group=None,
):
    team_tie = {}
    for criteri in desempat or []:
        tie_key = tie_key_resolver(criteri) if callable(tie_key_resolver) else ""
        if not tie_key:
            continue

        if callable(is_pipeline_tie) and is_pipeline_tie(criteri):
            try:
                team_key = int(equip_id)
            except Exception:
                team_key = None
            if team_key is None:
                team_tie[tie_key] = 0.0
            else:
                metric_map = (
                    pipeline_metric_map_for_crit(criteri)
                    if callable(pipeline_metric_map_for_crit)
                    else {}
                )
                team_tie[tie_key] = float((metric_map or {}).get(("equip", team_key), 0.0))
            continue

        if use_native_team_mode and equip_id is not None:
            value = (
                calc_metric_value_for_native_team(int(equip_id), criteri)
                if callable(calc_metric_value_for_native_team)
                else 0.0
            )
            team_tie[tie_key] = float(value)
            continue

        value = (
            calc_metric_value_for_group(member_ids, criteri)
            if callable(calc_metric_value_for_group)
            else 0.0
        )
        team_tie[tie_key] = float(value)

    return team_tie


def _build_team_by_app_score(
    *,
    equip_id,
    member_ids,
    members,
    aparells,
    use_native_team_mode,
    per_ins=None,
    exercise_selection_scope="",
    allow_main_participant_selection_step=False,
    get_main_selected_rows_agg_for_team=None,
    get_selected_rows_agg_for_derived_team=None,
    resolve_agregacio_exercicis_for_app=None,
    resolve_participants_for_app=None,
):
    derived_team_cache_key = _derived_team_cache_key(equip_id, member_ids)
    team_by_app = {}

    for comp_aparell in aparells or []:
        app_id = getattr(comp_aparell, "id", None)
        if app_id in (None, ""):
            continue
        app_id = int(app_id)

        if is_team_context_app(comp_aparell):
            if equip_id is None:
                continue
            rows_by_app = (
                get_main_selected_rows_agg_for_team(int(equip_id))
                if callable(get_main_selected_rows_agg_for_team)
                else {}
            )
            selected_rows = _mapping_get(rows_by_app or {}, app_id, [])
            if not selected_rows:
                continue
            agg_exercicis = (
                resolve_agregacio_exercicis_for_app(app_id)
                if callable(resolve_agregacio_exercicis_for_app)
                else "sum"
            )
            team_by_app[app_id] = float(
                _apply_simple_agg(
                    [_to_float(_selected_row_value(row)) for row in selected_rows],
                    agg_exercicis,
                )
            )
            continue

        if use_native_team_mode:
            continue

        if exercise_selection_scope == EXERCISE_SELECTION_SCOPE_TEAM_POOL:
            rows_by_app = (
                get_selected_rows_agg_for_derived_team(derived_team_cache_key, member_ids)
                if callable(get_selected_rows_agg_for_derived_team)
                else {}
            )
            selected_rows = _mapping_get(rows_by_app or {}, app_id, [])
            if selected_rows:
                agg_exercicis = (
                    resolve_agregacio_exercicis_for_app(app_id)
                    if callable(resolve_agregacio_exercicis_for_app)
                    else "sum"
                )
                team_by_app[app_id] = float(
                    _apply_simple_agg(
                        [_to_float(_selected_row_value(row)) for row in selected_rows],
                        agg_exercicis,
                    )
                )
            continue

        member_app_vals = []
        for member, _resolved_equip in members:
            member_payload = _mapping_get(per_ins or {}, getattr(member, "id", None), {}) or {}
            by_app_base = member_payload.get("by_app_base") or {}
            if app_id not in by_app_base and str(app_id) not in by_app_base:
                continue
            member_app_vals.append(_to_float(_mapping_get(by_app_base, app_id, 0.0)))

        if not member_app_vals:
            continue

        if allow_main_participant_selection_step:
            participants_cfg, agg_participants = (
                resolve_participants_for_app(app_id)
                if callable(resolve_participants_for_app)
                else ({"mode": "tots"}, "sum")
            )
            selected_member_vals = _pick_participants(
                member_app_vals,
                (participants_cfg or {}).get("mode"),
                int((participants_cfg or {}).get("n") or 1),
            )
            team_by_app[app_id] = float(_apply_simple_agg(selected_member_vals, agg_participants))
            continue

        team_by_app[app_id] = float(sum(member_app_vals))

    return team_by_app


def _build_global_member_score(
    *,
    member_ids,
    get_selected_rows_agg_for_ins=None,
    resolve_global_participants=None,
    global_member_agg_exercicis="sum",
):
    member_vals = []
    for member_id in member_ids or []:
        rows_by_app = (
            get_selected_rows_agg_for_ins(member_id)
            if callable(get_selected_rows_agg_for_ins)
            else {}
        )
        values = []
        for rows in (rows_by_app or {}).values():
            values.extend(_to_float(_selected_row_value(row)) for row in (rows or []))
        if values:
            member_vals.append(float(_apply_simple_agg(values, global_member_agg_exercicis)))

    if not member_vals:
        return 0.0

    participants_cfg, agg_participants = (
        resolve_global_participants()
        if callable(resolve_global_participants)
        else ({"mode": "tots"}, "sum")
    )
    selected_member_vals = _pick_participants(
        member_vals,
        (participants_cfg or {}).get("mode"),
        int((participants_cfg or {}).get("n") or 1),
    )
    return float(_apply_simple_agg(selected_member_vals, agg_participants))


def _build_team_rows(
    grouped,
    *,
    team_mode,
    aparells=None,
    equips_cfg=None,
    competicio=None,
    part_entries=None,
    part_custom_idx=None,
    particions_config=None,
    per_ins=None,
    agg_aparells="sum",
    exercise_selection_scope="",
    allow_main_participant_selection_step=False,
    allow_global_participant_selection_step=False,
    desempat=None,
    get_main_selected_rows_agg_for_team=None,
    get_selected_rows_agg_for_derived_team=None,
    get_selected_rows_agg_for_ins=None,
    resolve_agregacio_exercicis_for_app=None,
    resolve_participants_for_app=None,
    resolve_global_participants=None,
    global_member_agg_exercicis="sum",
    tie_key_resolver=None,
    is_pipeline_tie=None,
    pipeline_metric_map_for_crit=None,
    calc_metric_value_for_native_team=None,
    calc_metric_value_for_group=None,
):
    use_native_team_mode = normalize_team_mode(team_mode) == "native_team"
    partition_runtime = _resolve_team_partition_runtime(
        equips_cfg,
        use_native_team_mode=use_native_team_mode,
    )
    has_team_birth_partition = any(
        str((entry or {}).get("code") or "").strip() == BIRTH_YEAR_RANGE_PARTITION_CODE
        for entry in (part_entries or [])
    )

    out = {}
    for base_pkey, teams in (grouped or {}).items():
        for team_id_key, members in (teams or {}).items():
            if not members:
                continue

            members = _sorted_team_members(members)
            if team_id_key == "__sense_equip__":
                equip_id = None
                equip_nom = "Sense equip"
            else:
                equip_id = int(team_id_key)
                equip_obj = members[0][1]
                equip_nom = (str(getattr(equip_obj, "nom", None) or f"Equip {equip_id}").strip() or f"Equip {equip_id}")

            if has_team_birth_partition:
                base_partition_key = _partition_key_from_entries_for_team(
                    members,
                    part_entries,
                    part_custom_idx,
                    particions_config=particions_config,
                )
            else:
                base_partition_key = base_pkey

            if use_native_team_mode:
                final_pkey = base_partition_key
            else:
                manual_part = partition_runtime["manual_map"].get(equip_id) if equip_id is not None else None
                age_part = None
                if partition_runtime["age_active"] and not has_team_birth_partition:
                    age_part = _resolve_team_age_partition(
                        members,
                        competicio=competicio,
                        llindars=partition_runtime["llindars"],
                        sense_data_label=partition_runtime["age_label_empty"],
                    )
                team_part = _resolve_particio_equip(
                    manual_part,
                    age_part,
                    partition_runtime["combine_manual_age"],
                )
                if base_partition_key != "global" and team_part != "global":
                    final_pkey = f"{base_partition_key}|{team_part}"
                elif team_part != "global":
                    final_pkey = team_part
                else:
                    final_pkey = base_partition_key

            member_ids = [int(getattr(member, "id")) for member, _resolved_equip in members]
            if allow_global_participant_selection_step and not use_native_team_mode:
                team_score = _build_global_member_score(
                    member_ids=member_ids,
                    get_selected_rows_agg_for_ins=get_selected_rows_agg_for_ins,
                    resolve_global_participants=resolve_global_participants,
                    global_member_agg_exercicis=global_member_agg_exercicis,
                )
            else:
                team_by_app = _build_team_by_app_score(
                    equip_id=equip_id,
                    member_ids=member_ids,
                    members=members,
                    aparells=aparells,
                    use_native_team_mode=use_native_team_mode,
                    per_ins=per_ins,
                    exercise_selection_scope=exercise_selection_scope,
                    allow_main_participant_selection_step=allow_main_participant_selection_step,
                    get_main_selected_rows_agg_for_team=get_main_selected_rows_agg_for_team,
                    get_selected_rows_agg_for_derived_team=get_selected_rows_agg_for_derived_team,
                    resolve_agregacio_exercicis_for_app=resolve_agregacio_exercicis_for_app,
                    resolve_participants_for_app=resolve_participants_for_app,
                )
                team_score = float(_apply_simple_agg(list(team_by_app.values()), agg_aparells))
            team_tie = _compose_team_tie(
                equip_id=equip_id,
                member_ids=member_ids,
                use_native_team_mode=use_native_team_mode,
                desempat=desempat,
                tie_key_resolver=tie_key_resolver,
                is_pipeline_tie=is_pipeline_tie,
                pipeline_metric_map_for_crit=pipeline_metric_map_for_crit,
                calc_metric_value_for_native_team=calc_metric_value_for_native_team,
                calc_metric_value_for_group=calc_metric_value_for_group,
            )

            out.setdefault(final_pkey, []).append(
                {
                    "equip_id": equip_id,
                    "nom": equip_nom,
                    "participant": equip_nom,
                    "score": float(team_score),
                    "tie": team_tie,
                    "participants": len(members),
                    "_member_ids": member_ids,
                    "_team_mode": normalize_team_mode(team_mode),
                }
            )

    return out


def _build_team_grouped_and_rows(
    *,
    ins_list,
    team_mode,
    equips_cfg=None,
    aparells=None,
    team_notes_by_app=None,
    all_ins_by_id=None,
    filtres=None,
    part_entries=None,
    part_custom_idx=None,
    particions_config=None,
    team_context_code=None,
    assignment_fallback=None,
    team_assignment_map=None,
    resolved_team_by_ins_id=None,
    competicio=None,
    per_ins=None,
    agg_aparells="sum",
    exercise_selection_scope="",
    allow_main_participant_selection_step=False,
    allow_global_participant_selection_step=False,
    desempat=None,
    get_main_selected_rows_agg_for_team=None,
    get_selected_rows_agg_for_derived_team=None,
    get_selected_rows_agg_for_ins=None,
    resolve_agregacio_exercicis_for_app=None,
    resolve_participants_for_app=None,
    resolve_global_participants=None,
    global_member_agg_exercicis="sum",
    tie_key_resolver=None,
    is_pipeline_tie=None,
    pipeline_metric_map_for_crit=None,
    calc_metric_value_for_native_team=None,
    calc_metric_value_for_group=None,
):
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
        assignment_fallback=assignment_fallback,
        team_assignment_map=team_assignment_map,
        resolved_team_by_ins_id=resolved_team_by_ins_id,
    )
    rows = _build_team_rows(
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
        get_main_selected_rows_agg_for_team=get_main_selected_rows_agg_for_team,
        get_selected_rows_agg_for_derived_team=get_selected_rows_agg_for_derived_team,
        get_selected_rows_agg_for_ins=get_selected_rows_agg_for_ins,
        resolve_agregacio_exercicis_for_app=resolve_agregacio_exercicis_for_app,
        resolve_participants_for_app=resolve_participants_for_app,
        resolve_global_participants=resolve_global_participants,
        global_member_agg_exercicis=global_member_agg_exercicis,
        tie_key_resolver=tie_key_resolver,
        is_pipeline_tie=is_pipeline_tie,
        pipeline_metric_map_for_crit=pipeline_metric_map_for_crit,
        calc_metric_value_for_native_team=calc_metric_value_for_native_team,
        calc_metric_value_for_group=calc_metric_value_for_group,
    )
    return grouped, rows


__all__ = [
    "_build_resolved_team_by_ins_id",
    "_build_team_grouped",
    "_build_team_grouped_and_rows",
    "_build_team_rows",
    "_compose_team_tie",
    "_derived_team_cache_key",
    "_legacy_native_equip_for_classificacio",
    "_resolve_inscripcio_equip_for_classificacio",
]
