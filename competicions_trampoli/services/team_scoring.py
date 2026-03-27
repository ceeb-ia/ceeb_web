from __future__ import annotations

import ast
import copy
import re
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Tuple

from django.db import transaction

from ..models import Equip, Inscripcio, InscripcioEquipAssignacio
from ..models_trampoli import (
    Aparell,
    CompeticioAparell,
    CompeticioAparellEquipContextSource,
    InscripcioAparellExclusio,
)
from .equip_contexts import NATIVE_EQUIP_CONTEXT_CODE, normalize_equip_context_code

if TYPE_CHECKING:
    from ..models_scoring import TeamCompetitiveSubject


MEMBER_CODE_SUFFIX_RE = re.compile(r"__m\d+$")
TEAM_MEMBER_KEYS_HELPERS = {
    "members_sum",
    "members_avg",
    "members_min",
    "members_max",
    "members_count",
}


def is_team_context_app(comp_aparell: Optional[CompeticioAparell]) -> bool:
    return bool(comp_aparell and getattr(comp_aparell, "is_team_competition_unit", False))


def is_team_competition_unit(obj) -> bool:
    if obj is None:
        return False
    if isinstance(obj, Aparell):
        return obj.is_team_competition_unit
    return bool(getattr(obj, "is_team_competition_unit", False))


def subject_mode_for_schema(schema: dict, aparell: Optional[Aparell] = None) -> str:
    if is_team_competition_unit(aparell):
        return "team"
    return "individual"


def member_runtime_code(base_code: str, member_slot: int) -> str:
    return f"{base_code}__m{int(member_slot)}"


def member_runtime_var(base_var: str, member_slot: int) -> str:
    return f"{base_var}_m{int(member_slot)}"


def team_member_ids_for_subject(subject: TeamCompetitiveSubject) -> List[int]:
    ids = []
    for raw in list(subject.member_ids or []):
        try:
            value = int(raw)
        except Exception:
            continue
        if value > 0:
            ids.append(value)
    return ids


def team_member_payloads_for_subject(subject: TeamCompetitiveSubject) -> List[Dict[str, Any]]:
    ids = team_member_ids_for_subject(subject)
    names = list(subject.member_names or [])
    out = []
    for idx, member_id in enumerate(ids, start=1):
        name = str(names[idx - 1] if idx - 1 < len(names) else "").strip()
        out.append({
            "slot": idx,
            "id": member_id,
            "name": name or f"Membre {idx}",
            "code": str(member_id),
        })
    return out


def _replace_member_helper_calls(expr: str, replacements: Dict[str, List[str]]) -> str:
    if not isinstance(expr, str) or not expr.strip():
        return expr
    tree = ast.parse(expr, mode="eval")

    class Transformer(ast.NodeTransformer):
        def visit_Call(self, node):
            node = self.generic_visit(node)
            if not isinstance(node.func, ast.Name) or node.func.id not in TEAM_MEMBER_KEYS_HELPERS:
                return node
            if len(node.args) != 1 or not isinstance(node.args[0], ast.Name):
                return node
            base = node.args[0].id
            runtime_names = replacements.get(base) or []
            list_elts = [ast.Name(id=name, ctx=ast.Load()) for name in runtime_names]
            node.args = [ast.List(elts=list_elts, ctx=ast.Load())]
            return node

    tree = Transformer().visit(tree)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def expand_team_schema_for_member_count(schema: dict, member_count: int) -> dict:
    if not isinstance(schema, dict):
        return {}
    expanded = copy.deepcopy(schema)
    fields = expanded.get("fields") if isinstance(expanded.get("fields"), list) else []
    computed = expanded.get("computed") if isinstance(expanded.get("computed"), list) else []
    ui = expanded.get("ui") if isinstance(expanded.get("ui"), dict) else {}
    columns = ui.get("columns") if isinstance(ui.get("columns"), list) else []

    member_count = max(0, int(member_count or 0))
    replacements: Dict[str, List[str]] = {}
    var_replacements: Dict[str, List[str]] = {}
    new_fields: List[Dict[str, Any]] = []
    field_by_code = {
        str(field.get("code") or ""): field
        for field in fields
        if isinstance(field, dict) and field.get("code")
    }

    for field in fields:
        if not isinstance(field, dict):
            continue
        scope = str(field.get("scope") or "member").strip().lower() or "member"
        code = str(field.get("code") or "").strip()
        base_var = str(field.get("var") or "").strip()
        if scope != "member":
            field["scope"] = "shared"
            new_fields.append(field)
            continue

        replacements[code] = []
        if base_var:
            var_replacements[base_var] = []
        for member_slot in range(1, member_count + 1):
            cloned = copy.deepcopy(field)
            cloned["scope"] = "member"
            cloned["member_slot"] = member_slot
            cloned["base_code"] = code
            cloned["code"] = member_runtime_code(code, member_slot)
            replacements[code].append(cloned["code"])
            if base_var:
                cloned["base_var"] = base_var
                cloned["var"] = member_runtime_var(base_var, member_slot)
                var_replacements[base_var].append(cloned["var"])
            label = str(cloned.get("label") or code or "").strip()
            cloned["label"] = f"{label} · Individual {member_slot}".strip()
            new_fields.append(cloned)

    expanded["fields"] = new_fields

    if columns:
        expanded_cols: List[str] = []
        for col in columns:
            field = field_by_code.get(str(col))
            if field and str(field.get("scope") or "member").strip().lower() == "member":
                expanded_cols.extend(replacements.get(str(col), []))
            else:
                expanded_cols.append(col)
        ui["columns"] = expanded_cols
        expanded["ui"] = ui

    merge_replacements = {}
    merge_replacements.update(replacements)
    merge_replacements.update(var_replacements)
    for comp in computed:
        if not isinstance(comp, dict):
            continue
        formula = comp.get("formula")
        if isinstance(formula, str) and formula.strip():
            comp["formula"] = _replace_member_helper_calls(formula, merge_replacements)

    meta = expanded.get("meta") if isinstance(expanded.get("meta"), dict) else {}
    meta["subject_mode"] = "team"
    expanded["meta"] = meta
    return expanded


def runtime_schema_for_subject(schema: dict, *, aparell: Optional[Aparell] = None, member_count: int = 0) -> dict:
    if not is_team_competition_unit(aparell):
        out = copy.deepcopy(schema or {})
        meta = out.get("meta") if isinstance(out.get("meta"), dict) else {}
        meta["subject_mode"] = "individual"
        out["meta"] = meta
        for field in out.get("fields") or []:
            if isinstance(field, dict):
                field["scope"] = "member"
        return out
    return expand_team_schema_for_member_count(schema or {}, member_count)


def runtime_schema_for_comp_aparell(
    schema: dict,
    comp_aparell: Optional[CompeticioAparell],
    *,
    member_count: int = 0,
) -> dict:
    return runtime_schema_for_subject(
        schema or {},
        aparell=getattr(comp_aparell, "aparell", None),
        member_count=member_count,
    )


def _team_member_rows_for_context(competicio, context) -> Dict[int, List[Inscripcio]]:
    grouped: Dict[int, List[Inscripcio]] = {}
    context_code = normalize_equip_context_code(getattr(context, "code", ""))
    base_qs = (
        Inscripcio.objects
        .filter(competicio=competicio)
        .select_related("equip", "grup_competicio")
        .order_by("grup_competicio__display_num", "ordre_competicio", "ordre_sortida", "id")
    )
    if context_code == NATIVE_EQUIP_CONTEXT_CODE:
        for ins in base_qs.exclude(equip__isnull=True):
            grouped.setdefault(int(ins.equip_id), []).append(ins)
        return grouped

    rows = (
        InscripcioEquipAssignacio.objects
        .filter(competicio=competicio, context=context)
        .select_related("inscripcio__equip", "inscripcio__grup_competicio")
        .order_by("inscripcio__grup_competicio__display_num", "inscripcio__ordre_competicio", "inscripcio__ordre_sortida", "inscripcio_id")
    )
    for row in rows:
        ins = getattr(row, "inscripcio", None)
        if ins is None:
            continue
        grouped.setdefault(int(row.equip_id), []).append(ins)
    return grouped


def _subject_label(equip: Equip, context_name: str, members: List[Inscripcio]) -> str:
    member_names = [str(getattr(member, "nom_i_cognoms", "") or "").strip() for member in members if member is not None]
    team_name = str(getattr(equip, "nom", "") or f"Equip {getattr(equip, 'id', '')}").strip()
    if member_names:
        return f"{context_name} · {team_name} ({', '.join(member_names)})"
    return f"{context_name} · {team_name}"


def sync_team_subject_for_members(
    competicio,
    comp_aparell: CompeticioAparell,
    context,
    equip: Equip,
    members: List[Inscripcio],
) -> TeamCompetitiveSubject:
    member_ids = [int(member.id) for member in members if member is not None]
    member_names = [str(getattr(member, "nom_i_cognoms", "") or "").strip() for member in members if member is not None]
    label = _subject_label(equip, str(getattr(context, "nom", "") or getattr(context, "code", "")), members)
    subject, _created = TeamCompetitiveSubject.objects.update_or_create(
        competicio=competicio,
        comp_aparell=comp_aparell,
        context=context,
        equip=equip,
        defaults={
            "member_ids": member_ids,
            "member_names": member_names,
            "label": label,
        },
    )
    return subject


def build_team_subjects_for_comp_aparell(competicio, comp_aparell: CompeticioAparell) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not is_team_context_app(comp_aparell):
        return [], []

    source_rows = list(
        CompeticioAparellEquipContextSource.objects
        .filter(competicio=competicio, comp_aparell=comp_aparell)
        .select_related("context")
        .order_by("context__nom", "context__id")
    )
    if not source_rows:
        return [], [{
            "team_label": "Sense fonts configurades",
            "reasons": ["Aquest aparell d'equip no te cap context configurat al workspace d'equips."],
        }]

    excluded_ids = set(
        InscripcioAparellExclusio.objects
        .filter(comp_aparell=comp_aparell, inscripcio__competicio=competicio)
        .values_list("inscripcio_id", flat=True)
    )
    subjects: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []

    with transaction.atomic():
        for source in source_rows:
            context = source.context
            members_by_team = _team_member_rows_for_context(competicio, context)
            if not members_by_team:
                issues.append({
                    "context_code": str(getattr(context, "code", "") or ""),
                    "team_label": str(getattr(context, "nom", "") or getattr(context, "code", "Context")),
                    "reasons": ["Aquest context no te cap equip amb membres per aquest aparell."],
                })
                continue
            equips = list(
                Equip.objects
                .filter(competicio=competicio, id__in=list(members_by_team.keys()))
                .order_by("nom", "id")
            )
            equip_map = {equip.id: equip for equip in equips}
            for team_id, members in members_by_team.items():
                equip = equip_map.get(team_id)
                if equip is None:
                    continue
                invalid_reasons: List[str] = []
                member_ids = [int(member.id) for member in members]
                if not members:
                    invalid_reasons.append("L'equip no te membres assignats dins d'aquest context.")
                if len(set(member_ids)) != len(member_ids):
                    invalid_reasons.append("Hi ha membres duplicats dins del mateix equip.")
                if any(member_id in excluded_ids for member_id in member_ids):
                    invalid_reasons.append("Hi ha membres exclosos d'aquest aparell.")

                group_candidates = [int(getattr(member, "grup_competicio_id", 0) or 0) for member in members]
                group_id = next((gid for gid in group_candidates if gid), 0)
                meta_parts = []
                shared_entitats = sorted({
                    str(getattr(member, "entitat", "") or "").strip()
                    for member in members
                    if getattr(member, "entitat", None)
                })
                if shared_entitats:
                    meta_parts.append(", ".join(shared_entitats))

                subject_obj = sync_team_subject_for_members(competicio, comp_aparell, context, equip, members)
                subject = {
                    "id": f"team_unit:{subject_obj.id}",
                    "subject_id": int(subject_obj.id),
                    "subject_kind": "team_unit",
                    "equip_id": int(equip.id),
                    "context_id": int(context.id),
                    "context_code": str(getattr(context, "code", "") or ""),
                    "context_name": str(getattr(context, "nom", "") or getattr(context, "code", "")).strip(),
                    "name": str(getattr(equip, "nom", "") or f"Equip {equip.id}").strip(),
                    "members": [
                        {"id": int(member.id), "name": str(getattr(member, "nom_i_cognoms", "") or "").strip()}
                        for member in members
                    ],
                    "members_text": " + ".join(
                        str(getattr(member, "nom_i_cognoms", "") or "").strip() for member in members
                    ),
                    "order": min(
                        [int(getattr(member, "ordre_competicio", 10**9) or 10**9) for member in members] or [10**9]
                    ),
                    "group": group_id,
                    "group_display_num": getattr(next((m for m in members if getattr(m, "grup_competicio_id", None)), None), "grup", "") or "",
                    "allowed_app_ids": [] if invalid_reasons else [int(comp_aparell.id)],
                    "meta": " · ".join(meta_parts) if meta_parts else "",
                    "invalid_reasons": invalid_reasons,
                }
                if invalid_reasons:
                    issues.append(
                        {
                            "team_label": f"{subject['context_name']} · {subject['name']} ({subject.get('members_text') or 'sense membres'})",
                            "reasons": invalid_reasons,
                        }
                    )
                subjects.append(subject)

    subjects.sort(
        key=lambda item: (
            int(item.get("group") or 0),
            int(item.get("order") or 0),
            str(item.get("context_name") or "").lower(),
            str(item.get("name") or "").lower(),
            int(item.get("subject_id") or 0),
        )
    )
    return subjects, issues


def eligible_team_ids_for_comp_aparell(competicio, comp_aparell: CompeticioAparell) -> List[int]:
    subjects, _issues = build_team_subjects_for_comp_aparell(competicio, comp_aparell)
    return [int(subject["subject_id"]) for subject in subjects if int(comp_aparell.id) in (subject.get("allowed_app_ids") or [])]


def permission_runtime_code(row: dict, comp_aparell: Optional[CompeticioAparell]) -> str:
    code = str((row or {}).get("field_code") or "").strip()
    if not code:
        return code
    scope = str((row or {}).get("scope") or "shared").strip().lower() or "shared"
    if not is_team_context_app(comp_aparell) or scope != "member":
        return code
    return code


def build_permission_label(row: dict) -> str:
    code = str((row or {}).get("field_code") or "").strip()
    scope = str((row or {}).get("scope") or "shared").strip().lower() or "shared"
    return f"{code} · {'Individual' if scope == 'member' else 'Compartit'}"


def logical_team_inputs_to_runtime_inputs(inputs: dict, subject: TeamCompetitiveSubject, schema: dict) -> dict:
    if not isinstance(inputs, dict):
        return {}
    out = {}
    members = team_member_payloads_for_subject(subject)
    member_ids = [str(item["id"]) for item in members]
    for field in (schema.get("fields") or []):
        if not isinstance(field, dict) or not field.get("code"):
            continue
        code = str(field["code"])
        scope = str(field.get("scope") or "member").strip().lower() or "member"
        if scope != "member":
            if code in inputs:
                out[code] = copy.deepcopy(inputs.get(code))
            crash_code = f"__crash__{code}"
            if crash_code in inputs:
                out[crash_code] = copy.deepcopy(inputs.get(crash_code))
            continue
        member_map = inputs.get(code) if isinstance(inputs.get(code), dict) else {}
        crash_map = inputs.get(f"__crash__{code}") if isinstance(inputs.get(f"__crash__{code}"), dict) else {}
        for idx, member_id in enumerate(member_ids, start=1):
            runtime_code = member_runtime_code(code, idx)
            if member_id in member_map:
                out[runtime_code] = copy.deepcopy(member_map[member_id])
            crash_value = crash_map.get(member_id)
            if crash_value is not None:
                out[f"__crash__{runtime_code}"] = copy.deepcopy(crash_value)
    return out


def runtime_inputs_to_logical_team_inputs(inputs: dict, subject: TeamCompetitiveSubject, schema: dict) -> dict:
    if not isinstance(inputs, dict):
        return {}
    out = {}
    members = team_member_payloads_for_subject(subject)
    for field in (schema.get("fields") or []):
        if not isinstance(field, dict) or not field.get("code"):
            continue
        code = str(field["code"])
        scope = str(field.get("scope") or "member").strip().lower() or "member"
        if scope != "member":
            if code in inputs:
                out[code] = copy.deepcopy(inputs.get(code))
            crash_code = f"__crash__{code}"
            if crash_code in inputs:
                out[crash_code] = copy.deepcopy(inputs.get(crash_code))
            continue

        member_map = {}
        crash_map = {}
        for item in members:
            member_id = str(item["id"])
            runtime_code = member_runtime_code(code, item["slot"])
            if runtime_code in inputs:
                member_map[member_id] = copy.deepcopy(inputs.get(runtime_code))
            runtime_crash_code = f"__crash__{runtime_code}"
            if runtime_crash_code in inputs:
                crash_map[member_id] = copy.deepcopy(inputs.get(runtime_crash_code))
        out[code] = member_map
        if crash_map:
            out[f"__crash__{code}"] = crash_map
    return out
