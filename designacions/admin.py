# designacions_app/admin.py
from django.contrib import admin
from .models import DesignationRun, Referee, Match, Availability, Assignment

@admin.register(DesignationRun)
class DesignationRunAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "created_at", "task_id")
    search_fields = ("task_id",)

@admin.register(Referee)
class RefereeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "active")
    search_fields = ("code", "name")

@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ("code", "run", "club_local", "equip_visitant", "hour_raw", "venue")
    search_fields = ("code", "club_local", "equip_local", "equip_visitant", "venue")

@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("run", "match", "referee", "locked", "updated_at")
    search_fields = ("match__code", "referee__code", "referee__name")

@admin.register(Availability)
class AvailabilityAdmin(admin.ModelAdmin):
    list_display = ("run", "referee")
