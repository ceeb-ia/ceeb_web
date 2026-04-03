import ast
import re

from ..detail_schema_validation import build_validation_detail, legacy_validation_error_details
from ..scoring_schema_validation import (
    ALLOWED_FUNCTIONS,
    RESERVED_NAMES,
    DryRunEval,
    Shape,
    TMat,
    _ast_parse,
    _build_alias_map,
    _extract_names,
    _field_shape,
    _resolve_name,
    _topo_sort,
)
from ..team_scoring import (
    KIND_MEMBER_LIST,
    KIND_MEMBER_MATRIX,
    KIND_MEMBER_SCALAR,
    KIND_SHARED_LIST,
    KIND_SHARED_MATRIX,
    KIND_SHARED_SCALAR,
    infer_team_expr_kind,
    is_team_competition_unit,
)


DETAIL_DISPLAY_KIND_NONE = "none"
DETAIL_DISPLAY_KIND_SCALAR = "scalar"
DETAIL_DISPLAY_KIND_JUDGE_ROWS = "judge_rows"


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _field_is_direct_scoreable(field_cfg: dict):
    if not isinstance(field_cfg, dict):
        return False, "config de camp no valida"
    ftype = str(field_cfg.get("type") or "").strip().lower()
    shape = str(field_cfg.get("shape") or "").strip().lower()
    judges_cfg = field_cfg.get("judges") if isinstance(field_cfg.get("judges"), dict) else {}
    items_cfg = field_cfg.get("items") if isinstance(field_cfg.get("items"), dict) else {}
    n_judges = max(1, min(10, _safe_int(judges_cfg.get("count") or field_cfg.get("judges_count") or 1, 1)))
    n_items = max(0, min(50, _safe_int(items_cfg.get("count") or 0, 0)))
    if ftype == "number":
        return True, ""
    if ftype == "list" and shape == "judge":
        if n_judges == 1:
            return True, ""
        return False, "camp tipus llista amb mes d'un jutge"
    if ftype == "matrix" and shape in ("judge_x_item", "judge_x_element"):
        if n_judges == 1 and n_items == 1:
            return True, ""
        return False, "camp tipus matriu; per puntuacio directa nomes s'admet 1x1"
    return False, "tipus de camp no puntuable directament"


def _detail_display_meta_for_field(field_cfg: dict):
    if not isinstance(field_cfg, dict):
        return {"detail_displayable": False, "detail_display_kind": DETAIL_DISPLAY_KIND_NONE}
    ftype = str(field_cfg.get("type") or "").strip().lower()
    shape = str(field_cfg.get("shape") or "").strip().lower()
    if ftype == "number":
        return {"detail_displayable": True, "detail_display_kind": DETAIL_DISPLAY_KIND_SCALAR}
    if ftype == "list" and shape == "judge":
        return {"detail_displayable": True, "detail_display_kind": DETAIL_DISPLAY_KIND_JUDGE_ROWS}
    if ftype == "matrix" and shape in ("judge_x_item", "judge_x_element"):
        return {"detail_displayable": True, "detail_display_kind": DETAIL_DISPLAY_KIND_JUDGE_ROWS}
    return {"detail_displayable": False, "detail_display_kind": DETAIL_DISPLAY_KIND_NONE}


def _detail_display_meta_for_computed_shape(shape_info):
    if _is_scalar_shape_info(shape_info):
        return {"detail_displayable": True, "detail_display_kind": DETAIL_DISPLAY_KIND_SCALAR}
    return {"detail_displayable": False, "detail_display_kind": DETAIL_DISPLAY_KIND_NONE}


def _score_field_kind_for_app(field_cfg: dict, *, is_team_app: bool) -> str:
    if not isinstance(field_cfg, dict):
        return KIND_SHARED_SCALAR
    scope = str(field_cfg.get("scope") or "member").strip().lower() or "member"
    if not is_team_app:
        scope = "shared"
    ftype = str(field_cfg.get("type") or "number").strip().lower() or "number"
    if ftype == "number":
        return KIND_MEMBER_SCALAR if scope == "member" else KIND_SHARED_SCALAR
    if ftype == "list":
        return KIND_MEMBER_LIST if scope == "member" else KIND_SHARED_LIST
    return KIND_MEMBER_MATRIX if scope == "member" else KIND_SHARED_MATRIX


def _expr_uses_member_inputs(node, member_env: dict) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.Expression):
        return _expr_uses_member_inputs(node.body, member_env)
    if isinstance(node, ast.Name):
        return bool(member_env.get(node.id, False))
    if isinstance(node, ast.Constant):
        return False
    if isinstance(node, (ast.List, ast.Tuple)):
        return any(_expr_uses_member_inputs(elt, member_env) for elt in node.elts)
    if isinstance(node, ast.UnaryOp):
        return _expr_uses_member_inputs(node.operand, member_env)
    if isinstance(node, ast.Subscript):
        return _expr_uses_member_inputs(node.value, member_env)
    if isinstance(node, ast.BinOp):
        return _expr_uses_member_inputs(node.left, member_env) or _expr_uses_member_inputs(node.right, member_env)
    if isinstance(node, ast.Call):
        fn_name = node.func.id if isinstance(node.func, ast.Name) else ""
        if fn_name == "field" and node.args and isinstance(node.args[0], ast.Constant):
            return bool(member_env.get(str(getattr(node.args[0], "value", "")), False))
        return any(_expr_uses_member_inputs(arg, member_env) for arg in list(node.args or []))
    return False


def _parse_formula_root_call(formula: str):
    txt = str(formula or "").strip()
    if not txt:
        return "", ""
    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*$", txt, flags=re.DOTALL)
    if not match:
        return "", ""
    return str(match.group(1) or "").strip(), str(match.group(2) or "")


def _extract_first_arg(args_txt: str):
    txt = str(args_txt or "")
    if not txt.strip():
        return ""
    depth = 0
    quote = ""
    escaped = False
    for idx, ch in enumerate(txt):
        if quote:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == quote:
                quote = ""
            continue
        if ch in {"'", '"'}:
            quote = ch
            continue
        if ch in {"(", "[", "{"}:
            depth += 1
            continue
        if ch in {")", "]", "}"}:
            depth = max(0, depth - 1)
            continue
        if ch == "," and depth == 0:
            return txt[:idx].strip()
    return txt.strip()


def _extract_kwarg_int(args_txt: str, key: str):
    match = re.search(rf"\b{re.escape(str(key))}\s*=\s*(-?\d+)\b", str(args_txt or ""))
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _extract_kwarg_str(args_txt: str, key: str):
    match = re.search(
        rf"\b{re.escape(str(key))}\s*=\s*(?:(['\"])(.*?)\1|([A-Za-z_][A-Za-z0-9_]*))",
        str(args_txt or ""),
        flags=re.DOTALL,
    )
    if not match:
        return ""
    return str(match.group(2) or match.group(3) or "").strip()


def _extract_source_from_call(comp_cfg: dict, call_name: str, args_txt: str):
    if isinstance(comp_cfg, dict):
        builder = comp_cfg.get("builder")
        if isinstance(builder, dict):
            source = str(builder.get("source") or "").strip()
            if source:
                return source
    fn = str(call_name or "").strip().lower()
    if fn not in {"row_custom_compute", "column_custom_compute", "row_custom_agregation", "exec_by_judge", "items_reduce", "crash"}:
        return ""
    tok = _extract_first_arg(args_txt)
    if not tok:
        return ""
    match = re.match(r"""^\s*field\s*\(\s*(?:'([^']+)'|"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*))\s*\)\s*$""", tok)
    if match:
        return str(match.group(1) or match.group(2) or match.group(3) or "").strip()
    match = re.match(r"""^\s*(?:'([^']+)'|"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*))\s*$""", tok)
    if not match:
        return ""
    return str(match.group(1) or match.group(2) or match.group(3) or "").strip()


def _extract_best_n_value(args_txt: str):
    n_kw = _extract_kwarg_int(args_txt, "n")
    if n_kw is not None:
        return n_kw
    match = re.match(r"""^\s*[^,]+,\s*(-?\d+)\b""", str(args_txt or ""))
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _computed_mode_hint(comp_cfg: dict) -> str:
    if not isinstance(comp_cfg, dict):
        return ""
    builder = comp_cfg.get("builder") if isinstance(comp_cfg.get("builder"), dict) else {}
    preset = str(builder.get("preset") or "").strip().lower()
    if preset in {"row_compute", "column_compute", "row_agregation", "exec_trampoli", "select_sum_guided"}:
        return preset
    formula = str(comp_cfg.get("formula") or "").strip().lower()
    if re.match(r"^row_custom_compute\s*\(", formula):
        return "row_compute"
    if re.match(r"^column_custom_compute\s*\(", formula):
        return "column_compute"
    if re.match(r"^row_custom_agregation\s*\(", formula):
        return "row_agregation"
    if re.match(r"^exec_by_judge\s*\(", formula):
        return "exec_trampoli"
    if re.match(r"^select_sum\s*\(", formula):
        return "select_sum_guided"
    return ""


def _formula_forces_vector_return(formula: str) -> bool:
    call_name, args_txt = _parse_formula_root_call(formula)
    fn = str(call_name or "").strip().lower()
    if fn not in {"row_custom_compute", "column_custom_compute"}:
        return False
    rm = _extract_kwarg_str(args_txt, "return_mode").lower()
    return rm in {"by_judge", "by_item"}


def _schema_field_dims_map(schema_obj: dict):
    out = {}
    schema_obj = schema_obj or {}
    for field in (schema_obj.get("fields") or []):
        if not isinstance(field, dict) or not field.get("code"):
            continue
        code = str(field.get("code"))
        shape = _field_shape(field)
        out[code] = {"rows": shape.rows, "cols": shape.cols}
    return out


def _resolve_source_dims(source_code: str, inferred_shapes: dict, field_dims: dict):
    src = str(source_code or "").strip()
    if not src:
        return {"rows": None, "cols": None}
    info = inferred_shapes.get(src)
    if isinstance(info, dict):
        return {"rows": info.get("rows"), "cols": info.get("cols")}
    info = field_dims.get(src)
    if isinstance(info, dict):
        return {"rows": info.get("rows"), "cols": info.get("cols")}
    return {"rows": None, "cols": None}


def _is_scalar_shape_info(shape_info) -> bool:
    return isinstance(shape_info, dict) and shape_info.get("rows") == 1 and shape_info.get("cols") == 1


def _shape_desc(shape_info) -> str:
    if not isinstance(shape_info, dict):
        return "?"
    r_txt = "?" if shape_info.get("rows") is None else str(shape_info.get("rows"))
    c_txt = "?" if shape_info.get("cols") is None else str(shape_info.get("cols"))
    return f"{r_txt}x{c_txt}"


def _scoreable_from_conditional_vector(comp_cfg: dict, mode_hint: str, call_name: str, args_txt: str, inferred_shapes: dict, field_dims: dict, strict_unknown: bool):
    mode = str(mode_hint or "").strip().lower()
    fn = str(call_name or "").strip().lower()
    source_code = _extract_source_from_call(comp_cfg, fn, str(args_txt or ""))
    dims = _resolve_source_dims(source_code, inferred_shapes, field_dims)
    src_rows = dims.get("rows")
    src_cols = dims.get("cols")
    if mode in {"row_compute", "column_compute"} or fn in {"row_custom_compute", "column_custom_compute"}:
        is_row_compute = mode == "row_compute" or fn == "row_custom_compute"
        is_col_compute = mode == "column_compute" or fn == "column_custom_compute"
        rm = _extract_kwarg_str(args_txt, "return_mode").lower()
        if not _formula_forces_vector_return(comp_cfg.get("formula")) or rm in {"", "final"}:
            return True, "", True
        if is_row_compute:
            if rm != "by_judge":
                return True, "", True
            if src_rows == 1:
                return True, "return_mode by_judge amb 1 jutge (llista d'1)", True
            if src_rows is None:
                return (False, "no es pot inferir longitud de vector by_judge", True) if strict_unknown else (True, "longitud by_judge no inferible (UI tolerant)", True)
            return False, f"return_mode by_judge amb {src_rows} jutges", True
        if is_col_compute:
            if rm != "by_item":
                return True, "", True
            cnt = _extract_kwarg_int(args_txt, "count")
            if cnt is not None and cnt == 1:
                return True, "return_mode by_item amb count=1", True
            if src_cols == 1:
                return True, "return_mode by_item amb 1 item", True
            if src_cols is None:
                return (False, "no es pot inferir longitud de vector by_item", True) if strict_unknown else (True, "longitud by_item no inferible (UI tolerant)", True)
            return False, f"return_mode by_item amb {src_cols} items", True
    if mode in {"row_agregation", "exec_trampoli"} or fn in {"row_custom_agregation", "exec_by_judge", "items_reduce", "crash"}:
        if src_rows == 1:
            return True, "vector per jutge de longitud 1", True
        if src_rows is None:
            return (False, "no es pot inferir longitud de vector per jutge", True) if strict_unknown else (True, "longitud per jutge no inferible (UI tolerant)", True)
        return False, f"vector per jutge de longitud {src_rows}", True
    if fn == "best_n":
        n_val = _extract_best_n_value(args_txt)
        if n_val == 1:
            return True, "best_n amb n=1", True
        if n_val is None:
            return (False, "best_n sense n constant no es pot garantir mida 1", True) if strict_unknown else (True, "best_n sense n constant (UI tolerant)", True)
        return False, f"best_n amb n={n_val}", True
    return False, "", False


def _infer_schema_code_shapes(schema_obj: dict):
    schema_obj = schema_obj or {}
    params = schema_obj.get("params", {})
    if params is None or not isinstance(params, dict):
        params = {}
    fields = schema_obj.get("fields", [])
    computed = schema_obj.get("computed", [])
    if not isinstance(fields, list):
        fields = []
    if not isinstance(computed, list):
        computed = []
    field_codes = [field["code"] for field in fields if isinstance(field, dict) and isinstance(field.get("code"), str)]
    comp_codes = [comp["code"] for comp in computed if isinstance(comp, dict) and isinstance(comp.get("code"), str)]
    aliases = _build_alias_map(fields, computed, params)
    allowed_names = set(field_codes) | set(comp_codes) | set(aliases.keys()) | RESERVED_NAMES | ALLOWED_FUNCTIONS
    comp_deps = {code: set() for code in comp_codes}
    for idx, comp in enumerate(computed):
        if not isinstance(comp, dict):
            continue
        code = str(comp.get("code") or "").strip()
        formula = comp.get("formula")
        if not code or not isinstance(formula, str) or not formula.strip():
            continue
        try:
            tree = _ast_parse(formula, f"computed[{idx}]({code})")
            names = _extract_names(tree)
        except Exception:
            continue
        resolved = {_resolve_name(name, aliases) for name in names if name in allowed_names}
        for dep in resolved:
            if dep in comp_deps and dep != code:
                comp_deps[code].add(dep)
    try:
        order = _topo_sort(comp_codes, comp_deps)
    except Exception:
        order = list(comp_codes)
    ctx = {}
    for field in fields:
        if not isinstance(field, dict):
            continue
        code = str(field.get("code") or "").strip()
        if code:
            ctx[code] = TMat(_field_shape(field), name=code)
    ctx["params"] = TMat(Shape(1, 1), name="params")
    for short, code in aliases.items():
        if code in ctx:
            ctx[short] = ctx[code]
    for code in order:
        cobj = next((item for item in computed if isinstance(item, dict) and item.get("code") == code), None)
        if not cobj:
            continue
        formula = str(cobj.get("formula") or "")
        if not formula:
            continue
        try:
            tree = _ast_parse(formula, f"computed({code})")
            value = DryRunEval(ctx).visit(tree)
        except Exception:
            continue
        ctx[code] = value
        var = cobj.get("var")
        if isinstance(var, str) and var in aliases:
            ctx[var] = value
    out = {}
    for code in field_codes + comp_codes:
        tm = ctx.get(code)
        if isinstance(tm, TMat):
            out[code] = {"rows": tm.shape.rows, "cols": tm.shape.cols}
    return out


def _build_scoreable_meta_for_schema(schema_obj: dict, strict_unknown=False):
    schema_obj = schema_obj or {}
    meta = {"total": {"scoreable": True, "reason": ""}, "TOTAL": {"scoreable": True, "reason": ""}}
    inferred_shapes = {}
    infer_error = ""
    field_dims = _schema_field_dims_map(schema_obj)
    try:
        inferred_shapes = _infer_schema_code_shapes(schema_obj)
    except Exception as exc:
        infer_error = str(exc)
    for field in (schema_obj.get("fields") or []):
        if not isinstance(field, dict) or not field.get("code"):
            continue
        code = str(field["code"])
        ok, reason = _field_is_direct_scoreable(field)
        shape_info = inferred_shapes.get(code)
        if shape_info is not None:
            if _is_scalar_shape_info(shape_info):
                ok, reason = True, ""
            else:
                ok, reason = False, f"shape no escalar {_shape_desc(shape_info)}"
        meta[code] = {"scoreable": bool(ok), "reason": str(reason or "")}
    for comp in (schema_obj.get("computed") or []):
        if not isinstance(comp, dict) or not comp.get("code"):
            continue
        code = str(comp["code"])
        mode_hint = _computed_mode_hint(comp)
        formula_txt = str(comp.get("formula") or "")
        call_name, call_args = _parse_formula_root_call(formula_txt)
        cond_ok, cond_reason, cond_handled = _scoreable_from_conditional_vector(comp, mode_hint, call_name, call_args, inferred_shapes, field_dims, strict_unknown=bool(strict_unknown))
        if cond_handled:
            meta[code] = {"scoreable": bool(cond_ok), "reason": "" if cond_ok else cond_reason}
            continue
        shape_info = inferred_shapes.get(code)
        if shape_info is None:
            if mode_hint in {"row_compute", "column_compute", "select_sum_guided"}:
                meta[code] = {"scoreable": True, "reason": ""}
                continue
            if strict_unknown:
                reason = f"no es pot inferir shape (schema invalid): {infer_error}" if infer_error else "no es pot inferir shape del computed"
                meta[code] = {"scoreable": False, "reason": reason}
            else:
                meta[code] = {"scoreable": True, "reason": ""}
            continue
        if mode_hint in {"row_compute", "column_compute", "select_sum_guided"} and _is_scalar_shape_info(shape_info):
            meta[code] = {"scoreable": True, "reason": ""}
            continue
        if _is_scalar_shape_info(shape_info):
            meta[code] = {"scoreable": True, "reason": ""}
        else:
            meta[code] = {"scoreable": False, "reason": f"computed amb shape no escalar {_shape_desc(shape_info)}"}
    return meta


def _computed_is_member_dependent(comp_cfg: dict, tree, member_env: dict) -> bool:
    formula = str((comp_cfg or {}).get("formula") or "").strip()
    call_name, args_txt = _parse_formula_root_call(formula)
    source_code = _extract_source_from_call(comp_cfg, call_name, args_txt)
    if source_code and bool(member_env.get(source_code, False)):
        return True
    return _expr_uses_member_inputs(tree.body, member_env)


def build_metric_meta_for_schema_owner(schema_owner, schema_obj: dict, strict_unknown=False):
    schema_obj = schema_obj or {}
    is_team_app = bool(is_team_competition_unit(schema_owner))
    base_meta = _build_scoreable_meta_for_schema(schema_obj, strict_unknown=bool(strict_unknown))
    try:
        inferred_shapes = _infer_schema_code_shapes(schema_obj)
    except Exception:
        inferred_shapes = {}
    meta = {}
    for code, info in (base_meta or {}).items():
        item = dict(info if isinstance(info, dict) else {})
        item["kind"] = KIND_SHARED_SCALAR if str(code).strip().lower() == "total" else ""
        item.setdefault("member_dependent", False)
        item.setdefault("detail_displayable", str(code).strip().lower() == "total")
        item.setdefault("detail_display_kind", DETAIL_DISPLAY_KIND_SCALAR if str(code).strip().lower() == "total" else DETAIL_DISPLAY_KIND_NONE)
        meta[str(code)] = item
    params = schema_obj.get("params", {})
    if not isinstance(params, dict):
        params = {}
    fields = schema_obj.get("fields", [])
    if not isinstance(fields, list):
        fields = []
    computed = schema_obj.get("computed", [])
    if not isinstance(computed, list):
        computed = []
    aliases = _build_alias_map(fields, computed, params)
    allowed_names = set(aliases.keys()) | RESERVED_NAMES | ALLOWED_FUNCTIONS
    kind_env = {}
    member_env = {}
    computed_codes = set()
    comp_lookup = {}
    comp_index = {}
    comp_deps = {}
    ordered_codes = []
    for field in fields:
        if not isinstance(field, dict):
            continue
        code = str(field.get("code") or "").strip()
        if not code:
            continue
        kind = _score_field_kind_for_app(field, is_team_app=is_team_app)
        display_meta = _detail_display_meta_for_field(field)
        kind_env[code] = kind
        member_dependent = bool(is_team_app and str(field.get("scope") or "member").strip().lower() == "member")
        member_env[code] = member_dependent
        allowed_names.add(code)
        var = str(field.get("var") or "").strip()
        if var:
            kind_env[var] = kind
            member_env[var] = member_dependent
            allowed_names.add(var)
        meta.setdefault(code, {"scoreable": False, "reason": "", "kind": kind, "member_dependent": member_dependent, "detail_displayable": display_meta["detail_displayable"], "detail_display_kind": display_meta["detail_display_kind"]})
        meta[code]["kind"] = kind
        meta[code]["member_dependent"] = member_dependent
        meta[code]["detail_displayable"] = display_meta["detail_displayable"]
        meta[code]["detail_display_kind"] = display_meta["detail_display_kind"]
    for idx, comp in enumerate(computed):
        if not isinstance(comp, dict):
            continue
        code = str(comp.get("code") or "").strip()
        if not code:
            continue
        computed_codes.add(code)
        ordered_codes.append(code)
        comp_lookup[code] = comp
        comp_index[code] = idx
        allowed_names.add(code)
        var = str(comp.get("var") or "").strip()
        if var:
            allowed_names.add(var)
        formula = str(comp.get("formula") or "").strip()
        if not formula:
            comp_deps[code] = set()
            continue
        try:
            tree = _ast_parse(formula, f"computed[{idx}]({code})")
            names = _extract_names(tree)
            resolved_names = {aliases.get(name, name) for name in names}
            comp_deps[code] = {name for name in resolved_names if name in computed_codes}
        except Exception:
            comp_deps[code] = set()
    try:
        ordered_codes = _topo_sort(ordered_codes, comp_deps)
    except Exception:
        pass
    for code in ordered_codes:
        comp = comp_lookup.get(code) or {}
        idx = comp_index.get(code, 0)
        formula = str(comp.get("formula") or "").strip()
        kind = ""
        member_dependent = False
        display_meta = {"detail_displayable": False, "detail_display_kind": DETAIL_DISPLAY_KIND_NONE}
        if formula:
            try:
                tree = _ast_parse(formula, f"computed[{idx}]({code})")
                names = _extract_names(tree)
                unknown = [name for name in names if name not in allowed_names]
                if not unknown:
                    kind = infer_team_expr_kind(tree.body, kind_env)
                    member_dependent = _computed_is_member_dependent(comp, tree, member_env)
                    display_meta = _detail_display_meta_for_computed_shape(inferred_shapes.get(code))
                    if _formula_forces_vector_return(formula):
                        display_meta = {"detail_displayable": False, "detail_display_kind": DETAIL_DISPLAY_KIND_NONE}
            except Exception:
                kind = ""
                member_dependent = False
        meta.setdefault(code, {"scoreable": False, "reason": "", "kind": "", "member_dependent": member_dependent, "detail_displayable": display_meta["detail_displayable"], "detail_display_kind": display_meta["detail_display_kind"]})
        meta[code]["kind"] = kind
        meta[code]["member_dependent"] = member_dependent
        meta[code]["detail_displayable"] = display_meta["detail_displayable"]
        meta[code]["detail_display_kind"] = display_meta["detail_display_kind"]
    return meta


def build_validation_error_details(error_messages):
    raw_list = list(error_messages or [])
    if raw_list and all(isinstance(item, dict) and item.get("message") for item in raw_list):
        return [
            build_validation_detail(
                item.get("path") or "",
                item.get("message") or "",
                section=item.get("section"),
                severity=item.get("severity") or "error",
            )
            for item in raw_list
            if isinstance(item, dict) and str(item.get("message") or "").strip()
        ]
    return legacy_validation_error_details(raw_list)


__all__ = [
    "DETAIL_DISPLAY_KIND_NONE",
    "DETAIL_DISPLAY_KIND_SCALAR",
    "DETAIL_DISPLAY_KIND_JUDGE_ROWS",
    "build_metric_meta_for_schema_owner",
    "build_validation_error_details",
]
