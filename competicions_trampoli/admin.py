from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from competicions_trampoli.models_trampoli import CompeticioAparell

from .models import Competicio, CompeticioMembership
from .models_classificacions import ClassificacioTemplateGlobal


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
    list_display = ("competicio", "aparell", "ordre", "actiu")
    list_filter = ("actiu", "competicio")
    search_fields = ("competicio__nom", "aparell__nom", "aparell__codi")


@admin.register(ClassificacioTemplateGlobal)
class ClassificacioTemplateGlobalAdmin(admin.ModelAdmin):
    list_display = ("nom", "slug", "tipus", "activa", "version", "uses_count", "updated_at")
    list_filter = ("tipus", "activa")
    search_fields = ("nom", "slug", "descripcio")
    readonly_fields = ("version", "uses_count", "last_used_at", "created_at", "updated_at")


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
