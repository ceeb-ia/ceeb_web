from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse
from django.shortcuts import render
from django.conf import settings
from django.conf.urls.static import static
from ceeb_web import views

urlpatterns = [
    path("accounts/", include("django.contrib.auth.urls")),
    path('admin/', admin.site.urls),
    path('esports_individuals/', views.esports_individuals_view, name='esports_individuals'),
    path('task-status/<str:task_id>/', views.task_status_view, name='task_status'),
    path("logs/<str:task_id>/stream", views.sse_logs, name="sse_logs"),
    path("", views.HomeCalendarView.as_view(), name="home"),
    path("calendar/events/", views.CalendarEventsJsonView.as_view(), name="calendar_events_json"),
    path("calendar/events/create/", views.CalendarEventCreateView.as_view(), name="calendar_event_create"),
    path("calendar/events/<int:event_id>/update/", views.CalendarEventUpdateView.as_view(), name="calendar_event_update"),
    path("calendar/events/<int:event_id>/delete/", views.CalendarEventDeleteView.as_view(), name="calendar_event_delete"),
    path("", include("competicions_trampoli.urls")),

]
