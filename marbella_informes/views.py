from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView, DetailView, ListView, View
from django.http import JsonResponse
from .tasks import run_analysis_task
from .models import AnnualReport, AnnualDataset
from .forms import AnnualReportForm, AnnualDatasetFormSet
import os
from django.conf import settings
from .forms import PlotOverrideForm
from django.shortcuts import get_object_or_404, redirect, render


DEFAULT_DATASET_TYPES = [
    AnnualDataset.DatasetType.CLIENTS,
    AnnualDataset.DatasetType.RESERVES,
]


class AnnualReportCreateView(CreateView):
    model = AnnualReport
    form_class = AnnualReportForm
    template_name = "annual_report_form.html"

    def get_success_url(self):
        return reverse_lazy("annual_report_update", kwargs={"pk": self.object.pk})

    @transaction.atomic
    def form_valid(self, form):
        resp = super().form_valid(form)

        # guarda config
        cfg = form.cleaned_data.get("_config_payload", {})
        self.object.config = cfg
        self.object.save(update_fields=["config"])

        # crea “slots” de datasets per pujar a la mateixa pantalla
        existing = set(self.object.datasets.values_list("tipus", flat=True))
        for t in DEFAULT_DATASET_TYPES:
            if t not in existing:
                AnnualDataset.objects.create(report=self.object, tipus=t, fitxer="")  # fitxer buit (no s’usarà)
                # Nota: un FileField “buit” així no és ideal; alternativa:
                # crear el dataset només quan l’usuari pugui el fitxer.
                # Si prefereixes això, elimina aquesta creació i fes extra forms al formset.

        messages.success(self.request, "Informe creat. Ara pots adjuntar els Excels i configurar paràmetres.")
        return resp

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # en create, encara no hi ha formset “real” perquè no hi ha report guardat del tot
        ctx["formset"] = None
        ctx["is_create"] = True
        return ctx


class AnnualReportUpdateView(UpdateView):
    model = AnnualReport
    form_class = AnnualReportForm
    template_name = "annual_report_form.html"

    def get_success_url(self):
        return reverse_lazy("annual_report_update", kwargs={"pk": self.object.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.method == "POST":
            ctx["formset"] = AnnualDatasetFormSet(self.request.POST, self.request.FILES, instance=self.object)
        else:
            # assegura que existeixen “slots”
            existing = set(self.object.datasets.values_list("tipus", flat=True))
            for t in DEFAULT_DATASET_TYPES:
                if t not in existing:
                    AnnualDataset.objects.create(report=self.object, tipus=t, fitxer="", notes="")

            ctx["formset"] = AnnualDatasetFormSet(instance=self.object)

        ctx["is_create"] = False
        return ctx

    @transaction.atomic
    def form_valid(self, form):
        ctx = self.get_context_data()
        formset = ctx["formset"]

        if not formset.is_valid():
            return self.form_invalid(form)

        resp = super().form_valid(form)

        # guarda config
        cfg = form.cleaned_data.get("_config_payload", {})
        self.object.config = cfg
        self.object.save(update_fields=["config"])

        # guarda datasets
        formset.save()

        messages.success(self.request, "Dades desades correctament.")
        return resp


class AnnualReportDetailView(DetailView):
    model = AnnualReport
    template_name = "annual_report_detail.html"


    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        report = self.object  # el mateix que {{ object }} al template

        out = report.analysis_result or {}

        # nova estructura: {"kpis":..., "artifacts": {"plots":[...]}}
        artifacts = out.get("artifacts")

        # compat amb estructura antiga: {"kpis": {"artifacts": {...}}}
        if artifacts is None:
            artifacts = (out.get("kpis") or {}).get("artifacts")

        plots = (artifacts or {}).get("plots") or []

        ctx["plots"] = [
            {
                **p,
                "url": settings.MEDIA_URL.rstrip("/") + "/" + p["file"].lstrip("/")
            }
            for p in plots
            if isinstance(p, dict) and p.get("file")
        ]
        ctx["analysis_result"] = out
        return ctx

class AnnualReportListView(ListView):
    model = AnnualReport
    template_name = "annual_report_list.html"
    context_object_name = "reports"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            AnnualReport.objects
            .prefetch_related("datasets")
            .order_by("-any", "instal_lacio_nom")
        )

        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(instal_lacio_nom__icontains=q)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = (self.request.GET.get("q") or "").strip()
        return ctx
    


# --------------------------------------------------------------------------------------------------
#       VISTES DE PROCESSAT I ANÀLISI 
# --------------------------------------------------------------------------------------------------

class AnnualReportRunAnalysisView(View):
    def post(self, request, pk):
        report = AnnualReport.objects.get(pk=pk)
        report.status = "processing"
        report.progress = 0
        report.analysis_error = ""
        report.save(update_fields=["status", "progress", "analysis_error"])

        # Encua task (exemple Celery)
        run_analysis_task.apply_async(args=[report.pk], queue="heavy_queue")


        return redirect("annual_report_progress", pk=report.pk)
    
class AnnualReportProgressView(DetailView):
    model = AnnualReport
    template_name = "annual_report_progress.html"



class AnnualReportProgressJsonView(View):
    def get(self, request, pk):
        r = AnnualReport.objects.get(pk=pk)
        return JsonResponse({
            "status": r.status,
            "progress": r.progress,
            "error": r.analysis_error,
        })
    

class AnnualReportPlotEditView(View):
    template_name = "annual_report_plot_edit.html"

    def get(self, request, pk, plot_key):
        report = get_object_or_404(AnnualReport, pk=pk)

        cfg = report.config or {}
        plots_cfg = cfg.get("plots") or {}
        current = plots_cfg.get(plot_key) or {}

        form = PlotOverrideForm(initial={
            "enabled": current.get("enabled", True),
            "title": current.get("title", ""),
            "dpi": current.get("dpi"),
            "grid": current.get("grid"),
        })

        return render(request, self.template_name, {
            "report": report,
            "plot_key": plot_key,
            "form": form,
        })

    def post(self, request, pk, plot_key):
        report = get_object_or_404(AnnualReport, pk=pk)
        form = PlotOverrideForm(request.POST)

        if not form.is_valid():
            return render(request, self.template_name, {
                "report": report,
                "plot_key": plot_key,
                "form": form,
            })

        cfg = report.config or {}
        plots_cfg = cfg.get("plots") or {}
        plots_cfg[plot_key] = form.cleaned_data["_plot_override_payload"]
        cfg["plots"] = plots_cfg

        report.config = cfg
        report.save(update_fields=["config"])

        messages.success(request, f"Configuració del gràfic '{plot_key}' desada.")
        return redirect("annual_report_detail", pk=report.pk)