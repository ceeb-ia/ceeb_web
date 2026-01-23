# designacions_app/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("designacions/", views.upload_view, name="designacions_upload"),
    path("designacions/run/<int:run_id>/", views.run_detail_view, name="designacions_run_detail"),
    path("designacions/run/<int:run_id>/assignments/", views.assignments_view, name="designacions_assignments"),
    path("designacions/run/<int:run_id>/assignments/<int:assignment_id>/update/", views.update_assignment_view, name="designacions_update_assignment"),
    path("designacions/run/<int:run_id>/map/", views.run_map_view, name="designacions_run_map"),
    path("designacions/run/<int:run_id>/export/", views.export_excel_view, name="designacions_export_excel"),
    path("designacions/geocoding/pending/", views.geocoding_pending_view, name="designacions_geocoding_pending"),
    path("designacions/geocoding/<int:address_id>/update/", views.geocoding_update_view, name="designacions_geocoding_update"),
    path("designacions/task-status/<str:task_id>/", views.task_status_view, name="designacions_task_status"),
    path("designacions/logs/<str:task_id>/stream", views.logs_stream_view, name="designacions_logs_stream"),
    path("designacions/run/<int:run_id>/assignments/<int:assignment_id>/unassign/",views.unassign_assignment_view,name="designacions_unassign_assignment"),
    path("designacions/modalitats-preview/",views.modalitats_preview_view,name="designacions_modalitats_preview"),
    path("designacions/runs/", views.runs_list_view, name="designacions_runs_list"),
    path("designacions/run/<int:run_id>/delete/", views.run_delete_view, name="designacions_run_delete"),

]
