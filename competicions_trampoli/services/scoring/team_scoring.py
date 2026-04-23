from __future__ import annotations

import ast
import copy
import re
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Tuple

from django.apps import apps
from django.db import transaction

from ...models import Equip, Inscripcio, InscripcioEquipAssignacio
from ...models.competicio import (
    Aparell,
    CompeticioAparell,
    CompeticioAparellEquipContextSource,
    InscripcioAparellExclusio,
)
from .judge_presence import is_strict_presence_field, presence_key
from ..teams.team_series import enrich_team_subjects_with_series


def _team_subject_model():
    return apps.get_model("competicions_trampoli", "TeamCompetitiveSubject")


MEMBER_CODE_SUFFIX_RE = re.compile(r"__m\d+$")
MEMBER_CODE_SLOT_RE = re.compile(r"__m(?P<slot>\d+)$")
TEAM_MEMBER_KEYS_HELPERS = {
    "members_sum",
    "members_avg",
    "members_min",
    "members_max",
    "members_count",
    "member_treatment",
}
TEAM_MEMBER_AGG_HELPERS = set(TEAM_MEMBER_KEYS_HELPERS)
TEAM_MEMBER_PRESERVING_CALLS = {
    "row_custom_compute",
    "column_custom_compute",
    "row_custom_agregation",
    "exec_by_judge",
    "select_sum",
    "best_n",
    "sum",
    "avg",
    "min",
    "max",
    "float",
}
KIND_MEMBER_SCALAR = "member_scalar"
KIND_MEMBER_LIST = "member_list"
KIND_MEMBER_MATRIX = "member_matrix"
KIND_SHARED_SCALAR = "shared_scalar"
KIND_SHARED_LIST = "shared_list"
KIND_SHARED_MATRIX = "shared_matrix"
SCALAR_KINDS = {KIND_MEMBER_SCALAR, KIND_SHARED_SCALAR}
MEMBER_KINDS = {KIND_MEMBER_SCALAR, KIND_MEMBER_LIST, KIND_MEMBER_MATRIX}
SHARED_KINDS = {KIND_SHARED_SCALAR, KIND_SHARED_LIST, KIND_SHARED_MATRIX}
PERMISSION_MEMBER_MODE_SINGLE = "single"
PERMISSION_MEMBER_MODE_SUBSET = "subset"
PERMISSION_MEMBER_MODE_ALL = "all"
PERMISSION_MEMBER_MODES = {
    PERMISSION_MEMBER_MODE_SINGLE,
    PERMISSION_MEMBER_MODE_SUBSET,
    PERMISSION_MEMBER_MODE_ALL,
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


def _kind_is_member(kind: str) -> bool:
    return kind in MEMBER_KINDS


def _kind_is_scalar(kind: str) -> bool:
    return kind in SCALAR_KINDS


def _kind_for_scope(scope: str, suffix: str) -> str:
    return f"{'member' if scope == 'member' else 'shared'}_{suffix}"


def _field_kind(field: Dict[str, Any]) -> str:
    scope = str(field.get("scope") or "member").strip().lower() or "member"
    ftype = str(field.get("type") or "number").strip().lower() or "number"
    if ftype == "number":
        suffix = "scalar"
    elif ftype == "list":
        suffix = "list"
    else:
        suffix = "matrix"
    return _kind_for_scope(scope, suffix)


def _resolve_kind_from_name(name: str, kind_env: Dict[str, str]) -> str:
    return str(kind_env.get(str(name), KIND_SHARED_SCALAR))


def _resolve_kind_from_node(node: ast.AST, kind_env: Dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return _resolve_kind_from_name(node.id, kind_env)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _resolve_kind_from_name(str(node.value), kind_env)
    return KIND_SHARED_SCALAR


def _binop_kind(left_kind: str, right_kind: str) -> str:
    if _kind_is_scalar(left_kind) and _kind_is_scalar(right_kind):
        if _kind_is_member(left_kind) or _kind_is_member(right_kind):
            return KIND_MEMBER_SCALAR
        return KIND_SHARED_SCALAR
    if left_kind == right_kind:
        return left_kind
    if _kind_is_member(left_kind) and right_kind in SHARED_KINDS:
        return left_kind
    if _kind_is_member(right_kind) and left_kind in SHARED_KINDS:
        return right_kind
    return KIND_SHARED_SCALAR


def infer_team_expr_kind(node: ast.AST, kind_env: Dict[str, str]) -> str:
    if isinstance(node, ast.Expression):
        return infer_team_expr_kind(node.body, kind_env)
    if isinstance(node, ast.Name):
        return _resolve_kind_from_name(node.id, kind_env)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return _resolve_kind_from_name(str(node.value), kind_env)
        return KIND_SHARED_SCALAR
    if isinstance(node, (ast.List, ast.Tuple)):
        kinds = [infer_team_expr_kind(elt, kind_env) for elt in node.elts]
        if any(_kind_is_member(kind) for kind in kinds):
            return KIND_MEMBER_LIST
        return KIND_SHARED_LIST
    if isinstance(node, ast.UnaryOp):
        return infer_team_expr_kind(node.operand, kind_env)
    if isinstance(node, ast.Subscript):
        base_kind = infer_team_expr_kind(node.value, kind_env)
        if base_kind == KIND_MEMBER_MATRIX:
            return KIND_MEMBER_LIST
        if base_kind == KIND_SHARED_MATRIX:
            return KIND_SHARED_LIST
        if base_kind == KIND_MEMBER_LIST:
            return KIND_MEMBER_SCALAR
        if base_kind == KIND_SHARED_LIST:
            return KIND_SHARED_SCALAR
        return base_kind
    if isinstance(node, ast.BinOp):
        return _binop_kind(
            infer_team_expr_kind(node.left, kind_env),
            infer_team_expr_kind(node.right, kind_env),
        )
    if isinstance(node, ast.Call):
        fn_name = node.func.id if isinstance(node.func, ast.Name) else ""
        args = list(node.args or [])
        if fn_name == "field" and args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
            return _resolve_kind_from_name(str(args[0].value), kind_env)
        if fn_name == "crash":
            src_kind = _resolve_kind_from_node(args[0], kind_env) if args else KIND_SHARED_LIST
            return KIND_MEMBER_LIST if _kind_is_member(src_kind) else KIND_SHARED_LIST
        if fn_name in TEAM_MEMBER_AGG_HELPERS:
            return KIND_SHARED_SCALAR
        if fn_name in {"row_custom_compute", "column_custom_compute", "select_sum"}:
            src_kind = _resolve_kind_from_node(args[0], kind_env) if args else KIND_SHARED_SCALAR
            return KIND_MEMBER_SCALAR if _kind_is_member(src_kind) else KIND_SHARED_SCALAR
        if fn_name in {"row_custom_agregation", "exec_by_judge", "best_n"}:
            src_kind = _resolve_kind_from_node(args[0], kind_env) if args else KIND_SHARED_LIST
            return KIND_MEMBER_LIST if _kind_is_member(src_kind) else KIND_SHARED_LIST
        if fn_name in {"sum", "avg", "min", "max"}:
            src_kind = infer_team_expr_kind(args[0], kind_env) if args else KIND_SHARED_SCALAR
            return KIND_MEMBER_SCALAR if _kind_is_member(src_kind) else KIND_SHARED_SCALAR
        if fn_name == "float":
            src_kind = infer_team_expr_kind(args[0], kind_env) if args else KIND_SHARED_SCALAR
            return KIND_MEMBER_SCALAR if src_kind == KIND_MEMBER_SCALAR else KIND_SHARED_SCALAR
        if fn_name in TEAM_MEMBER_PRESERVING_CALLS:
            src_kind = _resolve_kind_from_node(args[0], kind_env) if args else KIND_SHARED_SCALAR
            return KIND_MEMBER_SCALAR if _kind_is_member(src_kind) else KIND_SHARED_SCALAR
        return KIND_SHARED_SCALAR
    return KIND_SHARED_SCALAR


def _slotify_member_expr(
    node: ast.AST,
    slot: int,
    *,
    name_replacements: Dict[str, List[str]],
    string_replacements: Dict[str, List[str]],
) -> ast.AST:
    class Transformer(ast.NodeTransformer):
        def visit_Name(self, inner_node):
            runtime_names = name_replacements.get(str(inner_node.id)) or []
            if slot - 1 < len(runtime_names):
                return ast.copy_location(ast.Name(id=runtime_names[slot - 1], ctx=ast.Load()), inner_node)
            return inner_node

        def visit_Constant(self, inner_node):
            if isinstance(inner_node.value, str):
                runtime_codes = string_replacements.get(str(inner_node.value)) or []
                if slot - 1 < len(runtime_codes):
                    return ast.copy_location(ast.Constant(value=runtime_codes[slot - 1]), inner_node)
            return inner_node

    cloned = copy.deepcopy(node)
    cloned = Transformer().visit(cloned)
    ast.fix_missing_locations(cloned)
    return cloned


def _expand_member_aggregate_calls(
    node: ast.AST,
    *,
    kind_env: Dict[str, str],
    name_replacements: Dict[str, List[str]],
    string_replacements: Dict[str, List[str]],
    member_count: int,
) -> ast.AST:
    class Transformer(ast.NodeTransformer):
        def visit_Call(self, inner_node):
            inner_node = self.generic_visit(inner_node)
            fn_name = inner_node.func.id if isinstance(inner_node.func, ast.Name) else ""
            if fn_name not in TEAM_MEMBER_AGG_HELPERS or not inner_node.args:
                return inner_node
            source_expr = inner_node.args[0]
            if infer_team_expr_kind(source_expr, kind_env) != KIND_MEMBER_SCALAR:
                return inner_node
            inner_node.args[0] = ast.List(
                elts=[
                    _slotify_member_expr(
                        source_expr,
                        slot,
                        name_replacements=name_replacements,
                        string_replacements=string_replacements,
                    )
                    for slot in range(1, max(0, int(member_count or 0)) + 1)
                ],
                ctx=ast.Load(),
            )
            return inner_node

    cloned = copy.deepcopy(node)
    cloned = Transformer().visit(cloned)
    ast.fix_missing_locations(cloned)
    return cloned


def expand_team_schema_for_member_count(schema: dict, member_count: int) -> dict:
    if not isinstance(schema, dict):
        return {}
    expanded = copy.deepcopy(schema)
    fields = expanded.get("fields") if isinstance(expanded.get("fields"), list) else []
    computed = expanded.get("computed") if isinstance(expanded.get("computed"), list) else []
    ui = expanded.get("ui") if isinstance(expanded.get("ui"), dict) else {}
    columns = ui.get("columns") if isinstance(ui.get("columns"), list) else []

    member_count = max(0, int(member_count or 0))
    name_replacements: Dict[str, List[str]] = {}
    string_replacements: Dict[str, List[str]] = {}
    kind_env: Dict[str, str] = {}
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
        kind_env[code] = _field_kind(field)
        if base_var:
            kind_env[base_var] = kind_env[code]
        if scope != "member":
            field["scope"] = "shared"
            new_fields.append(field)
            continue

        name_replacements[code] = []
        string_replacements[code] = []
        if base_var:
            name_replacements[base_var] = []
        for member_slot in range(1, member_count + 1):
            cloned = copy.deepcopy(field)
            cloned["scope"] = "member"
            cloned["member_slot"] = member_slot
            cloned["base_code"] = code
            cloned["code"] = member_runtime_code(code, member_slot)
            name_replacements[code].append(cloned["code"])
            string_replacements[code].append(cloned["code"])
            if base_var:
                cloned["base_var"] = base_var
                cloned["var"] = member_runtime_var(base_var, member_slot)
                name_replacements[base_var].append(cloned["var"])
            label = str(cloned.get("label") or code or "").strip()
            cloned["label"] = f"{label} · Individual {member_slot}".strip()
            new_fields.append(cloned)

    expanded["fields"] = new_fields

    expanded_cols: List[str] = []
    if columns:
        for col in columns:
            field = field_by_code.get(str(col))
            if field and str(field.get("scope") or "member").strip().lower() == "member":
                expanded_cols.extend(name_replacements.get(str(col), []))
            else:
                expanded_cols.append(col)

    new_computed: List[Dict[str, Any]] = []
    for comp in computed:
        if not isinstance(comp, dict):
            continue
        code = str(comp.get("code") or "").strip()
        base_var = str(comp.get("var") or "").strip()
        formula = str(comp.get("formula") or "").strip()
        expr = ast.parse(formula, mode="eval").body if formula else ast.Constant(value=0)
        kind = infer_team_expr_kind(expr, kind_env)

        if kind in MEMBER_KINDS:
            name_replacements[code] = []
            string_replacements[code] = []
            if base_var:
                name_replacements[base_var] = []
            for member_slot in range(1, member_count + 1):
                cloned = copy.deepcopy(comp)
                cloned["member_slot"] = member_slot
                cloned["base_code"] = code
                cloned["code"] = member_runtime_code(code, member_slot)
                name_replacements[code].append(cloned["code"])
                string_replacements[code].append(cloned["code"])
                if base_var:
                    cloned["base_var"] = base_var
                    cloned["var"] = member_runtime_var(base_var, member_slot)
                    name_replacements[base_var].append(cloned["var"])
                if formula:
                    cloned["formula"] = ast.unparse(
                        _slotify_member_expr(
                            expr,
                            member_slot,
                            name_replacements=name_replacements,
                            string_replacements=string_replacements,
                        )
                    )
                new_computed.append(cloned)
            if columns:
                expanded_cols.extend(name_replacements.get(code, []))
        else:
            cloned = copy.deepcopy(comp)
            if formula:
                cloned["formula"] = ast.unparse(
                    _expand_member_aggregate_calls(
                        expr,
                        kind_env=kind_env,
                        name_replacements=name_replacements,
                        string_replacements=string_replacements,
                        member_count=member_count,
                    )
                )
            new_computed.append(cloned)
            if columns:
                expanded_cols.append(code)

        kind_env[code] = kind
        if base_var:
            kind_env[base_var] = kind

    expanded["computed"] = new_computed
    if columns:
        seen_cols: List[str] = []
        for col in expanded_cols:
            if col not in seen_cols:
                seen_cols.append(col)
        ui["columns"] = seen_cols
        expanded["ui"] = ui

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
    rows = (
        InscripcioEquipAssignacio.objects
        .filter(competicio=competicio, context=context)
        .select_related("inscripcio__grup_competicio")
        .order_by("inscripcio__grup_competicio__display_num", "inscripcio__ordre_competicio", "inscripcio__ordre_sortida", "inscripcio_id")
    )
    for row in rows:
        ins = getattr(row, "inscripcio", None)
        if ins is None:
            continue
        grouped.setdefault(int(row.equip_id), []).append(ins)
    return grouped


def _subject_label(equip: Equip, context_name: str, members: List[Inscripcio]) -> str:
    max_length = 255
    member_names = [str(getattr(member, "nom_i_cognoms", "") or "").strip() for member in members if member is not None]
    team_name = str(getattr(equip, "nom", "") or f"Equip {getattr(equip, 'id', '')}").strip()
    base_label = f"{context_name} - {team_name}".strip(" -")
    if not member_names:
        return base_label[:max_length]

    members_label = ", ".join(member_names)
    full_label = f"{base_label} ({members_label})"
    if len(full_label) <= max_length:
        return full_label

    if len(base_label) >= max_length:
        return f"{base_label[:max_length - 3].rstrip()}..."

    available_for_members = max_length - len(base_label) - 3
    if available_for_members <= 3:
        return f"{base_label[:max_length - 3].rstrip()}..."

    trimmed_members = members_label[:available_for_members - 3].rstrip(" ,")
    if not trimmed_members:
        return base_label[:max_length]
    return f"{base_label} ({trimmed_members}...)"


def _expected_team_size_for_comp_aparell(comp_aparell: Optional[CompeticioAparell]) -> int:
    from ...models.scoring import ScoringSchema

    def _infer_from_context_sources() -> int:
        source_rows = list(
            CompeticioAparellEquipContextSource.objects
            .filter(competicio=comp_aparell.competicio, comp_aparell=comp_aparell)
            .values_list("context__code", "context__nom")
        )
        inferred_sizes = set()
        for context_code, context_name in source_rows:
            raw_tokens = [
                str(context_code or "").strip().lower(),
                str(context_name or "").strip().lower(),
            ]
            for token in raw_tokens:
                if not token:
                    continue
                if token.startswith("parell") or "parell" in token or any(
                    part in token for part in ("duo", "duet", "pair", "sync")
                ):
                    inferred_sizes.add(2)
                    break
                if "trio" in token:
                    inferred_sizes.add(3)
                    break
                if any(part in token for part in ("quartet", "quatre", "quad")):
                    inferred_sizes.add(4)
                    break
        if len(inferred_sizes) == 1:
            return next(iter(inferred_sizes))
        return 0

    if comp_aparell is None:
        return 0

    schema_obj = (
        ScoringSchema.objects
        .filter(comp_aparell=comp_aparell)
        .only("schema")
        .first()
    )
    if schema_obj is None and getattr(comp_aparell, "aparell_id", None):
        schema_obj = (
            ScoringSchema.objects
            .filter(aparell_id=comp_aparell.aparell_id)
            .only("schema")
            .first()
        )

    meta = (getattr(schema_obj, "schema", None) or {}).get("meta") if schema_obj is not None else {}
    if not isinstance(meta, dict):
        meta = {}
    try:
        expected = int(meta.get("expected_team_size") or 0)
    except Exception:
        expected = 0
    expected = max(0, expected)
    if expected:
        return expected
    return _infer_from_context_sources()


def sync_team_subject_for_members(
    competicio,
    comp_aparell: CompeticioAparell,
    context,
    equip: Equip,
    members: List[Inscripcio],
) -> TeamCompetitiveSubject:
    team_subject_model = _team_subject_model()
    member_ids = [int(member.id) for member in members if member is not None]
    member_names = [str(getattr(member, "nom_i_cognoms", "") or "").strip() for member in members if member is not None]
    label = _subject_label(equip, str(getattr(context, "nom", "") or getattr(context, "code", "")), members)
    subject, _created = team_subject_model.objects.update_or_create(
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
    expected_team_size = _expected_team_size_for_comp_aparell(comp_aparell)

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
                .filter(competicio=competicio, context=context, id__in=list(members_by_team.keys()))
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
                if expected_team_size and len(member_ids) != expected_team_size:
                    invalid_reasons.append(
                        f"L'equip ha de tenir {expected_team_size} membres per aquest aparell."
                    )
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
                    "label": str(getattr(subject_obj, "label", "") or "").strip(),
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

    subjects = enrich_team_subjects_with_series(competicio, comp_aparell, subjects)
    subjects.sort(
        key=lambda item: (
            int(item.get("serie_display_num") or 10**9),
            int(item.get("serie_order") or 10**9),
            int(item.get("group") or 0),
            int(item.get("order") or 0),
            str(item.get("context_name") or "").lower(),
            str(item.get("name") or "").lower(),
            int(item.get("subject_id") or 0),
        )
    )
    return subjects, issues


def build_team_subject_registry(competicio, comp_aparell: CompeticioAparell) -> Dict[str, Any]:
    subjects, issues = build_team_subjects_for_comp_aparell(competicio, comp_aparell)
    all_by_id: Dict[int, Dict[str, Any]] = {}
    eligible_by_id: Dict[int, Dict[str, Any]] = {}
    invalid_by_id: Dict[int, Dict[str, Any]] = {}

    for raw_subject in subjects:
        subject = dict(raw_subject or {})
        subject_id = int(subject.get("subject_id") or 0)
        if subject_id <= 0:
            continue
        all_by_id[subject_id] = subject
        if int(comp_aparell.id) in (subject.get("allowed_app_ids") or []):
            eligible_by_id[subject_id] = subject
        if subject.get("invalid_reasons") or str(subject.get("series_state") or "") == "invalid":
            invalid_by_id[subject_id] = subject

    return {
        "subjects": subjects,
        "issues": issues,
        "all_by_id": all_by_id,
        "eligible_by_id": eligible_by_id,
        "invalid_by_id": invalid_by_id,
    }


def team_subject_ids_for_serie_filter(subject_map: Dict[int, Dict[str, Any]], raw_serie_id) -> List[int]:
    clean_map = {
        int(subject_id): dict(subject or {})
        for subject_id, subject in (subject_map or {}).items()
        if int(subject_id or 0) > 0
    }
    if raw_serie_id in (None, ""):
        return list(clean_map.keys())
    try:
        clean_serie_id = int(raw_serie_id)
    except Exception:
        clean_serie_id = None
    if clean_serie_id:
        return [
            subject_id
            for subject_id, subject in clean_map.items()
            if int(subject.get("serie_id") or 0) == clean_serie_id
        ]
    return [
        subject_id
        for subject_id, subject in clean_map.items()
        if not subject.get("serie_id")
    ]


def eligible_team_ids_for_comp_aparell(competicio, comp_aparell: CompeticioAparell) -> List[int]:
    registry = build_team_subject_registry(competicio, comp_aparell)
    return list(registry["eligible_by_id"].keys())


def team_runtime_schema_for_subject(schema: dict, comp_aparell: Optional[CompeticioAparell], subject) -> dict:
    team_subject = subject.get("team_subject") if isinstance(subject, dict) else subject
    member_count = len(getattr(team_subject, "member_ids", []) or []) if team_subject is not None else 0
    return runtime_schema_for_comp_aparell(schema or {}, comp_aparell, member_count=member_count)


def runtime_input_codes(schema: dict) -> set:
    allowed = set()
    for field in (schema.get("fields") or []):
        if isinstance(field, dict) and field.get("code"):
            allowed.add(str(field["code"]))
            allowed.add(f"__crash__{field['code']}")
    return allowed


def parse_permission_member_slots(raw_value) -> List[int]:
    if raw_value in (None, "", [], (), set()):
        return []
    if isinstance(raw_value, (list, tuple, set)):
        raw_items = list(raw_value)
    else:
        raw_items = re.split(r"[\s,;]+", str(raw_value or "").strip())

    slots: List[int] = []
    for raw_item in raw_items:
        if raw_item in (None, ""):
            continue
        cleaned = str(raw_item).strip().upper()
        if cleaned.startswith("M"):
            cleaned = cleaned[1:]
        try:
            slot = int(cleaned)
        except Exception:
            continue
        if slot > 0:
            slots.append(slot)
    return slots


def _legacy_permission_member_slot(row: dict) -> Optional[int]:
    try:
        slot = int((row or {}).get("member_slot") or 0)
    except Exception:
        slot = 0
    if slot > 0:
        return slot

    runtime_code = str((row or {}).get("runtime_field_code") or "").strip()
    match = MEMBER_CODE_SLOT_RE.search(runtime_code)
    if not match:
        return None
    try:
        slot = int(match.group("slot"))
    except Exception:
        slot = 0
    return slot if slot > 0 else None


def normalize_permission_target(row: dict) -> Dict[str, Any]:
    clean_row = dict(row or {})
    scope = str(clean_row.get("scope") or "shared").strip().lower() or "shared"
    if scope != "member":
        clean_row.pop("member_mode", None)
        clean_row.pop("member_slots", None)
        clean_row.pop("member_slot", None)
        return clean_row

    member_mode = str(clean_row.get("member_mode") or "").strip().lower()
    member_slots = parse_permission_member_slots(clean_row.get("member_slots"))
    legacy_slot = _legacy_permission_member_slot(clean_row)
    if legacy_slot and legacy_slot not in member_slots:
        member_slots.append(legacy_slot)

    unique_slots: List[int] = []
    for slot in member_slots:
        if slot not in unique_slots:
            unique_slots.append(slot)

    if member_mode not in PERMISSION_MEMBER_MODES:
        member_mode = (
            PERMISSION_MEMBER_MODE_SINGLE
            if len(unique_slots) == 1
            else PERMISSION_MEMBER_MODE_ALL
        )

    clean_row["member_mode"] = member_mode
    if member_mode == PERMISSION_MEMBER_MODE_ALL:
        clean_row.pop("member_slots", None)
        clean_row.pop("member_slot", None)
    else:
        clean_row["member_slots"] = unique_slots
        if len(unique_slots) == 1:
            clean_row["member_slot"] = unique_slots[0]
        else:
            clean_row.pop("member_slot", None)
    return clean_row


def permission_target_label(row: dict) -> str:
    clean_row = normalize_permission_target(row)
    if str(clean_row.get("scope") or "shared").strip().lower() != "member":
        return "Compartit"

    member_mode = str(clean_row.get("member_mode") or PERMISSION_MEMBER_MODE_ALL).strip().lower()
    member_slots = parse_permission_member_slots(clean_row.get("member_slots"))
    if member_mode == PERMISSION_MEMBER_MODE_ALL:
        return "Tots"
    if not member_slots:
        return "Sense membres"
    return ",".join(f"M{slot}" for slot in member_slots)


def resolve_permission_runtime_entries(
    row: dict,
    comp_aparell: Optional[CompeticioAparell],
    *,
    member_count: int = 0,
) -> List[Dict[str, Any]]:
    clean_row = normalize_permission_target(row)
    code = str(clean_row.get("field_code") or "").strip()
    if not code:
        return []

    scope = str(clean_row.get("scope") or "shared").strip().lower() or "shared"
    if not is_team_context_app(comp_aparell) or scope != "member":
        shared_row = dict(clean_row)
        shared_row["runtime_field_code"] = str(shared_row.get("runtime_field_code") or code)
        shared_row["member_slot"] = None
        return [shared_row]

    member_count = max(0, int(member_count or 0))
    member_mode = str(clean_row.get("member_mode") or PERMISSION_MEMBER_MODE_ALL).strip().lower()
    if member_mode == PERMISSION_MEMBER_MODE_ALL:
        slots = list(range(1, member_count + 1))
    else:
        slots = [
            slot
            for slot in parse_permission_member_slots(clean_row.get("member_slots"))
            if slot > 0 and (member_count <= 0 or slot <= member_count)
        ]

    out: List[Dict[str, Any]] = []
    for slot in slots:
        resolved = dict(clean_row)
        resolved["runtime_field_code"] = member_runtime_code(code, slot)
        resolved["member_slot"] = slot
        resolved["member_label"] = f"M{slot}"
        out.append(resolved)
    return out


def permission_runtime_code(row: dict, comp_aparell: Optional[CompeticioAparell]) -> str:
    code = str((row or {}).get("field_code") or "").strip()
    if not code:
        return code
    resolved = resolve_permission_runtime_entries(row, comp_aparell, member_count=0)
    if not resolved:
        return code
    return str((resolved[0] or {}).get("runtime_field_code") or code)


def build_permission_label(row: dict) -> str:
    clean_row = normalize_permission_target(row)
    code = str(clean_row.get("field_code") or "").strip()
    scope = str(clean_row.get("scope") or "shared").strip().lower() or "shared"
    if scope != "member":
        return f"{code} · Compartit"
    return f"{code} · Individual · {permission_target_label(clean_row)}"


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
            presence_code = presence_key(code)
            if is_strict_presence_field(field) and presence_code in inputs:
                out[presence_code] = copy.deepcopy(inputs.get(presence_code))
            continue
        member_map = inputs.get(code) if isinstance(inputs.get(code), dict) else {}
        crash_map = inputs.get(f"__crash__{code}") if isinstance(inputs.get(f"__crash__{code}"), dict) else {}
        presence_code = presence_key(code)
        presence_map = inputs.get(presence_code) if is_strict_presence_field(field) and isinstance(inputs.get(presence_code), dict) else {}
        for idx, member_id in enumerate(member_ids, start=1):
            runtime_code = member_runtime_code(code, idx)
            if member_id in member_map:
                out[runtime_code] = copy.deepcopy(member_map[member_id])
            crash_value = crash_map.get(member_id)
            if crash_value is not None:
                out[f"__crash__{runtime_code}"] = copy.deepcopy(crash_value)
            if member_id in presence_map:
                out[presence_key(runtime_code)] = copy.deepcopy(presence_map.get(member_id))
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
            presence_code = presence_key(code)
            if is_strict_presence_field(field) and presence_code in inputs:
                out[presence_code] = copy.deepcopy(inputs.get(presence_code))
            continue

        member_map = {}
        crash_map = {}
        presence_map = {}
        for item in members:
            member_id = str(item["id"])
            runtime_code = member_runtime_code(code, item["slot"])
            if runtime_code in inputs:
                member_map[member_id] = copy.deepcopy(inputs.get(runtime_code))
            runtime_crash_code = f"__crash__{runtime_code}"
            if runtime_crash_code in inputs:
                crash_map[member_id] = copy.deepcopy(inputs.get(runtime_crash_code))
            runtime_presence_code = presence_key(runtime_code)
            if is_strict_presence_field(field) and runtime_presence_code in inputs:
                presence_map[member_id] = copy.deepcopy(inputs.get(runtime_presence_code))
        out[code] = member_map
        if crash_map:
            out[f"__crash__{code}"] = crash_map
        if presence_map:
            out[f"__presence__{code}"] = presence_map
    return out
