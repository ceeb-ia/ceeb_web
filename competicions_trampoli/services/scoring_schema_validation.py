# scoring_schema_validation.py
from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from django.core.exceptions import ValidationError


# =========================
# Config / helpers
# =========================

ALLOWED_FUNCTIONS: Set[str] = {
    "sum", "avg", "min", "max",
    "exec_by_judge", "select_sum", "best_n",
    "float", "field", "crash", "row_custom_compute",
    "column_custom_compute"
}

RESERVED_NAMES: Set[str] = set(ALLOWED_FUNCTIONS) | {"params"}

def is_identifier(name: str) -> bool:
    return isinstance(name, str) and name.isidentifier()

def fmt_loc(prefix: str, idx: Optional[int], code: Optional[str]) -> str:
    if idx is None and not code:
        return prefix
    parts = [prefix]
    if idx is not None:
        parts.append(f"[{idx}]")
    if code:
        parts.append(f"({code})")
    return " ".join(parts)

def _ast_parse(expr: str, loc: str) -> ast.AST:
    try:
        return ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ValidationError(f"{loc}: sintaxi invàlida a la fórmula: {e.msg} (línia {e.lineno}, col {e.offset})")

def _extract_names(tree: ast.AST) -> Set[str]:
    names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        # bloqueig bàsic d'atributs (com l'engine)
        if isinstance(node, ast.Attribute):
            # l'engine també ho bloqueja, millor avisar ja al desar
            raise ValidationError("No es permet accés per atribut (p.ex. x.y).")
    return names


# =========================
# Shape / dry-run B1
# =========================

@dataclass(frozen=True)
class Shape:
    """Sempre matrius: (rows, cols). rows/cols poden ser None si desconegut."""
    rows: Optional[int]
    cols: Optional[int]

    def is_scalar(self) -> bool:
        return self.rows == 1 and self.cols == 1

    def same_as(self, other: "Shape") -> bool:
        if self.rows is not None and other.rows is not None and self.rows != other.rows:
            return False
        if self.cols is not None and other.cols is not None and self.cols != other.cols:
            return False
        return True

    def __str__(self) -> str:
        r = "?" if self.rows is None else str(self.rows)
        c = "?" if self.cols is None else str(self.cols)
        return f"{r}x{c}"


class ShapeError(Exception):
    pass


class TMat:
    """
    Valor sentinella per dry-run. Només propaga shape i comprova compatibilitats.
    Política:
      - Tot són matrius.
      - Un 1x1 pot actuar com escalar en funcions que ho requereixin (auto-squeeze).
      - Operacions + i - requereixen shapes compatibles (mateixa mida; 1x1 NO fa broadcast per defecte).
      - * i / (matemàtica general) per simplicitat: només permet 1x1 amb 1x1.
        (Si vols escalar una matriu amb 1x1, es pot habilitar fàcilment.)
    """
    def __init__(self, shape: Shape, name: str = ""):
        self.shape = shape
        self.name = name or "<?>"

    def _bin_same(self, op: str, other: "TMat") -> "TMat":
        if not isinstance(other, TMat):
            raise ShapeError(f"{op}: operand dret no és matriu.")
        if not self.shape.same_as(other.shape):
            raise ShapeError(f"{op}: shapes incompatibles {self.shape} i {other.shape}.")
        return TMat(_merge_shape(self.shape, other.shape), name=f"({self.name}{op}{other.name})")

    def __add__(self, other: "TMat") -> "TMat":
        return self._bin_same("+", other)

    def __sub__(self, other: "TMat") -> "TMat":
        return self._bin_same("-", other)

    def __mul__(self, other: "TMat") -> "TMat":
        # conservador: només 1x1 * 1x1
        if not isinstance(other, TMat):
            raise ShapeError("*: operand dret no és matriu.")
        if not self.shape.is_scalar() or not other.shape.is_scalar():
            raise ShapeError(f"*: només es permet 1x1 * 1x1 (has posat {self.shape} * {other.shape}).")
        return TMat(Shape(1, 1), name=f"({self.name}*{other.name})")

    def __truediv__(self, other: "TMat") -> "TMat":
        if not isinstance(other, TMat):
            raise ShapeError("/: operand dret no és matriu.")
        if not self.shape.is_scalar() or not other.shape.is_scalar():
            raise ShapeError(f"/: només es permet 1x1 / 1x1 (has posat {self.shape} / {other.shape}).")
        return TMat(Shape(1, 1), name=f"({self.name}/{other.name})")

    def __pos__(self) -> "TMat":
        return self

    def __neg__(self) -> "TMat":
        return TMat(self.shape, name=f"(-{self.name})")


def _merge_shape(a: Shape, b: Shape) -> Shape:
    """Unifica (manté valor concret si existeix)."""
    rows = a.rows if a.rows is not None else b.rows
    cols = a.cols if a.cols is not None else b.cols
    return Shape(rows, cols)


# Funcions sentinella (mateixa signatura lògica que engine)
def fn_sum(x: TMat) -> TMat:
    # sum de qualsevol matriu -> 1x1
    return TMat(Shape(1, 1), name="sum")

def fn_avg(x: TMat) -> TMat:
    return TMat(Shape(1, 1), name="avg")

def fn_min(x: TMat) -> TMat:
    return TMat(Shape(1, 1), name="min")

def fn_max(x: TMat) -> TMat:
    return TMat(Shape(1, 1), name="max")

def fn_float(x: TMat) -> TMat:
    # auto-squeeze: si és 1x1 ok; si no, error (evitem "float" d'una matriu gran)
    if not x.shape.is_scalar():
        raise ShapeError(f"float(): només s'accepta 1x1; has passat {x.shape}.")
    return TMat(Shape(1, 1), name="float")

def fn_exec_by_judge(E: TMat, crash: TMat, params: Any) -> TMat:
    # E: JxN ; crash: Jx1 ; retorna Jx1
    if E.shape.rows is not None and crash.shape.rows is not None and E.shape.rows != crash.shape.rows:
        raise ShapeError(f"exec_by_judge(): J no coincideix: E {E.shape} vs crash {crash.shape}.")
    if crash.shape.cols is not None and crash.shape.cols != 1:
        raise ShapeError(f"exec_by_judge(): crash ha de ser Jx1; has passat {crash.shape}.")
    if E.shape.cols is None:
        # no podem saber N -> ok
        return TMat(Shape(E.shape.rows, 1), name="exec_by_judge")
    return TMat(Shape(E.shape.rows, 1), name="exec_by_judge")

def fn_select_sum(scores: TMat, n_valid: TMat, criteri: TMat) -> TMat:
    # scores: Jx1 (o 1xJ si vols); n_valid i criteri: 1x1
    if not n_valid.shape.is_scalar():
        raise ShapeError(f"select_sum(): n_valid ha de ser 1x1; has passat {n_valid.shape}.")
    if not criteri.shape.is_scalar():
        raise ShapeError(f"select_sum(): criteri ha de ser 1x1; has passat {criteri.shape}.")
    # scores: acceptem qualsevol shape, però recomanem 1D
    return TMat(Shape(1, 1), name="select_sum")

def fn_best_n(scores: TMat, n: TMat) -> TMat:
    if not n.shape.is_scalar():
        raise ShapeError(f"best_n(): n ha de ser 1x1; has passat {n.shape}.")
    # retorna Kx1 però K pot ser variable
    return TMat(Shape(None, 1), name="best_n")

def fn_field(code: TMat) -> TMat:
    # és runtime-only, però si apareix a fórmules, retornem 1x1 "placeholder"
    if not code.shape.is_scalar():
        raise ShapeError(f"field(): el codi ha de ser 1x1; has passat {code.shape}.")
    return TMat(Shape(1, 1), name="field")

def fn_crash(field_code: TMat) -> TMat:
    # runtime: crash(field_code) -> Jx1. Aquí ho deixem desconegut en rows.
    if not field_code.shape.is_scalar():
        raise ShapeError(f"crash(): field_code ha de ser 1x1; has passat {field_code.shape}.")
    return TMat(Shape(None, 1), name="crash")


SENTINEL_FUNCS = {
    "sum": fn_sum,
    "avg": fn_avg,
    "min": fn_min,
    "max": fn_max,
    "float": fn_float,
    "exec_by_judge": fn_exec_by_judge,
    "select_sum": fn_select_sum,
    "best_n": fn_best_n,
    "field": fn_field,
    "crash": fn_crash,
}


class DryRunEval(ast.NodeVisitor):
    """
    Evaluador de shapes. Permet:
      - constants: es consideren 1x1
      - Name: lookup a context
      - BinOp: + - * /
      - UnaryOp: + -
      - Call: funcions permeses
      - Subscript: només suporta el cas clau: matriu 1x1 accedida [0][0] -> 1x1
        (i en general, indexar no canvia a nivel de shape, però no ho fem complet per seguretat)
    """
    def __init__(self, context: Dict[str, TMat]):
        self.context = context

    def visit(self, node: ast.AST) -> TMat:
        if isinstance(node, ast.Expression):
            return self.visit(node.body)

        if isinstance(node, ast.Constant):
            # constants -> 1x1
            return TMat(Shape(1, 1), name=str(node.value))

        if isinstance(node, ast.Name):
            if node.id in self.context:
                return self.context[node.id]
            raise ShapeError(f"Nom desconegut: {node.id}")

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            v = self.visit(node.operand)
            return +v if isinstance(node.op, ast.UAdd) else -v

        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            a = self.visit(node.left)
            b = self.visit(node.right)
            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
            if isinstance(node.op, ast.Mult):
                return a * b
            if isinstance(node.op, ast.Div):
                return a / b

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ShapeError("Crida de funció no permesa (només funcions directes).")
            fname = node.func.id
            if fname not in SENTINEL_FUNCS:
                raise ShapeError(f"Funció no permesa: {fname}")
            args = [self.visit(a) for a in node.args]
            # ignorem kwargs per simplicitat (si ho necessites, ho afegim)
            return SENTINEL_FUNCS[fname](*args)  # type: ignore[misc]

        if isinstance(node, ast.Subscript):
            
            base = self.visit(node.value)

            sl = node.slice

            # --- 1) Accés per clau string: x['valid'] / x['count'] ---
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                # En validació, assumim que accedir a config/dict torna un valor escalar (1x1)
                return TMat(Shape(1, 1), name=f"{base.name}['{sl.value}']")

            # --- 2) Accés per índex enter constant: x[0] ---
            idx = None
            if isinstance(sl, ast.Constant) and isinstance(sl.value, int):
                idx = sl.value
            elif isinstance(sl, ast.Index) and isinstance(sl.value, ast.Constant) and isinstance(sl.value.value, int):
                idx = sl.value.value  # compat antics
            if idx is None:
                raise ShapeError("Indexació només permesa amb enters o strings constants (p.ex. [0] o ['valid']).")

            r, c = base.shape.rows, base.shape.cols

            # 1x1 -> segueix 1x1
            if base.shape.is_scalar():
                return TMat(Shape(1, 1), name=f"{base.name}[{idx}]")

            # Matriu com llista de files: M[i] -> 1 x C
            if r is None or r >= 1:
                # Si ja és 1xC, indexar dona element 1x1
                if r == 1 and (c is None or c >= 1):
                    return TMat(Shape(1, 1), name=f"{base.name}[{idx}]")
                return TMat(Shape(1, c), name=f"{base.name}[{idx}]")

            raise ShapeError(f"Indexació sobre matriu invàlida: {base.shape}.")
        
        
        if isinstance(node, (ast.List, ast.Tuple, ast.Dict)):
            # per simplicitat, prohibim construir estructures literals a fórmules
            raise ShapeError("No es permeten literals de llista/tuple/dict a les fórmules (usa camps/funcions).")

        raise ShapeError(f"Node no permès a la fórmula: {node.__class__.__name__}")


# =========================
# Validació principal
# =========================

def _field_shape(field: Dict[str, Any]) -> Shape:
    ftype = field.get("type")
    shape = field.get("shape")

    if ftype == "number":
        return Shape(1, 1)

    if ftype == "list" and shape == "judge":
        judges_cfg = field.get("judges") if isinstance(field.get("judges"), dict) else {}
        n_j = int(judges_cfg.get("count") or 1)
        n_j = max(1, min(10, n_j))
        return Shape(n_j, 1)

    if ftype == "matrix" and shape in ("judge_x_item", "judge_x_element"):
        judges_cfg = field.get("judges") if isinstance(field.get("judges"), dict) else {}
        n_j = int(judges_cfg.get("count") or 1)
        n_j = max(1, min(10, n_j))

        items_cfg = field.get("items") if isinstance(field.get("items"), dict) else {}
        n_i = int(items_cfg.get("count") or 0)
        n_i = max(0, min(50, n_i))

        # matriu J x I
        return Shape(n_j, n_i)

    # desconegut -> 1x1 (conservador)
    return Shape(1, 1)


def _build_alias_map(fields: List[Dict[str, Any]], computed: List[Dict[str, Any]], params: Dict[str, Any]) -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    if isinstance(params.get("aliases"), dict):
        for k, v in params["aliases"].items():
            if isinstance(k, str) and isinstance(v, str):
                aliases[k] = v

    for f in fields:
        if isinstance(f, dict) and f.get("var") and f.get("code"):
            aliases[str(f["var"])] = str(f["code"])
    for c in computed:
        if isinstance(c, dict) and c.get("var") and c.get("code"):
            aliases[str(c["var"])] = str(c["code"])
    return aliases


def _resolve_name(name: str, aliases: Dict[str, str]) -> str:
    return aliases.get(name, name)


def _topo_sort(nodes: List[str], deps: Dict[str, Set[str]]) -> List[str]:
    """
    Kahn topo sort. deps[n] = set(dependències (altres computed)).
    """
    indeg = {n: 0 for n in nodes}
    for n in nodes:
        for d in deps.get(n, set()):
            indeg[n] += 1

    # adjacency invertida: qui depèn de mi
    rev: Dict[str, Set[str]] = {n: set() for n in nodes}
    for n in nodes:
        for d in deps.get(n, set()):
            if d in rev:
                rev[d].add(n)

    q = [n for n in nodes if indeg[n] == 0]
    out: List[str] = []
    while q:
        cur = q.pop(0)
        out.append(cur)
        for nxt in rev.get(cur, set()):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)

    if len(out) != len(nodes):
        # cicle: extreu una pista simple
        remaining = [n for n in nodes if n not in out]
        raise ValidationError(f"S'ha detectat un cicle entre computed: {', '.join(remaining)}")
    return out


def validate_schema(schema: Dict[str, Any]) -> None:
    errors: List[str] = []

    if not isinstance(schema, dict):
        raise ValidationError("Schema: ha de ser un objecte (dict).")

    params = schema.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        errors.append("Schema.params ha de ser un dict.")

    fields = schema.get("fields", [])
    computed = schema.get("computed", [])

    if not isinstance(fields, list):
        errors.append("Schema.fields ha de ser una llista.")
        fields = []
    if not isinstance(computed, list):
        errors.append("Schema.computed ha de ser una llista.")
        computed = []

    # --- collect codes/vars and basic checks ---
    field_codes: List[str] = []
    comp_codes: List[str] = []

    seen_codes: Set[str] = set()
    seen_vars: Set[str] = set()

    def check_symbol(kind: str, idx: int, obj: Dict[str, Any]) -> None:
        loc = fmt_loc(kind, idx, obj.get("code"))
        code = obj.get("code")
        var = obj.get("var")

        if not code or not isinstance(code, str):
            errors.append(f"{loc}: falta 'code' (string).")
            return
        if not is_identifier(code):
            errors.append(f"{loc}: 'code' no és un identificador Python vàlid: {code!r}")
        if code in RESERVED_NAMES:
            errors.append(f"{loc}: 'code' reservat/no permès: {code!r}")
        if code in seen_codes:
            errors.append(f"{loc}: 'code' duplicat: {code!r}")
        seen_codes.add(code)

        if var:
            if not isinstance(var, str) or not is_identifier(var):
                errors.append(f"{loc}: 'var' no és un identificador vàlid: {var!r}")
            else:
                if var in RESERVED_NAMES:
                    errors.append(f"{loc}: 'var' reservat/no permès: {var!r}")
                if var in seen_vars:
                    errors.append(f"{loc}: 'var' duplicat: {var!r}")
                seen_vars.add(var)

    for i, f in enumerate(fields):
        if not isinstance(f, dict):
            errors.append(f"fields[{i}] ha de ser un objecte (dict).")
            continue
        check_symbol("fields", i, f)
        if isinstance(f.get("code"), str):
            field_codes.append(f["code"])

    for i, c in enumerate(computed):
        if not isinstance(c, dict):
            errors.append(f"computed[{i}] ha de ser un objecte (dict).")
            continue
        check_symbol("computed", i, c)
        if isinstance(c.get("code"), str):
            comp_codes.append(c["code"])

    # si ja hi ha errors greus, parem aviat
    if errors:
        raise ValidationError(errors)

    aliases = _build_alias_map(fields, computed, params if isinstance(params, dict) else {})
    # valida aliases: no apuntin a res inexistent
    all_codes = set(field_codes) | set(comp_codes)
    for short, code in aliases.items():
        if short in RESERVED_NAMES:
            errors.append(f"Alias '{short}' és un nom reservat.")
        if code not in all_codes:
            errors.append(f"Alias '{short}' apunta a un code inexistent: {code!r}")

    if errors:
        raise ValidationError(errors)

    # --- AST linter: noms desconeguts + dependències computed ---
    allowed_names = set(field_codes) | set(comp_codes) | set(aliases.keys()) | RESERVED_NAMES | ALLOWED_FUNCTIONS

    comp_deps: Dict[str, Set[str]] = {cc: set() for cc in comp_codes}
    comp_formula: Dict[str, str] = {}

    for i, c in enumerate(computed):
        code = str(c.get("code"))
        loc = fmt_loc("computed", i, code)
        formula = c.get("formula")
        if not formula or not isinstance(formula, str):
            errors.append(f"{loc}: falta 'formula' (string).")
            continue

        comp_formula[code] = formula
        tree = _ast_parse(formula, loc)

        try:
            names = _extract_names(tree)
        except ValidationError as ve:
            errors.append(f"{loc}: {ve.message}")
            continue

        # resolució d'aliases
        resolved = {_resolve_name(n, aliases) for n in names}

        # desconeguts (filtra funcions i params)
        unknown = [n for n in names if n not in allowed_names]
        if unknown:
            errors.append(f"{loc}: variables no declarades: {', '.join(sorted(set(unknown)))}")

        # dependències computed
        for r in resolved:
            if r in comp_deps and r != code:
                comp_deps[code].add(r)

    if errors:
        raise ValidationError(errors)

    # --- topo / cicles ---
    try:
        order = _topo_sort(comp_codes, comp_deps)
    except ValidationError as ve:
        raise

    # --- Dry-run B1: shape check en ordre topo ---
    # context inicial: camps + params (params -> 1x1 placeholder)
    ctx: Dict[str, TMat] = {}

    # camps
    for f in fields:
        code = str(f.get("code"))
        sh = _field_shape(f)
        ctx[code] = TMat(sh, name=code)

    # params: placeholder 1x1 (si vols, pots mapar cada param a 1x1)
    ctx["params"] = TMat(Shape(1, 1), name="params")

    # injecta aliases a context (apunten al mateix shape del seu code)
    for short, code in aliases.items():
        if code in ctx:
            ctx[short] = ctx[code]

    # computed en ordre topo
    for code in order:
        # troba objecte computed
        cobj = next((x for x in computed if isinstance(x, dict) and x.get("code") == code), None)
        if not cobj:
            continue
        formula = str(cobj.get("formula") or "")
        loc = f"computed({code})"

        tree = _ast_parse(formula, loc)
        try:
            # dry-run
            val = DryRunEval(ctx).visit(tree)
        except ShapeError as e:
            errors.append(f"{loc}: incoherència de shape: {e}")
            continue
        except ValidationError as ve:
            errors.append(f"{loc}: {ve.message}")
            continue

        # guarda shape del computed
        ctx[code] = val
        # si té var, també
        var = cobj.get("var")
        if isinstance(var, str) and var in aliases:
            ctx[var] = val

    if errors:
        raise ValidationError(errors)
