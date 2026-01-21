from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse
from django.shortcuts import render
from django.conf import settings
from django.conf.urls.static import static
from ceeb_web import views

urlpatterns = [
    path('about/', views.about_view, name='about'),
    path('admin/', admin.site.urls),
    path('marbella/', views.marbella_view, name='marbella'),
    path('esports_equip/', views.esports_equip_view, name='esports_equip'),
    path('esports_individuals/', views.esports_individuals_view, name='esports_individuals'),
    path('esports_individuals/llistats_provisionals/', views.llistats_provisionals_view, name='llistats_provisionals'),
    path('esports_individuals/llistats_definitius/', views.llistats_definitius_view, name='llistats_definitius'),
    path('esports_equip/calendaritzacions/', views.calendaritzacions_view, name='calendaritzacions'),
    path('esports_equip/calendaritzacions_fase_dos/', views.calendaritzacions_fase_dos_view, name='calendaritzacions_fase_dos'),
    path('esports_equip/designacions/', views.designacions_view, name='designacions'),
    path('formacio/', views.formacio_view, name='formacio'),
    path('formacio/certificats/', views.CertificatsUploadView.as_view(), name="certificats"),
    path('task-status/<str:task_id>/', views.task_status_view, name='task_status'),
    path("logs/<str:task_id>/stream", views.sse_logs, name="sse_logs"),
    path("chatbot/", views.chatbot_view, name="chatbot"),
    path("", include("alumnat.urls")),
    path("", views.HomeCalendarView.as_view(), name="home"),
    path("calendar/events/", views.CalendarEventsJsonView.as_view(), name="calendar_events_json"),
    path("calendar/events/create/", views.CalendarEventCreateView.as_view(), name="calendar_event_create"),
    path("calendar/events/<int:event_id>/update/", views.CalendarEventUpdateView.as_view(), name="calendar_event_update"),
    path("calendar/events/<int:event_id>/delete/", views.CalendarEventDeleteView.as_view(), name="calendar_event_delete"),
    path("", include("competicions_trampoli.urls")),
    path('', include('marbella_informes.urls')),
    path("", include("designacions.urls")),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)