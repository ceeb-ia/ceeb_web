# views_scoring.py
import json
from collections import defaultdict

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView, UpdateView

from .models import Competicio, Inscripcio
from .models_trampoli import Aparell, CompeticioAparell
from .models_scoring import ScoringSchema, ScoreEntry
from .forms import ScoringSchemaForm
from .scoring_engine import ScoringEngine, ScoringError


class ScoringNotesHome(TemplateView):
    """
    Pantalla de notes dinàmica basada en schema.
    Convivència amb la pantalla trampolí actual: és una home nova.
    """
    template_name = "competicio/scoring_notes_home.html"

    def get(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        competicio = self.competicio

        ins = (
            Inscripcio.objects
            .filter(competicio=competicio)
            .order_by("grup", "ordre_sortida", "id")
        )

        # Agrupació (igual que ja fas servir)
        from collections import defaultdict
        grouped = defaultdict(list)
        for r in ins:
            grouped[r.grup if r.grup is not None else 0].append(r)

        group_keys = sorted([k for k in grouped.keys() if k != 0])
        if 0 in grouped:
            group_keys = [0] + group_keys
        groups = [(g, grouped[g]) for g in group_keys]

        # Exercicis
        cfg = getattr(competicio, "cfg_trampoli", None)
        n_ex = int(getattr(cfg, "nombre_exercicis", 1) or 1) if cfg else 1
        n_ex = max(1, min(4, n_ex))
        exercicis = list(range(1, n_ex + 1))

        # Aparells de la competició
        aparells_cfg = (
            CompeticioAparell.objects
            .filter(competicio=competicio, actiu=True)
            .select_related("aparell")
            .order_by("ordre", "id")
        )

        # ─────────────────────────────
        # SCHEMAS (dict simple)
        # ─────────────────────────────
        schemas = {}
        for ca in aparells_cfg:
            ss, _ = ScoringSchema.objects.get_or_create(
                comp_aparell=ca,
                defaults={"schema": {}},
            )
            schemas[str(ca.id)] = ss.schema or {}

        # ─────────────────────────────
        # SCORES (dict clau -> dades)
        # ─────────────────────────────
        scores_qs = ScoreEntry.objects.filter(
            competicio=competicio,
            inscripcio__in=ins,
            exercici__in=exercicis,
            comp_aparell__in=aparells_cfg,
        )

        scores = {}
        for s in scores_qs:
            key = f"{s.inscripcio_id}|{s.exercici}|{s.comp_aparell_id}"
            scores[key] = {
                "inputs": s.inputs or {},
                "outputs": s.outputs or {},
                "total": float(s.total),
            }

        # ─────────────────────────────
        # INSCRIPCIONS (llista plana per JS)
        # ─────────────────────────────
        # inscripcions: llista plana per al JS
        inscripcions = []
        for g, rows in groups:
            for r in rows:
                meta_parts = []
                if getattr(r, "entitat", None):
                    meta_parts.append(str(r.entitat))
                if getattr(r, "categoria", None):
                    meta_parts.append(str(r.categoria))
                if getattr(r, "subcategoria", None):
                    meta_parts.append(str(r.subcategoria))

                inscripcions.append({
                    "id": r.id,
                    "order": getattr(r, "ordre_sortida", "") or "",
                    "name": getattr(r, "nom_i_cognoms", "") or "",
                    "group": getattr(r, "grup", 0) or 0,
                    "meta": " · ".join(meta_parts) if meta_parts else "",
                })


        # ─────────────────────────────
        # CONTEXT FINAL
        # ─────────────────────────────
        ctx.update({
            "competicio": competicio,
            "groups": groups,
            "aparells_cfg": aparells_cfg,
            "exercicis": exercicis,

            # per json_script
            "schemas": schemas,
            "scores": scores,
            "inscripcions": inscripcions,
        })
        return ctx


class ScoringSchemaUpdate(UpdateView):
    model = ScoringSchema
    form_class = ScoringSchemaForm
    template_name = "competicio/scoring_schema_builder.html"

    def dispatch(self, request, *args, **kwargs):
            # per poder tornar on toca
            self.next_url = request.GET.get("next")

            self.competicio = None
            self.comp_aparell = None
            self.aparell = None

            # MODE VELL (ve de: competicio/<pk>/aparell/<ap_id>/schema/)
            if "ap_id" in kwargs:
                self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
                self.comp_aparell = get_object_or_404(
                    CompeticioAparell,
                    pk=kwargs["ap_id"],
                    competicio=self.competicio,
                )
                self.aparell = self.comp_aparell.aparell

            # MODE NOU (ve de: trampoli/aparells/<pk>/puntuacio/)
            else:
                self.aparell = get_object_or_404(Aparell, pk=kwargs["pk"])

            return super().dispatch(request, *args, **kwargs)

    def get_object(self):
        # Primer intentem schema GLOBAL (aparell=...)
        obj = ScoringSchema.objects.filter(aparell=self.aparell).first()
        if obj:
            return obj

        # Si no existeix, el creem global
        obj = ScoringSchema.objects.create(aparell=self.aparell, schema={})
        return obj


    def form_valid(self, form):
        schema_json = form.cleaned_data.get("schema_json")
        if schema_json is not None:
            self.object.schema = schema_json
            self.object.save()
        return redirect(self.get_success_url())

    def get_success_url(self):
        # 1) si venies d'algun lloc, torna-hi
        if self.next_url:
            return self.next_url

        # 2) si estàs en una competició, torna a notes-v2
        if self.competicio:
            return reverse("scoring_notes_home", kwargs={"pk": self.competicio.id})

        # 3) si és global, torna a editar l'aparell (o a la llista)
        return reverse("aparell_update", kwargs={"pk": self.aparell.id})
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["schema_initial"] = self.object.schema or {}
        ctx["aparell"] = self.aparell

        # només si vens del flux antic
        if self.competicio:
            ctx["competicio"] = self.competicio
        if self.comp_aparell:
            ctx["comp_aparell"] = self.comp_aparell

        return ctx


@require_POST
@transaction.atomic
def scoring_save(request, pk):
    """
    Guarda inputs i calcula outputs per un ScoreEntry.
    Payload:
    {
      "inscripcio_id": 10,
      "exercici": 1,
      "comp_aparell_id": 5,
      "inputs": {...}
    }
    """
    competicio = get_object_or_404(Competicio, pk=pk)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON invàlid"}, status=400)

    ins_id = payload.get("inscripcio_id")
    comp_aparell_id = payload.get("comp_aparell_id")
    exercici = int(payload.get("exercici") or 1)
    inputs = payload.get("inputs", {})

    if not ins_id or not comp_aparell_id:
        return JsonResponse({"ok": False, "error": "Falten camps: inscripcio_id/comp_aparell_id"}, status=400)

    ins = get_object_or_404(Inscripcio, pk=ins_id, competicio=competicio)
    comp_aparell = get_object_or_404(CompeticioAparell, pk=comp_aparell_id, competicio=competicio, actiu=True)

    ss, _ = ScoringSchema.objects.get_or_create(comp_aparell=comp_aparell, defaults={"schema": {}})
    schema = ss.schema or {}

    try:
        engine = ScoringEngine(schema)
        result = engine.compute(inputs if isinstance(inputs, dict) else {})
    except ScoringError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    except Exception:
        return JsonResponse({"ok": False, "error": "Error inesperat calculant."}, status=500)

    entry, _ = ScoreEntry.objects.get_or_create(
        competicio=competicio,
        inscripcio=ins,
        exercici=max(1, min(4, exercici)),
        comp_aparell=comp_aparell,
    )
    entry.inputs = result.inputs
    entry.outputs = result.outputs
    entry.total = result.total
    entry.save()

    return JsonResponse({
        "ok": True,
        "inscripcio_id": ins.id,
        "exercici": entry.exercici,
        "comp_aparell_id": comp_aparell.id,
        "outputs": entry.outputs,
        "total": float(entry.total),
    })
