from django.contrib import admin
from django.conf import settings
from django.urls import include, path

from .access import app_authenticated_view
from .views import (
    CalendarEventCreateView,
    CalendarEventDeleteView,
    CalendarEventUpdateView,
    CalendarEventsJsonView,
    HomeCalendarView,
    InternalHomeView,
    sse_logs,
    task_status_view,
)


urlpatterns = [
    path("accounts/", include("django.contrib.auth.urls")),
    path("admin/", admin.site.urls),
    path("", InternalHomeView.as_view(), name="home"),
    path("calendar/", app_authenticated_view(HomeCalendarView.as_view(), "calendar"), name="calendar_home"),
    path("calendar/events/", app_authenticated_view(CalendarEventsJsonView.as_view(), "calendar"), name="calendar_events_json"),
    path("calendar/events/create/", app_authenticated_view(CalendarEventCreateView.as_view(), "calendar"), name="calendar_event_create"),
    path("calendar/events/<int:event_id>/update/", app_authenticated_view(CalendarEventUpdateView.as_view(), "calendar"), name="calendar_event_update"),
    path("calendar/events/<int:event_id>/delete/", app_authenticated_view(CalendarEventDeleteView.as_view(), "calendar"), name="calendar_event_delete"),
    path("task-status/<str:task_id>/", task_status_view, name="task_status"),
    path("logs/<str:task_id>/stream", sse_logs, name="sse_logs"),
]

if "competicions_trampoli" in settings.INSTALLED_APPS:
    urlpatterns.append(path("", include("competicions_trampoli.urls")))

if "designacions" in settings.INSTALLED_APPS:
    urlpatterns.append(path("", include("designacions.urls")))

if "marbella_informes" in settings.INSTALLED_APPS:
    urlpatterns.append(path("", include("marbella_informes.urls")))

if "certificats" in settings.INSTALLED_APPS:
    from certificats.views import CertificatsUploadView as CertificatsAppUploadView, processar_pdfs

    urlpatterns.extend(
        [
            path("formacio/certificats/", app_authenticated_view(CertificatsAppUploadView.as_view(), "certificats"), name="certificats"),
            path("formacio/certificats/processar/", app_authenticated_view(processar_pdfs, "certificats"), name="processar_pdfs"),
        ]
    )
