from django.urls import path
from django.conf.urls.static import static
from ceeb_web import settings
from ceeb_web.access import app_authenticated_view
from .views import AnnualReportCreateView, AnnualReportPlotEditView, AnnualReportUpdateView, AnnualReportDetailView, AnnualReportListView
from .views import AnnualReportRunAnalysisView, AnnualReportProgressView, AnnualReportProgressJsonView
from .views import AnnualReportGenerateReportView, AnnualReportReportProgressView, AnnualReportReportProgressJsonView, AnnualReportPdfView

urlpatterns = [
    path("annual/list/", app_authenticated_view(AnnualReportListView.as_view(), "informes"), name="annual_report_list"),
    path("annual/create/", app_authenticated_view(AnnualReportCreateView.as_view(), "informes"), name="annual_report_create"),
    path("annual/<int:pk>/edit/", app_authenticated_view(AnnualReportUpdateView.as_view(), "informes"), name="annual_report_update"),
    path("annual/<int:pk>/", app_authenticated_view(AnnualReportDetailView.as_view(), "informes"), name="annual_report_detail"),
    path("annual/<int:pk>/run-analysis/", app_authenticated_view(AnnualReportRunAnalysisView.as_view(), "informes"), name="annual_report_run_analysis"),
    path("annual/<int:pk>/progress/", app_authenticated_view(AnnualReportProgressView.as_view(), "informes"), name="annual_report_progress"),
    path("annual/<int:pk>/progress.json", app_authenticated_view(AnnualReportProgressJsonView.as_view(), "informes"), name="annual_report_progress_json"),
    path("annual-reports/<int:pk>/plots/<path:plot_key>/edit/", app_authenticated_view(AnnualReportPlotEditView.as_view(), "informes"), name="annual_report_plot_edit"),


    # Generar informe
    path("annual/<int:pk>/generate-report/", app_authenticated_view(AnnualReportGenerateReportView.as_view(), "informes"), name="annual_report_generate_report"),
    path("annual/<int:pk>/report-progress/", app_authenticated_view(AnnualReportReportProgressView.as_view(), "informes"), name="annual_report_report_progress"),
    path("annual/<int:pk>/report-progress.json", app_authenticated_view(AnnualReportReportProgressJsonView.as_view(), "informes"), name="annual_report_report_progress_json"),
    path("annual/<int:pk>/report.pdf", app_authenticated_view(AnnualReportPdfView.as_view(), "informes"), name="annual_report_pdf"),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
