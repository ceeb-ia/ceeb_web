from django.forms import formset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from .forms_judge import JudgeTokenCreateForm, PermissionRowForm
from .models import Competicio
from .models_trampoli import CompeticioAparell
from .models_scoring import ScoringSchema
from .models_judging import JudgeDeviceToken


def _schema_field_choices(schema: dict):
    # [(code, "CODE — Label"), ...]
    out = [("", "—")]
    for f in (schema.get("fields") or []):
        if isinstance(f, dict) and f.get("code"):
            code = f["code"]
            label = f.get("label") or code
            out.append((code, f"{code} — {label}"))
    return out


def _schema_field_by_code(schema: dict):
    return {f.get("code"): f for f in (schema.get("fields") or []) if isinstance(f, dict) and f.get("code")}


def _validate_permission_row(schema_by_code: dict, row: dict):
    """
    Normalitza i limita judge_index / items segons schema real.
    """
    code = row["field_code"]
    f = schema_by_code.get(code)
    if not f:
        raise ValueError("Camp no existeix al schema")

    # limit judges.count
    max_j = int(((f.get("judges") or {}).get("count")) or 1)
    j = int(row.get("judge_index") or 1)
    if j < 1 or j > max_j:
        raise ValueError(f"{code}: judge_index fora de rang (1..{max_j})")

    # si és matrix, valida rang items
    ftype = f.get("type") or "number"
    if ftype == "matrix":
        max_items = int(((f.get("items") or {}).get("count")) or 1)
        item_start = int(row.get("item_start") or 1)
        item_count = row.get("item_count")
        if item_start < 1 or item_start > max_items:
            raise ValueError(f"{code}: item_start fora de rang (1..{max_items})")
        if item_count is not None and item_count != "":
            item_count = int(item_count)
            if item_count < 1:
                raise ValueError(f"{code}: item_count invàlid")
            if item_start + item_count - 1 > max_items:
                raise ValueError(f"{code}: rang d'ítems supera {max_items}")
        else:
            item_count = None
    else:
        # per number/list, ignorem rang items
        item_start = 1
        item_count = None

    return {
        "field_code": code,
        "judge_index": j,
        "item_start": item_start,
        "item_count": item_count,
    }


@require_http_methods(["GET", "POST"])
def judges_qr_home(request, competicio_id):
    competicio = get_object_or_404(Competicio, pk=competicio_id)

    # aparell seleccionat
    comp_aparell_qs = CompeticioAparell.objects.filter(competicio=competicio, actiu=True).select_related("aparell")
    comp_aparell_id = request.GET.get("comp_aparell")
    comp_aparell = None
    if comp_aparell_id:
        comp_aparell = get_object_or_404(comp_aparell_qs, pk=comp_aparell_id)
    else:
        comp_aparell = comp_aparell_qs.first()

    schema = {}
    if comp_aparell:
        ss, _ = ScoringSchema.objects.get_or_create(aparell=comp_aparell.aparell, defaults={"schema": {}})
        schema = ss.schema or {}

    field_choices = _schema_field_choices(schema)
    schema_by_code = _schema_field_by_code(schema)

    PermissionFS = formset_factory(PermissionRowForm, extra=3, can_delete=True)

    if request.method == "POST":
        action = request.POST.get("action") or ""
        if action == "revoke":
            token_id = request.POST.get("token_id")
            tok = get_object_or_404(JudgeDeviceToken, pk=token_id, competicio=competicio)
            tok.revoked_at = timezone.now()
            tok.is_active = False
            tok.save(update_fields=["revoked_at", "is_active"])
            return redirect(f"{reverse('judges_qr_home', kwargs={'competicio_id': competicio.id})}?comp_aparell={comp_aparell.id}")

        # create token
        token_form = JudgeTokenCreateForm(request.POST)
        formset = PermissionFS(request.POST, form_kwargs={"field_choices": field_choices})

        if token_form.is_valid() and formset.is_valid() and comp_aparell:
            perms = []
            for f in formset.cleaned_data:
                if not f or f.get("DELETE"):
                    continue
                if not f.get("field_code"):
                    continue
                try:
                    perms.append(_validate_permission_row(schema_by_code, f))
                except ValueError as e:
                    # re-render amb error “global”
                    token_form.add_error(None, str(e))
                    break

            if not token_form.errors:
                label = token_form.cleaned_data.get("label") or ""
                JudgeDeviceToken.objects.create(
                    competicio=competicio,
                    comp_aparell=comp_aparell,
                    label=label,
                    permissions=perms,
                    is_active=True,
                )
                return redirect(f"{reverse('judges_qr_home', kwargs={'competicio_id': competicio.id})}?comp_aparell={comp_aparell.id}")
    else:
        token_form = JudgeTokenCreateForm()
        formset = PermissionFS(form_kwargs={"field_choices": field_choices})

    tokens = []
    if comp_aparell:
        tokens = (JudgeDeviceToken.objects
                  .filter(competicio=competicio, comp_aparell=comp_aparell)
                  .order_by("-created_at"))

    ctx = {
        "competicio": competicio,
        "comp_aparell": comp_aparell,
        "comp_aparell_qs": comp_aparell_qs,
        "schema": schema,
        "tokens": tokens,
        "token_form": token_form,
        "formset": formset,
    }
    return render(request, "judge/admin_tokens.html", ctx)


@require_http_methods(["GET"])
def judges_qr_print(request, competicio_id):
    competicio = get_object_or_404(Competicio, pk=competicio_id)
    comp_aparell_id = request.GET.get("comp_aparell")
    comp_aparell = get_object_or_404(CompeticioAparell, pk=comp_aparell_id, competicio=competicio, actiu=True)

    tokens = (JudgeDeviceToken.objects
              .filter(competicio=competicio, comp_aparell=comp_aparell, is_active=True, revoked_at__isnull=True)
              .order_by("label", "created_at"))

    ctx = {"competicio": competicio, "comp_aparell": comp_aparell, "tokens": tokens}
    return render(request, "judge/print_tokens.html", ctx)