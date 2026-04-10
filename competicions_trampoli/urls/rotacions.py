from django.urls import path

from .base import competition_view
from ..views import rotacions as views_rotacions


urlpatterns = [
    path(
        "competicio/<int:pk>/rotacions/",
        competition_view(views_rotacions.rotacions_planner, "rotacions.view"),
        name="rotacions_planner",
    ),
    path(
        "competicio/<int:pk>/rotacions/save/",
        competition_view(views_rotacions.rotacions_save, "rotacions.edit"),
        name="rotacions_save",
    ),
    path(
        "competicio/<int:pk>/rotacions/franges/auto/",
        competition_view(views_rotacions.franges_auto_create, "rotacions.edit"),
        name="rotacions_franges_auto_create",
    ),
    path(
        "competicio/<int:pk>/rotacions/franja/create/",
        competition_view(views_rotacions.franja_create, "rotacions.edit"),
        name="rotacions_franja_create",
    ),
    path(
        "competicio/<int:pk>/rotacions/franja/<int:franja_id>/delete/",
        competition_view(views_rotacions.franja_delete, "rotacions.edit"),
        name="rotacions_franja_delete",
    ),
    path(
        "competicio/<int:pk>/rotacions/estacio/descans/create/",
        competition_view(views_rotacions.estacio_descans_create, "rotacions.edit"),
        name="rotacions_estacio_descans_create",
    ),
    path(
        "competicio/<int:pk>/rotacions/estacio/<int:estacio_id>/delete/",
        competition_view(views_rotacions.estacio_delete, "rotacions.edit"),
        name="rotacions_estacio_delete",
    ),
    path(
        "competicio/<int:pk>/rotacions/franja/<int:franja_id>/extrapolar/",
        competition_view(views_rotacions.rotacions_extrapolar, "rotacions.edit"),
        name="rotacions_extrapolar",
    ),
    path(
        "competicio/<int:pk>/rotacions/estacions/reorder/",
        competition_view(views_rotacions.estacions_reorder, "rotacions.edit"),
        name="rotacions_estacions_reorder",
    ),
    path(
        "competicio/<int:pk>/rotacions/clear_all/",
        competition_view(views_rotacions.rotacions_clear_all, "rotacions.edit"),
        name="rotacions_clear_all",
    ),
    path(
        "competicio/<int:pk>/rotacions/out-of-program-visibility/save/",
        competition_view(views_rotacions.rotacions_out_of_program_visibility_save, "rotacions.edit"),
        name="rotacions_out_of_program_visibility_save",
    ),
    path(
        "competicio/<int:pk>/rotacions/franges/<int:franja_id>/insert_after/",
        competition_view(views_rotacions.franja_insert_after, "rotacions.edit"),
        name="rotacions_franja_insert_after",
    ),
    path(
        "competicio/<int:pk>/rotacions/franges/reorder/",
        competition_view(views_rotacions.franges_reorder, "rotacions.edit"),
        name="rotacions_franges_reorder",
    ),
    path(
        "competicio/<int:pk>/rotacions/franges/reorder-visual/",
        competition_view(views_rotacions.franges_reorder_visual, "rotacions.edit"),
        name="rotacions_franges_reorder_visual",
    ),
    path(
        "competicio/<int:pk>/rotacions/franges/<int:franja_id>/update_inline/",
        competition_view(views_rotacions.franja_update_inline, "rotacions.edit"),
        name="rotacions_franja_update_inline",
    ),
    path(
        "competicio/<int:pk>/rotacions/franges/<int:franja_id>/order_mode/",
        competition_view(views_rotacions.franja_order_mode_set, "rotacions.edit"),
        name="rotacions_franja_order_mode_set",
    ),
    path(
        "competicio/<int:pk>/rotacions/export-meta/save/",
        competition_view(views_rotacions.rotacions_export_meta_save, "rotacions.edit"),
        name="rotacions_export_meta_save",
    ),
    path(
        "competicio/<int:pk>/rotacions/export-meta/logo/upload/",
        competition_view(views_rotacions.rotacions_export_logo_upload, "rotacions.edit"),
        name="rotacions_export_logo_upload",
    ),
    path(
        "competicio/<int:pk>/rotacions/export-meta/logo/clear/",
        competition_view(views_rotacions.rotacions_export_logo_clear, "rotacions.edit"),
        name="rotacions_export_logo_clear",
    ),
    path(
        "competicio/<int:pk>/rotacions/franges/export_excel/",
        competition_view(views_rotacions.franges_export_excel, "rotacions.view"),
        name="rotacions_franges_export_excel",
    ),
]
