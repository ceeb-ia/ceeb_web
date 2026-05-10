"""URL routes for the optional Django calendaritzacions app."""

from __future__ import annotations

from django.urls import path

from calendaritzacions.django.views import (
    AuditDetailView,
    RunCreateView,
    RunDetailView,
    RunDownloadView,
    RunListView,
    RunStatusJsonView,
)


app_name = "calendaritzacions"

urlpatterns = [
    path("", RunListView.as_view(), name="run_list"),
    path("new/", RunCreateView.as_view(), name="run_create"),
    path("runs/<int:pk>/", RunDetailView.as_view(), name="run_detail"),
    path("runs/<int:pk>/status/", RunStatusJsonView.as_view(), name="run_status"),
    path("runs/<int:pk>/download/", RunDownloadView.as_view(), name="run_download"),
    path("runs/<int:pk>/audit/<slug:artifact>/", AuditDetailView.as_view(), name="audit_detail"),
]
