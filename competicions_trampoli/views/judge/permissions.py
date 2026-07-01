from ...services.scoring.team_scoring import (
    build_permission_label,
    normalize_permission_target,
    resolve_permission_runtime_entries,
)
from ...services.judging.supervision import normalize_judge_role
from ...services.scoring.judge_presence import merge_judge_patch_into_canonical, presence_key


def _sanitize_patch_by_permissions(schema: dict, permissions: list, patch: dict) -> dict:
    """
    Retorna un patch limitat a:
    - camps autoritzats
    - per matrix: nomes la fila judge_index i rang d'items si s'ha definit
    - per list: nomes index judge_index
    """
    by_code = {}
    for field in (schema.get("fields") or []):
        if isinstance(field, dict) and field.get("code"):
            by_code[field["code"]] = field

    def _effective_permissions_for_patch(perm):
        runtime_code = str(perm.get("runtime_field_code") or perm.get("field_code") or "").strip()
        field = by_code.get(runtime_code)
        if not field or normalize_judge_role(perm.get("role")) != "supervisor":
            return [perm]
        ftype = str(field.get("type") or "number").strip().lower()
        if ftype not in {"matrix", "list"}:
            return [perm]
        n_judges = max(1, int(((field.get("judges") or {}).get("count")) or perm.get("judge_index") or 1))
        out = []
        for judge_index in range(1, n_judges + 1):
            row = dict(perm)
            row["judge_index"] = judge_index
            out.append(row)
        return out

    perms_by_code = {}
    for perm in permissions:
        for effective_perm in _effective_permissions_for_patch(perm):
            runtime_code = str(effective_perm.get("runtime_field_code") or effective_perm.get("field_code") or "").strip()
            if not runtime_code:
                continue
            perms_by_code.setdefault(runtime_code, []).append(effective_perm)

    clean = {}

    for code, incoming_val in (patch or {}).items():
        is_crash_key = isinstance(code, str) and code.startswith("__crash__")
        base_code = code[len("__crash__"):] if is_crash_key else code

        if base_code not in perms_by_code:
            continue
        field = by_code.get(base_code)
        if not field:
            continue

        ftype = field.get("type") or "number"
        perms = perms_by_code[base_code]

        if is_crash_key:
            crash_cfg = field.get("crash") if isinstance(field.get("crash"), dict) else {}
            if ftype != "matrix" or not crash_cfg.get("enabled"):
                continue

            sets = []
            for perm in perms:
                judge_index = max(1, int(perm.get("judge_index") or 1))
                if isinstance(incoming_val, list):
                    value = incoming_val[judge_index - 1] if len(incoming_val) >= judge_index else None
                else:
                    value = incoming_val
                sets.append((judge_index - 1, value))
            clean[code] = {"__set_list__": sets}
            continue

        if ftype == "number":
            clean[base_code] = incoming_val
            continue

        if ftype == "list":
            sets = []
            for perm in perms:
                judge_index = max(1, int(perm.get("judge_index") or 1))
                if isinstance(incoming_val, list):
                    value = incoming_val[judge_index - 1] if len(incoming_val) >= judge_index else None
                else:
                    value = incoming_val
                sets.append((judge_index - 1, value))
            clean[base_code] = {"__set_list__": sets}
            continue

        if ftype == "matrix":
            n_items = int(((field.get("items") or {}).get("count")) or 0) or 1

            sets = []
            for perm in perms:
                judge_index = max(1, int(perm.get("judge_index") or 1))
                start = max(1, int(perm.get("item_start") or 1))
                count = perm.get("item_count")
                if count is None:
                    count = n_items - start + 1
                count = max(1, int(count))

                row = None
                if isinstance(incoming_val, list) and len(incoming_val) > 0:
                    if isinstance(incoming_val[0], list):
                        row = incoming_val[judge_index - 1] if len(incoming_val) >= judge_index else None
                    else:
                        row = incoming_val
                if row is None:
                    continue

                for offset in range(count):
                    item_index_1 = start + offset
                    item_index_0 = item_index_1 - 1
                    value = row[item_index_0] if len(row) > item_index_0 else None
                    sets.append((judge_index - 1, item_index_0, value))
            clean[base_code] = {"__set_matrix__": sets}
            continue

    return clean


def _normalize_permissions(perms):
    """
    Normalitza permisos per evitar errors.
    Espera list[dict].
    """
    if not isinstance(perms, list):
        return []
    out = []
    for perm in perms:
        if not isinstance(perm, dict):
            continue
        raw_perm = normalize_permission_target(perm)
        code = raw_perm.get("field_code")
        if not code:
            continue
        scope = str(raw_perm.get("scope") or "shared").strip().lower() or "shared"
        item_count = raw_perm.get("item_count")
        row = {
            "field_code": str(code),
            "runtime_field_code": str(raw_perm.get("runtime_field_code") or code),
            "scope": scope,
            "role": normalize_judge_role(raw_perm.get("role")),
            "judge_index": int(raw_perm.get("judge_index") or 1),
            "item_start": int(raw_perm.get("item_start") or 1),
            "item_count": (None if item_count in (None, "", "null") else int(item_count)),
        }
        if scope == "member":
            row["member_mode"] = str(raw_perm.get("member_mode") or "all")
            if raw_perm.get("member_slots") not in (None, ""):
                row["member_slots"] = list(raw_perm.get("member_slots") or [])
            if raw_perm.get("member_slot"):
                row["member_slot"] = int(raw_perm.get("member_slot"))
        row["label"] = build_permission_label(row)
        out.append(row)
    return out


def _allowed_input_codes_from_permissions(permissions: list) -> set:
    allowed_codes = set()
    for perm in permissions or []:
        code = perm.get("runtime_field_code") or perm.get("field_code")
        if not code:
            continue
        allowed_codes.add(str(code))
        allowed_codes.add(f"__crash__{code}")
        allowed_codes.add(presence_key(str(code)))
    return allowed_codes


def _subject_member_count(subject) -> int:
    if not isinstance(subject, dict):
        return 0
    team_subject = subject.get("team_subject")
    if team_subject is not None:
        return len(getattr(team_subject, "member_ids", []) or [])
    return len(subject.get("members") or [])


def _resolve_permissions_for_subject(permissions: list, comp_aparell, subject=None) -> list:
    member_count = _subject_member_count(subject)
    resolved = []
    for perm in permissions or []:
        resolved.extend(
            resolve_permission_runtime_entries(
                perm,
                comp_aparell,
                member_count=member_count,
            )
        )
    return resolved


def _apply_sanitized_patch(current_inputs: dict, sanitized_patch: dict, schema: dict) -> dict:
    out = merge_judge_patch_into_canonical(current_inputs or {}, sanitized_patch or {}, schema or {})

    by_code = {
        field.get("code"): field
        for field in (schema.get("fields") or [])
        if isinstance(field, dict) and field.get("code")
    }

    for code, payload in sanitized_patch.items():
        if isinstance(code, str) and code.startswith("__crash__"):
            base_code = code[len("__crash__"):]
            field = by_code.get(base_code, {})
            crash_cfg = field.get("crash") if isinstance(field.get("crash"), dict) else {}
            if (field.get("type") or "number") != "matrix" or not crash_cfg.get("enabled"):
                continue
            if isinstance(payload, dict) and "__set_list__" in payload:
                current = out.get(code)
                current = current if isinstance(current, list) else []
                max_idx = max((idx for idx, _ in payload["__set_list__"]), default=-1)
                while len(current) <= max_idx:
                    current.append(0)
                for idx, value in payload["__set_list__"]:
                    current[idx] = value
                out[code] = current
            continue

        field = by_code.get(code, {})
        ftype = field.get("type") or "number"

        if ftype == "number":
            out[code] = payload
            continue

        if ftype == "list" and isinstance(payload, dict) and "__set_list__" in payload:
            current = out.get(code)
            current = current if isinstance(current, list) else []
            max_idx = max((idx for idx, _ in payload["__set_list__"]), default=-1)
            while len(current) <= max_idx:
                current.append(None)
            for idx, value in payload["__set_list__"]:
                current[idx] = value
            out[code] = current
            continue

        if ftype == "matrix" and isinstance(payload, dict) and "__set_matrix__" in payload:
            current = out.get(code)
            current = current if isinstance(current, list) else []
            max_row = max((row for row, _, __ in payload["__set_matrix__"]), default=-1)
            while len(current) <= max_row:
                current.append([])
            n_items = int(((field.get("items") or {}).get("count")) or 0) or 1
            for row, col, value in payload["__set_matrix__"]:
                current_row = current[row] if isinstance(current[row], list) else []
                while len(current_row) < n_items:
                    current_row.append(None)
                current_row[col] = value
                current[row] = current_row
            out[code] = current
            continue

    return out
