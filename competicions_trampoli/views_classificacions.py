# views_classificacions.py
import json
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST
from django.db import transaction
from django.urls import reverse
from .models_scoring import ScoreEntry, ScoringSchema  
from .models import Competicio, Inscripcio, Equip
from .models_trampoli import CompeticioAparell, Aparell
from .models_classificacions import ClassificacioConfig
from .models_judging import PublicLiveToken
from .services.services_classificacions_2 import compute_classificacio, DEFAULT_SCHEMA, get_display_columns
from django.db import models
# views_classificacions.py
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_aware
from django.utils import timezone


def _active_cfg_values(competicio):
    cfgs = (
        ClassificacioConfig.objects
        .filter(competicio=competicio, activa=True)
        .order_by("ordre", "id")
    )
    return list(cfgs.values("id", "nom", "tipus", "ordre"))


def _live_data_payload(competicio, since_raw=None):
    last_note = (
        ScoreEntry.objects
        .filter(competicio=competicio)
        .order_by("-updated_at")
        .values_list("updated_at", flat=True)
        .first()
    )
    last_cfg = (
        ClassificacioConfig.objects
        .filter(competicio=competicio)
        .order_by("-updated_at")
        .values_list("updated_at", flat=True)
        .first()
    )
    stamp = max([d for d in [last_note, last_cfg] if d is not None], default=timezone.now())

    if since_raw:
        since_dt = parse_datetime(since_raw)
        if since_dt and not is_aware(since_dt):
            since_dt = timezone.make_aware(since_dt, timezone.get_current_timezone())
        if since_dt and stamp <= since_dt:
            return {"ok": True, "changed": False, "stamp": stamp.isoformat()}

    cfgs = (
        ClassificacioConfig.objects
        .filter(competicio=competicio, activa=True)
        .order_by("ordre", "id")
    )

    payload_cfgs = []
    for cfg in cfgs:
        data = compute_classificacio(competicio, cfg)
        parts = []
        for k in sorted(data.keys()):
            parts.append({"particio": k, "rows": data[k]})
        payload_cfgs.append({
            "id": cfg.id,
            "nom": cfg.nom,
            "tipus": cfg.tipus,
            "columns": get_display_columns(cfg.schema or {}),
            "parts": parts,
        })

    return {
        "ok": True,
        "changed": True,
        "stamp": stamp.isoformat(),
        "competicio": {"id": competicio.id, "nom": competicio.nom},
        "cfgs": payload_cfgs,
    }


class ClassificacionsLive(TemplateView):
    template_name = "competicio/classificacions_live.html"

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        competicio = self.competicio
        public_raw = (self.request.GET.get("public") or "").strip().lower()
        is_public = public_raw in {"1", "true", "yes", "on"}

        cfgs = (
            ClassificacioConfig.objects
            .filter(competicio=competicio, activa=True)
            .order_by("ordre", "id")
        )
        ctx.update({
            "competicio": competicio,
            "cfgs": list(cfgs.values("id", "nom", "tipus", "ordre")),
            "is_public": is_public,
            "hide_base_chrome": is_public,
            # interval suggerit (ms) perquè el JS el pugui usar
            "poll_ms": 4000,
        })
        return ctx


class ClassificacionsLoopLive(TemplateView):
    template_name = "competicio/classificacions_loop_live.html"

    @staticmethod
    def _parse_int_param(raw, default: int, min_value: int, max_value: int) -> int:
        try:
            value = int(raw)
        except Exception:
            value = default
        return max(min_value, min(max_value, value))

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        competicio = self.competicio

        public_raw = (self.request.GET.get("public") or "").strip().lower()
        is_public = public_raw in {"1", "true", "yes", "on"}

        cfgs = (
            ClassificacioConfig.objects
            .filter(competicio=competicio, activa=True)
            .order_by("ordre", "id")
        )

        poll_ms = self._parse_int_param(self.request.GET.get("poll_ms"), 4000, 1000, 60000)
        slide_ms = self._parse_int_param(self.request.GET.get("slide_ms"), 8000, 2000, 120000)
        rows_per_page = self._parse_int_param(self.request.GET.get("rows"), 12, 3, 60)

        transition = (self.request.GET.get("transition") or "fade").strip().lower()
        if transition not in {"fade", "none"}:
            transition = "fade"

        ctx.update({
            "competicio": competicio,
            "cfgs": list(cfgs.values("id", "nom", "tipus", "ordre")),
            "is_public": is_public,
            "hide_base_chrome": is_public,
            "poll_ms": poll_ms,
            "slide_ms": slide_ms,
            "rows_per_page": rows_per_page,
            "transition": transition,
        })
        return ctx


def classificacions_live_data(request, pk):
    """
    GET /competicio/<pk>/classificacions/live/data?since=<iso>
    Retorna:
      - changed: False si no hi ha canvis des de `since`
      - changed: True + dades si hi ha canvis
    """
    competicio = get_object_or_404(Competicio, pk=pk)

    # stamp = max(última nota, última cfg)
    last_note = (
        ScoreEntry.objects
            .filter(competicio=competicio)
            .order_by("-updated_at")
            .values_list("updated_at", flat=True)
            .first()    
        )
    last_cfg = (
        ClassificacioConfig.objects
        .filter(competicio=competicio)
        .order_by("-updated_at")
        .values_list("updated_at", flat=True)
        .first()
    )
    stamp = max([d for d in [last_note, last_cfg] if d is not None], default=timezone.now())

    # Si el client passa ?since=..., i no hi ha canvis, no recalculis
    since_raw = request.GET.get("since")
    if since_raw:
        since_dt = parse_datetime(since_raw)
        if since_dt and not is_aware(since_dt):
            since_dt = timezone.make_aware(since_dt, timezone.get_current_timezone())
        if since_dt and stamp <= since_dt:
            return JsonResponse({"ok": True, "changed": False, "stamp": stamp.isoformat()})

    cfgs = (
        ClassificacioConfig.objects
        .filter(competicio=competicio, activa=True)
        .order_by("ordre", "id")
    )

    payload_cfgs = []
    for cfg in cfgs:
        data = compute_classificacio(competicio, cfg)  # {particio_key: [rows]}
        parts = []
        for k in sorted(data.keys()):
            parts.append({"particio": k, "rows": data[k]})
        payload_cfgs.append({
            "id": cfg.id,
            "nom": cfg.nom,
            "tipus": cfg.tipus,
            "columns": get_display_columns(cfg.schema or {}),
            "parts": parts,
        })

    return JsonResponse({
        "ok": True,
        "changed": True,
        "stamp": stamp.isoformat(),
        "competicio": {"id": competicio.id, "nom": competicio.nom},
        "cfgs": payload_cfgs,
    })


class PublicClassificacionsLive(TemplateView):
    template_name = "competicio/classificacions_live.html"

    def dispatch(self, request, *args, **kwargs):
        self.token_obj = get_object_or_404(PublicLiveToken, pk=kwargs["token"])
        if not self.token_obj.is_valid():
            return JsonResponse({"ok": False, "error": "Token invalid o revocat"}, status=403)
        self.token_obj.touch()
        self.competicio = self.token_obj.competicio
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        cfgs = (
            ClassificacioConfig.objects
            .filter(competicio=self.competicio, activa=True)
            .order_by("ordre", "id")
        )
        ctx.update({
            "competicio": self.competicio,
            "cfgs": list(cfgs.values("id", "nom", "tipus", "ordre")),
            "is_public": True,
            "hide_base_chrome": True,
            "poll_ms": 4000,
            "data_url": self.request.build_absolute_uri(
                reverse("public_live_classificacions_data", kwargs={"token": self.token_obj.id})
            ),
        })
        return ctx


class PublicClassificacionsLoopLive(TemplateView):
    template_name = "competicio/classificacions_loop_live.html"

    @staticmethod
    def _parse_int_param(raw, default: int, min_value: int, max_value: int) -> int:
        try:
            value = int(raw)
        except Exception:
            value = default
        return max(min_value, min(max_value, value))

    def dispatch(self, request, *args, **kwargs):
        self.token_obj = get_object_or_404(PublicLiveToken, pk=kwargs["token"])
        if not self.token_obj.is_valid():
            return JsonResponse({"ok": False, "error": "Token invalid o revocat"}, status=403)
        self.token_obj.touch()
        self.competicio = self.token_obj.competicio
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        cfgs = (
            ClassificacioConfig.objects
            .filter(competicio=self.competicio, activa=True)
            .order_by("ordre", "id")
        )
        poll_ms = self._parse_int_param(self.request.GET.get("poll_ms"), 4000, 1000, 60000)
        slide_ms = self._parse_int_param(self.request.GET.get("slide_ms"), 8000, 2000, 120000)
        rows_per_page = self._parse_int_param(self.request.GET.get("rows"), 12, 3, 60)
        transition = (self.request.GET.get("transition") or "fade").strip().lower()
        if transition not in {"fade", "none"}:
            transition = "fade"

        ctx.update({
            "competicio": self.competicio,
            "cfgs": list(cfgs.values("id", "nom", "tipus", "ordre")),
            "is_public": True,
            "hide_base_chrome": True,
            "poll_ms": poll_ms,
            "slide_ms": slide_ms,
            "rows_per_page": rows_per_page,
            "transition": transition,
            "data_url": self.request.build_absolute_uri(
                reverse("public_live_classificacions_data", kwargs={"token": self.token_obj.id})
            ),
        })
        return ctx


def public_classificacions_live_data(request, token):
    token_obj = get_object_or_404(PublicLiveToken, pk=token)
    if not token_obj.is_valid():
        return JsonResponse({"ok": False, "error": "Token invalid o revocat"}, status=403)

    competicio = token_obj.competicio
    last_note = (
        ScoreEntry.objects
            .filter(competicio=competicio)
            .order_by("-updated_at")
            .values_list("updated_at", flat=True)
            .first()
        )
    last_cfg = (
        ClassificacioConfig.objects
        .filter(competicio=competicio)
        .order_by("-updated_at")
        .values_list("updated_at", flat=True)
        .first()
    )
    stamp = max([d for d in [last_note, last_cfg] if d is not None], default=timezone.now())

    since_raw = request.GET.get("since")
    if since_raw:
        since_dt = parse_datetime(since_raw)
        if since_dt and not is_aware(since_dt):
            since_dt = timezone.make_aware(since_dt, timezone.get_current_timezone())
        if since_dt and stamp <= since_dt:
            return JsonResponse({"ok": True, "changed": False, "stamp": stamp.isoformat()})

    cfgs = (
        ClassificacioConfig.objects
        .filter(competicio=competicio, activa=True)
        .order_by("ordre", "id")
    )

    payload_cfgs = []
    for cfg in cfgs:
        data = compute_classificacio(competicio, cfg)
        parts = []
        for k in sorted(data.keys()):
            parts.append({"particio": k, "rows": data[k]})
        payload_cfgs.append({
            "id": cfg.id,
            "nom": cfg.nom,
            "tipus": cfg.tipus,
            "columns": get_display_columns(cfg.schema or {}),
            "parts": parts,
        })

    return JsonResponse({
        "ok": True,
        "changed": True,
        "stamp": stamp.isoformat(),
        "competicio": {"id": competicio.id, "nom": competicio.nom},
        "cfgs": payload_cfgs,
    })


class ClassificacionsHome(TemplateView):
    template_name = "competicio/classificacions_builder_v2.html"

    def get(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        competicio = self.competicio

        # aparells actius (com a notes)
        aparells_cfg = CompeticioAparell.objects.filter(
            competicio=competicio,
            actiu=True,
        ).select_related("aparell").order_by("ordre", "id")

        # si no n'hi ha, crea'n un per defecte (mateix patró que notes)
        if not aparells_cfg.exists():
            a, _ = Aparell.objects.get_or_create(codi="TRAMP", defaults={"nom": "Trampolí"})
            CompeticioAparell.objects.create(
                competicio=competicio,
                aparell=a,
            )
            aparells_cfg = CompeticioAparell.objects.filter(
                competicio=competicio,
                actiu=True,
            ).select_related("aparell").order_by("ordre", "id")

        aparell_ids = list(aparells_cfg.values_list("aparell_id", flat=True))

        schemas_by_aparell = {
            s.aparell_id: (s.schema or {})
            for s in ScoringSchema.objects.filter(aparell_id__in=aparell_ids).only("aparell_id", "schema")
        }

        aparell_field_options = {}


        for ca in aparells_cfg:
            sch = schemas_by_aparell.get(ca.aparell_id, {}) or {}
            opts = []


            for f in (sch.get("fields") or []):
                if isinstance(f, dict) and f.get("code"):
                    judges_count = 1
                    j = f.get("judges")
                    if isinstance(j, dict):
                        try:
                            judges_count = int(j.get("count") or 1)
                        except Exception:
                            judges_count = 1
                    else:
                        try:
                            judges_count = int(f.get("judges_count") or 1)
                        except Exception:
                            judges_count = 1
                    judges_count = max(1, judges_count)
                    opts.append({
                        "code": str(f["code"]),
                        "label": str(f.get("label") or f["code"]),
                        "kind": "field",
                        "judges_count": judges_count,
                    })

            for c in (sch.get("computed") or []):
                if isinstance(c, dict) and c.get("code"):
                    opts.append({
                        "code": str(c["code"]),
                        "label": str(c.get("label") or c["code"]),
                        "kind": "computed",
                        "judges_count": 1,
                    })

            # dedup
            seen = set()
            dedup = []
            for o in opts:
                if o["code"] in seen:
                    continue
                seen.add(o["code"])
                dedup.append(o)

            aparell_field_options[str(ca.id)] = dedup

        cfgs = ClassificacioConfig.objects.filter(competicio=competicio).order_by("ordre", "id")

        # si no hi ha cap configuració, crea'n una de base
        if not cfgs.exists():
            ClassificacioConfig.objects.create(
                competicio=competicio,
                nom="General (total)",
                activa=True,
                ordre=1,
                tipus="individual",
                schema={
                    **DEFAULT_SCHEMA,
                    "particions": [],
                    "puntuacio": {**DEFAULT_SCHEMA["puntuacio"], "camp": "total", "agregacio": "sum"},
                    "presentacio": {"top_n": 0, "mostrar_empats": True},
                },
            )
            cfgs = ClassificacioConfig.objects.filter(competicio=competicio).order_by("ordre", "id")


        # Choices per filtres visuals (entitat/categoria/subcategoria/grup)
        ins_qs = Inscripcio.objects.filter(competicio=competicio)

        filter_choices = {}

        # entitat
        if _is_fk(Inscripcio, "entitat"):
            filter_choices["entitats"] = _distinct_fk(ins_qs, "entitat")
        else:
            filter_choices["entitats"] = [{"value": v, "label": str(v)} for v in _distinct_values(ins_qs, "entitat")]

        # categoria
        if _is_fk(Inscripcio, "categoria"):
            filter_choices["categories"] = _distinct_fk(ins_qs, "categoria")
        else:
            filter_choices["categories"] = [{"value": v, "label": str(v)} for v in _distinct_values(ins_qs, "categoria")]

        # subcategoria
        if _is_fk(Inscripcio, "subcategoria"):
            filter_choices["subcategories"] = _distinct_fk(ins_qs, "subcategoria")
        else:
            filter_choices["subcategories"] = [{"value": v, "label": str(v)} for v in _distinct_values(ins_qs, "subcategoria")]

        # grup (normalment text)
        filter_choices["grups"] = [{"value": v, "label": str(v)} for v in _distinct_values(ins_qs, "grup")]

        ctx["filter_choices"] = filter_choices


        cfg_payload = []
        for c in cfgs:
            cfg_payload.append({
                "id": c.id,
                "nom": c.nom,
                "activa": c.activa,
                "ordre": c.ordre,
                "tipus": c.tipus,
                "schema": c.schema or {},
            })

        aparell_payload = []
        for ca in aparells_cfg:
            aparell_payload.append({
                "id": ca.id,
                "nom": ca.aparell.nom,
                "codi": ca.aparell.codi,
                "nombre_exercicis": int(getattr(ca, "nombre_exercicis", 1) or 1),
            })

        equips_qs = (
            Equip.objects
            .filter(competicio=competicio)
            .annotate(membres_count=models.Count("membres"))
            .order_by("nom", "id")
        )
        equips_payload = []
        for e in equips_qs:
            equips_payload.append({
                "id": e.id,
                "nom": e.nom,
                "origen": e.origen,
                "membres_count": int(getattr(e, "membres_count", 0) or 0),
            })

        ctx.update({
            "competicio": competicio,
            "cfgs": cfg_payload,
            "aparells": aparell_payload,
            "equips": equips_payload,
        })

        ctx.update({
            "aparell_field_options": aparell_field_options,
        })

        return ctx


def _safe_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return default


def _field_is_direct_scoreable(field_cfg: dict):
    """
    Regla robusta per camps d'input:
    - number -> ok
    - list judge -> només si 1 jutge (equivalent 1x1)
    - matrix judge_x_* -> només 1 jutge i 1 item (1x1)
    """
    if not isinstance(field_cfg, dict):
        return False, "config de camp no valida"

    ftype = str(field_cfg.get("type") or "").strip().lower()
    shape = str(field_cfg.get("shape") or "").strip().lower()

    judges_cfg = field_cfg.get("judges") if isinstance(field_cfg.get("judges"), dict) else {}
    items_cfg = field_cfg.get("items") if isinstance(field_cfg.get("items"), dict) else {}

    n_judges = _safe_int(judges_cfg.get("count") or field_cfg.get("judges_count") or 1, 1)
    n_judges = max(1, min(10, n_judges))
    n_items = _safe_int(items_cfg.get("count") or 0, 0)
    n_items = max(0, min(50, n_items))

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


def _validate_camps_per_aparell(competicio, schema: dict):
    schema = schema or {}
    punt = (schema.get("puntuacio") or {})
    camps_per_aparell = punt.get("camps_per_aparell") or {}
    if not camps_per_aparell:
        return []
    if not isinstance(camps_per_aparell, dict):
        return ["puntuacio.camps_per_aparell ha de ser un objecte {app_id:[camps]}."]

    active_apps = list(
        CompeticioAparell.objects
        .filter(competicio=competicio, actiu=True)
        .select_related("aparell")
    )
    app_by_id = {ca.id: ca for ca in active_apps}
    if not app_by_id:
        return []

    aparell_ids = [ca.aparell_id for ca in active_apps]
    schemas_by_aparell = {
        s.aparell_id: (s.schema or {})
        for s in ScoringSchema.objects.filter(aparell_id__in=aparell_ids).only("aparell_id", "schema")
    }

    app_mode = ((punt.get("aparells") or {}).get("mode") or "tots").strip().lower()
    app_ids_raw = ((punt.get("aparells") or {}).get("ids") or [])
    selected_app_ids = set()
    if app_mode == "seleccionar":
        for x in app_ids_raw:
            try:
                selected_app_ids.add(int(x))
            except Exception:
                continue
    else:
        selected_app_ids = set(app_by_id.keys())

    errors = []
    for app_key, raw_codes in camps_per_aparell.items():
        try:
            app_id = int(app_key)
        except Exception:
            errors.append(f"app_id invalid a camps_per_aparell: {app_key}")
            continue

        if app_id not in app_by_id:
            errors.append(f"aparell {app_id} no valid o no actiu a la competicio.")
            continue
        if app_id not in selected_app_ids:
            continue

        if isinstance(raw_codes, str):
            codes = [x.strip() for x in raw_codes.split(",") if x and x.strip()]
        elif isinstance(raw_codes, list):
            codes = [str(x).strip() for x in raw_codes if str(x).strip()]
        else:
            errors.append(f"camps_per_aparell[{app_id}] ha de ser llista o string.")
            continue

        sch = schemas_by_aparell.get(app_by_id[app_id].aparell_id, {}) or {}
        meta = {
            "total": {"scoreable": True, "reason": ""},
            "TOTAL": {"scoreable": True, "reason": ""},
        }

        for f in (sch.get("fields") or []):
            if not isinstance(f, dict) or not f.get("code"):
                continue
            ok, reason = _field_is_direct_scoreable(f)
            meta[str(f["code"])] = {"scoreable": ok, "reason": reason}

        for c in (sch.get("computed") or []):
            if not isinstance(c, dict) or not c.get("code"):
                continue
            meta[str(c["code"])] = {"scoreable": True, "reason": ""}

        for code in codes:
            info = meta.get(code)
            if not info:
                errors.append(f"aparell {app_id}: camp '{code}' no existeix al schema.")
                continue
            if not info.get("scoreable", False):
                errors.append(f"aparell {app_id}: camp '{code}' no es puntuable directament ({info.get('reason')}).")

    return errors


@require_POST
@transaction.atomic
def classificacio_save(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invàlid")

    cid = payload.get("id")
    nom = (payload.get("nom") or "Classificació").strip()
    activa = bool(payload.get("activa", True))
    ordre = int(payload.get("ordre") or 1)
    tipus = (payload.get("tipus") or "individual").strip()
    schema = payload.get("schema") or {}

    if tipus not in ("individual", "entitat", "equips"):
        tipus = "individual"

    validation_errors = _validate_camps_per_aparell(competicio, schema)
    if validation_errors:
        return JsonResponse(
            {
                "ok": False,
                "error": "Configuracio de camps per aparell invalida.",
                "errors": validation_errors,
            },
            status=400,
        )

    if cid:
        obj = get_object_or_404(ClassificacioConfig, pk=cid, competicio=competicio)
        obj.nom = nom
        obj.activa = activa
        obj.ordre = ordre
        obj.tipus = tipus
        obj.schema = schema
        obj.save()
    else:
        obj = ClassificacioConfig.objects.create(
            competicio=competicio,
            nom=nom,
            activa=activa,
            ordre=ordre,
            tipus=tipus,
            schema=schema,
        )

    return JsonResponse({"ok": True, "id": obj.id})


@require_POST
@transaction.atomic
def classificacio_delete(request, pk, cid):
    competicio = get_object_or_404(Competicio, pk=pk)
    obj = get_object_or_404(ClassificacioConfig, pk=cid, competicio=competicio)
    obj.delete()
    return JsonResponse({"ok": True})


@require_POST
@transaction.atomic
def classificacio_reorder(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invàlid")

    order = payload.get("order") or []
    # order = [id1, id2, ...]
    for idx, cid in enumerate(order, start=1):
        ClassificacioConfig.objects.filter(competicio=competicio, id=cid).update(ordre=idx)

    return JsonResponse({"ok": True})


@require_POST
def classificacio_preview(request, pk, cid):
    competicio = get_object_or_404(Competicio, pk=pk)
    cfg = get_object_or_404(ClassificacioConfig, pk=cid, competicio=competicio)

    data = compute_classificacio(competicio, cfg)

    # Retorna una estructura fàcil pel front:
    # [
    #   {"particio": "global", "rows":[...]}
    # ]
    out = []
    for k in sorted(data.keys()):
        out.append({"particio": k, "rows": data[k]})

    return JsonResponse({
        "ok": True,
        "columns": get_display_columns(cfg.schema or {}),
        "data": out,
    })


def _is_fk(model_cls, field_name: str) -> bool:
    try:
        f = model_cls._meta.get_field(field_name)
        return isinstance(f, (models.ForeignKey, models.OneToOneField))
    except Exception:
        return False

def _distinct_values(qs, field_name: str):
    vals = qs.values_list(field_name, flat=True).distinct()
    out = []
    seen = set()
    for v in vals:
        if v is None:
            continue
        label = str(v).strip()
        if not label:
            continue
        key = " ".join(label.split()).casefold()   # treu dobles espais + case-insensitive
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
    return out


def _distinct_fk(qs, field_name: str):
    # retorna llista d'objectes {id, label}
    rel = qs.select_related(field_name).values_list(f"{field_name}_id", f"{field_name}__nom").distinct()
    out = []
    seen = set()
    for _id, nom in rel:
        if _id is None or _id in seen:
            continue
        seen.add(_id)
        out.append({"value": _id, "label": nom or str(_id)})
    return out




