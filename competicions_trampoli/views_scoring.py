# views_scoring.py
import json
import logging
from collections import defaultdict

from django.contrib import messages
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


logger = logging.getLogger(__name__)


def _recalculate_scores_for_comp_aparell(competicio, comp_aparell, chunk_size: int = 200) -> dict:
    """
    Recalculate all ScoreEntry rows for one competition + comp_aparell using the current
    global schema attached to the Aparell.
    """
    qs = (
        ScoreEntry.objects
        .filter(competicio=competicio, comp_aparell=comp_aparell)
        .order_by("id")
    )
    summary = {
        "total": qs.count(),
        "updated": 0,
        "failed": 0,
        "errors_preview": [],
    }

    ss, _ = ScoringSchema.objects.get_or_create(
        aparell=comp_aparell.aparell,
        defaults={"schema": {}},
    )

    try:
        engine = ScoringEngine(ss.schema or {})
    except Exception as exc:
        summary["engine_error"] = str(exc)
        logger.exception(
            "Schema recalc init failed for competicio=%s comp_aparell=%s: %s",
            getattr(competicio, "id", None),
            getattr(comp_aparell, "id", None),
            exc,
        )
        return summary

    for entry in qs.iterator(chunk_size=chunk_size):
        raw_inputs = entry.inputs if isinstance(entry.inputs, dict) else {}
        try:
            result = engine.compute(raw_inputs)
            entry.inputs = result.inputs
            entry.outputs = result.outputs
            entry.total = result.total
            entry.save(update_fields=["inputs", "outputs", "total", "updated_at"])
            summary["updated"] += 1
        except ScoringError as exc:
            summary["failed"] += 1
            if len(summary["errors_preview"]) < 5:
                summary["errors_preview"].append(f"{entry.id}: {exc}")
            logger.warning(
                "Schema recalc failed for ScoreEntry id=%s (domain): %s",
                entry.id,
                exc,
            )
        except Exception as exc:
            summary["failed"] += 1
            if len(summary["errors_preview"]) < 5:
                summary["errors_preview"].append(f"{entry.id}: error inesperat")
            logger.exception(
                "Schema recalc failed for ScoreEntry id=%s (unexpected): %s",
                entry.id,
                exc,
            )

    logger.info(
        "Schema recalc summary competicio=%s comp_aparell=%s total=%s updated=%s failed=%s",
        getattr(competicio, "id", None),
        getattr(comp_aparell, "id", None),
        summary["total"],
        summary["updated"],
        summary["failed"],
    )
    return summary


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


        # Aparells de la competició
        aparells_cfg = (
            CompeticioAparell.objects
            .filter(competicio=competicio, actiu=True)
            .select_related("aparell")
            .order_by("ordre", "id")
        )
        
        def clamp_ex(n):
            try:
                n = int(n or 1)
            except Exception:
                n = 1
            return max(1, min(4, n))


        # Exercicis
        exercicis_by_aparell = {}
        max_ex = 1
        for ca in aparells_cfg:
            n = clamp_ex(getattr(ca, "nombre_exercicis", 1))
            exercicis_by_aparell[str(ca.id)] = list(range(1, n + 1))
            max_ex = max(max_ex, n)

        exercicis = list(range(1, max_ex + 1))
        
        # ─────────────────────────────
        # SCHEMAS (dict simple)
        # ─────────────────────────────
        schemas = {}
        for ca in aparells_cfg:
            ss, _ = ScoringSchema.objects.get_or_create(
                aparell=ca.aparell,
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
            "exercicis_by_aparell": exercicis_by_aparell,

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
        # si estem en mode competició (competicio/<pk>/aparell/<ap_id>/schema/)
        if self.comp_aparell:
            obj, _ = ScoringSchema.objects.get_or_create(
                aparell=self.comp_aparell.aparell,
                defaults={"schema": {}},
            )
            return obj

        # si estem en mode global (trampoli/aparells/<pk>/puntuacio/)
        obj, _ = ScoringSchema.objects.get_or_create(
            aparell=self.aparell,
            defaults={"schema": {}},
        )
        return obj

    def form_valid(self, form):
        schema_json = form.cleaned_data.get("schema_json")
        schema_changed = False

        if schema_json is not None:
            previous_schema = self.object.schema if isinstance(self.object.schema, dict) else {}
            schema_changed = previous_schema != schema_json
            self.object.schema = schema_json
            self.object.save()

        # Auto recalc only in competition flow and only if schema really changed.
        if schema_changed and self.competicio and self.comp_aparell:
            summary = _recalculate_scores_for_comp_aparell(self.competicio, self.comp_aparell)
            engine_error = summary.get("engine_error")

            if engine_error:
                messages.error(
                    self.request,
                    f"Schema desat, pero no s'han recalculat notes: {engine_error}",
                )
            elif summary["failed"] > 0:
                preview = "; ".join(summary["errors_preview"])
                extra = f" Errors: {preview}" if preview else ""
                messages.warning(
                    self.request,
                    f"Schema desat. Recalculades {summary['updated']}/{summary['total']} notes"
                    f" ({summary['failed']} fallades).{extra}",
                )
            else:
                messages.success(
                    self.request,
                    f"Schema desat. Recalculades {summary['updated']}/{summary['total']} notes.",
                )

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

        next_url = self.request.GET.get("next")
        if next_url:
            ctx["next"] = next_url

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

    ss, _ = ScoringSchema.objects.get_or_create(aparell=comp_aparell.aparell, defaults={"schema": {}})
    schema = ss.schema or {}
    # --- FILTRA INPUTS DESCONeguts (evita "Nom desconegut: E_j") ---
    allowed = set()
    for f in (schema.get("fields") or []):
        if isinstance(f, dict) and f.get("code"):
            allowed.add(f["code"])
            # també permet crash keys si les uses (__crash__X)
            allowed.add(f"__crash__{f['code']}")

    clean_inputs = {}
    if isinstance(inputs, dict):
        for k, v in inputs.items():
            if k in allowed:
                clean_inputs[k] = v

    try:
        engine = ScoringEngine(schema)
        result = engine.compute(clean_inputs)
    except ScoringError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    except Exception:
        return JsonResponse({"ok": False, "error": "Error inesperat calculant."}, status=500)

    max_ex = max(1, min(4, int(getattr(comp_aparell, "nombre_exercicis", 1) or 1)))
    exercici = int(payload.get("exercici") or 1)
    exercici = max(1, min(max_ex, exercici))

    entry, _ = ScoreEntry.objects.get_or_create(
        competicio=competicio,
        inscripcio=ins,
        exercici=exercici,
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
