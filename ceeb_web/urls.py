from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse
from django.shortcuts import render
from django.conf import settings
from django.conf.urls.static import static
from ceeb_web import views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('about/', views.about_view, name='about'),
    path('admin/', admin.site.urls),
    path('esports_equip/', views.esports_equip_view, name='esports_equip'),
    path('esports_equip/calendaritzacions/', views.calendaritzacions_view, name='calendaritzacions'),
    path("calendaritzacions/status/<str:job_id>/", views.calendaritzacions_status, name="calendaritzacions_status"),
    path("calendaritzacions/download/<str:job_id>/", views.calendaritzacions_download, name="calendaritzacions_download"),
    path('esports_equip/certificats/', views.procesar_certificats_view, name="certificats"),
    path('task-status/<str:task_id>/', views.task_status_view, name='task_status'),
    path("logs/<str:task_id>/stream", views.sse_logs, name="sse_logs"),
    path("chatbot/", views.chatbot_view, name="chatbot"),


] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)