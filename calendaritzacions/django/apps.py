"""Django AppConfig for the optional calendaritzacions UI."""

from __future__ import annotations

from django.apps import AppConfig


class CalendaritzacionsDjangoConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "calendaritzacions.django"
    label = "calendaritzacions_django"
    verbose_name = "Calendaritzacions"
