from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any, Dict, List, Set

from django.core.exceptions import ValidationError

from .team_scoring import (
    KIND_MEMBER_SCALAR,
    MEMBER_CODE_SUFFIX_RE,
    TEAM_MEMBER_KEYS_HELPERS,
    infer_team_expr_kind,
    runtime_schema_for_subject,
)

ALLOWED_FUNCTIONS: Set[str] = {
    "sum", "avg", "min", "max",
    "exec_by_judge", "select_sum", "best_n",
    "float", "field", "crash", "row_custom_compute",
    "column_custom_compute", "row_custom_agregation",
    *TEAM_MEMBER_KEYS_HELPERS,
}
RESERVED_NAMES: Set[str] = set(ALLOWED_FUNCTIONS) | {"params"}


@dataclass(frozen=True)
class Shape:
    rows: int | None
    cols: int | None


class TMat:
    def __init__(self, shape: Shape, name: str = ""):
        self.shape = shape
        self.name = name


def _field_shape(field: Dict[str, Any]) -> Shape:
    if not isinstance(field, dict):
        return Shape(1, 1)
    ftype = str(field.get("type") or "number").strip().lower() or "number"
    judges = int((((field.get("judges") or {}).get("count")) or 1))
    items = int((((field.get("items") or {}).get("count")) or 1))
    if ftype == "matrix":
        return Shape(max(1, judges), max(1, items))
    if ftype == "list":
        return Shape(max(1, judges), 1)
    return Shape(1, 1)


def _build_alias_map(fields: List[Dict[str, Any]], computed: List[Dict[str, Any]], params: Dict[str, Any]) -> Dict[str, str]:
    return _build_aliases(fields, computed, params)


def _resolve_name(name: str, aliases: Dict[str, str]) -> str:
    return str(aliases.get(name, name))


def _topo_sort(nodes: List[str], deps: Dict[str, Set[str]]) -> List[str]:
    ordered: List[str] = []
    temporary: Set[str] = set()
    permanent: Set[str] = set()

    def visit(node: str):
        if node in permanent:
            return
        if node in temporary:
            raise ValidationError(f"Dependencia circular detectada: {node}")
        temporary.add(node)
        for dep in deps.get(node, set()):
            if dep in deps:
                visit(dep)
        temporary.remove(node)
        permanent.add(node)
        ordered.append(node)

    for node in list(nodes or []):
        if node not in permanent:
            visit(node)
    return ordered


def _ast_parse(expr: str, loc: str):
    return _parse_formula(expr, loc)


def _combine_shapes(a: Shape, b: Shape) -> Shape:
    rows = max(int(a.rows or 1), int(b.rows or 1))
    cols = max(int(a.cols or 1), int(b.cols or 1))
    return Shape(rows, cols)


class DryRunEval(ast.NodeVisitor):
    def __init__(self, ctx: Dict[str, TMat]):
        self.ctx = ctx or {}

    def visit_Name(self, node):
        return self.ctx.get(node.id, TMat(Shape(1, 1), name=node.id))

    def visit_Constant(self, node):
        return TMat(Shape(1, 1), name=repr(getattr(node, "value", "")))

    def visit_Num(self, node):  # pragma: no cover - legacy ast nodes
        return TMat(Shape(1, 1), name=str(getattr(node, "n", "")))

    def visit_List(self, node):
        if not node.elts:
            return TMat(Shape(1, 1), name="list")
        current = TMat(Shape(1, 1), name="list")
        for elt in node.elts:
            current = TMat(_combine_shapes(current.shape, self.visit(elt).shape), name="list")
        return current

    def visit_Tuple(self, node):
        return self.visit_List(node)

    def visit_UnaryOp(self, node):
        return self.visit(node.operand)

    def visit_BinOp(self, node):
        left = self.visit(node.left)
        right = self.visit(node.right)
        return TMat(_combine_shapes(left.shape, right.shape), name="binop")

    def visit_Call(self, node):
        fn_name = ""
        if isinstance(node.func, ast.Name):
            fn_name = node.func.id
        args = [self.visit(arg) for arg in node.args]
        if fn_name in {"row_custom_compute", "exec_by_judge"} and args:
            src = args[0]
            return TMat(Shape(src.shape.rows, 1), name=fn_name)
        if fn_name == "column_custom_compute" and args:
            src = args[0]
            return TMat(Shape(1, src.shape.cols), name=fn_name)
        if fn_name == "field" and node.args and isinstance(node.args[0], ast.Constant):
            key = str(node.args[0].value)
            return self.ctx.get(key, TMat(Shape(1, 1), name=key))
        current = TMat(Shape(1, 1), name=fn_name or "call")
        for arg in args:
            current = TMat(_combine_shapes(current.shape, arg.shape), name=fn_name or "call")
        return current

    def generic_visit(self, node):
        return TMat(Shape(1, 1), name=node.__class__.__name__)


def is_identifier(name: str) -> bool:
    return isinstance(name, str) and name.isidentifier()


def _fmt_loc(prefix: str, idx: int | None, code: str | None) -> str:
    out = prefix
    if idx is not None:
        out += f"[{idx}]"
    if code:
        out += f"({code})"
    return out


def _parse_formula(expr: str, loc: str):
    try:
        return ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ValidationError(
            f"{loc}: sintaxi invalida a la formula: {exc.msg} (linia {exc.lineno}, col {exc.offset})"
        )


def _extract_names(tree: ast.AST) -> Set[str]:
    names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            raise ValidationError("No es permet acces per atribut a les formules.")
        if isinstance(node, ast.Name):
            names.add(node.id)
    return names


def _build_aliases(fields: List[Dict[str, Any]], computed: List[Dict[str, Any]], params: Dict[str, Any]) -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    if isinstance(params.get("aliases"), dict):
        for key, value in params["aliases"].items():
            if isinstance(key, str) and isinstance(value, str):
                aliases[key] = value
    for item in list(fields or []) + list(computed or []):
        if isinstance(item, dict) and item.get("var") and item.get("code"):
            aliases[str(item["var"])] = str(item["code"])
    return aliases


def _field_kind(field: Dict[str, Any], *, is_team: bool) -> str:
    scope = str(field.get("scope") or "member").strip().lower() or "member"
    ftype = str(field.get("type") or "number").strip().lower() or "number"
    prefix = "member" if (is_team and scope == "member") else "shared"
    if ftype == "number":
        return f"{prefix}_scalar"
    if ftype == "list":
        return f"{prefix}_list"
    return f"{prefix}_matrix"


def _validate_member_helper_calls(tree: ast.AST, kind_env: Dict[str, str], *, is_team: bool, loc: str, errors: List[str]) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        fn_name = node.func.id
        if fn_name not in TEAM_MEMBER_KEYS_HELPERS:
            continue
        if not is_team:
            errors.append(f"{loc}: {fn_name} nomes es permes en aparells globals d'equip.")
            continue
        if not node.args:
            errors.append(f"{loc}: {fn_name} requereix una font member_scalar.")
            continue
        arg_kind = infer_team_expr_kind(node.args[0], kind_env)
        if arg_kind != KIND_MEMBER_SCALAR:
            errors.append(
                f"{loc}: {fn_name} nomes admet fonts member_scalar; rebut {arg_kind}."
            )


def validate_schema(schema: Dict[str, Any], *, aparell=None) -> None:
    errors: List[str] = []
    if not isinstance(schema, dict):
        raise ValidationError("Schema: ha de ser un objecte (dict).")

    params = schema.get("params", {})
    meta = schema.get("meta", {})
    fields = schema.get("fields", [])
    computed = schema.get("computed", [])
    if not isinstance(params, dict):
        errors.append("Schema.params ha de ser un dict.")
        params = {}
    if meta is not None and not isinstance(meta, dict):
        errors.append("Schema.meta ha de ser un dict.")
        meta = {}
    if not isinstance(fields, list):
        errors.append("Schema.fields ha de ser una llista.")
        fields = []
    if not isinstance(computed, list):
        errors.append("Schema.computed ha de ser una llista.")
        computed = []

    is_team = bool(aparell and getattr(aparell, "is_team_competition_unit", False))
    field_codes: Set[str] = set()
    computed_codes: Set[str] = set()
    seen_vars: Set[str] = set()

    for idx, field in enumerate(fields):
        if not isinstance(field, dict):
            errors.append(f"fields[{idx}] ha de ser un objecte (dict).")
            continue
        code = str(field.get("code") or "").strip()
        var = str(field.get("var") or "").strip()
        scope = str(field.get("scope") or "member").strip().lower() or "member"
        loc = _fmt_loc("fields", idx, code)
        if not code:
            errors.append(f"{loc}: falta 'code'.")
            continue
        if MEMBER_CODE_SUFFIX_RE.search(code):
            errors.append(f"{loc}: el sufix '__mN' esta reservat per runtime.")
        if not is_identifier(code):
            errors.append(f"{loc}: 'code' no es un identificador Python valid.")
        if code in RESERVED_NAMES:
            errors.append(f"{loc}: 'code' reservat/no permes.")
        if code in field_codes or code in computed_codes:
            errors.append(f"{loc}: 'code' duplicat.")
        field_codes.add(code)
        if var:
            if not is_identifier(var):
                errors.append(f"{loc}: 'var' no es un identificador Python valid.")
            elif var in RESERVED_NAMES:
                errors.append(f"{loc}: 'var' reservat/no permes.")
            elif var in seen_vars:
                errors.append(f"{loc}: 'var' duplicat.")
            seen_vars.add(var)
        if scope not in {"member", "shared"}:
            errors.append(f"{loc}: scope invalid: {scope!r}.")
        elif not is_team and scope == "shared":
            errors.append(f"{loc}: un aparell global individual no pot declarar camps compartits.")
    for idx, comp in enumerate(computed):
        if not isinstance(comp, dict):
            errors.append(f"computed[{idx}] ha de ser un objecte (dict).")
            continue
        code = str(comp.get("code") or "").strip()
        var = str(comp.get("var") or "").strip()
        loc = _fmt_loc("computed", idx, code)
        if not code:
            errors.append(f"{loc}: falta 'code'.")
            continue
        if not is_identifier(code):
            errors.append(f"{loc}: 'code' no es un identificador Python valid.")
        if code in RESERVED_NAMES:
            errors.append(f"{loc}: 'code' reservat/no permes.")
        if code in field_codes or code in computed_codes:
            errors.append(f"{loc}: 'code' duplicat.")
        computed_codes.add(code)
        if var:
            if not is_identifier(var):
                errors.append(f"{loc}: 'var' no es un identificador Python valid.")
            elif var in RESERVED_NAMES:
                errors.append(f"{loc}: 'var' reservat/no permes.")
            elif var in seen_vars:
                errors.append(f"{loc}: 'var' duplicat.")
            seen_vars.add(var)
        if not isinstance(comp.get("formula"), str) or not str(comp.get("formula") or "").strip():
            errors.append(f"{loc}: falta 'formula' (string).")

    if errors:
        raise ValidationError(errors)

    runtime_schema = runtime_schema_for_subject(schema or {}, aparell=aparell, member_count=2 if is_team else 0)
    runtime_fields = runtime_schema.get("fields", []) if isinstance(runtime_schema.get("fields"), list) else []
    runtime_computed = runtime_schema.get("computed", []) if isinstance(runtime_schema.get("computed"), list) else []
    runtime_params = runtime_schema.get("params", {}) if isinstance(runtime_schema.get("params"), dict) else {}
    runtime_codes = {
        str(item.get("code"))
        for item in list(runtime_fields) + list(runtime_computed)
        if isinstance(item, dict) and item.get("code")
    }
    aliases = _build_aliases(runtime_fields, runtime_computed, runtime_params)
    logical_aliases = _build_aliases(fields, computed, params)
    logical_names = field_codes | computed_codes | set(logical_aliases.keys())
    allowed_names = runtime_codes | logical_names | set(aliases.keys()) | RESERVED_NAMES | ALLOWED_FUNCTIONS
    kind_env: Dict[str, str] = {}
    for field in fields:
        if not isinstance(field, dict) or not field.get("code"):
            continue
        code = str(field.get("code") or "").strip()
        kind = _field_kind(field, is_team=is_team)
        kind_env[code] = kind
        var = str(field.get("var") or "").strip()
        if var:
            kind_env[var] = kind

    comp_deps: Dict[str, Set[str]] = {}
    comp_codes_list: List[str] = []
    comp_lookup: Dict[str, Dict[str, Any]] = {}
    comp_index: Dict[str, int] = {}
    for idx, comp in enumerate(computed):
        if not isinstance(comp, dict) or not comp.get("code"):
            continue
        code = str(comp.get("code") or "").strip()
        formula = str(comp.get("formula") or "").strip()
        comp_codes_list.append(code)
        comp_lookup[code] = comp
        comp_index[code] = idx
        if not formula:
            comp_deps[code] = set()
            continue
        tree = _parse_formula(formula, _fmt_loc("computed", idx, code))
        try:
            names = _extract_names(tree)
        except ValidationError:
            names = set()
        resolved = {logical_aliases.get(name, name) for name in names}
        comp_deps[code] = {name for name in resolved if name in computed_codes}

    ordered_codes = _topo_sort(comp_codes_list, comp_deps)

    for code in ordered_codes:
        comp = comp_lookup.get(code) or {}
        idx = comp_index.get(code)
        formula = str(comp.get("formula") or "").strip()
        loc = _fmt_loc("computed", idx, code)
        tree = _parse_formula(formula, loc)
        try:
            names = _extract_names(tree)
        except ValidationError as exc:
            errors.append(f"{loc}: {exc.message}")
            continue

        runtime_member_refs = sorted(name for name in names if MEMBER_CODE_SUFFIX_RE.search(str(name)))
        if runtime_member_refs:
            errors.append(f"{loc}: no es permet referenciar sufixos runtime __mN: {', '.join(runtime_member_refs)}")
        _validate_member_helper_calls(tree, kind_env, is_team=is_team, loc=loc, errors=errors)
        unknown = sorted(name for name in names if name not in allowed_names)
        if unknown:
            errors.append(f"{loc}: variables no declarades: {', '.join(unknown)}")

        kind = infer_team_expr_kind(tree.body, kind_env)
        kind_env[code] = kind
        var = str(comp.get("var") or "").strip()
        if var:
            kind_env[var] = kind

    if errors:
        raise ValidationError(errors)
