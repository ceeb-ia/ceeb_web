# designacions_app/urls.py
from django.urls import path

from ceeb_web.access import app_authenticated_view

from . import views

urlpatterns = [
    path("designacions/", app_authenticated_view(views.upload_view, "designacions"), name="designacions_upload"),
    path("designacions/run/<int:run_id>/", app_authenticated_view(views.run_detail_view, "designacions"), name="designacions_run_detail"),
    path("designacions/run/<int:run_id>/assignments/", app_authenticated_view(views.assignments_view, "designacions"), name="designacions_assignments"),
    path("designacions/run/<int:run_id>/assignments/<int:assignment_id>/explanation/", app_authenticated_view(views.assignment_explanation_view, "designacions"), name="designacions_assignment_explanation"),
    path("designacions/run/<int:run_id>/assignments/<int:assignment_id>/manual-options/", app_authenticated_view(views.manual_assignment_options_view, "designacions"), name="designacions_manual_assignment_options"),
    path("designacions/run/<int:run_id>/assignments/manual-suggestions-bulk/", app_authenticated_view(views.manual_assignment_suggestions_bulk_view, "designacions"), name="designacions_manual_assignment_suggestions_bulk"),
    path("designacions/run/<int:run_id>/assignments/<int:assignment_id>/update-async/", app_authenticated_view(views.update_assignment_async_view, "designacions"), name="designacions_update_assignment_async"),
    path("designacions/run/<int:run_id>/assignments/<int:assignment_id>/update/", app_authenticated_view(views.update_assignment_view, "designacions"), name="designacions_update_assignment"),
    path("designacions/run/<int:run_id>/map/", app_authenticated_view(views.run_map_view, "designacions"), name="designacions_run_map"),
    path("designacions/run/<int:run_id>/export/", app_authenticated_view(views.export_excel_view, "designacions"), name="designacions_export_excel"),
    path("designacions/geocoding/pending/", app_authenticated_view(views.geocoding_pending_view, "designacions"), name="designacions_geocoding_pending"),
    path("designacions/geocoding/<int:address_id>/update/", app_authenticated_view(views.geocoding_update_view, "designacions"), name="designacions_geocoding_update"),
    path("designacions/task-status/<str:task_id>/", app_authenticated_view(views.task_status_view, "designacions"), name="designacions_task_status"),
    path("designacions/logs/<str:task_id>/stream", app_authenticated_view(views.logs_stream_view, "designacions"), name="designacions_logs_stream"),
    path("designacions/run/<int:run_id>/assignments/<int:assignment_id>/unassign/", app_authenticated_view(views.unassign_assignment_view, "designacions"), name="designacions_unassign_assignment"),
    path("designacions/modalitats-preview/", app_authenticated_view(views.modalitats_preview_view, "designacions"), name="designacions_modalitats_preview"),
    path("designacions/runs/", app_authenticated_view(views.runs_list_view, "designacions"), name="designacions_runs_list"),
    path("designacions/run/<int:run_id>/delete/", app_authenticated_view(views.run_delete_view, "designacions"), name="designacions_run_delete"),

]
