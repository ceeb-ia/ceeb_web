from django.urls import path

from .base import competition_view
from ..views.classificacions.builder import (
    ClassificacionsHome,
    classificacio_delete,
    classificacio_preview,
    classificacio_reorder,
    classificacio_save,
)
from ..views.classificacions.export import classificacions_live_export_excel
from ..views.classificacions.live import (
    ClassificacionsLive,
    ClassificacionsLoopLive,
    PublicClassificacionsLive,
    PublicClassificacionsLoopLive,
    classificacions_live_data,
    public_classificacions_live_data,
)
from ..views.classificacions.templates import (
    classificacio_template_apply,
    classificacio_template_list,
    classificacio_template_save,
    classificacio_template_validate,
)


urlpatterns = [
    path(
        "competicio/<int:pk>/classificacions/",
        competition_view(ClassificacionsHome.as_view(), "classificacions.view"),
        name="classificacions_home",
    ),
    path(
        "competicio/<int:pk>/classificacions/save/",
        competition_view(classificacio_save, "classificacions.edit"),
        name="classificacio_save",
    ),
    path(
        "competicio/<int:pk>/classificacions/delete/<int:cid>/",
        competition_view(classificacio_delete, "classificacions.edit"),
        name="classificacio_delete",
    ),
    path(
        "competicio/<int:pk>/classificacions/reorder/",
        competition_view(classificacio_reorder, "classificacions.edit"),
        name="classificacio_reorder",
    ),
    path(
        "competicio/<int:pk>/classificacions/preview/<int:cid>/",
        competition_view(classificacio_preview, "classificacions.view"),
        name="classificacio_preview",
    ),
    path(
        "competicio/<int:pk>/classificacions/templates/",
        competition_view(classificacio_template_list, "classificacions.view"),
        name="classificacio_template_list",
    ),
    path(
        "competicio/<int:pk>/classificacions/templates/save/",
        competition_view(classificacio_template_save, "classificacions.edit"),
        name="classificacio_template_save",
    ),
    path(
        "competicio/<int:pk>/classificacions/templates/validate/",
        competition_view(classificacio_template_validate, "classificacions.edit"),
        name="classificacio_template_validate",
    ),
    path(
        "competicio/<int:pk>/classificacions/templates/apply/",
        competition_view(classificacio_template_apply, "classificacions.edit"),
        name="classificacio_template_apply",
    ),
    path(
        "competicio/<int:pk>/classificacions/live/",
        competition_view(ClassificacionsLive.as_view(), "classificacions.view"),
        name="classificacions_live",
    ),
    path(
        "competicio/<int:pk>/classificacions/loop/",
        competition_view(ClassificacionsLoopLive.as_view(), "classificacions.view"),
        name="classificacions_loop_live",
    ),
    path(
        "competicio/<int:pk>/classificacions/live/data/",
        competition_view(classificacions_live_data, "classificacions.view"),
        name="classificacions_live_data",
    ),
    path(
        "competicio/<int:pk>/classificacions/live/export.xlsx/",
        competition_view(classificacions_live_export_excel, "classificacions.view"),
        name="classificacions_live_export_excel",
    ),
    path(
        "public/live/<uuid:token>/",
        PublicClassificacionsLive.as_view(),
        name="public_live_portal",
    ),
    path(
        "public/live/<uuid:token>/loop/",
        PublicClassificacionsLoopLive.as_view(),
        name="public_live_loop",
    ),
    path(
        "public/live/<uuid:token>/data/",
        public_classificacions_live_data,
        name="public_live_classificacions_data",
    ),
]
