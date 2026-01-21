# scoring_engine.py
from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Callable

NUM_SALTS_DEFAULT = 11


class ScoringError(Exception):
    pass


def to_float(v: Any) -> float:
    try:
        if v is None or v == "":
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ---------- Funcions "trampolí" (les teves adaptades) ----------

def calc_execucio_jutge(deduccions: List[Any], crash_at: int, num_elements: int = NUM_SALTS_DEFAULT) -> float:
    """
    deduccions: [S1..Sn] en dècimes (0..10)
    crash_at: 0 = sense crash; si crash_at=3 => només compta fins S2
    num_elements: n d'elements (ex 11)
    """
    vals = list(deduccions or [])
    vals = (vals + [0] * num_elements)[:num_elements]

    norm = []
    for v in vals:
        x = to_float(v)
        norm.append(max(0.0, min(10.0, x)))

    # quants elements compten
    if crash_at and crash_at > 0:
        k = max(0, min(num_elements, int(crash_at) - 1))
    else:
        k = num_elements

    # punts base: S1..S10 sumen 1 punt per element fet; si hi ha més d'11, mantenim la regla:
    # només els 10 primers donen base.
    base = min(k, 10)

    ded = sum(norm[:k]) / 10.0
    return base - ded


def select_exec_notes(exec_scores: List[float], k: int, criteri: str) -> List[float]:
    vals = [float(x) for x in (exec_scores or [])]
    n = len(vals)
    if n == 0:
        return []
    k = max(1, min(int(k), n))

    if criteri == "minimes":
        return sorted(vals)[:k]
    if criteri == "maximes":
        return sorted(vals, reverse=True)[:k]

    if criteri == "eliminar_extrems":
        s = sorted(vals)
        if len(s) <= k:
            return s

        # Cas n = k + 1: elimina el més allunyat de la mediana (empat -> elimina el màxim)
        if len(s) == k + 1:
            m = len(s)
            if m % 2 == 1:
                med = s[m // 2]
            else:
                med = (s[m // 2 - 1] + s[m // 2]) / 2.0

            dists = [abs(x - med) for x in s]
            max_dist = max(dists)
            idxs = [i for i, d in enumerate(dists) if d == max_dist]
            drop_idx = idxs[-1]
            s.pop(drop_idx)
            return s

        # Cas general: treu parelles min+max fins quedar k
        while len(s) > k and (len(s) - 2) >= k:
            s = s[1:-1]

        # Si encara sobra 1, aplica mediana
        if len(s) > k:
            m = len(s)
            if m % 2 == 1:
                med = s[m // 2]
            else:
                med = (s[m // 2 - 1] + s[m // 2]) / 2.0
            dists = [abs(x - med) for x in s]
            max_dist = max(dists)
            idxs = [i for i, d in enumerate(dists) if d == max_dist]
            drop_idx = idxs[-1]
            s.pop(drop_idx)

        return s

    # "totes": millors k
    return sorted(vals, reverse=True)[:k]


# ---------- Evaluador segur amb AST ----------

ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod)
ALLOWED_UNARYOPS = (ast.UAdd, ast.USub)

def _is_safe_name(name: str) -> bool:
    return name.isidentifier() and not name.startswith("__")


class SafeEval(ast.NodeVisitor):
    def __init__(self, context: Dict[str, Any], functions: Dict[str, Callable[..., Any]]):
        self.context = context
        self.functions = functions

    def visit(self, node):
        # nodes permesos
        if isinstance(node, ast.Expression):
            return self.visit(node.body)

        if isinstance(node, ast.Constant):
            return node.value

        if isinstance(node, ast.Name):
            if node.id in self.context:
                return self.context[node.id]
            raise ScoringError(f"Nom desconegut: {node.id}")

        if isinstance(node, ast.BinOp) and isinstance(node.op, ALLOWED_BINOPS):
            left = self.visit(node.left)
            right = self.visit(node.right)
            return self._binop(node.op, left, right)

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ALLOWED_UNARYOPS):
            val = self.visit(node.operand)
            return +val if isinstance(node.op, ast.UAdd) else -val

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ScoringError("Crida de funció no permesa.")
            fname = node.func.id
            if fname not in self.functions:
                raise ScoringError(f"Funció no permesa: {fname}")
            args = [self.visit(a) for a in node.args]
            kwargs = {kw.arg: self.visit(kw.value) for kw in node.keywords}
            return self.functions[fname](*args, **kwargs)

        if isinstance(node, ast.Subscript):
            # permet dict/list indexing simple: x["a"] o x[0]
            base = self.visit(node.value)
            idx = self.visit(node.slice)
            try:
                return base[idx]
            except Exception:
                raise ScoringError("Accés a índex no vàlid.")

        if isinstance(node, ast.Dict):
            return {self.visit(k): self.visit(v) for k, v in zip(node.keys, node.values)}

        if isinstance(node, ast.List):
            return [self.visit(elt) for elt in node.elts]

        if isinstance(node, ast.Tuple):
            return tuple(self.visit(elt) for elt in node.elts)

        raise ScoringError(f"Expressió no permesa: {node.__class__.__name__}")

    def _binop(self, op, left, right):
        l = left
        r = right
        if isinstance(op, ast.Add):
            return l + r
        if isinstance(op, ast.Sub):
            return l - r
        if isinstance(op, ast.Mult):
            return l * r
        if isinstance(op, ast.Div):
            return l / r
        if isinstance(op, ast.Mod):
            return l % r
        raise ScoringError("Operador no permès.")


def safe_eval(expr: str, context: Dict[str, Any], functions: Dict[str, Callable[..., Any]]) -> Any:
    if not isinstance(expr, str) or not expr.strip():
        return 0
    tree = ast.parse(expr, mode="eval")
    # bloqueja noms perillosos via context/functions only
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            raise ScoringError("Accés per atribut no permès.")
        if isinstance(node, ast.Name) and not _is_safe_name(node.id):
            raise ScoringError("Nom no permès.")
    return SafeEval(context, functions).visit(tree)


# ---------- Engine principal ----------

@dataclass
class EngineResult:
    inputs: Dict[str, Any]
    outputs: Dict[str, Any]
    total: float


class ScoringEngine:
    """
    Schema esperat (mínim):
    {
      "params": {...},
      "fields": [{code,label,type,...}],
      "computed": [{code,label,type,formula}],
      "ui": {...}
    }
    """

    def __init__(self, schema: Dict[str, Any]):
        if not isinstance(schema, dict):
            raise ScoringError("Schema invàlid (no és dict).")
        self.schema = schema
        self.params = schema.get("params", {}) if isinstance(schema.get("params", {}), dict) else {}

        self.fields = schema.get("fields", []) if isinstance(schema.get("fields", []), list) else []
        self.computed = schema.get("computed", []) if isinstance(schema.get("computed", []), list) else []

        self.field_codes = [f.get("code") for f in self.fields if isinstance(f, dict) and f.get("code")]
        self.comp_codes = [c.get("code") for c in self.computed if isinstance(c, dict) and c.get("code")]

        self._functions = self._build_functions()

    def _field_cfg(self, code: str) -> dict:
        for f in self.fields:
            if isinstance(f, dict) and f.get("code") == code:
                return f
        return {}

    def _crash_key(self, field_code: str) -> str:
        return f"__crash__{field_code}"


    def _build_functions(self) -> Dict[str, Callable[..., Any]]:
        def _sum(x):
            return sum(x or [])
        def _avg(x):
            x = list(x or [])
            return (sum(x) / len(x)) if x else 0.0
        def _min(x):
            x = list(x or [])
            return min(x) if x else 0.0
        def _max(x):
            x = list(x or [])
            return max(x) if x else 0.0

        def exec_by_judge(E, crash, params):
            n_elements = int((params or {}).get("n_elements") or (params or {}).get("num_elements") or NUM_SALTS_DEFAULT)
            n_elements = max(1, min(50, n_elements))
            # E: judge_x_element
            rows = list(E or [])
            cr = list(crash or [])
            out = []
            for j, row in enumerate(rows):
                crash_at = int(cr[j]) if j < len(cr) else 0
                out.append(calc_execucio_jutge(row or [], crash_at, num_elements=n_elements))
            return out

        def select_sum(scores, n_valid, criteri):
            selected = select_exec_notes(scores or [], int(n_valid or 1), str(criteri or "totes"))
            return float(sum(selected))

        def best_n(scores, n):
            s = sorted([to_float(x) for x in (scores or [])], reverse=True)
            return s[: max(0, int(n or 0))]

        def as_float(x):
            return to_float(x)
        
        def field(code):
            return self._field_cfg(str(code))

        def crash(field_code):
            return (self._latest_context or {}).get(self._crash_key(str(field_code)), [])

        return {
            "sum": _sum,
            "avg": _avg,
            "min": _min,
            "max": _max,
            "exec_by_judge": exec_by_judge,
            "select_sum": select_sum,
            "best_n": best_n,
            "float": as_float,
            "field": field,
            "crash": crash,
        }

    def validate_and_normalize_inputs(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(inputs, dict):
            raise ScoringError("inputs ha de ser un objecte JSON (dict).")

        normalized: Dict[str, Any] = {}

        for f in self.fields:
            if not isinstance(f, dict):
                continue
            code = f.get("code")
            ftype = f.get("type")
            if not code:
                continue

            raw = inputs.get(code)

            # --- per camp: jutges i items ---
            judges_cfg = f.get("judges") if isinstance(f.get("judges"), dict) else {}
            n_judges = int(judges_cfg.get("count") or 1)
            n_judges = max(1, min(10, n_judges))

            items_cfg = f.get("items") if isinstance(f.get("items"), dict) else {}
            n_items = int(items_cfg.get("count") or 0)
            n_items = max(0, min(50, n_items))

            mn = f.get("min")
            mx = f.get("max")

            if ftype == "number":
                x = to_float(raw)
                if mn is not None: x = max(float(mn), x)
                if mx is not None: x = min(float(mx), x)
                normalized[code] = x

            elif ftype == "list" and f.get("shape") == "judge":
                arr = raw if isinstance(raw, list) else []
                while len(arr) < n_judges:
                    arr.append(0)
                arr = arr[:n_judges]
                out = []
                for v in arr:
                    x = to_float(v)
                    if mn is not None: x = max(float(mn), x)
                    if mx is not None: x = min(float(mx), x)
                    out.append(x)
                normalized[code] = out

            elif ftype == "matrix" and f.get("shape") in ("judge_x_item", "judge_x_element"):
                # normalitza n_judges x n_items
                mat = raw if isinstance(raw, list) else []
                while len(mat) < n_judges:
                    mat.append([0] * n_items)
                mat = mat[:n_judges]

                out = []
                for j in range(n_judges):
                    row = mat[j] if isinstance(mat[j], list) else []
                    row = (row + [0] * n_items)[:n_items]
                    r2 = []
                    for v in row:
                        x = to_float(v)
                        if mn is not None: x = max(float(mn), x)
                        if mx is not None: x = min(float(mx), x)
                        r2.append(x)
                    out.append(r2)
                normalized[code] = out

                # crash per camp
                crash_cfg = f.get("crash") if isinstance(f.get("crash"), dict) else {}
                if crash_cfg.get("enabled"):
                    ck = self._crash_key(code)
                    raw_crash = inputs.get(ck, [])
                    cr = raw_crash if isinstance(raw_crash, list) else []
                    while len(cr) < n_judges:
                        cr.append(0)
                    cr = cr[:n_judges]
                    # crash_at 0..n_items
                    normalized[ck] = [max(0, min(n_items, int(x or 0))) for x in cr]

            else:
                normalized[code] = raw

        return normalized


    def compute(self, inputs: Dict[str, Any]) -> EngineResult:
        norm_inputs = self.validate_and_normalize_inputs(inputs)

        context: Dict[str, Any] = {}
        # exposa inputs i params
        context.update(norm_inputs)
        self._latest_context = context
        context["params"] = self.params

        outputs: Dict[str, Any] = {}

        # --- Aliases: permet 'x' com a variable curta ---
        aliases = {}
        # 1) aliases globals
        if isinstance(self.params.get("aliases"), dict):
            aliases.update(self.params["aliases"])

        # 2) aliases per field/computed via "var"
        for f in self.fields:
            if isinstance(f, dict) and f.get("var") and f.get("code"):
                aliases[str(f["var"])] = str(f["code"])
        for c in self.computed:
            if isinstance(c, dict) and c.get("var") and c.get("code"):
                aliases[str(c["var"])] = str(c["code"])

        # Injecta variables curtes al context (si existeix el codi)
        for short, code in aliases.items():
            if short and code:
                if code in context:
                    context[short] = context[code]

        # computed: resolució seqüencial simple (si vols, després hi afegeixes topological sort)
        for c in self.computed:
            if not isinstance(c, dict):
                continue
            code = c.get("code")
            formula = c.get("formula")
            if not code or not formula:
                continue
            val = safe_eval(formula, {**context, **outputs}, self._functions)
            outputs[code] = val

        total = to_float(outputs.get("TOTAL", outputs.get("total", 0)))
        return EngineResult(inputs=norm_inputs, outputs=outputs, total=total)
