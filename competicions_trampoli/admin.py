from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Competicio, CompeticioMembership
from .models.classificacions import ClassificacioTemplateGlobal
from .models.competicio import (
    CompeticioAparell,
    CompeticioAparellFase,
    FasePartitionState,
    ProgramUnit,
    ProgramUnitSlot,
    QualificationRun,
)
from .models.judging import JudgeConversation, JudgeConversationMessage
from .models.rotacions import RotacioAssignacioProgramUnit


class CompeticioMembershipByCompeticioInline(admin.TabularInline):
    model = CompeticioMembership
    fk_name = "competicio"
    extra = 0
    autocomplete_fields = ("user", "granted_by")


class CompeticioMembershipByUserInline(admin.TabularInline):
    model = CompeticioMembership
    fk_name = "user"
    extra = 0
    autocomplete_fields = ("competicio", "granted_by")


@admin.register(Competicio)
class CompeticioAdmin(admin.ModelAdmin):
    list_display = ("nom", "tipus", "data", "created_at")
    search_fields = ("nom",)
    list_filter = ("tipus",)
    inlines = (CompeticioMembershipByCompeticioInline,)


@admin.register(CompeticioMembership)
class CompeticioMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "competicio", "role", "is_active", "granted_by", "updated_at")
    list_filter = ("role", "is_active", "competicio")
    search_fields = ("user__username", "user__email", "competicio__nom")
    autocomplete_fields = ("user", "competicio", "granted_by")


@admin.register(CompeticioAparell)
class CompeticioAparellAdmin(admin.ModelAdmin):
    list_display = ("competicio", "display_nom", "display_codi", "aparell", "ordre", "actiu")
    list_filter = ("actiu", "competicio")
    search_fields = ("competicio__nom", "nom_local", "codi_local", "aparell__nom", "aparell__codi")


@admin.register(CompeticioAparellFase)
class CompeticioAparellFaseAdmin(admin.ModelAdmin):
    list_display = ("nom", "codi", "competicio", "comp_aparell", "parent", "ordre", "estat")
    list_filter = ("estat", "competicio")
    search_fields = ("nom", "codi", "competicio__nom", "comp_aparell__nom_local", "comp_aparell__codi_local")
    autocomplete_fields = ("competicio", "comp_aparell", "parent")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ProgramUnit)
class ProgramUnitAdmin(admin.ModelAdmin):
    list_display = ("nom", "fase", "tipus", "ordre", "capacity", "status")
    list_filter = ("tipus", "status", "fase__competicio")
    search_fields = ("nom", "fase__nom", "fase__codi", "fase__comp_aparell__nom_local")
    autocomplete_fields = ("fase",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(ProgramUnitSlot)
class ProgramUnitSlotAdmin(admin.ModelAdmin):
    list_display = ("unit", "slot_index", "ordre", "status", "subject_kind", "subject_id", "locked")
    list_filter = ("status", "subject_kind", "locked")
    search_fields = ("unit__nom", "subject_kind", "subject_id", "source_particio_key")
    autocomplete_fields = ("unit",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(QualificationRun)
class QualificationRunAdmin(admin.ModelAdmin):
    list_display = ("fase", "source_classificacio", "source_phase", "status", "snapshot_hash", "applied_at", "created_at")
    list_filter = ("status", "fase__competicio")
    search_fields = ("fase__nom", "source_classificacio__nom", "snapshot_hash")
    autocomplete_fields = ("fase", "source_phase")
    readonly_fields = ("created_at", "updated_at")


@admin.register(FasePartitionState)
class FasePartitionStateAdmin(admin.ModelAdmin):
    list_display = ("fase", "partition_key", "status", "qualification_run", "confirmed_at", "updated_at")
    list_filter = ("status", "fase__competicio")
    search_fields = ("fase__nom", "partition_key", "source_snapshot_hash")
    autocomplete_fields = ("fase", "qualification_run")
    readonly_fields = ("created_at", "updated_at")


@admin.register(RotacioAssignacioProgramUnit)
class RotacioAssignacioProgramUnitAdmin(admin.ModelAdmin):
    list_display = ("assignacio", "program_unit", "ordre")
    list_filter = ("program_unit__fase__competicio", "program_unit__fase")
    search_fields = ("program_unit__nom", "program_unit__fase__nom", "assignacio__competicio__nom")
    autocomplete_fields = ("program_unit",)


@admin.register(ClassificacioTemplateGlobal)
class ClassificacioTemplateGlobalAdmin(admin.ModelAdmin):
    list_display = ("nom", "slug", "tipus", "activa", "version", "uses_count", "updated_at")
    list_filter = ("tipus", "activa")
    search_fields = ("nom", "slug", "descripcio")
    readonly_fields = ("version", "uses_count", "last_used_at", "created_at", "updated_at")


@admin.register(JudgeConversation)
class JudgeConversationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "competicio",
        "comp_aparell",
        "judge_token",
        "status",
        "priority",
        "unread_for_org",
        "unread_for_judge",
        "last_message_at",
    )
    list_filter = ("status", "priority", "competicio")
    search_fields = ("judge_token__label", "judge_token__id")
    autocomplete_fields = ("competicio", "comp_aparell")
    readonly_fields = ("created_at", "updated_at")


@admin.register(JudgeConversationMessage)
class JudgeConversationMessageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "conversation",
        "sender_type",
        "message_type",
        "sender_user",
        "created_at",
    )
    list_filter = ("sender_type", "message_type", "competicio")
    search_fields = ("text", "judge_token__label", "conversation__id")
    autocomplete_fields = ("conversation", "competicio", "comp_aparell", "sender_user")
    readonly_fields = ("created_at",)


User = get_user_model()


try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    inlines = (CompeticioMembershipByUserInline,)
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "is_staff",
        "is_active",
        "global_roles_summary",
    )
    list_filter = DjangoUserAdmin.list_filter + ("groups",)

    @admin.display(description="Global roles")
    def global_roles_summary(self, obj):
        names = list(obj.groups.order_by("name").values_list("name", flat=True))
        return ", ".join(names) if names else "-"
