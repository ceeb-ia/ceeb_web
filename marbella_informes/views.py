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
import pandas as pd
from .tasks import generate_report_task
from django.http import HttpResponse
from weasyprint import HTML
from django.template.loader import render_to_string




DEFAULT_DATASET_TYPES = [
    AnnualDataset.DatasetType.CLIENTS,
    AnnualDataset.DatasetType.RESERVES,
]

MONTHLY_DATASET_TYPES = [
    AnnualDataset.DatasetType.OCASIONALS,
]

# ------------- HELPERS -------------------------------
def infer_month_from_excel_upload(uploaded_file) -> int | None:
    df = pd.read_excel(uploaded_file)  # si és .xls pot requerir xlrd al teu entorn
    if "Mes" not in df.columns:
        return None

    s = df["Mes"].dropna()
    if s.empty:
        return None

    try:
        m = int(s.iloc[0])
    except Exception:
        return None

    return m if 1 <= m <= 12 else None

def ensure_single_month(df) -> int | None:
    if "Mes" not in df.columns:
        return None
    vals = df["Mes"].dropna().astype(int)
    if vals.empty:
        return None
    if vals.nunique() != 1:
        return None
    m = int(vals.iloc[0])
    return m if 1 <= m <= 12 else None


def handle_ocasionals_uploads(request, report):
    files = request.FILES.getlist("ocasionals_files")
    if not files:
        return

    used_months = set()
    for f in files:
        # IMPORTANT: si fas read_excel aquí, després hasuries de “rebobinar” el fitxer abans de desar-lo
        # perquè read_excel consumeix el stream.
        df = pd.read_excel(f)
        month = ensure_single_month(df)  # o infer_month_from_excel_upload(f) si no vols nunique()

        if not month:
            messages.warning(request, f"Fitxer '{f.name}': no puc detectar un únic Mes (1..12).")
            continue

        if month in used_months:
            messages.warning(request, f"Mes {month:02d}: has pujat més d’un fitxer; s’usarà l’últim ({f.name}).")
        used_months.add(month)

        ds, _ = AnnualDataset.objects.get_or_create(
            report=report,
            tipus=AnnualDataset.DatasetType.OCASIONALS,
            period=month,
            defaults={"notes": f"Mes {month:02d}"},
        )

        # Rebobina el punter del fitxer perquè el save() guardi el contingut complet
        try:
            f.seek(0)
        except Exception:
            pass

        ds.fitxer.save(f.name, f, save=True)

    missing = [m for m in range(1, 13) if m not in used_months]
    if missing and len(files) >= 12:
        messages.warning(request, f"Ocasionals: falten mesos {missing}.")


def ensure_dataset_slots(report: AnnualReport):
    existing = {(d.tipus, d.period) for d in report.datasets.all()}

    # no mensuals (period=None)
    for t in DEFAULT_DATASET_TYPES:
        if (t, None) not in existing:
            AnnualDataset.objects.create(report=report, tipus=t, period=None, fitxer="", notes="")

    # mensuals: 12 mesos
    for t in MONTHLY_DATASET_TYPES:
        for m in range(1, 13):
            if (t, m) not in existing:
                AnnualDataset.objects.create(report=report, tipus=t, period=m, fitxer="", notes=f"Mes {m:02d}")




#  ------------------------ VISTES DE CRUD DE REPORTS I DATASETS --------------------------------
class AnnualReportCreateView(CreateView):
    model = AnnualReport
    form_class = AnnualReportForm
    template_name = "annual_report_form.html"

    def get_success_url(self):
        return reverse_lazy("annual_report_update", kwargs={"pk": self.object.pk})

    @transaction.atomic
    def form_valid(self, form):
        resp = super().form_valid(form)
        handle_ocasionals_uploads(self.request, self.object)

        # guarda config
        cfg = form.cleaned_data.get("_config_payload", {})
        self.object.config = cfg
        self.object.save(update_fields=["config"])

        # crea “slots” de datasets per pujar a la mateixa pantalla
        ensure_dataset_slots(self.object)

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

        ensure_dataset_slots(self.object)

        qs = self.object.datasets.exclude(tipus=AnnualDataset.DatasetType.OCASIONALS)

        if self.request.method == "POST":
            ctx["formset"] = AnnualDatasetFormSet(self.request.POST, self.request.FILES, instance=self.object, queryset=qs)
        else:
            ctx["formset"] = AnnualDatasetFormSet(instance=self.object, queryset=qs)

        ctx["is_create"] = False
        return ctx

    @transaction.atomic
    def form_valid(self, form):
        ctx = self.get_context_data()
        formset = ctx["formset"]

        if not formset.is_valid():
            return self.form_invalid(form)

        resp = super().form_valid(form)
        handle_ocasionals_uploads(self.request, self.object)
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
    


# --------------------------------------------------------------------------------------------------
#       VISTES DE REDACCIÓ I GENERACIÓ D'INFORMES
# --------------------------------------------------------------------------------------------------

class AnnualReportGenerateReportView(View):
    def post(self, request, pk):
        report = AnnualReport.objects.get(pk=pk)

        # opcional: bloqueja si no hi ha anàlisi
        if not report.analysis_result:
            messages.error(request, "Cal executar l'anàlisi abans de generar l'informe.")
            return redirect("annual_report_detail", pk=pk)

        report.report_status = "report_processing"
        report.report_progress = 0
        report.report_error = ""
        report.save(update_fields=["report_status", "report_progress", "report_error"])

        generate_report_task.apply_async(args=[report.pk], queue="heavy_queue")
        return redirect("annual_report_report_progress", pk=report.pk)


class AnnualReportReportProgressJsonView(View):
    def get(self, request, pk):
        r = AnnualReport.objects.get(pk=pk)
        return JsonResponse({
            "status": r.report_status,
            "progress": r.report_progress,
            "error": r.report_error,
            "file": r.report_file.url if r.report_file else None,
        })


class AnnualReportDetailView(DetailView):
    model = AnnualReport
    template_name = "annual_report_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # views.py (dins AnnualReportDetailView.get_context_data)
        report = self.object
        ctx["sections"] = report.sections.all().order_by("key")
        ctx["report_file_url"] = report.report_file.url if report.report_file else None
        return ctx


class AnnualReportReportProgressView(DetailView):
    model = AnnualReport
    template_name = "annual_report_report_progress.html"


class AnnualReportPdfView(DetailView):
    model = AnnualReport
    template_name = "annual_report_pdf.html"

    def get(self, request, *args, **kwargs):
        report = self.get_object()

        # prepara context igual que un render normal
        sections = report.sections.all().order_by("key")

        out = report.analysis_result or {}
        artifacts = out.get("artifacts") or (out.get("kpis") or {}).get("artifacts") or {}
        plots = artifacts.get("plots") or []
        plot_map = {p.get("key"): p for p in plots if isinstance(p, dict)}

        html_str = render_to_string(self.template_name, {
            "report": report,
            "sections": sections,
            "plot_map": plot_map,
        })

        pdf = HTML(string=html_str, base_url=request.build_absolute_uri("/")).write_pdf()

        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="informe_{report.instal_lacio_nom}_{report.any}.pdf"'
        return resp
