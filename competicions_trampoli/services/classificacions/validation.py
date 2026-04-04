import ast
import re

from ...models_scoring import ScoringSchema
from ...models_trampoli import CompeticioAparell, CompeticioAparellEquipContextSource
from ..birth_year_ranges import validate_birth_year_range_partition_config
from ..classificacio_templates import (
    json_clone,
    normalize_particions_custom,
    normalize_particions_schema,
    split_particio_custom_values,
)
from ..detail_schema_validation import (
    build_validation_detail,
    detail_section_key_for_tipus,
    legacy_validation_error_details,
    validate_detail_schema,
    validation_details_to_messages,
)
from ..equip_contexts import get_equip_context, normalize_equip_context_code
from ..inscripcions.queries import get_allowed_group_fields
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
    is_team_context_app,
    is_team_competition_unit,
)
from .filters import (
    CLASSIFICACIO_FILTER_KEYS,
    EXERCISE_SELECTION_SCOPE_INHERIT,
    EXERCISE_SELECTION_SCOPE_PER_MEMBER,
    EXERCISE_SELECTION_SCOPE_TEAM_POOL,
    infer_team_mode_from_comp_aparells,
    normalize_classificacio_equips_cfg,
    normalize_classificacio_filters,
    normalize_equip_assignment_source,
    normalize_exercise_selection_scope,
    normalize_team_mode,
)
from .partitions import (
    BIRTH_YEAR_RANGE_PARTITION_CODE,
    normalize_particions_config,
    normalize_particions_v2_entries,
    normalize_schema_legacy_team_birth_partition,
    particio_codes_from_entries,
)


DETAIL_DISPLAY_KIND_NONE = "none"
DETAIL_DISPLAY_KIND_SCALAR = "scalar"
DETAIL_DISPLAY_KIND_JUDGE_ROWS = "judge_rows"


def _is_native_team_metric_compatible(info: dict) -> bool:
    clean_info = info if isinstance(info, dict) else {}
    kind = str(clean_info.get("kind") or "").strip()
    return kind not in {KIND_MEMBER_SCALAR, KIND_MEMBER_LIST, KIND_MEMBER_MATRIX}


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


def build_metric_meta_for_comp_aparell(comp_aparell, schema_obj: dict, strict_unknown=False):
    return build_metric_meta_for_schema_owner(comp_aparell, schema_obj, strict_unknown=bool(strict_unknown))


def build_scoreable_meta_for_schema(schema_obj: dict, strict_unknown=False):
    return _build_scoreable_meta_for_schema(schema_obj, strict_unknown=bool(strict_unknown))


def _selected_app_ids_from_schema(schema_local):
    apps_cfg = ((schema_local.get("puntuacio") or {}).get("aparells") or {})
    out = []
    seen = set()
    for raw in (apps_cfg.get("ids") or []):
        try:
            app_id = int(raw)
        except Exception:
            continue
        if app_id > 0 and app_id not in seen:
            seen.add(app_id)
            out.append(app_id)
    return out


def _get_team_context_capabilities(competicio, context_code):
    normalized_code = normalize_equip_context_code(context_code)
    context_obj = get_equip_context(competicio, normalized_code)
    if context_obj is None:
        return {
            "context_code": normalized_code,
            "exists": False,
            "has_team_apps": False,
            "eligible_team_app_ids": [],
        }
    eligible_team_app_ids = list(
        CompeticioAparellEquipContextSource.objects
        .filter(
            competicio=competicio,
            context=context_obj,
            comp_aparell__actiu=True,
            comp_aparell__aparell__competition_unit="team",
        )
        .values_list("comp_aparell_id", flat=True)
        .distinct()
    )
    eligible_team_app_ids = sorted({int(app_id) for app_id in eligible_team_app_ids})
    return {
        "context_code": normalized_code,
        "exists": True,
        "has_team_apps": bool(eligible_team_app_ids),
        "eligible_team_app_ids": eligible_team_app_ids,
    }


def _required_context_message_for_app(competicio, app_id):
    source_codes = list(
        CompeticioAparellEquipContextSource.objects
        .filter(competicio=competicio, comp_aparell_id=app_id)
        .select_related("context")
        .order_by("context__nom", "context__id")
        .values_list("context__code", flat=True)
    )
    clean_codes = [str(code or "").strip() for code in source_codes if str(code or "").strip()]
    if len(clean_codes) == 1:
        return f"requereix context {clean_codes[0]}"
    if clean_codes:
        return f"requereix un dels contexts {', '.join(clean_codes)}"
    return "requereix un context compatible"


def _validate_filtres_schema(schema: dict):
    schema = schema if isinstance(schema, dict) else {}
    raw_filters = schema.get("filtres")
    errors = []
    if raw_filters in (None, ""):
        raw_filters = {}
    if not isinstance(raw_filters, dict):
        schema["filtres"] = {}
        return ["filtres ha de ser un objecte."]
    allowed_keys = set(CLASSIFICACIO_FILTER_KEYS)
    for key in sorted(raw_filters.keys()):
        if key not in allowed_keys:
            errors.append(f"filtres.{key}: clau no admesa.")
            continue
        if not isinstance(raw_filters.get(key), list):
            errors.append(f"filtres.{key}: ha de ser una llista.")
    schema["filtres"] = normalize_classificacio_filters(raw_filters)
    return errors


def _normalize_tie_camps_for_validation(tie_obj) -> list:
    if not isinstance(tie_obj, dict):
        return []
    out = []
    raw = tie_obj.get("camps")
    if isinstance(raw, list):
        out = [str(x).strip() for x in raw if str(x).strip()]
    elif isinstance(raw, str):
        out = [x.strip() for x in raw.split(",") if x and x.strip()]
    if not out:
        legacy = str(tie_obj.get("camp") or "").strip()
        if legacy:
            out = [legacy]
    dedup = []
    seen = set()
    for code in out:
        if code in seen:
            continue
        seen.add(code)
        dedup.append(code)
    return dedup


def _get_active_and_selected_app_ids(competicio, punt: dict):
    active_app_ids = set(
        CompeticioAparell.objects.filter(competicio=competicio, actiu=True).values_list("id", flat=True)
    )
    app_mode = str(((punt or {}).get("aparells") or {}).get("mode") or "seleccionar").strip().lower()
    app_ids_raw = ((punt or {}).get("aparells") or {}).get("ids") or []
    if app_mode != "seleccionar":
        return active_app_ids, set(active_app_ids)
    selected_ids = set()
    for raw in app_ids_raw:
        try:
            selected_ids.add(int(raw))
        except Exception:
            continue
    return active_app_ids, selected_ids


def _parse_positive_int_list(raw):
    values = raw if isinstance(raw, list) else ([raw] if raw not in (None, "", []) else [])
    out = []
    seen = set()
    for item in values:
        try:
            value = int(item)
        except Exception:
            continue
        if value > 0 and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _validate_exercicis_cfg_obj(cfg, prefix: str):
    errors = []
    if not isinstance(cfg, dict):
        return [f"{prefix} ha de ser un objecte."]
    allowed_modes = {"tots", "millor_1", "millor_n", "pitjor_1", "pitjor_n", "primer", "ultim", "index", "llista"}
    mode = str(cfg.get("mode") or "tots").strip().lower()
    if mode not in allowed_modes:
        errors.append(f"{prefix}.mode invalid: {mode}")
        return errors
    if mode in {"millor_n", "pitjor_n"}:
        try:
            best_n = int(cfg.get("best_n") or 1)
        except Exception:
            best_n = 0
        if best_n < 1:
            errors.append(f"{prefix}.best_n ha de ser >= 1.")
    if mode == "index":
        try:
            index = int(cfg.get("index"))
        except Exception:
            index = 0
        if index < 1:
            errors.append(f"{prefix}.index ha de ser >= 1.")
    if mode == "llista":
        ids = _parse_positive_int_list(cfg.get("ids"))
        if not ids:
            errors.append(f"{prefix}.ids ha de contenir almenys un index valid (>0).")
    if "max_per_participant" in cfg:
        try:
            max_pp = int(cfg.get("max_per_participant"))
        except Exception:
            max_pp = -1
        if max_pp < 0:
            errors.append(f"{prefix}.max_per_participant ha de ser >= 0.")
    return errors


def _validate_victories_granular_options(victories, prefix: str):
    errors = []
    if not isinstance(victories, dict):
        return errors
    mode_camps = str(victories.get("mode_camps") or "agregat").strip().lower()
    if mode_camps not in {"agregat", "separat"}:
        errors.append(f"{prefix}.mode_camps invalid: {mode_camps}")
    mode_exercicis = str(victories.get("mode_exercicis") or "agregat").strip().lower()
    if mode_exercicis not in {"agregat", "separat"}:
        errors.append(f"{prefix}.mode_exercicis invalid: {mode_exercicis}")
    mode_sel = str(victories.get("mode_seleccio_exercicis_camps_separats") or "per_camp").strip().lower()
    if mode_sel not in {"per_camp", "global"}:
        errors.append(f"{prefix}.mode_seleccio_exercicis_camps_separats invalid: {mode_sel}")
    for key in ("agregacio_victories_camps", "agregacio_victories_exercicis"):
        raw = str(victories.get(key) or "sum").strip().lower()
        if raw not in {"sum", "avg", "median", "max", "min"}:
            errors.append(f"{prefix}.{key} invalid: {raw}")
    return errors


def _is_derived_team_scope_enabled(*, tipus="individual", team_mode="") -> bool:
    return (
        str(tipus or "").strip().lower() == "equips"
        and normalize_team_mode(team_mode) == "derived_from_individual"
    )


def _effective_tie_exercise_selection_scope(tie: dict, *, main_scope=None):
    tie_scope = normalize_exercise_selection_scope(
        (tie or {}).get("exercise_selection_scope"),
        allow_inherit=True,
    )
    if tie_scope == EXERCISE_SELECTION_SCOPE_INHERIT:
        return main_scope or EXERCISE_SELECTION_SCOPE_PER_MEMBER
    return tie_scope


def _validate_exercise_selection_scope(schema: dict, *, tipus="individual", team_mode=""):
    schema = schema or {}
    punt = schema.get("puntuacio")
    if not isinstance(punt, dict):
        punt = {}
    schema["puntuacio"] = punt
    allow_scope = _is_derived_team_scope_enabled(tipus=tipus, team_mode=team_mode)
    errors = []
    raw_main_scope = punt.get("exercise_selection_scope")
    main_scope = normalize_exercise_selection_scope(raw_main_scope)
    if allow_scope:
        if raw_main_scope not in (None, "") and str(raw_main_scope).strip().lower() not in {"per_member", "team_pool"}:
            errors.append(f"puntuacio.exercise_selection_scope invalid: {raw_main_scope}")
        punt["exercise_selection_scope"] = main_scope or EXERCISE_SELECTION_SCOPE_PER_MEMBER
    elif raw_main_scope not in (None, ""):
        errors.append(
            "puntuacio.exercise_selection_scope nomes es compatible amb tipus='equips' + team_mode=derived_from_individual."
        )
    desempat = schema.get("desempat") or []
    if not isinstance(desempat, list):
        return errors
    for idx, tie in enumerate(desempat):
        if not isinstance(tie, dict):
            continue
        raw_tie_scope = tie.get("exercise_selection_scope")
        tie_scope = normalize_exercise_selection_scope(raw_tie_scope, allow_inherit=True)
        if allow_scope:
            if raw_tie_scope not in (None, "") and str(raw_tie_scope).strip().lower() not in {"hereta", "per_member", "team_pool"}:
                errors.append(f"desempat[{idx}].exercise_selection_scope invalid: {raw_tie_scope}")
            if tie_scope == EXERCISE_SELECTION_SCOPE_INHERIT:
                tie.pop("exercise_selection_scope", None)
            else:
                tie["exercise_selection_scope"] = tie_scope
        elif raw_tie_scope not in (None, ""):
            errors.append(
                f"desempat[{idx}].exercise_selection_scope nomes es compatible amb tipus='equips' + team_mode=derived_from_individual."
            )
    return errors


def _validate_particions_config_schema(schema: dict, tipus="individual"):
    schema = schema or {}
    errors = []
    part_entries = normalize_particions_v2_entries(
        schema.get("particions_v2") or [],
        fallback_codes=schema.get("particions") or [],
    )
    parts = particio_codes_from_entries(part_entries)
    if BIRTH_YEAR_RANGE_PARTITION_CODE not in parts:
        return errors
    _cfg, cfg_errors = validate_birth_year_range_partition_config(
        ((schema.get("particions_config") or {}).get(BIRTH_YEAR_RANGE_PARTITION_CODE)),
        require_ranges=True,
    )
    for err in cfg_errors:
        errors.append(f"particions_config.any_naixement_forquilla: {err}")
    return errors


def _resolve_tie_target_app_ids(tie, *, selected_app_ids):
    if not isinstance(tie, dict):
        return []
    scope = tie.get("scope") or {}
    if not isinstance(scope, dict):
        scope = {}
    app_scope = scope.get("aparells") or {}
    if not isinstance(app_scope, dict):
        app_scope = {}
    app_mode = str(app_scope.get("mode") or "").strip().lower()
    if app_mode == "seleccionar":
        return _parse_positive_int_list(app_scope.get("ids"))
    raw_app_id = tie.get("aparell_id")
    if raw_app_id not in (None, "", 0, "0"):
        try:
            app_id = int(raw_app_id)
        except Exception:
            return []
        return [app_id] if app_id > 0 else []
    return list(selected_app_ids or [])


def _validate_desempat_mode_compatibility(
    competicio,
    schema_local,
    *,
    tipus="individual",
    team_mode="",
    context_code="",
    capabilities=None,
    selected_apps=None,
):
    if str(tipus or "").strip().lower() != "equips":
        return []
    if normalize_team_mode(team_mode) != "native_team":
        return []

    capabilities = capabilities or _get_team_context_capabilities(competicio, context_code)
    selected_apps = list(selected_apps or [])
    selected_app_ids = [int(getattr(app, "id", 0) or 0) for app in selected_apps if getattr(app, "id", None)]
    selected_ids_set = set(selected_app_ids)
    eligible_ids = set(capabilities.get("eligible_team_app_ids") or [])
    active_apps = {
        int(ca.id): ca
        for ca in CompeticioAparell.objects
        .filter(competicio=competicio, actiu=True)
        .select_related("aparell")
    }
    schemas_by_aparell = {
        s.aparell_id: (s.schema or {})
        for s in ScoringSchema.objects.filter(
            aparell_id__in=[ca.aparell_id for ca in active_apps.values()]
        ).only("aparell_id", "schema")
    }
    metric_meta_cache = {}
    errors = []

    for idx, tie in enumerate((schema_local.get("desempat") or [])):
        prefix = f"desempat[{idx}]"
        if not isinstance(tie, dict):
            continue

        if "agregacio_participants" in tie and str(tie.get("agregacio_participants") or "").strip():
            errors.append(f"{prefix}.agregacio_participants no es compatible amb team_mode=native_team.")

        scope = tie.get("scope") or {}
        if not isinstance(scope, dict):
            scope = {}
        if "participants" in scope:
            errors.append(f"{prefix}.scope.participants no es compatible amb team_mode=native_team.")

        target_ids = _resolve_tie_target_app_ids(tie, selected_app_ids=selected_app_ids)
        camps = _normalize_tie_camps_for_validation(tie)
        for app_id in target_ids:
            comp_aparell = active_apps.get(int(app_id))
            if comp_aparell is None:
                errors.append(f"{prefix}: aparell {app_id} no valid o no actiu.")
                continue
            if not is_team_context_app(comp_aparell):
                errors.append(f"{prefix}: l'aparell {app_id} no es valid per team_mode=native_team.")
                continue
            if int(app_id) not in eligible_ids:
                errors.append(
                    f"{prefix}: l'aparell {app_id} {_required_context_message_for_app(competicio, app_id)}; "
                    f"no admet el context {context_code}."
                )
                continue
            if int(app_id) not in selected_ids_set:
                errors.append(f"{prefix}: l'aparell {app_id} no forma part dels aparells seleccionats.")
                continue
            if int(app_id) not in metric_meta_cache:
                metric_meta_cache[int(app_id)] = build_metric_meta_for_comp_aparell(
                    comp_aparell,
                    schemas_by_aparell.get(comp_aparell.aparell_id, {}) or {},
                    strict_unknown=True,
                )
            metric_meta = metric_meta_cache[int(app_id)]
            for code in camps:
                info = metric_meta.get(code)
                if not info:
                    errors.append(f"{prefix}: aparell {app_id}: camp '{code}' no existeix al schema.")
                    continue
                if not info.get("scoreable", False):
                    errors.append(
                        f"{prefix}: aparell {app_id}: camp '{code}' no es puntuable directament "
                        f"({info.get('reason')})."
                    )
                    continue
                if not _is_native_team_metric_compatible(info):
                    errors.append(
                        f"{prefix}: aparell {app_id}: camp '{code}' no es compatible amb team_mode=native_team."
                    )
    return errors


def _validate_camps_per_aparell(competicio, schema: dict):
    schema = schema or {}
    punt = schema.get("puntuacio") or {}
    if not isinstance(punt, dict):
        punt = {}

    active_apps = list(
        CompeticioAparell.objects
        .filter(competicio=competicio, actiu=True)
        .select_related("aparell")
    )
    app_by_id = {ca.id: ca for ca in active_apps}
    if not app_by_id:
        return []

    schemas_by_aparell = {
        s.aparell_id: (s.schema or {})
        for s in ScoringSchema.objects.filter(aparell_id__in=[ca.aparell_id for ca in active_apps]).only("aparell_id", "schema")
    }

    _, selected_ids = _get_active_and_selected_app_ids(competicio, punt)
    selected_ids = selected_ids or set(app_by_id.keys())
    equips_cfg = normalize_classificacio_equips_cfg(schema.get("equips") or {})
    team_mode = normalize_team_mode(equips_cfg.get("team_mode"))
    meta_cache = {}
    errors = []

    camps_map = punt.get("camps_per_aparell") or {}
    if not isinstance(camps_map, dict):
        return ["puntuacio.camps_per_aparell ha de ser un objecte {app_id: [camps]}."] 

    for app_id in sorted(selected_ids):
        raw_selected = camps_map.get(str(app_id))
        if raw_selected is None:
            raw_selected = camps_map.get(app_id)
        if raw_selected in (None, "", [], {}):
            errors.append(f"puntuacio.camps_per_aparell[{app_id}] ha de contenir almenys un camp real.")

    for raw_app_id, raw_camps in camps_map.items():
        try:
            app_id = int(raw_app_id)
        except Exception:
            errors.append(f"puntuacio.camps_per_aparell: app_id invalid {raw_app_id}")
            continue

        if app_id not in app_by_id:
            errors.append(f"puntuacio.camps_per_aparell: aparell {app_id} no valid o no actiu.")
            continue
        if selected_ids and app_id not in selected_ids:
            errors.append(f"puntuacio.camps_per_aparell: aparell {app_id} no esta seleccionat a puntuacio.")
            continue

        if app_id not in meta_cache:
            sch = schemas_by_aparell.get(app_by_id[app_id].aparell_id, {}) or {}
            meta_cache[app_id] = build_scoreable_meta_for_schema(sch, strict_unknown=True)
        meta = meta_cache[app_id]

        if isinstance(raw_camps, str):
            camps = [x.strip() for x in raw_camps.split(",") if x and x.strip()]
        elif isinstance(raw_camps, list):
            camps = [str(x).strip() for x in raw_camps if str(x).strip()]
        else:
            errors.append(f"puntuacio.camps_per_aparell[{app_id}] ha de ser llista o CSV.")
            continue

        if not camps:
            errors.append(f"puntuacio.camps_per_aparell[{app_id}] ha de contenir almenys un camp real.")
            continue

        for code in camps:
            info = meta.get(code)
            if not info:
                errors.append(f"puntuacio.camps_per_aparell[{app_id}]: camp '{code}' no existeix al schema.")
                continue
            if not info.get("scoreable", False):
                errors.append(
                    f"puntuacio.camps_per_aparell[{app_id}]: camp '{code}' no es puntuable directament "
                    f"({info.get('reason')})."
                )
                continue
            if team_mode == "native_team" and not _is_native_team_metric_compatible(info):
                errors.append(
                    f"puntuacio.camps_per_aparell[{app_id}]: camp '{code}' no es compatible amb team_mode=native_team."
                )

    return errors


def _validate_presentacio_columns_details(competicio, schema: dict, tipus="individual"):
    schema = schema or {}
    punt = schema.get("puntuacio") or {}
    equips_cfg = schema.get("equips") or {}
    team_mode = str((equips_cfg.get("team_mode") or "")).strip().lower()
    presentacio = schema.get("presentacio") if isinstance(schema.get("presentacio"), dict) else {}

    active_apps = list(
        CompeticioAparell.objects
        .filter(competicio=competicio, actiu=True)
        .select_related("aparell")
    )
    app_by_id = {ca.id: ca for ca in active_apps}
    _, selected_ids = _get_active_and_selected_app_ids(competicio, punt)
    schemas_by_aparell = {
        s.aparell_id: (s.schema or {})
        for s in ScoringSchema.objects.filter(aparell_id__in=[ca.aparell_id for ca in active_apps]).only("aparell_id", "schema")
    }

    meta_cache = {}
    errors = []
    details = []

    cols = presentacio.get("columnes") or []
    if not isinstance(cols, list):
        errors.append("presentacio.columnes ha de ser una llista.")
        return errors, details

    if app_by_id:
        for idx, col in enumerate(cols):
            if not isinstance(col, dict):
                continue
            if str(col.get("type") or "builtin").strip().lower() != "raw":
                continue

            src = col.get("source") if isinstance(col.get("source"), dict) else {}
            try:
                app_id = int(src.get("aparell_id"))
            except Exception:
                errors.append(f"presentacio.columnes[{idx}] raw: aparell invalid.")
                continue
            if app_id not in app_by_id:
                errors.append(f"presentacio.columnes[{idx}] raw: aparell {app_id} no valid o no actiu.")
                continue
            if team_mode == "native_team" and getattr(app_by_id[app_id].aparell, "competition_unit", "") != "team":
                errors.append(
                    f"presentacio.columnes[{idx}] raw: en team_mode=native_team nomes es poden mostrar aparells d'equip."
                )
                continue
            if selected_ids and app_id not in selected_ids:
                errors.append(f"presentacio.columnes[{idx}] raw: aparell {app_id} no esta seleccionat a puntuacio.")
                continue

            camp = str(src.get("camp") or "").strip()
            if not camp:
                errors.append(f"presentacio.columnes[{idx}] raw: camp obligatori.")
                continue

            if app_id not in meta_cache:
                sch = schemas_by_aparell.get(app_by_id[app_id].aparell_id, {}) or {}
                meta_cache[app_id] = build_metric_meta_for_comp_aparell(
                    app_by_id[app_id],
                    sch,
                    strict_unknown=True,
                )
            info = meta_cache[app_id].get(camp)
            if not info:
                errors.append(
                    f"presentacio.columnes[{idx}] raw: camp '{camp}' no existeix al schema de l'aparell {app_id}."
                )
                continue
            if not info.get("scoreable", False):
                errors.append(
                    f"presentacio.columnes[{idx}] raw: camp '{camp}' no es puntuable directament "
                    f"({info.get('reason')})."
                )
                continue
            if team_mode == "native_team" and not _is_native_team_metric_compatible(info):
                errors.append(
                    f"presentacio.columnes[{idx}] raw: en team_mode=native_team els camps individuals per membre nomes es poden mostrar a presentacio.detall.sections de tipus team_members_table."
                )

    raw_detail = presentacio.get("detall")
    if raw_detail is None:
        return errors, details

    detail_key = detail_section_key_for_tipus(tipus=tipus, team_mode=team_mode)

    def normalize_app(raw):
        try:
            value = int(raw)
        except Exception:
            return None
        return value if value > 0 else None

    def is_app_available(app_id):
        return app_id in app_by_id

    def get_app_unit(app_id):
        comp_app = app_by_id.get(app_id)
        if comp_app is None:
            return ""
        return getattr(comp_app.aparell, "competition_unit", "") or ""

    def get_scoreable_info(app_id, camp):
        if app_id not in meta_cache:
            comp_app = app_by_id.get(app_id)
            if comp_app is None:
                return None
            sch = schemas_by_aparell.get(comp_app.aparell_id, {}) or {}
            meta_cache[app_id] = build_metric_meta_for_comp_aparell(
                comp_app,
                sch,
                strict_unknown=True,
            )
        return meta_cache[app_id].get(camp)

    def validate_exercise(app_id, raw_exercici):
        try:
            exercise = int(raw_exercici or 1)
        except Exception:
            exercise = 0
        if exercise < 1:
            return "exercici invalid."
        comp_app = app_by_id.get(app_id)
        max_ex = max(1, int(getattr(comp_app, "nombre_exercicis", 1) or 1)) if comp_app else 1
        if exercise > max_ex:
            return f"exercici {exercise} fora de rang per l'aparell {app_id} (maxim {max_ex})."
        return None

    details = validate_detail_schema(
        raw_detail,
        detail_section_key=detail_key,
        normalize_app=normalize_app,
        is_app_available=is_app_available,
        get_app_unit=get_app_unit,
        get_scoreable_info=get_scoreable_info,
        selected_apps=(selected_ids or None),
        validate_exercise=validate_exercise,
    )
    errors.extend(validation_details_to_messages(details))
    return errors, details


def _validate_exercicis_selection(competicio, schema: dict):
    schema = schema or {}
    punt = (schema.get("puntuacio") or {})

    mode_sel = str(punt.get("mode_seleccio_exercicis") or "per_aparell_global").strip().lower()
    allowed_sel = {"per_aparell_global", "per_aparell_override", "global_pool"}
    if mode_sel not in allowed_sel:
        return [f"puntuacio.mode_seleccio_exercicis invalid: {mode_sel}"]

    errors = []
    ex_global = punt.get("exercicis") or {}
    errors.extend(_validate_exercicis_cfg_obj(ex_global, "puntuacio.exercicis"))

    if mode_sel != "per_aparell_override":
        return errors

    raw_map = punt.get("exercicis_per_aparell") or {}
    if not isinstance(raw_map, dict):
        errors.append("puntuacio.exercicis_per_aparell ha de ser un objecte {app_id: cfg}.")
        return errors

    active_app_ids, selected_ids = _get_active_and_selected_app_ids(competicio, punt)

    for app_key, ex_cfg in raw_map.items():
        try:
            app_id = int(app_key)
        except Exception:
            errors.append(f"puntuacio.exercicis_per_aparell: app_id invalid {app_key}")
            continue
        if app_id not in active_app_ids:
            errors.append(f"puntuacio.exercicis_per_aparell: aparell {app_id} no valid o no actiu.")
            continue
        if app_id not in selected_ids:
            continue
        errors.extend(_validate_exercicis_cfg_obj(ex_cfg, f"puntuacio.exercicis_per_aparell[{app_id}]"))

    return errors


def _validate_no_tots_mode(schema: dict):
    schema = schema or {}
    errors = []

    punt = schema.get("puntuacio") or {}
    if not isinstance(punt, dict):
        punt = {}
    app_mode = str(((punt.get("aparells") or {}).get("mode") or "seleccionar")).strip().lower()
    if app_mode == "tots":
        errors.append("puntuacio.aparells.mode='tots' no esta permès; cal seleccionar aparells explicitament.")

    desempat = schema.get("desempat") or []
    if not isinstance(desempat, list):
        return errors

    for idx, tie in enumerate(desempat):
        if not isinstance(tie, dict):
            continue
        scope = tie.get("scope") or {}
        if not isinstance(scope, dict):
            continue
        app_scope = scope.get("aparells") or {}
        if not isinstance(app_scope, dict):
            continue
        tie_mode = str(app_scope.get("mode") or "hereta").strip().lower()
        if tie_mode == "tots":
            errors.append(
                f"desempat[{idx}].scope.aparells.mode='tots' no esta permès; usa 'hereta' o seleccio explicita."
            )

    return errors


def _validate_tie_camps_per_aparell(competicio, schema: dict):
    schema = schema or {}
    punt = (schema.get("puntuacio") or {})
    desempat = schema.get("desempat") or []
    if not isinstance(desempat, list):
        return ["desempat ha de ser una llista."]

    active_apps = list(
        CompeticioAparell.objects
        .filter(competicio=competicio, actiu=True)
        .select_related("aparell")
    )
    app_by_id = {ca.id: ca for ca in active_apps}
    if not app_by_id:
        return []

    schemas_by_aparell = {
        s.aparell_id: (s.schema or {})
        for s in ScoringSchema.objects.filter(aparell_id__in=[ca.aparell_id for ca in active_apps]).only("aparell_id", "schema")
    }

    _, selected_ids_main = _get_active_and_selected_app_ids(competicio, punt)
    active_app_ids = set(app_by_id.keys())
    meta_cache = {}
    errors = []

    for idx, tie in enumerate(desempat):
        if not isinstance(tie, dict):
            continue

        camps = _normalize_tie_camps_for_validation(tie)
        if not camps:
            continue

        scope = tie.get("scope") or {}
        if not isinstance(scope, dict):
            scope = {}
        app_scope = scope.get("aparells") or {}
        if not isinstance(app_scope, dict):
            app_scope = {}
        app_mode = str(app_scope.get("mode") or "hereta").strip().lower()

        if app_mode == "seleccionar":
            target_ids = set(_parse_positive_int_list(app_scope.get("ids")))
        elif app_mode == "tots":
            target_ids = set(active_app_ids)
        else:
            target_ids = set(selected_ids_main)

        for app_id in sorted(target_ids):
            if app_id not in active_app_ids:
                errors.append(f"desempat[{idx}]: aparell {app_id} no valid o no actiu.")
                continue

            if app_id not in meta_cache:
                sch = schemas_by_aparell.get(app_by_id[app_id].aparell_id, {}) or {}
                meta_cache[app_id] = build_scoreable_meta_for_schema(sch, strict_unknown=True)
            meta = meta_cache[app_id]

            for code in camps:
                info = meta.get(code)
                if not info:
                    errors.append(f"desempat[{idx}]: aparell {app_id}: camp '{code}' no existeix al schema.")
                    continue
                if not info.get("scoreable", False):
                    errors.append(
                        f"desempat[{idx}]: aparell {app_id}: camp '{code}' no es puntuable directament "
                        f"({info.get('reason')})."
                    )

    return errors


def _validate_tie_exercicis_selection(competicio, schema: dict, *, tipus="individual", team_mode=""):
    schema = schema or {}
    punt = (schema.get("puntuacio") or {})
    desempat = schema.get("desempat") or []
    if not isinstance(desempat, list):
        return ["desempat ha de ser una llista."]

    errors = []
    active_app_ids, selected_ids_main = _get_active_and_selected_app_ids(competicio, punt)
    allow_exercise_scope = _is_derived_team_scope_enabled(tipus=tipus, team_mode=team_mode)
    main_scope = (
        normalize_exercise_selection_scope(punt.get("exercise_selection_scope"))
        if allow_exercise_scope
        else EXERCISE_SELECTION_SCOPE_PER_MEMBER
    )

    for idx, tie in enumerate(desempat):
        if not isinstance(tie, dict):
            errors.append(f"desempat[{idx}] ha de ser un objecte.")
            continue

        scope = tie.get("scope") or {}
        if not isinstance(scope, dict):
            errors.append(f"desempat[{idx}].scope ha de ser un objecte.")
            scope = {}
        ex_scope = scope.get("exercicis") or {}
        if scope.get("exercicis") is not None and not isinstance(scope.get("exercicis"), dict):
            errors.append(f"desempat[{idx}].scope.exercicis ha de ser un objecte.")
        if not isinstance(ex_scope, dict):
            ex_scope = {}

        effective_tie_scope = _effective_tie_exercise_selection_scope(
            tie,
            main_scope=main_scope,
        )
        if effective_tie_scope == EXERCISE_SELECTION_SCOPE_TEAM_POOL:
            if scope.get("exercicis") not in (None, {}):
                errors.append(
                    f"desempat[{idx}].scope.exercicis no es compatible amb exercise_selection_scope=team_pool."
                )
            mode_sel_present = (
                tie.get("mode_seleccio_exercicis") not in (None, "")
                or ex_scope.get("mode_seleccio_exercicis") not in (None, "")
            )
            if mode_sel_present:
                errors.append(
                    f"desempat[{idx}].mode_seleccio_exercicis no es compatible amb exercise_selection_scope=team_pool."
                )
            raw_map = tie.get("exercicis_per_aparell")
            if raw_map is None:
                raw_map = ex_scope.get("exercicis_per_aparell")
            if raw_map not in (None, {}, []):
                errors.append(
                    f"desempat[{idx}].exercicis_per_aparell no es compatible amb exercise_selection_scope=team_pool."
                )
            if scope.get("participants") not in (None, {}):
                errors.append(
                    f"desempat[{idx}].scope.participants no es compatible amb exercise_selection_scope=team_pool."
                )
            if tie.get("agregacio_participants") not in (None, ""):
                errors.append(
                    f"desempat[{idx}].agregacio_participants no es compatible amb exercise_selection_scope=team_pool."
                )
            continue

        ex_mode = str(ex_scope.get("mode") or "hereta").strip().lower()
        if ex_mode != "hereta":
            errors.extend(
                _validate_exercicis_cfg_obj(ex_scope, f"desempat[{idx}].scope.exercicis")
            )

        mode_sel_raw = (
            tie.get("mode_seleccio_exercicis")
            or ex_scope.get("mode_seleccio_exercicis")
            or "hereta"
        )
        mode_sel = str(mode_sel_raw).strip().lower()
        allowed_sel = {"hereta", "per_aparell_global", "per_aparell_override", "global_pool"}
        if mode_sel not in allowed_sel:
            errors.append(f"desempat[{idx}].mode_seleccio_exercicis invalid: {mode_sel}")
            continue
        if mode_sel != "per_aparell_override":
            continue

        app_scope = scope.get("aparells") or {}
        if not isinstance(app_scope, dict):
            app_scope = {}
        app_mode = str(app_scope.get("mode") or "hereta").strip().lower()

        if app_mode == "seleccionar":
            target_ids = set(_parse_positive_int_list(app_scope.get("ids")))
        elif app_mode == "tots":
            target_ids = set(active_app_ids)
        else:
            target_ids = set(selected_ids_main)

        raw_map = tie.get("exercicis_per_aparell")
        if raw_map is None:
            raw_map = ex_scope.get("exercicis_per_aparell")
        if raw_map is None:
            raw_map = {}
        if not isinstance(raw_map, dict):
            errors.append(f"desempat[{idx}].exercicis_per_aparell ha de ser un objecte {{app_id: cfg}}.")
            continue

        for app_key, ex_cfg in raw_map.items():
            try:
                app_id = int(app_key)
            except Exception:
                errors.append(f"desempat[{idx}].exercicis_per_aparell: app_id invalid {app_key}")
                continue
            if app_id not in active_app_ids:
                errors.append(
                    f"desempat[{idx}].exercicis_per_aparell: aparell {app_id} no valid o no actiu."
                )
                continue
            if target_ids and app_id not in target_ids:
                continue
            errors.extend(
                _validate_exercicis_cfg_obj(
                    ex_cfg,
                    f"desempat[{idx}].exercicis_per_aparell[{app_id}]",
                )
            )

    return errors


def _validate_victories_schema(competicio, schema: dict, tipus="individual"):
    schema = schema or {}
    punt = (schema.get("puntuacio") or {})
    if not isinstance(punt, dict):
        punt = {}

    errors = []
    mode_resultat = str(punt.get("mode_resultat_aparells") or "score").strip().lower()
    if mode_resultat not in {"score", "victories"}:
        errors.append(f"puntuacio.mode_resultat_aparells invalid: {mode_resultat}")
        mode_resultat = "score"

    victories = punt.get("victories") or {}
    if punt.get("victories") is not None and not isinstance(punt.get("victories"), dict):
        errors.append("puntuacio.victories ha de ser un objecte.")
        victories = {}

    for key in ("punts_victoria", "punts_empat"):
        raw = victories.get(key, 1 if key == "punts_victoria" else 0.5)
        try:
            float(raw)
        except Exception:
            errors.append(f"puntuacio.victories.{key} ha de ser numeric.")

    sense_nota_mode = str(victories.get("sense_nota_mode") or "skip").strip().lower()
    if sense_nota_mode not in {"skip"}:
        errors.append(f"puntuacio.victories.sense_nota_mode invalid: {sense_nota_mode}")

    if mode_resultat == "victories" and str(tipus or "individual").strip().lower() != "individual":
        errors.append("puntuacio.mode_resultat_aparells='victories' nomes es compatible amb tipus='individual'.")

    if mode_resultat == "victories":
        errors.extend(_validate_victories_granular_options(victories, "puntuacio.victories"))

    compare_ties = victories.get("desempat_comparacio") or []
    if victories.get("desempat_comparacio") is not None and not isinstance(compare_ties, list):
        errors.append("puntuacio.victories.desempat_comparacio ha de ser una llista.")
        compare_ties = []

    for idx, tie in enumerate(compare_ties):
        if not isinstance(tie, dict):
            errors.append(f"puntuacio.victories.desempat_comparacio[{idx}] ha de ser un objecte.")
            continue
        scope = tie.get("scope") or {}
        if not isinstance(scope, dict):
            scope = {}
        if scope.get("aparells") not in (None, {}):
            errors.append(f"puntuacio.victories.desempat_comparacio[{idx}].scope.aparells no esta permes.")
        if scope.get("participants") not in (None, {}):
            errors.append(f"puntuacio.victories.desempat_comparacio[{idx}].scope.participants no esta permes.")
        camps = _normalize_tie_camps_for_validation(tie)
        if not camps:
            errors.append(f"puntuacio.victories.desempat_comparacio[{idx}] requereix almenys un camp.")

    return errors


def validate_particions_schema(competicio, schema: dict):
    schema = schema or {}
    errors = []
    allowed_fields = get_allowed_group_fields(competicio)
    allowed_codes = {str(field.get("code") or "").strip() for field in allowed_fields if str(field.get("code") or "").strip()}
    part_entries = normalize_particions_v2_entries(
        schema.get("particions_v2") or [],
        fallback_codes=schema.get("particions") or [],
    )
    parts = particio_codes_from_entries(part_entries)
    for idx, entry in enumerate(part_entries):
        code = str(entry.get("code") or "").strip()
        if code not in allowed_codes:
            errors.append(f"particions: camp no permes per aquesta competicio: '{code}'")
        apply_mode = str(entry.get("apply_mode") or "all").strip().lower()
        if idx == 0:
            if apply_mode != "all":
                errors.append("particions_v2[0].apply_mode ha de ser 'all'.")
        elif apply_mode not in {"all", "some_parents"}:
            errors.append(f"particions_v2[{idx}].apply_mode invalid: {apply_mode}")
        if idx == 0 and entry.get("parent_values"):
            errors.append("particions_v2[0].parent_values no s'admet al primer nivell.")
        if idx > 0 and apply_mode == "some_parents":
            values = split_particio_custom_values(entry.get("parent_values"))
            if not values:
                errors.append(f"particions_v2[{idx}].parent_values ha de tenir almenys un valor.")
    custom_map = normalize_particions_custom(schema.get("particions_custom") or {})
    for code, cfg in custom_map.items():
        if code not in allowed_codes:
            errors.append(f"particions_custom['{code}']: camp no permes per aquesta competicio.")
            continue
        if code not in parts:
            errors.append(f"particions_custom['{code}']: cal incloure el camp a particions.")
        mode = str(cfg.get("mode") or "raw").strip().lower()
        if mode not in {"raw", "custom"}:
            errors.append(f"particions_custom['{code}'].mode invalid: {mode}")
        if mode != "custom":
            continue
        values_owner = {}
        groups = cfg.get("grups") or []
        if not isinstance(groups, list):
            errors.append(f"particions_custom['{code}'].grups ha de ser una llista.")
            continue
        for gidx, group in enumerate(groups):
            if not isinstance(group, dict):
                errors.append(f"particions_custom['{code}'].grups[{gidx}] ha de ser un objecte.")
                continue
            values = split_particio_custom_values(group.get("values"))
            for val in values:
                key = " ".join(str(val).split()).casefold()
                owner = values_owner.get(key)
                if owner is not None:
                    errors.append(
                        f"particions_custom['{code}']: valor repetit entre grups ({val}) a indexos {owner} i {gidx}."
                    )
                    continue
                values_owner[key] = gidx
    return errors


def selected_app_ids_from_schema(schema_local):
    return _selected_app_ids_from_schema(schema_local)


def get_team_context_capabilities(competicio, context_code):
    return _get_team_context_capabilities(competicio, context_code)

def validate_schema_for_competicio_detailed(competicio, schema_local, tipus="individual"):
    raw_input_schema = schema_local if isinstance(schema_local, dict) else {}
    raw_filters_for_validation = raw_input_schema.get("filtres")
    schema_local, legacy_info = normalize_schema_legacy_team_birth_partition(
        competicio,
        raw_input_schema,
        tipus=tipus,
        persist=False,
    )
    schema_local = normalize_particions_schema(schema_local or {})
    errors = list(legacy_info.get("compatibility_errors") or [])
    details = []
    errors.extend(_validate_filtres_schema({**schema_local, "filtres": raw_filters_for_validation}))
    equips_cfg = normalize_classificacio_equips_cfg(schema_local.get("equips") or {})
    schema_local["equips"] = equips_cfg
    raw_assignment_source = (schema_local.get("equips") or {}).get("assignment_source") or {}
    assignment_source = equips_cfg.get("assignment_source") or normalize_equip_assignment_source(raw_assignment_source)
    context_code = normalize_equip_context_code(assignment_source.get("context_code") or equips_cfg.get("context_code"))
    selected_app_ids = _selected_app_ids_from_schema(schema_local)
    selected_apps = {
        ca.id: ca
        for ca in CompeticioAparell.objects.filter(competicio=competicio, id__in=selected_app_ids).select_related("aparell")
    }
    selected_apps_list = [selected_apps[app_id] for app_id in selected_app_ids if app_id in selected_apps]
    tipus_norm = str(tipus or "").strip().lower()
    if tipus_norm == "individual":
        for app_id in selected_app_ids:
            ca = selected_apps.get(app_id)
            if ca is not None and is_team_context_app(ca):
                errors.append(
                    f"puntuacio.aparells.ids: l'aparell {app_id} es un aparell global d'equip i no es valid per tipus='individual'."
                )
    elif tipus_norm == "equips":
        capabilities = _get_team_context_capabilities(competicio, context_code)
        if not capabilities["exists"]:
            errors.append(f"equips.context_code no existeix: {context_code}")
        explicit_team_mode = normalize_team_mode(equips_cfg.get("team_mode"))
        inferred_team_mode = infer_team_mode_from_comp_aparells(selected_apps_list)
        effective_team_mode = explicit_team_mode or inferred_team_mode
        selected_team_app_ids = {
            int(app_id)
            for app_id in selected_app_ids
            if (selected_apps.get(app_id) is not None and is_team_context_app(selected_apps[app_id]))
        }
        if not capabilities["has_team_apps"] and not selected_team_app_ids:
            effective_team_mode = "derived_from_individual"
        elif not effective_team_mode:
            errors.append("equips.team_mode es obligatori quan el context participa en aparells d'equip.")
        schema_local["equips"]["context_code"] = context_code
        schema_local["equips"]["team_mode"] = effective_team_mode
        if explicit_team_mode and effective_team_mode != explicit_team_mode and capabilities["has_team_apps"]:
            errors.append("equips.team_mode no concorda amb els aparells seleccionats.")
        if effective_team_mode == "derived_from_individual":
            for app_id in selected_app_ids:
                ca = selected_apps.get(app_id)
                if ca is not None and is_team_context_app(ca):
                    errors.append(
                        f"puntuacio.aparells.ids: l'aparell {app_id} no es valid per team_mode=derived_from_individual."
                    )
        elif effective_team_mode == "native_team":
            eligible_ids = set(capabilities["eligible_team_app_ids"])
            for app_id in selected_app_ids:
                ca = selected_apps.get(app_id)
                if ca is None:
                    continue
                if not is_team_context_app(ca):
                    errors.append(
                        f"puntuacio.aparells.ids: l'aparell {app_id} no es valid per team_mode=native_team."
                    )
                elif int(app_id) not in eligible_ids:
                    errors.append(
                        f"puntuacio.aparells.ids: l'aparell {app_id} "
                        f"{_required_context_message_for_app(competicio, app_id)}; "
                        f"no admet el context {context_code}."
                    )
            if bool(equips_cfg.get("incloure_sense_equip", False)):
                errors.append("equips.incloure_sense_equip no es compatible amb team_mode=native_team.")
            if equips_cfg.get("particions_manuals"):
                errors.append("equips.particions_manuals no es compatible amb team_mode=native_team.")
            errors.extend(
                _validate_desempat_mode_compatibility(
                    competicio,
                    schema_local,
                    tipus=tipus,
                    team_mode=effective_team_mode,
                    context_code=context_code,
                    capabilities=capabilities,
                    selected_apps=selected_apps_list,
                )
            )
    errors.extend(
        _validate_exercise_selection_scope(
            schema_local,
            tipus=tipus,
            team_mode=schema_local.get("equips", {}).get("team_mode", ""),
        )
    )
    errors.extend(validate_particions_schema(competicio, schema_local))
    errors.extend(_validate_particions_config_schema(schema_local, tipus=tipus))
    errors.extend(_validate_no_tots_mode(schema_local))
    errors.extend(_validate_camps_per_aparell(competicio, schema_local))
    errors.extend(_validate_tie_camps_per_aparell(competicio, schema_local))
    presentacio_errors, presentacio_details = _validate_presentacio_columns_details(competicio, schema_local, tipus=tipus)
    errors.extend(presentacio_errors)
    details.extend(presentacio_details)
    errors.extend(_validate_exercicis_selection(competicio, schema_local))
    errors.extend(
        _validate_tie_exercicis_selection(
            competicio,
            schema_local,
            tipus=tipus,
            team_mode=schema_local.get("equips", {}).get("team_mode", ""),
        )
    )
    errors.extend(_validate_victories_schema(competicio, schema_local, tipus=tipus))
    return schema_local, errors, details


def validate_schema_for_competicio(competicio, schema_local, tipus="individual"):
    schema_local, errors, _details = validate_schema_for_competicio_detailed(
        competicio,
        schema_local,
        tipus=tipus,
    )
    return schema_local, errors


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
    "build_metric_meta_for_comp_aparell",
    "build_scoreable_meta_for_schema",
    "build_metric_meta_for_schema_owner",
    "build_validation_error_details",
    "get_team_context_capabilities",
    "selected_app_ids_from_schema",
    "validate_particions_schema",
    "validate_schema_for_competicio_detailed",
    "validate_schema_for_competicio",
]
