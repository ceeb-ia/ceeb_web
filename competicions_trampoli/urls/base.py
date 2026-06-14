from django.contrib.auth.decorators import login_required
from django.urls import path

from ceeb_web.access import app_authenticated_view

from ..access import require_competicio_capability, require_global_groups
from ..views.classificacions.global_templates import (
    ClassificacioTemplateGlobalBuilder,
    ClassificacioTemplateGlobalDeleteView,
    ClassificacioTemplateGlobalList,
    classificacio_template_global_save,
)
from ..views.competition.aparatus import (
    AparellCreate,
    AparellDeleteView,
    AparellList,
    AparellUpdate,
)
from ..views.competition.competicio import (
    CompeticioCreateView,
    CompeticioDeleteView,
    CompeticioHomeView,
    CompeticioListView,
    CompeticioUpdateView,
    notes_home_router,
)
from ..views.scoring.schema import ScoringSchemaUpdate


def competition_view(view, capability, competicio_kwarg="pk"):
    return login_required(
        require_competicio_capability(capability, competicio_kwarg=competicio_kwarg)(view)
    )


def authenticated_view(view):
    return login_required(view)


def global_authenticated_view(view, *group_names):
    return login_required(require_global_groups(*group_names)(view))


urlpatterns = [
    path(
        "trampoli/aparells/",
        global_authenticated_view(AparellList.as_view(), "platform_admin", "competicions_manager"),
        name="aparells_list",
    ),
    path(
        "trampoli/aparells/nou/",
        global_authenticated_view(AparellCreate.as_view(), "platform_admin", "competicions_manager"),
        name="aparell_create",
    ),
    path(
        "trampoli/aparells/<int:pk>/editar/",
        global_authenticated_view(AparellUpdate.as_view(), "platform_admin", "competicions_manager"),
        name="aparell_update",
    ),
    path(
        "trampoli/aparells/<int:pk>/eliminar/",
        global_authenticated_view(AparellDeleteView.as_view(), "platform_admin", "competicions_manager"),
        name="aparell_delete",
    ),
    path(
        "trampoli/aparells/<int:pk>/puntuacio/",
        global_authenticated_view(ScoringSchemaUpdate.as_view(), "platform_admin", "competicions_manager"),
        name="aparell_scoring_schema_update",
    ),
    path(
        "trampoli/classificacio-templates/",
        global_authenticated_view(
            ClassificacioTemplateGlobalList.as_view(),
            "platform_admin",
            "competicions_manager",
        ),
        name="classificacio_template_global_list",
    ),
    path(
        "trampoli/classificacio-templates/nou/",
        global_authenticated_view(
            ClassificacioTemplateGlobalBuilder.as_view(),
            "platform_admin",
            "competicions_manager",
        ),
        name="classificacio_template_global_create",
    ),
    path(
        "trampoli/classificacio-templates/<int:pk>/editar/",
        global_authenticated_view(
            ClassificacioTemplateGlobalBuilder.as_view(),
            "platform_admin",
            "competicions_manager",
        ),
        name="classificacio_template_global_update",
    ),
    path(
        "trampoli/classificacio-templates/save/",
        global_authenticated_view(
            classificacio_template_global_save,
            "platform_admin",
            "competicions_manager",
        ),
        name="classificacio_template_global_save",
    ),
    path(
        "trampoli/classificacio-templates/<int:pk>/eliminar/",
        global_authenticated_view(
            ClassificacioTemplateGlobalDeleteView.as_view(),
            "platform_admin",
            "competicions_manager",
        ),
        name="classificacio_template_global_delete",
    ),
    path(
        "competicions/nova/",
        global_authenticated_view(CompeticioCreateView.as_view(), "platform_admin", "competicions_manager"),
        name="create",
    ),
    path("competicions/created/", app_authenticated_view(CompeticioListView.as_view(), "competicions"), name="created"),
    path("competicions/", app_authenticated_view(CompeticioHomeView.as_view(), "competicions"), name="competicions_home"),
    path(
        "competicions/<int:pk>/editar/",
        competition_view(CompeticioUpdateView.as_view(), "competition.edit"),
        name="competicio_update",
    ),
    path(
        "competicions/<int:pk>/delete/",
        competition_view(CompeticioDeleteView.as_view(), "competition.delete"),
        name="delete",
    ),
    path(
        "competicio/<int:pk>/notes/",
        competition_view(notes_home_router, "competition.view"),
        name="notes_home",
    ),
]
