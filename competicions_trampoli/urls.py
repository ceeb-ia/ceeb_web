from django.urls import path

from .views_trampoli import TrampoliConfigUpdate, TrampoliNotesHome, trampoli_guardar_nota, TrampoliAparellList, TrampoliAparellCreate, TrampoliAparellUpdate
from .views import CompeticioCreateView, CompeticioDeleteView, CompeticioHomeView, CompeticioListView, InscripcionsImportExcelView, InscripcionsListView
from competicions_trampoli import views, views_rotacions
from .views_trampoli import AparellList, AparellCreate, AparellUpdate


urlpatterns = [
    path("competicions/nova/", CompeticioCreateView.as_view(), name="create"),
    path("competicions/<int:pk>/importar/", InscripcionsImportExcelView.as_view(), name="import"),
    path("competicions/created/", CompeticioListView.as_view(), name="created"),   
    path("competicions/<int:pk>/inscripcions/", InscripcionsListView.as_view(), name="inscripcions_list"),
    path("competicions/<int:pk>/delete/", CompeticioDeleteView.as_view(), name="delete"),   
    path("competicions/", CompeticioHomeView.as_view(), name="competicions_home"),
    path("competicio/<int:pk>/inscripcions/reorder/", views.inscripcions_reorder, name="inscripcions_reorder"),
    path("competicio/<int:pk>/inscripcio/<int:ins_id>/editar/", views.InscripcioUpdateView.as_view(), name="inscripcio_edit"),
    path("competicio/<int:pk>/inscripcio/<int:ins_id>/eliminar/", views.InscripcioDeleteView.as_view(), name="inscripcio_delete"),
    path("competicio/<int:pk>/inscripcio/nova/", views.InscripcioCreateView.as_view(), name="inscripcio_add"),
    path("competicio/<int:pk>/notes/", views.notes_home_router, name="notes_home"),
    path("competicio/<int:pk>/notes/trampoli/", TrampoliNotesHome.as_view(), name="trampoli_notes_home"),
    path("competicio/<int:pk>/notes/trampoli/configuracio/",TrampoliConfigUpdate.as_view(),name="trampoli_config"),
    path("competicio/<int:pk>/notes/trampoli/guardar/", trampoli_guardar_nota, name="trampoli_save"),
    path("competicio/<int:pk>/notes/trampoli/aparells/", TrampoliAparellList.as_view(), name="trampoli_aparells_list"),
    path("competicio/<int:pk>/notes/trampoli/aparells/nou/", TrampoliAparellCreate.as_view(), name="trampoli_aparell_create"),
    path("competicio/<int:pk>/notes/trampoli/aparells/<int:ap_id>/editar/", TrampoliAparellUpdate.as_view(), name="trampoli_aparell_update"),
    path("competicio/<int:pk>/inscripcions/merge-tabs/", views.inscripcions_merge_tabs, name="inscripcions_merge_tabs"),
    path("trampoli/aparells/", AparellList.as_view(), name="aparells_list"),
    path("trampoli/aparells/nou/", AparellCreate.as_view(), name="aparell_create"),
    path("trampoli/aparells/<int:pk>/editar/", AparellUpdate.as_view(), name="aparell_update"),
    path("competicio/<int:pk>/rotacions/", views_rotacions.rotacions_planner, name="rotacions_planner"),
    path("competicio/<int:pk>/rotacions/save/", views_rotacions.rotacions_save, name="rotacions_save"),
    path("competicio/<int:pk>/rotacions/franges/auto/",views_rotacions.franges_auto_create,name="rotacions_franges_auto_create",),
    path("competicio/<int:pk>/rotacions/franja/create/", views_rotacions.franja_create, name="rotacions_franja_create"),
    path("competicio/<int:pk>/rotacions/franja/<int:franja_id>/delete/", views_rotacions.franja_delete, name="rotacions_franja_delete"),
    path("competicio/<int:pk>/rotacions/estacio/descans/create/",views_rotacions.estacio_descans_create,name="rotacions_estacio_descans_create",),
    path("competicio/<int:pk>/rotacions/estacio/<int:estacio_id>/delete/",views_rotacions.estacio_delete,name="rotacions_estacio_delete",),
    path("competicio/<int:pk>/rotacions/franja/<int:franja_id>/extrapolar/", views_rotacions.rotacions_extrapolar, name="rotacions_extrapolar"),
    path("competicio/<int:pk>/rotacions/estacions/reorder/", views_rotacions.estacions_reorder, name="rotacions_estacions_reorder"),
    path(
    "competicio/<int:pk>/rotacions/clear_all/",
    views_rotacions.rotacions_clear_all,
    name="rotacions_clear_all",
    ),

]
