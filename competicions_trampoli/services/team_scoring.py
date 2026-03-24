from __future__ import annotations

import ast
import copy
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..models import Equip, Inscripcio, InscripcioEquipAssignacio
from ..models_trampoli import CompeticioAparell, InscripcioAparellExclusio
from .equip_contexts import NATIVE_EQUIP_CONTEXT_CODE, normalize_equip_context_code


MEMBER_CODE_SUFFIX_RE = re.compile(r"__m\d+$")


def is_team_context_app(comp_aparell: Optional[CompeticioAparell]) -> bool:
    return bool(comp_aparell and getattr(comp_aparell, "participant_mode", "") == CompeticioAparell.ParticipantMode.TEAM_CONTEXT)


def subject_mode_for_schema(schema: dict, comp_aparell: Optional[CompeticioAparell] = None) -> str:
    meta = schema.get("meta") if isinstance(schema, dict) else {}
    mode = str((meta or {}).get("subject_mode") or "").strip().lower()
    if mode in {"individual", "team_context"}:
        return mode
    if is_team_context_app(comp_aparell):
        return "team_context"
    return "individual"


def expected_team_size_for_schema(schema: dict, comp_aparell: Optional[CompeticioAparell] = None) -> int:
    meta = schema.get("meta") if isinstance(schema, dict) else {}
    raw = (meta or {}).get("expected_team_size")
    try:
        val = int(raw)
    except Exception:
        val = 0
    if val >= 2:
        return val
    try:
        app_val = int(getattr(comp_aparell, "expected_team_size", 0) or 0)
    except Exception:
        app_val = 0
    return max(2, app_val or 2)


def member_runtime_code(base_code: str, member_slot: int) -> str:
    return f"{base_code}__m{int(member_slot)}"


def member_runtime_var(base_var: str, member_slot: int) -> str:
    return f"{base_var}_m{int(member_slot)}"


def _replace_member_tokens(expr: str, replacements: Dict[str, str]) -> str:
    if not isinstance(expr, str) or not expr.strip() or not replacements:
        return expr
    tree = ast.parse(expr, mode="eval")

    class Transformer(ast.NodeTransformer):
        def visit_Name(self, node):
            mapped = replacements.get(node.id)
            if mapped:
                return ast.copy_location(ast.Name(id=mapped, ctx=node.ctx), node)
            return node

    tree = Transformer().visit(tree)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def expand_team_scoped_schema(schema: dict, comp_aparell: Optional[CompeticioAparell] = None) -> dict:
    if not isinstance(schema, dict):
        return {}

    expanded = copy.deepcopy(schema)
    mode = subject_mode_for_schema(expanded, comp_aparell)
    meta = expanded.setdefault("meta", {})
    meta["subject_mode"] = mode
    if mode != "team_context":
        meta.setdefault("expected_team_size", None)
        for field in expanded.get("fields") or []:
            if isinstance(field, dict):
                field.setdefault("scope", "shared")
        return expanded

    expected_team_size = expected_team_size_for_schema(expanded, comp_aparell)
    meta["expected_team_size"] = expected_team_size
    fields = expanded.get("fields") if isinstance(expanded.get("fields"), list) else []
    already_expanded = any(
        isinstance(field, dict)
        and str(field.get("scope") or "shared").strip().lower() == "member"
        and (
            field.get("member_slot") is not None
            or field.get("base_code")
            or MEMBER_CODE_SUFFIX_RE.search(str(field.get("code") or ""))
        )
        for field in fields
    )
    if already_expanded:
        return expanded
    new_fields: List[Dict[str, Any]] = []
    member_replacements: Dict[str, str] = {}

    for field in fields:
        if not isinstance(field, dict):
            continue
        scope = str(field.get("scope") or "shared").strip().lower() or "shared"
        code = str(field.get("code") or "").strip()
        base_var = str(field.get("var") or "").strip()
        if scope != "member":
            field["scope"] = "shared"
            new_fields.append(field)
            continue

        for member_slot in range(1, expected_team_size + 1):
            cloned = copy.deepcopy(field)
            cloned["scope"] = "member"
            cloned["member_slot"] = member_slot
            cloned["base_code"] = code
            cloned["code"] = member_runtime_code(code, member_slot)
            if base_var:
                cloned["base_var"] = base_var
                cloned["var"] = member_runtime_var(base_var, member_slot)
                member_replacements[base_var] = cloned["var"]
            member_replacements[code] = cloned["code"]
            label = str(cloned.get("label") or code or "").strip()
            cloned["label"] = f"{label} · Membre {member_slot}".strip()
            new_fields.append(cloned)

    expanded["fields"] = new_fields

    ui = expanded.get("ui") if isinstance(expanded.get("ui"), dict) else {}
    cols = ui.get("columns") if isinstance(ui.get("columns"), list) else []
    if cols:
        expanded_cols: List[str] = []
        for col in cols:
            field = next((f for f in fields if isinstance(f, dict) and str(f.get("code") or "") == str(col)), None)
            if field and str(field.get("scope") or "shared").strip().lower() == "member":
                expanded_cols.extend(member_runtime_code(str(col), slot) for slot in range(1, expected_team_size + 1))
            else:
                expanded_cols.append(col)
        ui["columns"] = expanded_cols
        expanded["ui"] = ui

    for comp in expanded.get("computed") or []:
        if not isinstance(comp, dict):
            continue
        formula = comp.get("formula")
        if isinstance(formula, str) and formula.strip():
            comp["formula"] = _replace_member_tokens(formula, member_replacements)
        if comp.get("var") and isinstance(comp["var"], str):
            comp["var"] = comp["var"].strip()

    return expanded


def runtime_schema_for_comp_aparell(schema: dict, comp_aparell: Optional[CompeticioAparell]) -> dict:
    return expand_team_scoped_schema(schema or {}, comp_aparell=comp_aparell)


def permission_runtime_code(row: dict, comp_aparell: Optional[CompeticioAparell]) -> str:
    code = str((row or {}).get("field_code") or "").strip()
    scope = str((row or {}).get("scope") or "shared").strip().lower() or "shared"
    if scope != "member" or not is_team_context_app(comp_aparell):
        return code
    slot = int((row or {}).get("member_slot") or 1)
    return member_runtime_code(code, slot)


def build_permission_label(row: dict) -> str:
    code = str((row or {}).get("field_code") or "").strip()
    scope = str((row or {}).get("scope") or "shared").strip().lower() or "shared"
    if scope == "member":
        return f"{code} · Membre {int((row or {}).get('member_slot') or 1)}"
    return f"{code} · Compartit"


def get_member_field_slots(schema: dict) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for field in (schema.get("fields") or []):
        if not isinstance(field, dict):
            continue
        if str(field.get("scope") or "shared").strip().lower() != "member":
            continue
        code = str(field.get("code") or "").strip()
        out[code] = max(out.get(code, 0), 1)
    return out


def _team_member_rows_for_app(competicio, comp_aparell: CompeticioAparell) -> Dict[int, List[Inscripcio]]:
    context_code = normalize_equip_context_code(getattr(getattr(comp_aparell, "team_context", None), "code", ""))
    grouped: Dict[int, List[Inscripcio]] = {}
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

    ctx = getattr(comp_aparell, "team_context", None)
    if ctx is None:
        return grouped

    rows = (
        InscripcioEquipAssignacio.objects
        .filter(competicio=competicio, context=ctx)
        .select_related("inscripcio__equip", "inscripcio__grup_competicio")
        .order_by("inscripcio__grup_competicio__display_num", "inscripcio__ordre_competicio", "inscripcio__ordre_sortida", "inscripcio_id")
    )
    for row in rows:
        ins = getattr(row, "inscripcio", None)
        if ins is None:
            continue
        grouped.setdefault(int(row.equip_id), []).append(ins)
    return grouped


def _build_team_issue_label(equip: Equip, members: List[Inscripcio]) -> str:
    member_names = [str(getattr(m, "nom_i_cognoms", "") or "").strip() for m in members if m is not None]
    team_name = str(getattr(equip, "nom", "") or f"Equip {getattr(equip, 'id', '')}").strip()
    if member_names:
        return f"{team_name} ({', '.join(member_names)})"
    return team_name


def build_team_subjects_for_comp_aparell(competicio, comp_aparell: CompeticioAparell) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not is_team_context_app(comp_aparell):
        return [], []

    members_by_team = _team_member_rows_for_app(competicio, comp_aparell)
    equips = list(
        Equip.objects
        .filter(competicio=competicio, id__in=list(members_by_team.keys()))
        .order_by("nom", "id")
    )
    equip_map = {equip.id: equip for equip in equips}
    expected_size = int(getattr(comp_aparell, "expected_team_size", 0) or 0)
    issues: List[Dict[str, Any]] = []
    subjects: List[Dict[str, Any]] = []
    member_seen_counter: Counter[int] = Counter()

    excluded_pairs = set(
        InscripcioAparellExclusio.objects
        .filter(comp_aparell=comp_aparell, inscripcio__competicio=competicio)
        .values_list("inscripcio_id", flat=False)
    )
    excluded_ids = {int(pair[0]) for pair in excluded_pairs}

    for team_id, members in members_by_team.items():
        equip = equip_map.get(team_id)
        if equip is None:
            continue
        for member in members:
            member_seen_counter[int(member.id)] += 1

        member_ids = [int(m.id) for m in members]
        invalid_reasons: List[str] = []
        if expected_size and len(members) != expected_size:
            invalid_reasons.append(f"Mida invalida: {len(members)} membres, calen {expected_size}.")
        if any(member_id in excluded_ids for member_id in member_ids):
            invalid_reasons.append("Hi ha membres exclosos d'aquest aparell.")
        if len(set(member_ids)) != len(member_ids):
            invalid_reasons.append("Hi ha membres duplicats dins del mateix equip.")

        group_candidates = [int(getattr(m, "grup_competicio_id", 0) or 0) for m in members]
        group_id = next((g for g in group_candidates if g), 0)
        if not group_id and group_candidates:
            group_id = int(group_candidates[0] or 0)
        meta_parts = []
        shared_entitats = sorted({str(getattr(m, "entitat", "") or "").strip() for m in members if getattr(m, "entitat", None)})
        if shared_entitats:
            meta_parts.append(", ".join(shared_entitats))

        subject = {
            "id": f"equip:{equip.id}",
            "subject_id": int(equip.id),
            "subject_kind": "equip",
            "name": str(getattr(equip, "nom", "") or f"Equip {equip.id}").strip(),
            "members": [
                {
                    "id": int(member.id),
                    "name": str(getattr(member, "nom_i_cognoms", "") or "").strip(),
                }
                for member in members
            ],
            "members_text": " + ".join(str(getattr(m, "nom_i_cognoms", "") or "").strip() for m in members),
            "order": min([int(getattr(m, "ordre_competicio", 10**9) or 10**9) for m in members] or [10**9]),
            "group": group_id,
            "group_display_num": getattr(next((m for m in members if getattr(m, "grup_competicio_id", None)), None), "grup", "") or "",
            "allowed_app_ids": [int(comp_aparell.id)] if not invalid_reasons else [],
            "meta": " · ".join(meta_parts) if meta_parts else "",
            "invalid_reasons": invalid_reasons,
        }
        if invalid_reasons:
            issues.append(
                {
                    "equip_id": int(equip.id),
                    "team_label": _build_team_issue_label(equip, members),
                    "reasons": invalid_reasons,
                }
            )
        subjects.append(subject)

    for member_id, total in member_seen_counter.items():
        if total > 1:
            for subject in subjects:
                member_ids = [int(m["id"]) for m in subject.get("members") or []]
                if member_id in member_ids:
                    subject.setdefault("invalid_reasons", []).append("Un membre esta assignat a mes d'un equip en aquest context.")

    deduped_issues: List[Dict[str, Any]] = []
    seen_issue_keys = set()
    for subject in subjects:
        if not subject.get("invalid_reasons"):
            continue
        subject["allowed_app_ids"] = []
        issue_key = (subject["subject_id"], tuple(subject["invalid_reasons"]))
        if issue_key in seen_issue_keys:
            continue
        seen_issue_keys.add(issue_key)
        deduped_issues.append(
            {
                "equip_id": int(subject["subject_id"]),
                "team_label": f"{subject['name']} ({subject.get('members_text') or 'sense membres'})",
                "reasons": list(subject["invalid_reasons"]),
            }
        )

    return subjects, deduped_issues or issues


def eligible_team_ids_for_comp_aparell(competicio, comp_aparell: CompeticioAparell) -> List[int]:
    subjects, _issues = build_team_subjects_for_comp_aparell(competicio, comp_aparell)
    return [int(subject["subject_id"]) for subject in subjects if int(comp_aparell.id) in (subject.get("allowed_app_ids") or [])]
