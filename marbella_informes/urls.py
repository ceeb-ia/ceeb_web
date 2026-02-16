from django.urls import path
from .views import AnnualReportCreateView, AnnualReportPlotEditView, AnnualReportUpdateView, AnnualReportDetailView, AnnualReportListView
from .views import AnnualReportRunAnalysisView, AnnualReportProgressView, AnnualReportProgressJsonView
from .views import AnnualReportGenerateReportView, AnnualReportReportProgressView, AnnualReportReportProgressJsonView, AnnualReportPdfView

urlpatterns = [
    path("annual/list/", AnnualReportListView.as_view(), name="annual_report_list"),
    path("annual/create/", AnnualReportCreateView.as_view(), name="annual_report_create"),
    path("annual/<int:pk>/edit/", AnnualReportUpdateView.as_view(), name="annual_report_update"),
    path("annual/<int:pk>/", AnnualReportDetailView.as_view(), name="annual_report_detail"),
    path("annual/<int:pk>/run-analysis/", AnnualReportRunAnalysisView.as_view(), name="annual_report_run_analysis"),
    path("annual/<int:pk>/progress/", AnnualReportProgressView.as_view(), name="annual_report_progress"),
    path("annual/<int:pk>/progress.json", AnnualReportProgressJsonView.as_view(), name="annual_report_progress_json"),
    path("annual-reports/<int:pk>/plots/<path:plot_key>/edit/", AnnualReportPlotEditView.as_view(), name="annual_report_plot_edit"),


    # Generar informe
    path("annual/<int:pk>/generate-report/", AnnualReportGenerateReportView.as_view(), name="annual_report_generate_report"),
    path("annual/<int:pk>/report-progress/", AnnualReportReportProgressView.as_view(), name="annual_report_report_progress"),
    path("annual/<int:pk>/report-progress.json", AnnualReportReportProgressJsonView.as_view(), name="annual_report_report_progress_json"),
    path("annual/<int:pk>/report.pdf", AnnualReportPdfView.as_view(), name="annual_report_pdf"),

]
