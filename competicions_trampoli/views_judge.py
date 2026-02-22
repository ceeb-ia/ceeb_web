import io
import json
import qrcode

from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from .models_judging import JudgeDeviceToken
from .models import Inscripcio, Competicio
from .models_trampoli import CompeticioAparell
from .models_scoring import ScoringSchema, ScoreEntry
from .scoring_engine import ScoringEngine, ScoringError



def _sanitize_patch_by_permissions(schema: dict, permissions: list, patch: dict) -> dict:
    """
    Retorna un patch limitat a:
    - camps autoritzats
    - per matrix: només la fila judge_index i rang d'ítems si s'ha definit
    - per list: només index judge_index
    """
    # index de fields per code
    by_code = {}
    for f in (schema.get("fields") or []):
        if isinstance(f, dict) and f.get("code"):
            by_code[f["code"]] = f

    perms_by_code = {}
    for p in permissions:
        perms_by_code.setdefault(p["field_code"], []).append(p)

    clean = {}

    for code, incoming_val in (patch or {}).items():
        if code not in perms_by_code:
            continue
        f = by_code.get(code)
        if not f:
            continue

        ftype = f.get("type") or "number"

        # per simplicitat: si hi ha més d'un permís pel mateix code,
        # aquí apliquem TOTS (unió). Normalment en tindràs 1.
        perms = perms_by_code[code]

        if ftype == "number":
            clean[code] = incoming_val
            continue

        if ftype == "list":
            # incoming_val ha de ser una llista; però nosaltres només acceptem el nostre índex
            # i ho reconstruïm sobre el valor existent més tard amb MERGE
            # aquí deixem un patch del tipus {"CODE": {"__set_list__": [(idx, val), ...]}}
            sets = []
            for p in perms:
                j = max(1, int(p.get("judge_index") or 1))
                # incoming pot ser llista completa o valor “nu”
                if isinstance(incoming_val, list):
                    v = incoming_val[j-1] if len(incoming_val) >= j else None
                else:
                    v = incoming_val
                sets.append((j-1, v))
            clean[code] = {"__set_list__": sets}
            continue

        if ftype == "matrix":
            n_items = int(((f.get("items") or {}).get("count")) or 0) or 1

            sets = []
            for p in perms:
                j = max(1, int(p.get("judge_index") or 1))
                start = max(1, int(p.get("item_start") or 1))
                count = p.get("item_count")
                if count is None:
                    count = n_items - start + 1
                count = max(1, int(count))

                # incoming_val pot ser matriu completa o només la fila
                row = None
                if isinstance(incoming_val, list) and len(incoming_val) > 0:
                    if isinstance(incoming_val[0], list):
                        row = incoming_val[j-1] if len(incoming_val) >= j else None
                    else:
                        # fila sola
                        row = incoming_val
                if row is None:
                    continue

                for k in range(count):
                    idx1 = start + k
                    idx0 = idx1 - 1
                    v = row[idx0] if len(row) > idx0 else None
                    sets.append((j-1, idx0, v))
            clean[code] = {"__set_matrix__": sets}
            continue

        # altres tipus: ignora
    return clean

def _normalize_permissions(perms):
    """
    Normalitza permisos per evitar errors.
    Espera list[dict].
    """
    if not isinstance(perms, list):
        return []
    out = []
    for p in perms:
        if not isinstance(p, dict):
            continue
        code = p.get("field_code")
        if not code:
            continue
        out.append({
            "field_code": str(code),
            "judge_index": int(p.get("judge_index") or 1),
            "item_start": int(p.get("item_start") or 1),
            "item_count": (None if p.get("item_count") in (None, "", "null") else int(p["item_count"])),
        })
    return out


def judge_qr_png(request, token):
    tok = get_object_or_404(JudgeDeviceToken, pk=token)
    url = request.build_absolute_uri(reverse("judge_portal", kwargs={"token": str(tok.id)}))
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return HttpResponse(buf.getvalue(), content_type="image/png")


@require_http_methods(["GET"])
def judge_portal(request, token):
    tok = get_object_or_404(JudgeDeviceToken, pk=token)
    if not tok.is_valid():
        return render(request, "judge/invalid_token.html", {"token": tok}, status=403)

    tok.touch()

    comp_aparell = tok.comp_aparell
    competicio = tok.competicio

    ss, _ = ScoringSchema.objects.get_or_create(
        aparell=comp_aparell.aparell,
        defaults={"schema": {}},
    )
    schema = ss.schema or {}

    permissions = _normalize_permissions(tok.permissions)

    # Llista d'inscripcions (mateix criteri que uses a notes home)
    ins_qs = (
        Inscripcio.objects
        .filter(competicio=competicio)
        .order_by("grup", "ordre_sortida", "id")
    )

    # Prefetch entries existents (per mostrar valors actuals)
    entries = ScoreEntry.objects.filter(
        competicio=competicio,
        comp_aparell=comp_aparell,
    )
    entry_map = {}
    for e in entries:
        entry_map[(e.inscripcio_id, e.exercici)] = e

    # Construïm un “snapshot” dels inputs rellevants per inscripció/exercici
    # Per simplicitat: assumim exercici=1 si al teu flux n’hi ha més, ho pots estendre.
    max_ex = max(1, int(getattr(comp_aparell, "nombre_exercicis", 1) or 1))
    req_ex = request.GET.get("ex")
    try:
        exercici_default = int(req_ex or 1)
    except Exception:
        exercici_default = 1
    exercici_default = max(1, min(max_ex, exercici_default)) 
    scores_payload = {}
    for ins in ins_qs:
        e = entry_map.get((ins.id, exercici_default))
        scores_payload[str(ins.id)] = {
            "inputs": (e.inputs if e and isinstance(e.inputs, dict) else {}),
            "outputs": (e.outputs if e and isinstance(e.outputs, dict) else {}),
            "total": (float(e.total) if e else 0.0),
            "updated_at": (e.updated_at.isoformat() if e else None),
        }

    ctx = {
        "token_obj": tok,
        "token": str(tok.id),
        "competicio": competicio,
        "comp_aparell": comp_aparell,
        "schema": schema,
        "permissions": permissions,
        "inscripcions": ins_qs,
        "scores_payload_json": json.dumps(scores_payload),
        "save_url": reverse("judge_save_partial", kwargs={"token": str(tok.id)}),
        "exercici": exercici_default,
    }
    return render(request, "judge/portal.html", ctx)

def _apply_sanitized_patch(current_inputs: dict, sanitized_patch: dict, schema: dict) -> dict:
    out = dict(current_inputs or {})

    by_code = {f.get("code"): f for f in (schema.get("fields") or []) if isinstance(f, dict) and f.get("code")}

    for code, payload in sanitized_patch.items():
        f = by_code.get(code, {})
        ftype = f.get("type") or "number"

        if ftype == "number":
            out[code] = payload
            continue

        if ftype == "list" and isinstance(payload, dict) and "__set_list__" in payload:
            cur = out.get(code)
            cur = cur if isinstance(cur, list) else []
            # assegura llargada
            max_idx = max((i for i,_ in payload["__set_list__"]), default=-1)
            while len(cur) <= max_idx:
                cur.append(None)
            for i, v in payload["__set_list__"]:
                cur[i] = v
            out[code] = cur
            continue

        if ftype == "matrix" and isinstance(payload, dict) and "__set_matrix__" in payload:
            cur = out.get(code)
            cur = cur if isinstance(cur, list) else []
            # assegura files
            max_row = max((r for r,_,__ in payload["__set_matrix__"]), default=-1)
            while len(cur) <= max_row:
                cur.append([])
            # assegura cols per cada fila que toquem
            n_items = int(((f.get("items") or {}).get("count")) or 0) or 1
            for r, c, v in payload["__set_matrix__"]:
                row = cur[r] if isinstance(cur[r], list) else []
                while len(row) < n_items:
                    row.append(None)
                row[c] = v
                cur[r] = row
            out[code] = cur
            continue

    return out



@require_POST
@transaction.atomic
def judge_save_partial(request, token):
    tok = get_object_or_404(JudgeDeviceToken, pk=token)
    if not tok.is_valid():
        return JsonResponse({"ok": False, "error": "Token invàlid o revocat"}, status=403)

    tok.touch()

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON invàlid"}, status=400)

    ins_id = payload.get("inscripcio_id")
    exercici = int(payload.get("exercici") or 1)
    inputs_patch = payload.get("inputs_patch", {})

    if not ins_id:
        return JsonResponse({"ok": False, "error": "Falta inscripcio_id"}, status=400)
    if not isinstance(inputs_patch, dict):
        return JsonResponse({"ok": False, "error": "inputs_patch ha de ser objecte JSON"}, status=400)

    # Seguretat: només permetre editar camps que apareixen a permissions
    permissions = _normalize_permissions(tok.permissions)
    allowed_codes = {p["field_code"] for p in permissions}
    patch_codes = set(inputs_patch.keys())
    if not patch_codes.issubset(allowed_codes):
        return JsonResponse({"ok": False, "error": "Intentes editar un camp no autoritzat per aquest QR"}, status=403)

    competicio: Competicio = tok.competicio
    comp_aparell: CompeticioAparell = tok.comp_aparell

    ins = get_object_or_404(Inscripcio, pk=ins_id, competicio=competicio)

    ss, _ = ScoringSchema.objects.get_or_create(aparell=comp_aparell.aparell, defaults={"schema": {}})
    schema = ss.schema or {}

    entry, _ = ScoreEntry.objects.get_or_create(
        competicio=competicio,
        inscripcio=ins,
        exercici=exercici,
        comp_aparell=comp_aparell,
        defaults={"inputs": {}, "outputs": {}, "total": 0},
    )

    sanitized = _sanitize_patch_by_permissions(schema, permissions, inputs_patch)
    current_inputs = entry.inputs if isinstance(entry.inputs, dict) else {}

    # MERGE per no trepitjar altres camps/jutges
    merged_inputs = _apply_sanitized_patch(current_inputs, sanitized, schema)

    # Filtrat d'inputs segons schema.fields (mateixa idea que tens a scoring_save)
    allowed = set()
    for f in (schema.get("fields") or []):
        if isinstance(f, dict) and f.get("code"):
            allowed.add(f["code"])
            allowed.add(f"__crash__{f['code']}")

    clean_inputs = {k: v for k, v in merged_inputs.items() if k in allowed}

    try:
        engine = ScoringEngine(schema)
        result = engine.compute(clean_inputs)
    except ScoringError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    except Exception:
        return JsonResponse({"ok": False, "error": "Error inesperat calculant puntuació"}, status=500)

    entry.inputs = result.inputs
    entry.outputs = result.outputs
    entry.total = result.total
    entry.save(update_fields=["inputs", "outputs", "total", "updated_at"])

    return JsonResponse({
        "ok": True,
        "inputs": entry.inputs or {},
        "outputs": entry.outputs or {},
        "total": float(entry.total),
        "updated_at": entry.updated_at.isoformat(),
    })

