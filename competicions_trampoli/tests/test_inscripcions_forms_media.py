import json
import re
from io import BytesIO, StringIO
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.sessions.backends.db import SessionStore
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Max
from django.test import RequestFactory, TestCase
from django.urls import Resolver404, resolve, reverse
from django.utils import timezone
from openpyxl import load_workbook

from ceeb_web.auth_groups import GLOBAL_AUTH_GROUPS

from .. import live_cache
from ..access import user_has_competicio_capability
from ..forms import CompeticioAparellForm
from ..models import (
    Competicio,
    Equip,
    EquipContext,
    GrupCompeticio,
    Inscripcio,
    InscripcioEquipAssignacio,
    InscripcioMedia,
)
from ..models_judging import (
    JudgeConversation,
    JudgeConversationMessage,
    JudgeDeviceToken,
    PublicLiveToken,
)
from ..models_classificacions import ClassificacioConfig, ClassificacioTemplateGlobal
from ..models_rotacions import (
    RotacioAssignacio,
    RotacioAssignacioGrup,
    RotacioAssignacioSerieEquip,
    RotacioEstacio,
    RotacioFranja,
)
from ..models_scoring import (
    ScoringSchema,
    ScoreEntry,
    ScoreEntryVideo,
    ScoreEntryVideoEvent,
    SerieEquip,
    SerieEquipItem,
    TeamScoreEntry,
    TeamCompetitiveSubject,
    TeamScoreEntryVideo,
    TeamScoreEntryVideoEvent,
)
from ..models_trampoli import (
    Aparell,
    CompeticioAparell,
    CompeticioAparellEquipContextSource,
    InscripcioAparellExclusio,
)
from ..models import CompeticioMembership
from ..scoring_engine import ScoringEngine
from ..inscripcions_views_shared import (
    _split_custom_sort_tokens,
    renumber_groups_for_competicio,
    sort_records_by_field_stable,
)
from ..services.inscripcions.history import (
    apply_inscripcions_history_snapshot,
    capture_inscripcions_history_snapshot,
)
from ..services.inscripcions.queries import (
    COLUMN_FILTER_EMPTY_TOKEN,
    _build_inscripcions_filtered_qs,
    build_inscripcions_sort_context_key,
    get_competicio_custom_sort_rank_map,
)
from ..services.classificacions.builder import scoreable_codes_by_app_id as _scoreable_codes_by_app_id
from ..services.classificacions.compute import DEFAULT_SCHEMA, compute_classificacio
from ..services.classificacions.export import _normalize_excel_cell
from ..services.classificacions.partitions import normalize_schema_legacy_team_birth_partition
from ..services.classificacions.validation import (
    build_metric_meta_for_comp_aparell as _build_metric_meta_for_comp_aparell,
    build_scoreable_meta_for_schema as _build_scoreable_meta_for_schema,
    validate_particions_schema as _validate_particions_schema,
    validate_schema_for_competicio as _validate_schema_for_competicio,
)
from ..services.classificacio_templates import (
    normalize_particions_schema as _normalize_particions_schema,
    schema_to_template_schema as _schema_to_template_schema,
    template_schema_to_competicio_schema as _template_schema_to_competicio_schema,
)
from ..views.classificacions.builder import ClassificacionsHome
from ..services.competition_groups import (
    assign_groups_by_display_num,
    compact_competition_order_for_group,
    ensure_group_for_display_num,
    get_group_maps,
    get_group_participant_counts,
    get_out_of_program_group_ids,
    get_programmed_group_ids,
    group_label,
    move_inscripcio_to_group,
    next_group_display_num,
)
from ..services.team_scoring import (
    build_permission_label,
    build_team_subjects_for_comp_aparell,
    resolve_permission_runtime_entries,
    runtime_schema_for_comp_aparell,
)
from ..services.team_series import safe_deactivate_empty_serie
from ..views_judge_admin import _member_slot_choices, _validate_permission_row
from ..templatetags.competicio_extras import (
    DEFAULT_COMPETITION_BACKGROUND,
    get_competicio_background_url_from_request,
)

from .base import _BaseTrampoliDataMixin


class InscripcioManualFormViewTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp manual form")
        self.other_comp = self._create_competicio("Comp altre")
        User = get_user_model()
        self.user = User.objects.create_user(
            username="manual_form_editor",
            password="testpass123",
            email="manual-form@example.com",
        )
        CompeticioMembership.objects.create(
            user=self.user,
            competicio=self.comp,
            role=CompeticioMembership.Role.EDITOR,
            is_active=True,
        )
        self.client.force_login(self.user)

    def _add_url(self):
        return reverse("inscripcio_add", kwargs={"pk": self.comp.id})

    def _edit_url(self, inscripcio):
        return reverse("inscripcio_edit", kwargs={"pk": self.comp.id, "ins_id": inscripcio.id})

    def _add_url_with_context(self, context_code):
        return f"{self._add_url()}?team_context={context_code}"

    def _edit_url_with_context(self, inscripcio, context_code):
        return f"{self._edit_url(inscripcio)}?team_context={context_code}"

    def test_create_form_uses_schema_fields_and_competition_scoped_choices(self):
        self.comp.inscripcions_schema = {
            "columns": [
                {"code": "categoria", "label": "Categoria", "kind": "builtin"},
                {"code": "subcategoria", "label": "Subcategoria", "kind": "builtin"},
                {"code": "modalitat", "label": "Modalitat", "kind": "extra"},
            ],
            "value_aliases": {
                "entitat": {"club a": "Club A"},
                "categoria": {"open": "Open"},
                "subcategoria": {"nivell 4": "Nivell 4"},
            },
        }
        self.comp.save(update_fields=["inscripcions_schema"])

        GrupCompeticio.objects.create(
            competicio=self.comp,
            legacy_num=1,
            display_num=1,
            nom="Matinal",
            actiu=True,
        )
        GrupCompeticio.objects.create(
            competicio=self.comp,
            legacy_num=2,
            display_num=2,
            nom="",
            actiu=True,
        )
        equip = Equip.objects.create(competicio=self.comp, nom="Equip A")
        Equip.objects.create(competicio=self.other_comp, nom="Equip Extern")
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A",
            entitat="club a",
            categoria="open",
            subcategoria="nivell 4",
            equip=equip,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="B",
            entitat="Club B",
            categoria="Base",
            subcategoria="Nivell 3",
        )
        Inscripcio.objects.create(
            competicio=self.other_comp,
            nom_i_cognoms="C",
            entitat="Club Extern",
            categoria="Externa",
            subcategoria="Externa",
        )

        response = self.client.get(self._add_url())
        self.assertEqual(response.status_code, 200)

        form = response.context["form"]
        self.assertNotIn("categoria", form.fields)
        self.assertNotIn("subcategoria", form.fields)
        self.assertNotIn("document", form.fields)
        self.assertIn("grup_competicio_choice", form.fields)
        self.assertIn("entitat_choice", form.fields)
        self.assertIn("entitat_altres", form.fields)
        self.assertIn("categoria_choice", form.fields)
        self.assertIn("categoria_altres", form.fields)
        self.assertIn("subcategoria_choice", form.fields)
        self.assertIn("subcategoria_altres", form.fields)
        self.assertIn("equip_choice", form.fields)
        self.assertIn("equip_altres", form.fields)
        self.assertIn("extra__modalitat", form.fields)

        group_choices = dict(form.fields["grup_competicio_choice"].choices)
        self.assertEqual(group_choices[""], "Sense grup")
        self.assertIn("Matinal", group_choices.values())
        self.assertIn("Grup 2", group_choices.values())

        entity_choices = dict(form.fields["entitat_choice"].choices)
        self.assertIn("Club A", entity_choices)
        self.assertIn("Club B", entity_choices)
        self.assertIn("__other__", entity_choices)
        self.assertNotIn("club a", entity_choices)
        self.assertNotIn("Club Extern", entity_choices)

        categoria_choices = dict(form.fields["categoria_choice"].choices)
        self.assertIn("Open", categoria_choices)
        self.assertIn("Base", categoria_choices)
        self.assertNotIn("open", categoria_choices)
        self.assertNotIn("Externa", categoria_choices)

        subcategoria_choices = dict(form.fields["subcategoria_choice"].choices)
        self.assertIn("Nivell 4", subcategoria_choices)
        self.assertIn("Nivell 3", subcategoria_choices)
        self.assertNotIn("nivell 4", subcategoria_choices)
        self.assertNotIn("Externa", subcategoria_choices)

        equip_choices = dict(form.fields["equip_choice"].choices)
        self.assertEqual(equip_choices[str(equip.id)], "Equip A")
        self.assertIn("__other__", equip_choices)
        self.assertNotIn("Equip Extern", equip_choices.values())

        self.assertEqual(response.context["show_altres_fields"], {
            "entitat_altres": False,
            "categoria_altres": False,
            "subcategoria_altres": False,
            "equip_altres": False,
        })

    def test_create_form_saves_group_text_other_equip_other_and_extra_fields(self):
        self.comp.inscripcions_schema = {
            "columns": [
                {"code": "categoria", "label": "Categoria", "kind": "builtin"},
                {"code": "subcategoria", "label": "Subcategoria", "kind": "builtin"},
                {"code": "modalitat", "label": "Modalitat", "kind": "extra"},
            ]
        }
        self.comp.save(update_fields=["inscripcions_schema"])
        group = GrupCompeticio.objects.create(
            competicio=self.comp,
            legacy_num=4,
            display_num=4,
            nom="Tarda",
            actiu=True,
        )

        response = self.client.post(
            self._add_url(),
            data={
                "nom_i_cognoms": "Nova gimnasta",
                "entitat_choice": "__other__",
                "entitat_altres": "Club Nou",
                "categoria_choice": "__other__",
                "categoria_altres": "Open",
                "subcategoria_choice": "__other__",
                "subcategoria_altres": "Nivell 4",
                "grup_competicio_choice": str(group.id),
                "equip_choice": "__other__",
                "equip_altres": "Equip Nou",
                "extra__modalitat": "Sincronitzada",
            },
        )

        self.assertEqual(response.status_code, 302)

        inscripcio = Inscripcio.objects.get(competicio=self.comp, nom_i_cognoms="Nova gimnasta")
        self.assertEqual(inscripcio.entitat, "Club Nou")
        self.assertEqual(inscripcio.categoria, "Open")
        self.assertEqual(inscripcio.subcategoria, "Nivell 4")
        self.assertEqual(inscripcio.grup_competicio_id, group.id)
        self.assertEqual(inscripcio.grup, 4)
        self.assertEqual(inscripcio.ordre_sortida, 1)
        self.assertEqual(inscripcio.ordre_competicio, 1)
        self.assertIsNone(inscripcio.equip_id)
        equip = Equip.objects.get(competicio=self.comp, nom="Equip Nou")
        self.assertEqual(equip.origen, Equip.Origen.MANUAL)
        self.assertEqual(equip.criteri, {})
        self.assertTrue(
            InscripcioEquipAssignacio.objects.filter(
                competicio=self.comp,
                context__code="native",
                inscripcio=inscripcio,
                equip=equip,
            ).exists()
        )
        self.assertEqual(inscripcio.extra, {"modalitat": "Sincronitzada"})

    def test_create_form_requires_other_values_when_other_is_selected(self):
        response = self.client.post(
            self._add_url(),
            data={
                "nom_i_cognoms": "Sense valors",
                "entitat_choice": "__other__",
                "entitat_altres": "",
                "categoria_choice": "__other__",
                "categoria_altres": "",
                "subcategoria_choice": "__other__",
                "subcategoria_altres": "",
                "grup_competicio_choice": "",
                "equip_choice": "__other__",
                "equip_altres": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "entitat_altres", "Cal indicar l'entitat si tries Altres.")
        self.assertFormError(response.context["form"], "categoria_altres", "Cal indicar la categoria si tries Altres.")
        self.assertFormError(response.context["form"], "subcategoria_altres", "Cal indicar la subcategoria si tries Altres.")
        self.assertFormError(response.context["form"], "equip_altres", "Cal indicar l'equip si tries Altres.")
        self.assertEqual(response.context["show_altres_fields"], {
            "entitat_altres": True,
            "categoria_altres": True,
            "subcategoria_altres": True,
            "equip_altres": True,
        })
        self.assertFalse(Inscripcio.objects.filter(competicio=self.comp, nom_i_cognoms="Sense valors").exists())

    def test_create_form_reuses_existing_team_when_other_is_selected(self):
        existing = Equip.objects.create(competicio=self.comp, nom="Equip Reutilitzat")

        response = self.client.post(
            self._add_url(),
            data={
                "nom_i_cognoms": "Amb equip existent",
                "entitat_choice": "",
                "categoria_choice": "",
                "subcategoria_choice": "",
                "grup_competicio_choice": "",
                "equip_choice": "__other__",
                "equip_altres": "Equip Reutilitzat",
            },
        )

        self.assertEqual(response.status_code, 302)
        inscripcio = Inscripcio.objects.get(competicio=self.comp, nom_i_cognoms="Amb equip existent")
        self.assertIsNone(inscripcio.equip_id)
        self.assertTrue(
            InscripcioEquipAssignacio.objects.filter(
                competicio=self.comp,
                context__code="native",
                inscripcio=inscripcio,
                equip=existing,
            ).exists()
        )
        self.assertEqual(Equip.objects.filter(competicio=self.comp, nom="Equip Reutilitzat").count(), 1)

    def test_edit_form_keeps_inactive_group_available_and_can_clear_it(self):
        self.comp.inscripcions_schema = {
            "columns": [
                {"code": "modalitat", "label": "Modalitat", "kind": "extra"},
            ]
        }
        self.comp.save(update_fields=["inscripcions_schema"])
        base_ctx = self._ensure_native_equip_context(self.comp)

        inactive_group = GrupCompeticio.objects.create(
            competicio=self.comp,
            legacy_num=7,
            display_num=7,
            nom="Grup ocult",
            actiu=False,
        )
        equip = Equip.objects.create(competicio=self.comp, nom="Equip Fix")
        inscripcio = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Edita'm",
            entitat="Club A",
            categoria="Open",
            subcategoria="Nivell 4",
            grup=7,
            grup_competicio=inactive_group,
            equip=equip,
            ordre_sortida=1,
            ordre_competicio=1,
            extra={"modalitat": "Dobles"},
        )
        InscripcioEquipAssignacio.objects.create(
            competicio=self.comp,
            context=base_ctx,
            inscripcio=inscripcio,
            equip=equip,
        )

        response = self.client.get(self._edit_url(inscripcio))
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertIn((str(inactive_group.id), "Grup ocult"), form.fields["grup_competicio_choice"].choices)
        self.assertEqual(form["extra__modalitat"].value(), "Dobles")
        self.assertEqual(form["entitat_choice"].value(), "Club A")
        self.assertEqual(form["categoria_choice"].value(), "Open")
        self.assertEqual(form["subcategoria_choice"].value(), "Nivell 4")
        self.assertEqual(form["equip_choice"].value(), str(equip.id))

        response = self.client.post(
            self._edit_url(inscripcio),
            data={
                "nom_i_cognoms": "Edita'm",
                "entitat_choice": "Club A",
                "categoria_choice": "Open",
                "subcategoria_choice": "Nivell 4",
                "grup_competicio_choice": "",
                "equip_choice": str(equip.id),
                "extra__modalitat": "Dobles",
            },
        )

        self.assertEqual(response.status_code, 302)
        inscripcio.refresh_from_db()
        self.assertEqual(inscripcio.entitat, "Club A")
        self.assertIsNone(inscripcio.grup_competicio_id)
        self.assertIsNone(inscripcio.grup)
        self.assertIsNone(inscripcio.ordre_competicio)
        self.assertTrue(
            InscripcioEquipAssignacio.objects.filter(
                competicio=self.comp,
                context__code="native",
                inscripcio=inscripcio,
                equip=equip,
            ).exists()
        )

    def test_form_fallback_without_schema_only_uses_basic_fields(self):
        response = self.client.get(self._add_url())
        self.assertEqual(response.status_code, 200)

        form = response.context["form"]
        self.assertEqual(
            set(form.fields.keys()),
            {
                "nom_i_cognoms",
                "entitat_choice",
                "entitat_altres",
                "categoria_choice",
                "categoria_altres",
                "subcategoria_choice",
                "subcategoria_altres",
                "grup_competicio_choice",
                "equip_choice",
                "equip_altres",
            },
        )

    def test_create_form_ignores_requested_context_and_uses_base_assignment(self):
        team_ctx = EquipContext.objects.create(competicio=self.comp, code="finals", nom="Finals")
        existing_team = Equip.objects.create(competicio=self.comp, nom="Equip Base")

        response = self.client.get(self._add_url_with_context(team_ctx.code))

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(response.context["team_context_selected_code"], "native")
        self.assertEqual(form.fields["equip_choice"].label, "Equip (Base)")
        self.assertContains(
            response,
            "Els equips seleccionats en crear una inscripcio sempre s'assignen al context",
        )
        self.assertNotContains(response, 'id="team-context-select"', html=False)

        response = self.client.post(
            self._add_url_with_context(team_ctx.code),
            data={
                "nom_i_cognoms": "Nova contextual",
                "entitat_choice": "",
                "categoria_choice": "",
                "subcategoria_choice": "",
                "grup_competicio_choice": "",
                "equip_choice": str(existing_team.id),
                "team_context": team_ctx.code,
            },
        )

        self.assertEqual(response.status_code, 302)
        inscripcio = Inscripcio.objects.get(competicio=self.comp, nom_i_cognoms="Nova contextual")
        self.assertIsNone(inscripcio.equip_id)

        assignacio = InscripcioEquipAssignacio.objects.get(
            competicio=self.comp,
            context__code="native",
            inscripcio=inscripcio,
        )
        self.assertEqual(assignacio.equip_id, existing_team.id)
        self.assertEqual(assignacio.origen, InscripcioEquipAssignacio.Origen.MANUAL)
        self.assertFalse(
            InscripcioEquipAssignacio.objects.filter(
                competicio=self.comp,
                context=team_ctx,
                inscripcio=inscripcio,
            ).exists()
        )

    def test_edit_form_custom_context_reads_contextual_team_and_shows_native_hint(self):
        native_team = Equip.objects.create(competicio=self.comp, nom="Equip Base")
        contextual_team = Equip.objects.create(competicio=self.comp, nom="Equip Finals")
        base_ctx = self._ensure_native_equip_context(self.comp)
        team_ctx = EquipContext.objects.create(competicio=self.comp, code="finals", nom="Finals")
        inscripcio = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Contextual",
            ordre_sortida=1,
        )
        InscripcioEquipAssignacio.objects.create(
            competicio=self.comp,
            context=base_ctx,
            inscripcio=inscripcio,
            equip=native_team,
        )
        InscripcioEquipAssignacio.objects.create(
            competicio=self.comp,
            context=team_ctx,
            inscripcio=inscripcio,
            equip=contextual_team,
        )

        response = self.client.get(self._edit_url_with_context(inscripcio, team_ctx.code))

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(response.context["team_context_selected_code"], team_ctx.code)
        self.assertEqual(form.fields["equip_choice"].label, "Equip (Finals)")
        self.assertEqual(form["equip_choice"].value(), str(contextual_team.id))
        self.assertEqual(response.context["team_base_hint"], "Equip Base")
        self.assertContains(response, "Aquest formulari assignara l'equip al context")
        self.assertContains(response, "Equip base actual: Equip Base")

    def test_edit_form_custom_context_can_clear_assignment_without_changing_native_team(self):
        native_team = Equip.objects.create(competicio=self.comp, nom="Equip Base")
        contextual_team = Equip.objects.create(competicio=self.comp, nom="Equip Finals")
        base_ctx = self._ensure_native_equip_context(self.comp)
        team_ctx = EquipContext.objects.create(competicio=self.comp, code="finals", nom="Finals")
        inscripcio = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Treu contextual",
            entitat="Club A",
            categoria="Open",
            subcategoria="Nivell 4",
            ordre_sortida=1,
        )
        InscripcioEquipAssignacio.objects.create(
            competicio=self.comp,
            context=base_ctx,
            inscripcio=inscripcio,
            equip=native_team,
        )
        InscripcioEquipAssignacio.objects.create(
            competicio=self.comp,
            context=team_ctx,
            inscripcio=inscripcio,
            equip=contextual_team,
        )

        response = self.client.post(
            self._edit_url_with_context(inscripcio, team_ctx.code),
            data={
                "nom_i_cognoms": "Treu contextual",
                "entitat_choice": "Club A",
                "categoria_choice": "Open",
                "subcategoria_choice": "Nivell 4",
                "grup_competicio_choice": "",
                "equip_choice": "",
                "team_context": team_ctx.code,
            },
        )

        self.assertEqual(response.status_code, 302)
        inscripcio.refresh_from_db()
        self.assertTrue(
            InscripcioEquipAssignacio.objects.filter(
                competicio=self.comp,
                context__code="native",
                inscripcio=inscripcio,
                equip=native_team,
            ).exists()
        )
        self.assertFalse(
            InscripcioEquipAssignacio.objects.filter(
                competicio=self.comp,
                context=team_ctx,
                inscripcio=inscripcio,
            ).exists()
        )

    def test_edit_form_native_can_clear_assignment_without_resolving_legacy_team(self):
        native_team = Equip.objects.create(competicio=self.comp, nom="Equip Base")
        base_ctx = self._ensure_native_equip_context(self.comp)
        inscripcio = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Native clear",
            entitat="Club A",
            categoria="Open",
            subcategoria="Nivell 4",
            equip=native_team,
            ordre_sortida=1,
        )
        InscripcioEquipAssignacio.objects.create(
            competicio=self.comp,
            context=base_ctx,
            inscripcio=inscripcio,
            equip=native_team,
        )

        response = self.client.post(
            self._edit_url(inscripcio),
            data={
                "nom_i_cognoms": "Native clear",
                "entitat_choice": "Club A",
                "categoria_choice": "Open",
                "subcategoria_choice": "Nivell 4",
                "grup_competicio_choice": "",
                "equip_choice": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        inscripcio.refresh_from_db()
        self.assertEqual(inscripcio.equip_id, native_team.id)
        self.assertFalse(
            InscripcioEquipAssignacio.objects.filter(
                competicio=self.comp,
                context__code="native",
                inscripcio=inscripcio,
            ).exists()
        )

        follow_up = self.client.get(self._edit_url(inscripcio))
        self.assertEqual(follow_up.status_code, 200)
        self.assertEqual(follow_up.context["form"]["equip_choice"].value(), "")


class InscripcioAparellExclusioModelTests(_BaseTrampoliDataMixin, TestCase):
    def test_clean_rejects_cross_competition_pair(self):
        comp_a = self._create_competicio("Comp A")
        comp_b = self._create_competicio("Comp B")
        ins = self._create_inscripcio(comp_a, "Participant A")

        app_b = self._create_aparell("DMT_B", "DMT B")
        comp_app_b = self._create_comp_aparell(comp_b, app_b)

        ex = InscripcioAparellExclusio(inscripcio=ins, comp_aparell=comp_app_b)
        with self.assertRaises(ValidationError):
            ex.full_clean()


class InscripcionsSetAparellsViewTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio()
        self.user = self._login_competicio_user(
            self.comp,
            role=CompeticioMembership.Role.EDITOR,
            username_prefix="set_aparells_editor",
        )
        app1 = self._create_aparell("TRAMP_I", "Tramp I")
        app2 = self._create_aparell("TRAMP_II", "Tramp II")

        self.comp_app_1 = self._create_comp_aparell(self.comp, app1, ordre=1, actiu=True)
        self.comp_app_2 = self._create_comp_aparell(self.comp, app2, ordre=2, actiu=True)

        self.ins = self._create_inscripcio(self.comp, "Ginmasta 1")

    def test_set_aparells_creates_and_replaces_exclusions(self):
        url = reverse("inscripcions_set_aparells", kwargs={"pk": self.comp.id})

        r1 = self.client.post(
            url,
            data=json.dumps(
                {
                    "inscripcio_id": self.ins.id,
                    "selected_comp_aparell_ids": [self.comp_app_1.id],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(
            list(
                InscripcioAparellExclusio.objects.filter(inscripcio=self.ins)
                .values_list("comp_aparell_id", flat=True)
            ),
            [self.comp_app_2.id],
        )

        r2 = self.client.post(
            url,
            data=json.dumps(
                {
                    "inscripcio_id": self.ins.id,
                    "selected_comp_aparell_ids": [self.comp_app_1.id, self.comp_app_2.id],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(
            InscripcioAparellExclusio.objects.filter(inscripcio=self.ins).exists()
        )

    def test_set_aparells_rejects_ids_outside_competition(self):
        other_comp = self._create_competicio("Comp Altre")
        other_app = self._create_aparell("TUMB_X", "Tumbling X")
        other_comp_app = self._create_comp_aparell(other_comp, other_app, ordre=1, actiu=True)

        url = reverse("inscripcions_set_aparells", kwargs={"pk": self.comp.id})
        r = self.client.post(
            url,
            data=json.dumps(
                {
                    "inscripcio_id": self.ins.id,
                    "selected_comp_aparell_ids": [self.comp_app_1.id, other_comp_app.id],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)


class InscripcionsMediaFlowTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Media")
        self.ins = self._create_inscripcio(self.comp, "LUCIA POZO SANCHEZ")
        self.ins.entitat = "Collegi Sagrat Cor Diputacio"
        self.ins.subcategoria = "GEN"
        self.ins.sexe = "F"
        self.ins.save(update_fields=["entitat", "subcategoria", "sexe"])

        self.ins_2 = self._create_inscripcio(self.comp, "MARTA LOPEZ", ordre=2, grup=1)
        self.ins_2.entitat = "Club Prova"
        self.ins_2.subcategoria = "GEN"
        self.ins_2.sexe = "F"
        self.ins_2.save(update_fields=["entitat", "subcategoria", "sexe"])

        User = get_user_model()
        self.user = User.objects.create_user(
            username="media_editor_user",
            password="testpass123",
            email="media-editor@example.com",
        )
        CompeticioMembership.objects.create(
            user=self.user,
            competicio=self.comp,
            role=CompeticioMembership.Role.EDITOR,
            is_active=True,
        )
        self.client.force_login(self.user)

    def _upload_media(self, inscripcio_id, filename="track.mp3", content_type="audio/mpeg"):
        url = reverse("inscripcions_media_upload", kwargs={"pk": self.comp.id})
        f = SimpleUploadedFile(filename, b"abc123", content_type=content_type)
        return self.client.post(
            url,
            data={
                "inscripcio_id": inscripcio_id,
                "media_file": f,
            },
        )

    def test_manual_upload_creates_primary_media(self):
        res = self._upload_media(self.ins.id, filename="routine.mp3", content_type="audio/mpeg")
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertTrue(payload.get("ok"))
        self.assertTrue(InscripcioMedia.objects.filter(inscripcio=self.ins).exists())
        item = InscripcioMedia.objects.get(inscripcio=self.ins)
        self.assertEqual(item.source, InscripcioMedia.Source.MANUAL)
        self.assertEqual(item.tipus, InscripcioMedia.Tipus.AUDIO)
        self.assertTrue(item.is_primary)

    def test_set_primary_and_delete_promotes_next_item(self):
        r1 = self._upload_media(self.ins.id, filename="first.mp3")
        self.assertEqual(r1.status_code, 200)
        r2 = self._upload_media(self.ins.id, filename="second.mp3")
        self.assertEqual(r2.status_code, 200)

        first = InscripcioMedia.objects.get(original_filename="first.mp3")
        second = InscripcioMedia.objects.get(original_filename="second.mp3")
        self.assertTrue(first.is_primary)
        self.assertFalse(second.is_primary)

        set_primary_url = reverse("inscripcions_media_set_primary", kwargs={"pk": self.comp.id})
        set_res = self.client.post(
            set_primary_url,
            data=json.dumps({"media_id": second.id}),
            content_type="application/json",
        )
        self.assertEqual(set_res.status_code, 200)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_primary)
        self.assertTrue(second.is_primary)

        delete_url = reverse("inscripcions_media_delete", kwargs={"pk": self.comp.id})
        del_res = self.client.post(
            delete_url,
            data=json.dumps({"media_id": second.id}),
            content_type="application/json",
        )
        self.assertEqual(del_res.status_code, 200)

        self.assertFalse(InscripcioMedia.objects.filter(id=second.id).exists())
        first.refresh_from_db()
        self.assertTrue(first.is_primary)

    def test_assisted_preview_and_apply_creates_assisted_media(self):
        preview_url = reverse("inscripcions_media_match_preview", kwargs={"pk": self.comp.id})
        preview_res = self.client.post(
            preview_url,
            data=json.dumps(
                {
                    "files": [
                        {
                            "key": "0",
                            "filename": "1 - -LUCIA POZO SANCHEZ-Collegi-Sagrat-Cor-Diputacio-GEN-F.mp3",
                            "relative_path": "music/1 - -LUCIA POZO SANCHEZ-Collegi-Sagrat-Cor-Diputacio-GEN-F.mp3",
                            "size": 1234,
                        }
                    ]
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(preview_res.status_code, 200)
        rows = preview_res.json().get("rows", [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("suggested_inscripcio_id"), self.ins.id)

        apply_url = reverse("inscripcions_media_match_apply", kwargs={"pk": self.comp.id})
        media_file = SimpleUploadedFile(
            "1 - -LUCIA POZO SANCHEZ-Collegi-Sagrat-Cor-Diputacio-GEN-F.mp3",
            b"abc123",
            content_type="audio/mpeg",
        )
        apply_res = self.client.post(
            apply_url,
            data={
                "mapping_json": json.dumps(
                    [
                        {
                            "key": "0",
                            "inscripcio_id": self.ins.id,
                            "score": rows[0].get("score"),
                        }
                    ]
                ),
                "file_0": media_file,
            },
        )
        self.assertEqual(apply_res.status_code, 200)
        payload = apply_res.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("created_count"), 1)

        item = InscripcioMedia.objects.get(inscripcio=self.ins)
        self.assertEqual(item.source, InscripcioMedia.Source.ASSISTED)
