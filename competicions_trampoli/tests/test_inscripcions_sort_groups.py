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
from ..models.judging import (
    JudgeConversation,
    JudgeConversationMessage,
    JudgeDeviceToken,
    PublicLiveToken,
)
from ..models.classificacions import ClassificacioConfig, ClassificacioTemplateGlobal
from ..models.rotacions import (
    RotacioAssignacio,
    RotacioAssignacioGrup,
    RotacioAssignacioSerieEquip,
    RotacioEstacio,
    RotacioFranja,
)
from ..models.scoring import (
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
from ..models.competicio import (
    Aparell,
    CompeticioAparell,
    CompeticioAparellEquipContextSource,
    InscripcioAparellExclusio,
)
from ..models import CompeticioMembership
from ..scoring_engine import ScoringEngine
from ..services.inscripcions.groups import renumber_groups_for_competicio
from ..services.inscripcions.sorting import (
    _split_custom_sort_tokens,
    sort_records_by_field_stable,
)
from ..services.inscripcions.history import (
    apply_inscripcions_history_snapshot,
    capture_inscripcions_history_snapshot,
)
from ..services.inscripcions.queries import (
    COLUMN_FILTER_EMPTY_TOKEN,
    _build_inscripcions_filtered_qs,
    _resolve_group_creation_buckets,
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
from ..views.judge.admin import _member_slot_choices, _validate_permission_row
from ..templatetags.competicio_extras import (
    DEFAULT_COMPETITION_BACKGROUND,
    get_competicio_background_url_from_request,
)

from .base import _BaseTrampoliDataMixin


class InscripcionsSortFlowTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = Competicio.objects.create(
            nom="Comp sort flow",
            tipus=Competicio.Tipus.TRAMPOLI,
        )
        User = get_user_model()
        self.user = User.objects.create_user(
            username="sort_editor_user",
            password="testpass123",
            email="sort-editor@example.com",
        )
        self.readonly_user = User.objects.create_user(
            username="sort_readonly_user",
            password="testpass123",
            email="sort-readonly@example.com",
        )
        CompeticioMembership.objects.create(
            user=self.user,
            competicio=self.comp,
            role=CompeticioMembership.Role.EDITOR,
            is_active=True,
        )
        CompeticioMembership.objects.create(
            user=self.readonly_user,
            competicio=self.comp,
            role=CompeticioMembership.Role.READONLY,
            is_active=True,
        )
        self.client.force_login(self.user)

    def _post_json(self, url_name, payload):
        url = reverse(url_name, kwargs={"pk": self.comp.id})
        return self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def _post_history(self, direction):
        url_name = "inscripcions_history_undo" if direction == "undo" else "inscripcions_history_redo"
        url = reverse(url_name, kwargs={"pk": self.comp.id})
        return self.client.post(url, data="{}", content_type="application/json")

    def _toggle_competition_tail(self, enabled, **overrides):
        payload = {
            "enabled": enabled,
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "group_by": [],
        }
        payload.update(overrides)
        return self._post_json("inscripcions_sort_competition_tail_toggle", payload)

    def _groups_payload(self, **overrides):
        payload = {
            "resolution_mode": "auto",
            "strategy": "count",
            "group_count": 1,
            "preview_only": True,
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "group_by": [],
        }
        payload.update(overrides)
        return payload

    def _create_native_team_member(self, team_name, member_name, *, ordre_sortida):
        equip = self._create_equip(self.comp, team_name)
        inscripcio = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms=member_name,
            ordre_sortida=ordre_sortida,
        )
        self._assign_equip(self.comp, inscripcio, equip)
        return equip, inscripcio

    def test_save_birth_year_range_config_persists_and_divides_inscripcions_list(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Participant 2008",
            ordre_sortida=1,
            data_naixement=date(2008, 5, 4),
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Participant 2011",
            ordre_sortida=2,
            data_naixement=date(2011, 2, 10),
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Participant 2013",
            ordre_sortida=3,
            data_naixement=date(2013, 7, 1),
        )

        resp = self._post_json(
            "inscripcions_save_birth_year_range_config",
            {
                "config": {
                    "ranges": [
                        {"label": "Fins 2010-12-31", "until_date": "2010-12-31"},
                        {"label": "2011-01-01 a 2012-12-31", "from_date": "2011-01-01", "until_date": "2012-12-31"},
                        {"label": "Des de 2013-01-01", "from_date": "2013-01-01"},
                    ],
                    "sense_data_label": "Sense data",
                    "fora_rang_label": "Fora de forquilla",
                }
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))

        self.comp.refresh_from_db()
        saved_cfg = (
            (self.comp.inscripcions_view.get("derived_group_config") or {})
            .get("any_naixement_forquilla")
            or {}
        )
        self.assertEqual(
            saved_cfg.get("ranges"),
            [
                {"label": "Fins 2010-12-31", "from_date": None, "until_date": "2010-12-31"},
                {"label": "2011-01-01 a 2012-12-31", "from_date": "2011-01-01", "until_date": "2012-12-31"},
                {"label": "Des de 2013-01-01", "from_date": "2013-01-01", "until_date": None},
            ],
        )

        response = self.client.get(
            reverse("inscripcions_list", kwargs={"pk": self.comp.id}),
            {"group_by": ["any_naixement_forquilla"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [tab.get("label") for tab in (response.context.get("tabs") or [])],
            ["Fins 2010-12-31", "2011-01-01 a 2012-12-31", "Des de 2013-01-01"],
        )

    def test_save_birth_year_range_config_rejects_overlapping_ranges(self):
        resp = self._post_json(
            "inscripcions_save_birth_year_range_config",
            {
                "config": {
                    "ranges": [
                        {"label": "Fins 2010-12-31", "until_date": "2010-12-31"},
                        {"label": "2010-06-01 a 2012-12-31", "from_date": "2010-06-01", "until_date": "2012-12-31"},
                    ]
                }
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("solapament", resp.content.decode("utf-8").lower())

    def test_save_birth_year_range_config_rejects_range_without_any_limit(self):
        resp = self._post_json(
            "inscripcions_save_birth_year_range_config",
            {
                "config": {
                    "ranges": [
                        {"label": "Sense limits"},
                    ]
                }
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("cal indicar data inici", resp.content.decode("utf-8").lower())

    def test_groups_preview_uses_saved_birth_year_ranges_as_tabs_layer(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Participant 2008",
            ordre_sortida=1,
            data_naixement=date(2008, 5, 4),
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Participant 2011",
            ordre_sortida=2,
            data_naixement=date(2011, 2, 10),
            grup=None,
        )

        save_resp = self._post_json(
            "inscripcions_save_birth_year_range_config",
            {
                "config": {
                    "ranges": [
                        {"label": "Fins 2010-12-31", "until_date": "2010-12-31"},
                        {"label": "Des de 2011-01-01", "from_date": "2011-01-01"},
                    ]
                }
            },
        )
        self.assertEqual(save_resp.status_code, 200)

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(
                strategy="per_bucket",
                group_by=["any_naixement_forquilla"],
            ),
        )
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertEqual(data.get("layers_used"), ["tabs"])
        self.assertEqual(data.get("effective_bucket_count"), 2)
        groups = (data.get("preview") or {}).get("groups") or []
        self.assertEqual(
            [group.get("suggested_name") for group in groups],
            ["Fins 2010-12-31", "Des de 2011-01-01"],
        )

    def test_legacy_birth_year_range_config_is_exposed_as_dates_and_still_groups(self):
        self.comp.inscripcions_view = {
            "derived_group_config": {
                "any_naixement_forquilla": {
                    "ranges": [
                        {"label": "2007-2009", "from_year": 2007, "to_year": 2009},
                        {"label": "2010-2012", "from_year": 2010, "to_year": 2012},
                    ],
                    "sense_data_label": "Sense data",
                    "fora_rang_label": "Fora de forquilla",
                }
            }
        }
        self.comp.save(update_fields=["inscripcions_view"])

        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Participant 2008",
            ordre_sortida=1,
            data_naixement=date(2008, 5, 4),
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Participant 2011",
            ordre_sortida=2,
            data_naixement=date(2011, 2, 10),
        )

        response = self.client.get(
            reverse("inscripcions_list", kwargs={"pk": self.comp.id}),
            {"group_by": ["any_naixement_forquilla"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["birth_year_range_group_config"]["ranges"],
            [
                {"label": "2007-2009", "from_date": "2007-01-01", "until_date": "2009-12-31"},
                {"label": "2010-2012", "from_date": "2010-01-01", "until_date": "2012-12-31"},
            ],
        )
        self.assertEqual(
            [tab.get("label") for tab in (response.context.get("tabs") or [])],
            ["2007-2009", "2010-2012"],
        )

    def test_inscripcions_list_group_column_uses_group_label_with_fallbacks(self):
        named_group = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Participant Final",
            grup=2,
            ordre_sortida=1,
        )
        fallback_group = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Participant Grup 3",
            grup=3,
            ordre_sortida=2,
        )
        no_group = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Participant Sense Grup",
            ordre_sortida=3,
        )

        group = GrupCompeticio.objects.get(competicio=self.comp, display_num=2)
        group.nom = "Final"
        group.save(update_fields=["nom"])

        self.comp.inscripcions_view = {
            "table_columns": ["nom_i_cognoms", "grup"],
        }
        self.comp.save(update_fields=["inscripcions_view"])

        response = self.client.get(reverse("inscripcions_list", kwargs={"pk": self.comp.id}))
        self.assertEqual(response.status_code, 200)

        body = response.content.decode("utf-8")
        self.assertRegex(
            body,
            re.compile(
                r"Participant Final.*?<td class=\"[^\"]*\">\s*Final\s*</td>",
                re.S,
            ),
        )
        self.assertRegex(
            body,
            re.compile(
                r"Participant Grup 3.*?<td class=\"[^\"]*\">\s*Grup 3\s*</td>",
                re.S,
            ),
        )
        self.assertRegex(
            body,
            re.compile(
                r"Participant Sense Grup.*?<td class=\"[^\"]*\">\s*-\s*</td>",
                re.S,
            ),
        )

    def test_inscripcions_list_renders_explicit_sort_scope_labels(self):
        response = self.client.get(reverse("inscripcions_list", kwargs={"pk": self.comp.id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Totes les inscripcions filtrades")
        self.assertContains(response, "Dins de cada pestanya activa")
        self.assertContains(response, "Dins de cada grup")
        self.assertContains(response, "Nomes un grup numeric concret")
        self.assertContains(response, "incloent membres fora del filtre actual")

    def test_inscripcions_list_hides_show_real_order_button_but_keeps_other_group_actions(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Participant Grup 1",
            grup=1,
            ordre_sortida=1,
        )

        response = self.client.get(reverse("inscripcions_list", kwargs={"pk": self.comp.id}))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Mostrar ordre real")
        self.assertContains(response, "Veure ordre competició")
        self.assertContains(response, "Desar ordre competició")

    def test_inscripcions_list_renders_competition_order_tail_toggle_state(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alpha",
            grup=1,
            ordre_sortida=1,
            ordre_competicio=2,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Beta",
            grup=1,
            ordre_sortida=2,
            ordre_competicio=1,
        )

        apply_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "nom_i_cognoms",
                "sort_dir": "asc",
                "scope": "all_groups",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(apply_resp.status_code, 200)
        self.assertTrue(apply_resp.json().get("ok"))
        self.assertTrue(apply_resp.json().get("competition_order_tail"))

        response = self.client.get(reverse("inscripcions_list", kwargs={"pk": self.comp.id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ordre de competici")
        self.assertContains(response, "Criteri final actiu")

    def test_inscripcions_list_renders_unified_groups_panel(self):
        response = self.client.get(reverse("inscripcions_list", kwargs={"pk": self.comp.id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="groups-workspace-shell"')
        self.assertContains(response, "Divisions actives:")
        self.assertContains(response, "Ordenacions detectades:")
        self.assertContains(response, "Resolucio final:")
        self.assertNotContains(response, "Base de creacio:")
        self.assertNotContains(response, "Crear grups per pestanyes")
        self.assertNotContains(response, "Crear grups per ordenacio")

    def test_sort_context_key_changes_when_column_filters_change(self):
        base_filters = {
            "q": "",
            "categoria": "",
            "subcategoria": "",
            "entitat": "",
            "column_filters": {"categoria": ["Alevi"]},
        }
        other_filters = {
            **base_filters,
            "column_filters": {"categoria": ["Infantil"]},
        }

        key_a = build_inscripcions_sort_context_key(self.comp.id, filters=base_filters, group_by=[])
        key_b = build_inscripcions_sort_context_key(self.comp.id, filters=other_filters, group_by=[])

        self.assertNotEqual(key_a, key_b)

    def test_build_filtered_qs_supports_multiple_column_filters_with_extra_values(self):
        self.comp.inscripcions_schema = {
            "columns": [
                {"code": "modalitat", "label": "Modalitat", "kind": "extra"},
            ]
        }
        self.comp.save(update_fields=["inscripcions_schema"])

        keep_1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi Solo",
            categoria="Alevi",
            ordre_sortida=1,
            extra={"modalitat": "Solo"},
        )
        keep_2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Infantil Solo",
            categoria="Infantil",
            ordre_sortida=2,
            extra={"modalitat": "Solo"},
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi Duo",
            categoria="Alevi",
            ordre_sortida=3,
            extra={"modalitat": "Duo"},
        )

        qs = _build_inscripcions_filtered_qs(
            self.comp,
            {
                "q": "",
                "categoria": "",
                "subcategoria": "",
                "entitat": "",
                "column_filters": {
                    "categoria": ["Alevi", "Infantil"],
                    "modalitat": ["Solo"],
                },
            },
        )

        self.assertEqual(
            list(qs.order_by("ordre_sortida", "id").values_list("id", flat=True)),
            [keep_1.id, keep_2.id],
        )

    def test_build_filtered_qs_supports_equip_and_empty_token(self):
        equip, keep = self._create_native_team_member("Equip Base", "Amb equip", ordre_sortida=1)
        empty = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Sense equip",
            ordre_sortida=2,
        )

        team_qs = _build_inscripcions_filtered_qs(
            self.comp,
            {
                "q": "",
                "categoria": "",
                "subcategoria": "",
                "entitat": "",
                "column_filters": {"equip": [str(equip.id)]},
            },
        )
        empty_qs = _build_inscripcions_filtered_qs(
            self.comp,
            {
                "q": "",
                "categoria": "",
                "subcategoria": "",
                "entitat": "",
                "column_filters": {"equip": [COLUMN_FILTER_EMPTY_TOKEN]},
            },
        )

        self.assertEqual(list(team_qs.values_list("id", flat=True)), [keep.id])
        self.assertEqual(list(empty_qs.values_list("id", flat=True)), [empty.id])

    def test_filter_values_endpoint_excludes_self_filter_and_marks_selected_tokens(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi A",
            categoria="Alevi",
            entitat="Club A",
            ordre_sortida=1,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Infantil A",
            categoria="Infantil",
            entitat="Club A",
            ordre_sortida=2,
        )

        response = self._post_json(
            "inscripcions_filter_values",
            {
                "column_code": "categoria",
                "filters": {
                    "q": "",
                    "categoria": "",
                    "subcategoria": "",
                    "entitat": "Club A",
                    "column_filters": {"categoria": ["Alevi"]},
                },
                "group_by": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("column_code"), "categoria")
        values = data.get("values") or []
        labels = [row.get("label") for row in values]
        self.assertIn("Alevi", labels)
        self.assertIn("Infantil", labels)
        selected = {
            row.get("token"): row.get("selected")
            for row in values
        }
        self.assertTrue(selected.get("Alevi"))

    def test_filter_values_endpoint_returns_empty_option(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Sense subcategoria",
            subcategoria="",
            ordre_sortida=1,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Amb subcategoria",
            subcategoria="Open",
            ordre_sortida=2,
        )

        response = self._post_json(
            "inscripcions_filter_values",
            {
                "column_code": "subcategoria",
                "filters": {
                    "q": "",
                    "categoria": "",
                    "subcategoria": "",
                    "entitat": "",
                    "column_filters": {},
                },
                "group_by": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        values = response.json().get("values") or []
        tokens = [row.get("token") for row in values]
        self.assertIn(COLUMN_FILTER_EMPTY_TOKEN, tokens)

    def test_sort_apply_tab_preserves_tab_block_order(self):
        beta_1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="David",
            categoria="Beta",
            ordre_sortida=1,
        )
        beta_2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Carla",
            categoria="Beta",
            ordre_sortida=2,
        )
        alpha_1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Biel",
            categoria="Alpha",
            ordre_sortida=3,
        )
        alpha_2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Anna",
            categoria="Alpha",
            ordre_sortida=4,
        )

        response = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "nom_i_cognoms",
                "sort_dir": "asc",
                "scope": "tab",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("ok"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [beta_2.id, beta_1.id, alpha_2.id, alpha_1.id])

    def test_sort_apply_all_can_reorder_tab_blocks(self):
        beta_1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="David",
            categoria="Beta",
            ordre_sortida=1,
        )
        beta_2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Carla",
            categoria="Beta",
            ordre_sortida=2,
        )
        alpha_1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Biel",
            categoria="Alpha",
            ordre_sortida=3,
        )
        alpha_2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Anna",
            categoria="Alpha",
            ordre_sortida=4,
        )

        response = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "nom_i_cognoms",
                "sort_dir": "asc",
                "scope": "all",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("ok"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [alpha_2.id, alpha_1.id, beta_2.id, beta_1.id])

    def test_sort_apply_group_reorders_full_group_even_outside_filter(self):
        visible = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Zulu",
            entitat="Club A",
            ordre_sortida=1,
            grup=1,
        )
        hidden = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alpha",
            entitat="Club B",
            ordre_sortida=2,
            grup=1,
        )
        other = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Resta",
            ordre_sortida=3,
            grup=2,
        )

        response = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "nom_i_cognoms",
                "sort_dir": "asc",
                "scope": "group",
                "group_num": 1,
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": "Club A"},
                "group_by": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("ok"))

        visible.refresh_from_db()
        hidden.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(hidden.ordre_sortida, 1)
        self.assertEqual(visible.ordre_sortida, 2)
        self.assertEqual(other.ordre_sortida, 3)

    def test_sort_apply_all_groups_reorders_full_visible_groups_only(self):
        g1_visible = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Zulu",
            entitat="Club A",
            ordre_sortida=1,
            grup=1,
        )
        g1_hidden = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alpha",
            entitat="Club B",
            ordre_sortida=2,
            grup=1,
        )
        g2_visible = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Yara",
            entitat="Club A",
            ordre_sortida=3,
            grup=2,
        )
        g2_hidden = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Beta",
            entitat="Club B",
            ordre_sortida=4,
            grup=2,
        )
        g3_first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Omega",
            entitat="Club C",
            ordre_sortida=5,
            grup=3,
        )
        g3_second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Gamma",
            entitat="Club D",
            ordre_sortida=6,
            grup=3,
        )

        response = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "nom_i_cognoms",
                "sort_dir": "asc",
                "scope": "all_groups",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": "Club A"},
                "group_by": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("ok"))

        g1_visible.refresh_from_db()
        g1_hidden.refresh_from_db()
        g2_visible.refresh_from_db()
        g2_hidden.refresh_from_db()
        g3_first.refresh_from_db()
        g3_second.refresh_from_db()

        self.assertEqual(g1_hidden.ordre_sortida, 1)
        self.assertEqual(g1_visible.ordre_sortida, 2)
        self.assertEqual(g2_hidden.ordre_sortida, 3)
        self.assertEqual(g2_visible.ordre_sortida, 4)
        self.assertEqual(g3_first.ordre_sortida, 5)
        self.assertEqual(g3_second.ordre_sortida, 6)

    def test_group_competition_order_preview_returns_saved_order_for_full_group(self):
        first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Participant 1",
            entitat="Club A",
            grup=2,
            ordre_sortida=1,
        )
        second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Participant 2",
            entitat="Club B",
            grup=2,
            ordre_sortida=2,
        )
        third = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Participant 3",
            entitat="Club C",
            grup=2,
            ordre_sortida=3,
        )
        group = GrupCompeticio.objects.get(competicio=self.comp, display_num=2)
        group.nom = "Final"
        group.save(update_fields=["nom"])
        Inscripcio.objects.filter(pk=first.pk).update(ordre_competicio=2)
        Inscripcio.objects.filter(pk=second.pk).update(ordre_competicio=1)
        Inscripcio.objects.filter(pk=third.pk).update(ordre_competicio=3)

        response = self._post_json(
            "inscripcions_group_competition_order_preview",
            {"group_num": 2},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("group_label"), "Final")
        self.assertEqual(data.get("total_count"), 3)
        self.assertTrue(data.get("can_edit"))
        self.assertEqual(
            data.get("rows"),
            [
                {
                    "id": second.id,
                    "label": "Participant 2",
                    "secondary_label": "Club B",
                    "saved_order": 1,
                },
                {
                    "id": first.id,
                    "label": "Participant 1",
                    "secondary_label": "Club A",
                    "saved_order": 2,
                },
                {
                    "id": third.id,
                    "label": "Participant 3",
                    "secondary_label": "Club C",
                    "saved_order": 3,
                },
            ],
        )

    def test_group_competition_order_preview_falls_back_to_group_number_when_unnamed(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Sense nom de grup",
            grup=3,
            ordre_sortida=1,
        )

        response = self._post_json(
            "inscripcions_group_competition_order_preview",
            {"group_num": 3},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("group_label"), "Grup 3")

    def test_group_competition_order_preview_allows_readonly_and_save_remains_protected(self):
        first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Readonly 1",
            grup=1,
            ordre_sortida=1,
        )
        second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Readonly 2",
            grup=1,
            ordre_sortida=2,
        )

        self.client.force_login(self.readonly_user)

        preview_res = self._post_json(
            "inscripcions_group_competition_order_preview",
            {"group_num": 1},
        )
        self.assertEqual(preview_res.status_code, 200)
        self.assertFalse(preview_res.json().get("can_edit"))

        save_url = reverse("inscripcions_save_group_competition_order", kwargs={"pk": self.comp.id})
        save_res = self.client.post(
            save_url,
            data=json.dumps({"group_num": 1, "ids": [second.id, first.id]}),
            content_type="application/json",
        )
        self.assertEqual(save_res.status_code, 403)

    def test_sort_apply_reapplying_existing_criterion_keeps_priority(self):
        i1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I1",
            entitat="B",
            categoria="beta",
            ordre_sortida=1,
        )
        i2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I2",
            entitat="A",
            categoria="alpha",
            ordre_sortida=2,
        )
        i3 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I3",
            entitat="A",
            categoria="beta",
            ordre_sortida=3,
        )
        i4 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I4",
            entitat="B",
            categoria="alpha",
            ordre_sortida=4,
        )

        base_payload = {
            "scope": "all",
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "group_by": [],
        }

        r1 = self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "entitat", "sort_dir": "asc"},
        )
        self.assertEqual(r1.status_code, 200)
        self.assertTrue(r1.json().get("ok"))

        r2 = self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "categoria", "sort_dir": "asc"},
        )
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json().get("ok"))

        # Reapliquem el primer criteri amb una direccio diferent.
        # Ha de mantenir la prioritat original (primer criteri = mes important).
        r3 = self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "entitat", "sort_dir": "desc"},
        )
        self.assertEqual(r3.status_code, 200)
        self.assertTrue(r3.json().get("ok"))
        self.assertEqual(r3.json().get("stack_count"), 2)

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [i4.id, i1.id, i2.id, i3.id])

    def test_custom_sort_save_reapplies_active_stack_immediately(self):
        i1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I1",
            categoria="B",
            ordre_sortida=1,
        )
        i2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I2",
            categoria="C",
            ordre_sortida=2,
        )
        i3 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I3",
            categoria="A",
            ordre_sortida=3,
        )

        base_payload = {
            "scope": "all",
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "group_by": [],
        }

        r_apply = self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "categoria", "sort_dir": "custom"},
        )
        self.assertEqual(r_apply.status_code, 200)
        self.assertTrue(r_apply.json().get("ok"))

        r_custom = self._post_json(
            "inscripcions_sort_custom_save",
            {
                "sort_key": "categoria",
                "order": ["C", "B", "A"],
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
                "preserve_missing_context": True,
            },
        )
        self.assertEqual(r_custom.status_code, 200)
        data = r_custom.json()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("reapplied"))
        self.assertEqual(data.get("stack_count"), 1)

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [i2.id, i1.id, i3.id])

    def test_competition_order_tail_toggle_requires_active_stack(self):
        first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alpha",
            grup=1,
            ordre_sortida=1,
            ordre_competicio=2,
        )
        second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Beta",
            grup=1,
            ordre_sortida=2,
            ordre_competicio=1,
        )

        response = self._toggle_competition_tail(True)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertFalse(data.get("applied"))
        self.assertEqual(data.get("reason"), "no_stack")
        self.assertFalse(data.get("competition_order_tail"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [first.id, second.id])

    def test_competition_order_tail_is_less_prioritary_than_active_stack(self):
        g1_first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alpha",
            grup=1,
            ordre_sortida=1,
            ordre_competicio=2,
        )
        g1_second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Beta",
            grup=1,
            ordre_sortida=2,
            ordre_competicio=1,
        )
        g2_first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Charlie",
            grup=2,
            ordre_sortida=3,
            ordre_competicio=2,
        )
        g2_second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Delta",
            grup=2,
            ordre_sortida=4,
            ordre_competicio=1,
        )

        apply_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "nom_i_cognoms",
                "sort_dir": "asc",
                "scope": "all_groups",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(apply_resp.status_code, 200)
        data = apply_resp.json()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("competition_order_tail"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [g1_first.id, g1_second.id, g2_first.id, g2_second.id])

    def test_sort_apply_enables_competition_order_tail_by_default(self):
        g1_first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alpha",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=1,
            ordre_competicio=2,
        )
        g1_second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Beta",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=2,
            ordre_competicio=1,
        )
        g2_first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Charlie",
            categoria="Mateixa",
            grup=2,
            ordre_sortida=3,
            ordre_competicio=2,
        )
        g2_second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Delta",
            categoria="Mateixa",
            grup=2,
            ordre_sortida=4,
            ordre_competicio=1,
        )

        apply_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "categoria",
                "sort_dir": "asc",
                "scope": "all_groups",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(apply_resp.status_code, 200)
        data = apply_resp.json()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("competition_order_tail"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [g1_second.id, g1_first.id, g2_second.id, g2_first.id])

    def test_competition_order_tail_toggle_applies_and_persists_to_ordre_sortida(self):
        g1_first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alpha",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=1,
            ordre_competicio=2,
        )
        g1_second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Beta",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=2,
            ordre_competicio=1,
        )
        g2_first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Charlie",
            categoria="Mateixa",
            grup=2,
            ordre_sortida=3,
            ordre_competicio=2,
        )
        g2_second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Delta",
            categoria="Mateixa",
            grup=2,
            ordre_sortida=4,
            ordre_competicio=1,
        )

        apply_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "categoria",
                "sort_dir": "asc",
                "scope": "all_groups",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(apply_resp.status_code, 200)
        self.assertTrue(apply_resp.json().get("ok"))

        toggle_resp = self._toggle_competition_tail(True)
        self.assertEqual(toggle_resp.status_code, 200)
        data = toggle_resp.json()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("applied"))
        self.assertTrue(data.get("competition_order_tail"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [g1_second.id, g1_first.id, g2_second.id, g2_first.id])

    def test_competition_order_tail_toggle_disable_restores_stack_only_order(self):
        g1_first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alpha",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=1,
            ordre_competicio=2,
        )
        g1_second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Beta",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=2,
            ordre_competicio=1,
        )
        g2_first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Charlie",
            categoria="Mateixa",
            grup=2,
            ordre_sortida=3,
            ordre_competicio=2,
        )
        g2_second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Delta",
            categoria="Mateixa",
            grup=2,
            ordre_sortida=4,
            ordre_competicio=1,
        )

        apply_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "categoria",
                "sort_dir": "asc",
                "scope": "all_groups",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(apply_resp.status_code, 200)
        self.assertTrue(apply_resp.json().get("ok"))

        toggle_on_resp = self._toggle_competition_tail(True)
        self.assertEqual(toggle_on_resp.status_code, 200)
        self.assertTrue(toggle_on_resp.json().get("competition_order_tail"))

        disable_resp = self._toggle_competition_tail(False)
        self.assertEqual(disable_resp.status_code, 200)
        data = disable_resp.json()
        self.assertTrue(data.get("ok"))
        self.assertFalse(data.get("competition_order_tail"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [g1_first.id, g1_second.id, g2_first.id, g2_second.id])

    def test_competition_order_tail_manual_disable_is_respected_on_next_sort_apply(self):
        g1_first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alpha",
            categoria="Mateixa",
            subcategoria="Compartida",
            grup=1,
            ordre_sortida=1,
            ordre_competicio=2,
        )
        g1_second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Beta",
            categoria="Mateixa",
            subcategoria="Compartida",
            grup=1,
            ordre_sortida=2,
            ordre_competicio=1,
        )
        g2_first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Charlie",
            categoria="Mateixa",
            subcategoria="Compartida",
            grup=2,
            ordre_sortida=3,
            ordre_competicio=2,
        )
        g2_second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Delta",
            categoria="Mateixa",
            subcategoria="Compartida",
            grup=2,
            ordre_sortida=4,
            ordre_competicio=1,
        )

        first_apply = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "categoria",
                "sort_dir": "asc",
                "scope": "all_groups",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(first_apply.status_code, 200)
        self.assertTrue(first_apply.json().get("competition_order_tail"))

        disable_resp = self._toggle_competition_tail(False)
        self.assertEqual(disable_resp.status_code, 200)
        self.assertFalse(disable_resp.json().get("competition_order_tail"))

        second_apply = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "subcategoria",
                "sort_dir": "asc",
                "scope": "all_groups",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(second_apply.status_code, 200)
        data = second_apply.json()
        self.assertTrue(data.get("ok"))
        self.assertFalse(data.get("competition_order_tail"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [g1_first.id, g1_second.id, g2_first.id, g2_second.id])

    def test_competition_order_tail_places_missing_saved_order_last_and_stable(self):
        first_missing = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alpha",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=1,
        )
        second_with = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Beta",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=2,
            ordre_competicio=2,
        )
        third_with = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Charlie",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=3,
            ordre_competicio=1,
        )
        second_missing = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Delta",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=4,
        )
        Inscripcio.objects.filter(pk__in=[first_missing.pk, second_missing.pk]).update(
            ordre_competicio=None
        )

        apply_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "categoria",
                "sort_dir": "asc",
                "scope": "all_groups",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(apply_resp.status_code, 200)
        self.assertTrue(apply_resp.json().get("ok"))

        toggle_resp = self._toggle_competition_tail(True)
        self.assertEqual(toggle_resp.status_code, 200)
        self.assertTrue(toggle_resp.json().get("competition_order_tail"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(
            actual_ids,
            [third_with.id, second_with.id, first_missing.id, second_missing.id],
        )

    def test_sort_clear_resets_competition_order_tail_flag(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alpha",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=1,
            ordre_competicio=2,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Beta",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=2,
            ordre_competicio=1,
        )

        apply_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "categoria",
                "sort_dir": "asc",
                "scope": "all_groups",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(apply_resp.status_code, 200)
        self.assertTrue(apply_resp.json().get("ok"))
        self.assertTrue(self._toggle_competition_tail(True).json().get("competition_order_tail"))

        clear_resp = self._post_json(
            "inscripcions_sort_clear",
            {
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(clear_resp.status_code, 200)
        data = clear_resp.json()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("cleared"))
        self.assertFalse(data.get("competition_order_tail"))

    def test_competition_order_tail_applies_independently_per_group(self):
        g1_first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Anna",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=1,
            ordre_competicio=2,
        )
        g2_first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Biel",
            categoria="Mateixa",
            grup=2,
            ordre_sortida=2,
            ordre_competicio=2,
        )
        g1_second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Carla",
            categoria="Mateixa",
            grup=1,
            ordre_sortida=3,
            ordre_competicio=1,
        )
        g2_second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="David",
            categoria="Mateixa",
            grup=2,
            ordre_sortida=4,
            ordre_competicio=1,
        )

        apply_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "categoria",
                "sort_dir": "asc",
                "scope": "all",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(apply_resp.status_code, 200)
        self.assertTrue(apply_resp.json().get("ok"))

        toggle_resp = self._toggle_competition_tail(True)
        self.assertEqual(toggle_resp.status_code, 200)
        self.assertTrue(toggle_resp.json().get("competition_order_tail"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [g1_second.id, g2_second.id, g1_first.id, g2_first.id])

    def test_custom_sort_save_does_not_reapply_if_mode_is_not_custom(self):
        i1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I1",
            categoria="B",
            ordre_sortida=1,
        )
        i2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I2",
            categoria="C",
            ordre_sortida=2,
        )
        i3 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I3",
            categoria="A",
            ordre_sortida=3,
        )

        base_payload = {
            "scope": "all",
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "group_by": [],
        }

        r_apply = self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "categoria", "sort_dir": "asc"},
        )
        self.assertEqual(r_apply.status_code, 200)
        self.assertTrue(r_apply.json().get("ok"))

        after_apply_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(after_apply_ids, [i3.id, i1.id, i2.id])

        r_custom = self._post_json(
            "inscripcions_sort_custom_save",
            {
                "sort_key": "categoria",
                "order": ["C", "B", "A"],
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
                "preserve_missing_context": True,
            },
        )
        self.assertEqual(r_custom.status_code, 200)
        data = r_custom.json()
        self.assertTrue(data.get("ok"))
        self.assertFalse(data.get("reapplied"))
        self.assertEqual(data.get("reapplied_updated"), 0)

        after_custom_save_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(after_custom_save_ids, [i3.id, i1.id, i2.id])

    def test_custom_sort_values_for_group_use_named_labels(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="G1",
            grup=2,
            ordre_sortida=1,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="G2",
            grup=2,
            ordre_sortida=2,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="G3",
            grup=3,
            ordre_sortida=3,
        )
        group = GrupCompeticio.objects.get(competicio=self.comp, display_num=2)
        group.nom = "Final"
        group.save(update_fields=["nom"])

        response = self._post_json(
            "inscripcions_sort_custom_values",
            {
                "sort_key": "grup",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))

        values_by_token = {str(item["value"]): item for item in data.get("values", [])}
        self.assertEqual(values_by_token["2"]["label"], "Final")
        self.assertEqual(values_by_token["2"]["count"], 2)
        self.assertEqual(values_by_token["3"]["label"], "Grup 3")

    def test_custom_sort_values_for_equip_use_team_names_and_skip_empty(self):
        equip, _first = self._create_native_team_member("Equip Alpha", "E1", ordre_sortida=1)
        second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="E2",
            ordre_sortida=2,
        )
        self._assign_equip(self.comp, second, equip)
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Sense equip",
            ordre_sortida=3,
        )

        response = self._post_json(
            "inscripcions_sort_custom_values",
            {
                "sort_key": "equip",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(
            data.get("values"),
            [
                {
                    "value": str(equip.id),
                    "label": "Equip Alpha",
                    "count": 2,
                    "detected": True,
                    "in_custom": False,
                }
            ],
        )

    def test_equip_sort_apply_uses_team_name_for_fallback(self):
        equip_beta, ins_beta = self._create_native_team_member("Beta", "Beta 1", ordre_sortida=1)
        equip_alpha, ins_alpha = self._create_native_team_member("Alpha", "Alpha 1", ordre_sortida=2)

        response = self._post_json(
            "inscripcions_sort_apply",
            {
                "sort_key": "equip",
                "sort_dir": "asc",
                "scope": "all",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("ok"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [ins_alpha.id, ins_beta.id])

    def test_equip_custom_sort_save_reapplies_active_stack_immediately(self):
        equip_alpha, ins_alpha = self._create_native_team_member("Alpha", "Alpha 1", ordre_sortida=1)
        equip_beta, ins_beta = self._create_native_team_member("Beta", "Beta 1", ordre_sortida=2)

        base_payload = {
            "scope": "all",
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "group_by": [],
        }

        r_apply = self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "equip", "sort_dir": "custom"},
        )
        self.assertEqual(r_apply.status_code, 200)
        self.assertTrue(r_apply.json().get("ok"))

        r_custom = self._post_json(
            "inscripcions_sort_custom_save",
            {
                "sort_key": "equip",
                "order": [str(equip_beta.id), str(equip_alpha.id)],
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
                "preserve_missing_context": True,
            },
        )
        self.assertEqual(r_custom.status_code, 200)
        data = r_custom.json()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("reapplied"))
        self.assertEqual(data.get("stack_count"), 1)

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [ins_beta.id, ins_alpha.id])

    def test_equip_custom_order_survives_team_rename(self):
        equip_alpha, ins_alpha = self._create_native_team_member("Alpha", "Alpha 1", ordre_sortida=1)
        equip_beta, ins_beta = self._create_native_team_member("Beta", "Beta 1", ordre_sortida=2)

        base_payload = {
            "scope": "all",
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "group_by": [],
        }

        self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "equip", "sort_dir": "custom"},
        )
        save_resp = self._post_json(
            "inscripcions_sort_custom_save",
            {
                "sort_key": "equip",
                "order": [str(equip_beta.id), str(equip_alpha.id)],
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
                "preserve_missing_context": True,
            },
        )
        self.assertEqual(save_resp.status_code, 200)
        self.assertTrue(save_resp.json().get("ok"))

        equip_alpha.nom = "Alfa"
        equip_alpha.save(update_fields=["nom"])
        equip_beta.nom = "Zeta"
        equip_beta.save(update_fields=["nom"])

        asc_resp = self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "equip", "sort_dir": "asc"},
        )
        self.assertEqual(asc_resp.status_code, 200)
        self.assertTrue(asc_resp.json().get("ok"))

        custom_resp = self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "equip", "sort_dir": "custom"},
        )
        self.assertEqual(custom_resp.status_code, 200)
        self.assertTrue(custom_resp.json().get("ok"))

        actual_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(actual_ids, [ins_beta.id, ins_alpha.id])

    def test_history_undo_redo_restores_sort_apply(self):
        i1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I1",
            entitat="B",
            ordre_sortida=1,
        )
        i2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I2",
            entitat="A",
            ordre_sortida=2,
        )
        base_payload = {
            "scope": "all",
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "group_by": [],
        }

        r_apply = self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "entitat", "sort_dir": "asc"},
        )
        self.assertEqual(r_apply.status_code, 200)
        self.assertTrue(r_apply.json().get("ok"))

        ordered_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(ordered_ids, [i2.id, i1.id])

        r_undo = self._post_history("undo")
        self.assertEqual(r_undo.status_code, 200)
        self.assertTrue(r_undo.json().get("ok"))
        self.assertTrue(r_undo.json().get("applied"))

        undone_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(undone_ids, [i1.id, i2.id])

        r_redo = self._post_history("redo")
        self.assertEqual(r_redo.status_code, 200)
        self.assertTrue(r_redo.json().get("ok"))
        self.assertTrue(r_redo.json().get("applied"))

        redone_ids = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(redone_ids, [i2.id, i1.id])

    def test_history_new_action_clears_redo_branch(self):
        i1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I1",
            entitat="B",
            ordre_sortida=1,
        )
        i2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I2",
            entitat="A",
            ordre_sortida=2,
        )
        base_payload = {
            "scope": "all",
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "group_by": [],
        }
        self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "entitat", "sort_dir": "asc"},
        )
        self._post_history("undo")

        r_reorder = self._post_json(
            "inscripcions_reorder",
            {
                "ids": [i2.id, i1.id],
                "moved_id": i2.id,
                "new_index": 0,
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(r_reorder.status_code, 200)
        self.assertTrue(r_reorder.json().get("ok"))
        self.assertFalse(r_reorder.json().get("history", {}).get("can_redo"))

        r_redo = self._post_history("redo")
        self.assertEqual(r_redo.status_code, 200)
        self.assertTrue(r_redo.json().get("ok"))
        self.assertFalse(r_redo.json().get("applied"))

    def test_sort_undo_compat_wrapper_uses_global_history(self):
        i1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I1",
            entitat="B",
            ordre_sortida=1,
        )
        i2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I2",
            entitat="A",
            ordre_sortida=2,
        )
        base_payload = {
            "scope": "all",
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "group_by": [],
        }
        self._post_json(
            "inscripcions_sort_apply",
            {**base_payload, "sort_key": "entitat", "sort_dir": "asc"},
        )

        r_compat = self._post_json(
            "inscripcions_sort_undo",
            {"filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""}, "group_by": []},
        )
        self.assertEqual(r_compat.status_code, 200)
        data = r_compat.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("restored"), 1)

        ids_after = list(
            Inscripcio.objects.filter(competicio=self.comp)
            .order_by("ordre_sortida", "id")
            .values_list("id", flat=True)
        )
        self.assertEqual(ids_after, [i1.id, i2.id])

    def test_reorder_cleans_orphan_group_labels(self):
        i1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I1",
            ordre_sortida=1,
            grup=1,
        )
        i2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I2",
            ordre_sortida=2,
            grup=2,
        )
        self.comp.inscripcions_view = {"group_names": {"1": "Un", "2": "Dos"}}
        self.comp.save(update_fields=["inscripcions_view"])

        resp = self._post_json(
            "inscripcions_reorder",
            {
                "ids": [i2.id, i1.id],
                "moved_id": i1.id,
                "new_index": 1,
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))

        i1.refresh_from_db()
        self.assertEqual(i1.grup, 1)

        self.comp.refresh_from_db()
        self.assertEqual(self.comp.inscripcions_view.get("group_names"), {"1": "Un", "2": "Dos"})

    def test_reorder_prefers_target_group_over_previous_row_group(self):
        i1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I1",
            ordre_sortida=1,
            grup=1,
        )
        i2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I2",
            ordre_sortida=2,
            grup=1,
        )
        i3 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I3",
            ordre_sortida=3,
            grup=2,
        )
        i4 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I4",
            ordre_sortida=4,
            grup=2,
        )

        resp = self._post_json(
            "inscripcions_reorder",
            {
                "ids": [i2.id, i1.id, i3.id, i4.id],
                "moved_id": i1.id,
                "new_index": 1,
                "target_group": 2,
                "mode": "group_edit",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))

        i1.refresh_from_db()
        self.assertEqual(i1.grup, 2)
        self.assertEqual(i1.ordre_competicio, 3)

    def test_reorder_without_header_target_keeps_legacy_edge_behavior(self):
        i1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I1",
            ordre_sortida=1,
            grup=1,
        )
        i2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I2",
            ordre_sortida=2,
            grup=2,
        )

        resp = self._post_json(
            "inscripcions_reorder",
            {
                "ids": [i2.id, i1.id],
                "moved_id": i2.id,
                "new_index": 0,
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))

        i2.refresh_from_db()
        self.assertEqual(i2.grup, 2)

    def test_save_group_competition_order_updates_only_real_order(self):
        i1 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I1",
            ordre_sortida=1,
            grup=1,
        )
        i2 = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="I2",
            ordre_sortida=2,
            grup=1,
        )

        resp = self._post_json(
            "inscripcions_save_group_competition_order",
            {
                "group_num": 1,
                "ids": [i2.id, i1.id],
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))

        i1.refresh_from_db()
        i2.refresh_from_db()
        self.assertEqual(i1.ordre_sortida, 1)
        self.assertEqual(i2.ordre_sortida, 2)
        self.assertEqual(i2.ordre_competicio, 1)
        self.assertEqual(i1.ordre_competicio, 2)

    def test_groups_preview_marks_existing_group_as_reduced_when_members_remain_outside_filter(self):
        moving = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Visible",
            entitat="Club A",
            ordre_sortida=1,
            grup=1,
        )
        staying = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Resta",
            entitat="Club B",
            ordre_sortida=2,
            grup=1,
        )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(filters={"q": "", "categoria": "", "subcategoria": "", "entitat": "Club A"}),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))

        preview = data.get("preview") or {}
        existing_groups = preview.get("existing_groups") or []
        self.assertEqual(len(existing_groups), 1)
        existing = existing_groups[0]
        self.assertEqual(existing.get("group_num"), 1)
        self.assertEqual(existing.get("impact_kind"), "reduced")
        self.assertEqual(existing.get("members_count"), 2)
        self.assertEqual(existing.get("moving_members_count"), 1)
        self.assertEqual(existing.get("remaining_members_count"), 1)
        self.assertEqual(existing.get("moving_member_names_preview"), [moving.nom_i_cognoms])

        sources = existing.get("sources") or []
        self.assertEqual(sum(int(row.get("moving_count") or 0) for row in sources), 1)
        self.assertEqual(sum(int(row.get("remaining_count") or 0) for row in sources), 1)
        self.assertEqual(preview.get("existing_members_total"), 2)

        self.assertEqual(staying.grup, 1)

    def test_groups_preview_selected_scope_uses_selected_ids_even_outside_filters(self):
        club_a = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Club A",
            entitat="Club A",
            ordre_sortida=1,
            grup=None,
        )
        club_b = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Club B",
            entitat="Club B",
            ordre_sortida=2,
            grup=None,
        )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(
                scope="selected",
                selected_ids=[club_b.id],
                filters={"q": "", "categoria": "", "subcategoria": "", "entitat": "Club A"},
            ),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))

        preview = data.get("preview") or {}
        self.assertEqual(preview.get("members_total"), 1)
        groups = preview.get("groups") or []
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get("member_names_preview"), [club_b.nom_i_cognoms])
        self.assertEqual(club_a.grup, None)
        self.assertEqual(club_b.grup, None)

    def test_groups_preview_selected_scope_can_use_sort_context_filters_for_bucket_resolution(self):
        ins_free_a = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Free A",
            ordre_sortida=1,
            grup=None,
            categoria="Alevi",
        )
        ins_free_b = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Free B",
            ordre_sortida=2,
            grup=None,
            categoria="Infantil",
        )

        sort_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "scope": "all",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
                "sort_key": "categoria",
                "sort_dir": "asc",
            },
        )
        self.assertEqual(sort_resp.status_code, 200)
        self.assertTrue(sort_resp.json().get("ok"))

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(
                strategy="per_bucket",
                scope="selected",
                selected_ids=[ins_free_a.id, ins_free_b.id],
                filters={"q": "", "categoria": "", "subcategoria": "", "entitat": "Club Inexistent"},
                sort_context_filters={"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            ),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))

        preview = data.get("preview") or {}
        groups = preview.get("groups") or []
        self.assertEqual(len(groups), 2)
        self.assertEqual(sorted(group.get("members_count") for group in groups), [1, 1])

    def test_groups_preview_marks_existing_group_as_removed_when_all_members_move(self):
        first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Primer",
            ordre_sortida=1,
            grup=1,
        )
        second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Segon",
            ordre_sortida=2,
            grup=1,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Sense grup",
            ordre_sortida=3,
            grup=None,
        )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))

        preview = data.get("preview") or {}
        existing_groups = preview.get("existing_groups") or []
        self.assertEqual(len(existing_groups), 1)
        existing = existing_groups[0]
        self.assertEqual(existing.get("group_num"), 1)
        self.assertEqual(existing.get("impact_kind"), "removed")
        self.assertEqual(existing.get("members_count"), 2)
        self.assertEqual(existing.get("moving_members_count"), 2)
        self.assertEqual(existing.get("remaining_members_count"), 0)
        self.assertEqual(existing.get("moving_member_names_preview"), [first.nom_i_cognoms, second.nom_i_cognoms])
        self.assertEqual(preview.get("existing_groups_total"), 1)

    def test_groups_preview_existing_group_exposes_existing_name_label(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Primer",
            ordre_sortida=1,
            grup=1,
        )
        renumber_groups_for_competicio(self.comp)
        group = GrupCompeticio.objects.get(competicio=self.comp, display_num=1)
        group.nom = "Final"
        group.save(update_fields=["nom"])

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(),
        )
        self.assertEqual(resp.status_code, 200)

        preview = resp.json().get("preview") or {}
        existing_groups = preview.get("existing_groups") or []
        self.assertEqual(len(existing_groups), 1)
        self.assertEqual(existing_groups[0].get("group_label"), "Final")

    def test_groups_preview_suggests_name_from_single_sort_bucket(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A1",
            entitat="Club A",
            ordre_sortida=1,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A2",
            entitat="Club A",
            ordre_sortida=2,
            grup=None,
        )

        sort_payload = {
            "scope": "all",
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "group_by": [],
            "sort_key": "entitat",
            "sort_dir": "asc",
        }
        sort_resp = self._post_json("inscripcions_sort_apply", sort_payload)
        self.assertEqual(sort_resp.status_code, 200)
        self.assertTrue(sort_resp.json().get("ok"))

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(strategy="per_bucket"),
        )
        self.assertEqual(resp.status_code, 200)

        groups = (resp.json().get("preview") or {}).get("groups") or []
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get("suggested_name"), "Club A")

    def test_groups_preview_suggests_name_from_single_tab_bucket(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A1",
            categoria="Alevi",
            ordre_sortida=1,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A2",
            categoria="Alevi",
            ordre_sortida=2,
            grup=None,
        )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(strategy="per_bucket", group_by=["categoria"]),
        )
        self.assertEqual(resp.status_code, 200)

        groups = (resp.json().get("preview") or {}).get("groups") or []
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get("suggested_name"), "Alevi")

    def test_groups_preview_auto_resolution_combines_group_by_and_sort(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi A",
            categoria="Alevi",
            entitat="Club A",
            ordre_sortida=1,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi B",
            categoria="Alevi",
            entitat="Club B",
            ordre_sortida=2,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Infantil A",
            categoria="Infantil",
            entitat="Club A",
            ordre_sortida=3,
            grup=None,
        )

        sort_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "scope": "all",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
                "sort_key": "entitat",
                "sort_dir": "asc",
            },
        )
        self.assertEqual(sort_resp.status_code, 200)
        self.assertTrue(sort_resp.json().get("ok"))

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(strategy="per_bucket", group_by=["categoria"]),
        )
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertEqual(data.get("resolution_mode"), "auto")
        self.assertEqual(data.get("layers_used"), ["tabs", "sort"])
        self.assertEqual(data.get("effective_bucket_count"), 3)

        preview = data.get("preview") or {}
        groups = preview.get("groups") or []
        self.assertEqual(len(groups), 3)
        self.assertEqual(preview.get("layers_used"), ["tabs", "sort"])
        self.assertEqual(preview.get("effective_bucket_count"), 3)
        self.assertEqual(
            [group.get("suggested_name") for group in groups],
            ["Alevi · Club A", "Infantil · Club A", "Alevi · Club B"],
        )

    def test_groups_preview_auto_resolution_uses_tabs_only_without_sort(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi 1",
            categoria="Alevi",
            ordre_sortida=1,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi 2",
            categoria="Alevi",
            ordre_sortida=2,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Infantil 1",
            categoria="Infantil",
            ordre_sortida=3,
            grup=None,
        )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(strategy="per_bucket", group_by=["categoria"]),
        )
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertEqual(data.get("layers_used"), ["tabs"])
        self.assertEqual(data.get("effective_bucket_count"), 2)
        groups = (data.get("preview") or {}).get("groups") or []
        self.assertEqual([group.get("suggested_name") for group in groups], ["Alevi", "Infantil"])

    def test_groups_preview_auto_resolution_uses_sort_only_without_group_by(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Club A 1",
            entitat="Club A",
            ordre_sortida=1,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Club A 2",
            entitat="Club A",
            ordre_sortida=2,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Club B 1",
            entitat="Club B",
            ordre_sortida=3,
            grup=None,
        )

        sort_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "scope": "all",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
                "sort_key": "entitat",
                "sort_dir": "asc",
            },
        )
        self.assertEqual(sort_resp.status_code, 200)
        self.assertTrue(sort_resp.json().get("ok"))

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(strategy="per_bucket"),
        )
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertEqual(data.get("layers_used"), ["sort"])
        self.assertEqual(data.get("effective_bucket_count"), 2)
        groups = (data.get("preview") or {}).get("groups") or []
        self.assertEqual([group.get("suggested_name") for group in groups], ["Club A", "Club B"])

    def test_groups_preview_auto_resolution_deduplicates_redundant_sort_partition(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi 1",
            categoria="Alevi",
            ordre_sortida=1,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Infantil 1",
            categoria="Infantil",
            ordre_sortida=2,
            grup=None,
        )

        sort_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "scope": "all",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
                "sort_key": "categoria",
                "sort_dir": "asc",
            },
        )
        self.assertEqual(sort_resp.status_code, 200)
        self.assertTrue(sort_resp.json().get("ok"))

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(strategy="per_bucket", group_by=["categoria"]),
        )
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertEqual(data.get("layers_used"), ["tabs"])
        self.assertEqual(data.get("effective_bucket_count"), 2)

    def test_groups_preview_selected_keys_accept_combined_bucket_key(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi A",
            categoria="Alevi",
            entitat="Club A",
            ordre_sortida=1,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi B",
            categoria="Alevi",
            entitat="Club B",
            ordre_sortida=2,
            grup=None,
        )

        sort_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "scope": "all",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
                "sort_key": "entitat",
                "sort_dir": "asc",
            },
        )
        self.assertEqual(sort_resp.status_code, 200)
        self.assertTrue(sort_resp.json().get("ok"))

        records = list(
            _build_inscripcions_filtered_qs(
                self.comp,
                {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            ).order_by("ordre_sortida", "id")
        )
        resolution = _resolve_group_creation_buckets(
            self.comp,
            records,
            group_codes=["categoria"],
            partition_codes=["entitat"],
        )
        combined_key = ((resolution.get("buckets") or [])[0] or {}).get("key")

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(
                strategy="per_bucket",
                group_by=["categoria"],
                selected_keys=[combined_key],
            ),
        )
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertEqual(data.get("buckets_applied"), 1)
        preview = data.get("preview") or {}
        self.assertEqual(preview.get("members_total"), 1)
        groups = preview.get("groups") or []
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get("suggested_name"), "Alevi · Club A")

    def test_groups_preview_tab_merges_apply_before_combining_with_sort(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi A",
            categoria="Alevi",
            entitat="Club A",
            ordre_sortida=1,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Infantil A",
            categoria="Infantil",
            entitat="Club A",
            ordre_sortida=2,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi B",
            categoria="Alevi",
            entitat="Club B",
            ordre_sortida=3,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Infantil B",
            categoria="Infantil",
            entitat="Club B",
            ordre_sortida=4,
            grup=None,
        )
        self.comp.tab_merges = {
            "categoria": [[json.dumps(["Alevi"], ensure_ascii=False), json.dumps(["Infantil"], ensure_ascii=False)]]
        }
        self.comp.save(update_fields=["tab_merges"])

        sort_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "scope": "all",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
                "sort_key": "entitat",
                "sort_dir": "asc",
            },
        )
        self.assertEqual(sort_resp.status_code, 200)
        self.assertTrue(sort_resp.json().get("ok"))

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(strategy="per_bucket", group_by=["categoria"]),
        )
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertEqual(data.get("layers_used"), ["tabs", "sort"])
        self.assertEqual(data.get("effective_bucket_count"), 2)
        groups = (data.get("preview") or {}).get("groups") or []
        self.assertEqual(
            [group.get("suggested_name") for group in groups],
            ["Alevi + Infantil · Club A", "Alevi + Infantil · Club B"],
        )

    def test_groups_preview_existing_groups_use_combined_sources(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi A",
            categoria="Alevi",
            entitat="Club A",
            ordre_sortida=1,
            grup=1,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Alevi B",
            categoria="Alevi",
            entitat="Club B",
            ordre_sortida=2,
            grup=1,
        )

        sort_resp = self._post_json(
            "inscripcions_sort_apply",
            {
                "scope": "all",
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
                "sort_key": "entitat",
                "sort_dir": "asc",
            },
        )
        self.assertEqual(sort_resp.status_code, 200)
        self.assertTrue(sort_resp.json().get("ok"))

        records = list(
            _build_inscripcions_filtered_qs(
                self.comp,
                {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            ).order_by("ordre_sortida", "id")
        )
        resolution = _resolve_group_creation_buckets(
            self.comp,
            records,
            group_codes=["categoria"],
            partition_codes=["entitat"],
        )
        combined_key = ((resolution.get("buckets") or [])[0] or {}).get("key")

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(
                strategy="per_bucket",
                group_by=["categoria"],
                selected_keys=[combined_key],
            ),
        )
        self.assertEqual(resp.status_code, 200)

        preview = resp.json().get("preview") or {}
        existing_groups = preview.get("existing_groups") or []
        self.assertEqual(len(existing_groups), 1)
        existing = existing_groups[0]
        self.assertEqual(existing.get("impact_kind"), "reduced")
        source_map = {row.get("label"): row for row in existing.get("sources") or []}
        self.assertEqual(source_map["Alevi / Club A"]["moving_count"], 1)
        self.assertEqual(source_map["Alevi / Club A"]["remaining_count"], 0)
        self.assertEqual(source_map["Alevi / Club B"]["moving_count"], 0)
        self.assertEqual(source_map["Alevi / Club B"]["remaining_count"], 1)

    def test_groups_preview_builds_composed_name_from_weighted_sources(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A1",
            entitat="Club A",
            ordre_sortida=1,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A2",
            entitat="Club A",
            ordre_sortida=2,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="B1",
            entitat="Club B",
            ordre_sortida=3,
            grup=None,
        )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(
                source="tabs",
                strategy="count",
                group_count=1,
                group_by=["entitat"],
            ),
        )
        self.assertEqual(resp.status_code, 200)

        groups = (resp.json().get("preview") or {}).get("groups") or []
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get("suggested_name"), "Club A + Club B")

    def test_groups_preview_selected_scope_adds_main_filter_components_to_name(self):
        club_a = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A1",
            categoria="Alevi",
            entitat="Club A",
            ordre_sortida=1,
            grup=None,
        )
        club_b = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="B1",
            categoria="Alevi",
            entitat="Club B",
            ordre_sortida=2,
            grup=None,
        )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            {
                "resolution_mode": "auto",
                "strategy": "count",
                "group_count": 1,
                "preview_only": True,
                "scope": "selected",
                "selected_ids": [club_a.id, club_b.id],
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "sort_context_filters": {"q": "", "categoria": "Alevi", "subcategoria": "", "entitat": ""},
                "group_by": ["entitat"],
            },
        )
        self.assertEqual(resp.status_code, 200)

        groups = (resp.json().get("preview") or {}).get("groups") or []
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get("suggested_name"), "Alevi · Club A + Club B")

    def test_groups_preview_deduplicates_filters_already_present_in_bucket_name(self):
        ins = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A1",
            categoria="Alevi",
            entitat="Club A",
            ordre_sortida=1,
            grup=None,
        )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            {
                "resolution_mode": "auto",
                "strategy": "count",
                "group_count": 1,
                "preview_only": True,
                "scope": "selected",
                "selected_ids": [ins.id],
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "sort_context_filters": {"q": "", "categoria": "Alevi", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria", "entitat"],
            },
        )
        self.assertEqual(resp.status_code, 200)

        groups = (resp.json().get("preview") or {}).get("groups") or []
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get("suggested_name"), "Alevi · Club A")

    def test_groups_preview_workspace_filters_override_main_filters_for_same_field(self):
        ins = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A1",
            categoria="Alevi",
            entitat="Club A",
            ordre_sortida=1,
            grup=None,
        )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            {
                "resolution_mode": "auto",
                "strategy": "count",
                "group_count": 1,
                "preview_only": True,
                "scope": "selected",
                "selected_ids": [ins.id],
                "filters": {"q": "", "categoria": "Infantil", "subcategoria": "", "entitat": ""},
                "sort_context_filters": {"q": "", "categoria": "Alevi", "subcategoria": "", "entitat": ""},
                "group_by": ["entitat"],
            },
        )
        self.assertEqual(resp.status_code, 200)

        groups = (resp.json().get("preview") or {}).get("groups") or []
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get("suggested_name"), "Infantil · Club A")

    def test_groups_preview_compacts_multiselect_filter_values_after_three_labels(self):
        ins = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A1",
            ordre_sortida=1,
            grup=None,
        )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            {
                "resolution_mode": "auto",
                "strategy": "count",
                "group_count": 1,
                "preview_only": True,
                "scope": "selected",
                "selected_ids": [ins.id],
                "filters": {
                    "q": "",
                    "categoria": "",
                    "subcategoria": "",
                    "entitat": "",
                    "entitats": ["Club A", "Club B", "Club C", "Club D"],
                },
                "sort_context_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(resp.status_code, 200)

        groups = (resp.json().get("preview") or {}).get("groups") or []
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get("suggested_name"), "Club A + Club B + Club C + 1 més")

    def test_groups_preview_disambiguates_duplicate_suggested_names(self):
        for idx in range(1, 5):
            Inscripcio.objects.create(
                competicio=self.comp,
                nom_i_cognoms=f"A{idx}",
                entitat="Club A",
                ordre_sortida=idx,
                grup=None,
            )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(
                source="tabs",
                strategy="count",
                group_count=2,
                group_by=["entitat"],
            ),
        )
        self.assertEqual(resp.status_code, 200)

        groups = (resp.json().get("preview") or {}).get("groups") or []
        self.assertEqual(
            [group.get("suggested_name") for group in groups],
            ["Club A (1)", "Club A (2)"],
        )

    def test_groups_preview_ignores_generic_fallback_labels(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Sense Nom 1",
            ordre_sortida=1,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Sense Nom 2",
            ordre_sortida=2,
            grup=None,
        )

        resp = self._post_json("inscripcions_groups_from_sort", self._groups_payload())
        self.assertEqual(resp.status_code, 200)

        groups = (resp.json().get("preview") or {}).get("groups") or []
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].get("suggested_name"), "")

    def test_groups_apply_persists_suggested_name_without_overwriting_existing_manual_names(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Manual",
            entitat="Club X",
            ordre_sortida=1,
            grup=1,
        )
        renumber_groups_for_competicio(self.comp)
        existing_group = GrupCompeticio.objects.get(competicio=self.comp, display_num=1)
        existing_group.nom = "Manual"
        existing_group.save(update_fields=["nom"])
        self.comp.inscripcions_view = {"group_names": {"1": "Manual"}}
        self.comp.save(update_fields=["inscripcions_view"])

        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Nou 1",
            entitat="Club A",
            ordre_sortida=2,
            grup=None,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Nou 2",
            entitat="Club A",
            ordre_sortida=3,
            grup=None,
        )

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(
                source="tabs",
                strategy="per_bucket",
                preview_only=False,
                group_by=["entitat"],
                filters={"q": "", "categoria": "", "subcategoria": "", "entitat": "Club A"},
            ),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))

        existing_group.refresh_from_db()
        self.assertEqual(existing_group.nom, "Manual")

        new_group = GrupCompeticio.objects.get(competicio=self.comp, display_num=2)
        self.assertEqual(new_group.nom, "Club A")

        self.comp.refresh_from_db()
        self.assertEqual(
            self.comp.inscripcions_view.get("group_names"),
            {"1": "Manual", "2": "Club A"},
        )

    def test_groups_apply_deactivates_group_that_becomes_empty(self):
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Primer",
            ordre_sortida=1,
            grup=1,
        )
        Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Segon",
            ordre_sortida=2,
            grup=1,
        )
        renumber_groups_for_competicio(self.comp)
        old_group = GrupCompeticio.objects.get(competicio=self.comp, display_num=1)
        self.assertTrue(old_group.actiu)

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(preview_only=False),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))

        old_group.refresh_from_db()
        self.assertFalse(old_group.actiu)
        self.assertTrue(
            GrupCompeticio.objects.filter(competicio=self.comp, display_num=2, actiu=True).exists()
        )

    def test_groups_apply_with_rotations_keeps_programmed_group_when_members_remain(self):
        first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Primer",
            entitat="Club A",
            ordre_sortida=1,
            grup=1,
        )
        second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Segon",
            entitat="Club B",
            ordre_sortida=2,
            grup=1,
        )
        group = first.grup_competicio
        franja = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici="09:00",
            hora_fi="09:30",
            ordre=1,
            titol="Franja 1",
        )
        estacio = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="descans",
            ordre=1,
            actiu=True,
        )
        assignacio = RotacioAssignacio.objects.create(
            competicio=self.comp,
            franja=franja,
            estacio=estacio,
        )
        RotacioAssignacioGrup.objects.create(assignacio=assignacio, grup=group, ordre=1)

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(
                preview_only=False,
                filters={"q": "", "categoria": "", "subcategoria": "", "entitat": "Club A"},
            ),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.grup, 2)
        self.assertEqual(second.grup, 1)
        self.assertTrue(
            GrupCompeticio.objects.filter(competicio=self.comp, display_num=2, actiu=True).exists()
        )

    def test_groups_apply_with_rotations_rejects_emptying_programmed_group(self):
        first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Primer",
            ordre_sortida=1,
            grup=1,
        )
        second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Segon",
            ordre_sortida=2,
            grup=1,
        )
        group = first.grup_competicio
        franja = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici="09:00",
            hora_fi="09:30",
            ordre=1,
            titol="Franja 1",
        )
        estacio = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="descans",
            ordre=1,
            actiu=True,
        )
        assignacio = RotacioAssignacio.objects.create(
            competicio=self.comp,
            franja=franja,
            estacio=estacio,
        )
        RotacioAssignacioGrup.objects.create(assignacio=assignacio, grup=group, ordre=1)

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(preview_only=False),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("No es pot deixar buit un grup inclos al programa de rotacions", resp.content.decode("utf-8"))

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.grup, 1)
        self.assertEqual(second.grup, 1)


class GroupNameSyncTests(TestCase):
    def test_renumber_remaps_group_labels_and_drops_stale(self):
        comp = Competicio.objects.create(
            nom="Comp labels remap",
            tipus=Competicio.Tipus.TRAMPOLI,
            inscripcions_view={"group_names": {"1": "Antic", "2": "Beta", "4": "Gamma"}},
        )
        Inscripcio.objects.create(
            competicio=comp,
            nom_i_cognoms="I1",
            ordre_sortida=1,
            grup=2,
        )
        Inscripcio.objects.create(
            competicio=comp,
            nom_i_cognoms="I2",
            ordre_sortida=2,
            grup=4,
        )

        renumber_groups_for_competicio(comp)

        comp.refresh_from_db()
        self.assertEqual(comp.inscripcions_view.get("group_names"), {"2": "Beta", "4": "Gamma"})

    def test_renumber_without_groups_clears_group_labels(self):
        comp = Competicio.objects.create(
            nom="Comp labels clear",
            tipus=Competicio.Tipus.TRAMPOLI,
            inscripcions_view={"group_names": {"1": "Orfe", "9": "Fantasma"}},
        )

        renumber_groups_for_competicio(comp)

        comp.refresh_from_db()
        self.assertNotIn("group_names", comp.inscripcions_view or {})


class ProgrammedGroupReconfigurationTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Programmed Group Reconfig")
        self.comp.group_by_default = ["entitat"]
        self.comp.save(update_fields=["group_by_default"])
        User = get_user_model()
        self.user = User.objects.create_user(
            username="programmed_group_editor",
            password="testpass123",
            email="programmed-group-editor@example.com",
        )
        CompeticioMembership.objects.create(
            user=self.user,
            competicio=self.comp,
            role=CompeticioMembership.Role.EDITOR,
            is_active=True,
        )
        self.client.force_login(self.user)

    def _attach_rotation_to_group(self, group):
        next_order = (RotacioFranja.objects.filter(competicio=self.comp).aggregate(max_ordre=Max("ordre")).get("max_ordre") or 0) + 1
        franja = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici="09:00",
            hora_fi="09:30",
            ordre=next_order,
            titol=f"Franja {next_order}",
        )
        estacio = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="descans",
            ordre=next_order,
            actiu=True,
        )
        assignacio = RotacioAssignacio.objects.create(
            competicio=self.comp,
            franja=franja,
            estacio=estacio,
        )
        RotacioAssignacioGrup.objects.create(assignacio=assignacio, grup=group, ordre=1)

    def test_make_independent_group_with_rotations_creates_new_group_when_origin_keeps_members(self):
        first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A1",
            entitat="Club A",
            ordre_sortida=1,
            grup=1,
        )
        second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A2",
            entitat="Club A",
            ordre_sortida=2,
            grup=1,
        )
        third = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="B1",
            entitat="Club B",
            ordre_sortida=3,
            grup=1,
        )
        self._attach_rotation_to_group(first.grup_competicio)

        url = reverse("inscripcions_list", kwargs={"pk": self.comp.id})
        res = self.client.get(
            url,
            {
                "make_independent_group": "1",
                "lvl": "g1",
                "v1": "Club A",
            },
            follow=True,
        )
        self.assertEqual(res.status_code, 200)

        first.refresh_from_db()
        second.refresh_from_db()
        third.refresh_from_db()
        self.assertEqual(first.grup, 2)
        self.assertEqual(second.grup, 2)
        self.assertEqual(third.grup, 1)
        self.assertContains(res, "Creat el grup 2")

    def test_make_independent_group_with_rotations_rejects_emptying_programmed_origin(self):
        first = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A1",
            entitat="Club A",
            ordre_sortida=1,
            grup=1,
        )
        second = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="A2",
            entitat="Club A",
            ordre_sortida=2,
            grup=1,
        )
        self._attach_rotation_to_group(first.grup_competicio)

        url = reverse("inscripcions_list", kwargs={"pk": self.comp.id})
        res = self.client.get(
            url,
            {
                "make_independent_group": "1",
                "lvl": "g1",
                "v1": "Club A",
            },
            follow=True,
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "No es pot deixar buit un grup inclos al programa de rotacions")

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.grup, 1)
        self.assertEqual(second.grup, 1)


class GroupManagerV1Tests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Group Manager V1")

        self.programmed_group = GrupCompeticio.objects.create(
            competicio=self.comp,
            legacy_num=1,
            display_num=1,
            nom="Final",
            actiu=True,
        )
        self.other_group = GrupCompeticio.objects.create(
            competicio=self.comp,
            legacy_num=2,
            display_num=2,
            nom="",
            actiu=True,
        )
        self.empty_group = GrupCompeticio.objects.create(
            competicio=self.comp,
            legacy_num=3,
            display_num=3,
            nom="",
            actiu=True,
        )

        self.ins_programmed_a = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Programmed A",
            ordre_sortida=1,
            grup=1,
        )
        self.ins_programmed_b = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Programmed B",
            ordre_sortida=2,
            grup=1,
        )
        self.ins_other = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Other Group",
            ordre_sortida=3,
            grup=2,
        )
        self.ins_free_a = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Free A",
            ordre_sortida=4,
        )
        self.ins_free_b = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Free B",
            ordre_sortida=5,
        )

        self._attach_rotation_to_group(self.programmed_group)

        User = get_user_model()
        self.user = User.objects.create_user(
            username="group_manager_editor",
            password="testpass123",
            email="group-manager@example.com",
        )
        CompeticioMembership.objects.create(
            user=self.user,
            competicio=self.comp,
            role=CompeticioMembership.Role.EDITOR,
            is_active=True,
        )
        self.client.force_login(self.user)

    def _post_json(self, url_name, payload):
        url = reverse(url_name, kwargs={"pk": self.comp.id})
        return self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def _groups_payload(self, **overrides):
        payload = {
            "resolution_mode": "auto",
            "strategy": "count",
            "group_count": 1,
            "preview_only": True,
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "group_by": [],
        }
        payload.update(overrides)
        return payload

    def _attach_rotation_to_group(self, group):
        next_order = (RotacioFranja.objects.filter(competicio=self.comp).aggregate(max_ordre=Max("ordre")).get("max_ordre") or 0) + 1
        franja = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici="09:00",
            hora_fi="09:30",
            ordre=next_order,
            titol=f"Franja {next_order}",
        )
        estacio = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="descans",
            ordre=next_order,
            actiu=True,
        )
        assignacio = RotacioAssignacio.objects.create(
            competicio=self.comp,
            franja=franja,
            estacio=estacio,
        )
        RotacioAssignacioGrup.objects.create(assignacio=assignacio, grup=group, ordre=1)

    def _groups_contract_path(self, action):
        return f"/competicio/{self.comp.id}/inscripcions/groups/{action}/"

    def _post_groups_contract(self, action, payload):
        path = self._groups_contract_path(action)
        try:
            resolve(path.lstrip("/"))
        except Resolver404:
            self.skipTest(f"Pending groups endpoint not implemented yet: {path}")
        return self.client.post(
            path,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_group_helpers_report_labels_counts_and_programmed_state(self):
        counts = get_group_participant_counts(self.comp)
        maps = get_group_maps(self.comp)
        programmed_ids = get_programmed_group_ids(self.comp)
        out_of_program_ids = get_out_of_program_group_ids(self.comp)

        self.assertEqual(group_label(self.programmed_group), "Final")
        self.assertEqual(group_label(self.other_group), "Grup 2")
        self.assertEqual(counts[self.programmed_group.id], 2)
        self.assertEqual(counts[self.other_group.id], 1)
        self.assertIn(self.programmed_group.id, programmed_ids)
        self.assertIn(self.other_group.id, out_of_program_ids)
        self.assertEqual(maps["by_display_num"][1].nom, "Final")
        self.assertEqual(maps["by_display_num"][2].display_num, 2)

    def test_assign_groups_by_display_num_creates_new_groups_and_updates_legacy_fields(self):
        new_group_num = next_group_display_num(self.comp)
        moved_ids = assign_groups_by_display_num(
            self.comp,
            {
                new_group_num: [self.ins_free_a.id, self.ins_free_b.id],
            },
        )

        self.assertEqual(moved_ids, {self.ins_free_a.id, self.ins_free_b.id})
        new_group = GrupCompeticio.objects.get(competicio=self.comp, display_num=new_group_num)
        self.ins_free_a.refresh_from_db()
        self.ins_free_b.refresh_from_db()

        self.assertEqual(self.ins_free_a.grup, new_group_num)
        self.assertEqual(self.ins_free_a.grup_competicio_id, new_group.id)
        self.assertEqual(self.ins_free_a.ordre_competicio, 1)
        self.assertEqual(self.ins_free_b.grup, new_group_num)
        self.assertEqual(self.ins_free_b.grup_competicio_id, new_group.id)
        self.assertEqual(self.ins_free_b.ordre_competicio, 2)
        self.assertEqual(group_label(new_group), f"Grup {new_group_num}")

    def test_move_inscripcio_to_group_appends_target_order_and_compacts_origin_group(self):
        moved = move_inscripcio_to_group(self.ins_programmed_b, self.other_group)

        self.assertTrue(moved)
        self.ins_programmed_a.refresh_from_db()
        self.ins_programmed_b.refresh_from_db()
        self.ins_other.refresh_from_db()

        self.assertEqual(self.ins_programmed_a.grup, 1)
        self.assertEqual(self.ins_programmed_a.ordre_competicio, 1)
        self.assertEqual(self.ins_programmed_b.grup, 2)
        self.assertEqual(self.ins_programmed_b.ordre_competicio, 2)
        self.assertEqual(self.ins_other.ordre_competicio, 1)

    def test_manual_unassign_requires_compacting_group_order(self):
        Inscripcio.objects.filter(pk=self.ins_programmed_b.pk).update(
            grup_competicio=None,
            grup=None,
            ordre_competicio=None,
        )
        compact_competition_order_for_group(self.programmed_group)

        self.ins_programmed_a.refresh_from_db()
        self.ins_programmed_b.refresh_from_db()

        self.assertEqual(self.ins_programmed_a.ordre_competicio, 1)
        self.assertIsNone(self.ins_programmed_b.grup)
        self.assertIsNone(self.ins_programmed_b.grup_competicio_id)
        self.assertIsNone(self.ins_programmed_b.ordre_competicio)

    def test_set_group_name_updates_view_and_returns_history_payload(self):
        resp = self.client.post(
            reverse("inscripcions_set_group_name", kwargs={"pk": self.comp.id}),
            data=json.dumps({"group": 1, "name": "Final A"}),
            content_type="application/json",
        )

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload.get("ok"))
        self.assertIn("history", payload)
        self.assertEqual(payload.get("name"), "Final A")

        self.programmed_group.refresh_from_db()
        self.comp.refresh_from_db()
        self.assertEqual(self.programmed_group.nom, "Final A")
        self.assertEqual(self.comp.inscripcions_view.get("group_names"), {"1": "Final A"})

    def test_groups_workspace_contract_returns_summary_and_group_cards(self):
        payload = {
            "scope": "selected",
            "selected_ids": [self.ins_programmed_a.id, self.ins_free_a.id],
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "page": 1,
            "page_size": 25,
        }
        resp = self._post_groups_contract("workspace", payload)

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertIn("summary", data)
        self.assertIn("groups", data)
        self.assertIn("filters", data)
        self.assertIn("candidates", data)

        summary = data.get("summary") or {}
        self.assertGreaterEqual(int(summary.get("groups_total") or 0), 3)
        self.assertGreaterEqual(int(summary.get("groups_with_members") or 0), 1)
        self.assertGreaterEqual(int(summary.get("empty_groups") or 0), 1)
        self.assertEqual(int(summary.get("assigned_count") or 0), 3)
        self.assertEqual(int(summary.get("unassigned_count") or 0), 2)
        self.assertEqual(int(summary.get("programmed_groups") or 0), 1)
        self.assertEqual(int(summary.get("out_of_program_groups") or 0), 1)

    def test_groups_workspace_contract_keeps_selection_and_omits_filtered_target_ids_by_default(self):
        resp = self._post_groups_contract(
            "workspace",
            {
                "selected_ids": [self.ins_programmed_a.id, self.ins_free_a.id],
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "page": 1,
                "page_size": 2,
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("selected_ids"), [self.ins_programmed_a.id, self.ins_free_a.id])
        self.assertEqual(int((data.get("selection") or {}).get("count") or 0), 2)
        self.assertNotIn("target_ids", data)

    def test_groups_workspace_resolve_filtered_ids_operation_returns_full_filtered_set(self):
        resp = self._post_groups_contract(
            "workspace",
            {
                "operation": "resolve_filtered_ids",
                "filters": {
                    "q": "",
                    "categoria": "",
                    "subcategoria": "",
                    "entitat": "",
                    "group_state": "unassigned",
                },
                "page": 1,
                "page_size": 1,
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("operation"), "resolve_filtered_ids")
        self.assertEqual(data.get("target_ids"), [self.ins_free_a.id, self.ins_free_b.id])
        self.assertEqual(int(data.get("total") or 0), 2)

    def test_groups_workspace_resolve_auto_context_returns_global_buckets_without_selection(self):
        self.ins_programmed_a.categoria = "Alevi"
        self.ins_programmed_a.save(update_fields=["categoria"])
        self.ins_free_a.categoria = "Alevi"
        self.ins_free_a.save(update_fields=["categoria"])
        self.ins_programmed_b.categoria = "Senior"
        self.ins_programmed_b.save(update_fields=["categoria"])
        self.ins_other.categoria = "Senior"
        self.ins_other.save(update_fields=["categoria"])
        self.ins_free_b.categoria = "Infantil"
        self.ins_free_b.save(update_fields=["categoria"])

        resp = self._post_groups_contract(
            "workspace",
            {
                "operation": "resolve_auto_context",
                "selected_ids": [],
                "sort_context_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "workspace_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "fallback_mode": "all_filtered",
                "group_by": ["categoria"],
                "source_scope": "competition_all",
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("operation"), "resolve_auto_context")
        self.assertEqual(int(data.get("selection_count") or 0), 0)
        self.assertEqual(data.get("source_scope"), "competition_all")
        self.assertEqual(int(data.get("source_total") or 0), 5)
        self.assertEqual(int(data.get("buckets_total") or 0), 3)
        self.assertEqual(len(data.get("default_bucket_keys") or []), 3)
        self.assertFalse(data.get("used_fallback"))
        self.assertEqual(
            sorted(bucket.get("label") for bucket in (data.get("buckets") or [])),
            ["Alevi", "Infantil", "Senior"],
        )

    def test_groups_workspace_resolve_auto_context_tracks_visible_and_selected_counts(self):
        self.ins_programmed_a.categoria = "Alevi"
        self.ins_programmed_a.save(update_fields=["categoria"])
        self.ins_free_a.categoria = "Alevi"
        self.ins_free_a.save(update_fields=["categoria"])
        self.ins_programmed_b.categoria = "Senior"
        self.ins_programmed_b.save(update_fields=["categoria"])
        self.ins_other.categoria = "Infantil"
        self.ins_other.save(update_fields=["categoria"])
        self.ins_free_b.categoria = "Senior"
        self.ins_free_b.save(update_fields=["categoria"])

        resp = self._post_groups_contract(
            "workspace",
            {
                "operation": "resolve_auto_context",
                "selected_ids": [self.ins_programmed_a.id, self.ins_free_b.id],
                "sort_context_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "workspace_filters": {
                    "q": "",
                    "categoria": "",
                    "subcategoria": "",
                    "entitat": "",
                    "categories": ["Alevi"],
                },
                "fallback_mode": "all_filtered",
                "group_by": ["categoria"],
                "source_scope": "competition_all",
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(int(data.get("selection_count") or 0), 2)
        self.assertEqual(int(data.get("buckets_total") or 0), 3)
        self.assertEqual(sorted(data.get("layers_used") or []), ["tabs"])
        buckets_by_label = {
            bucket.get("label"): bucket
            for bucket in (data.get("buckets") or [])
        }
        self.assertEqual(int((buckets_by_label["Alevi"] or {}).get("global_count") or 0), 2)
        self.assertEqual(int((buckets_by_label["Alevi"] or {}).get("visible_count") or 0), 2)
        self.assertEqual(int((buckets_by_label["Alevi"] or {}).get("selected_count") or 0), 1)
        self.assertEqual(int((buckets_by_label["Infantil"] or {}).get("visible_count") or 0), 0)
        self.assertEqual(int((buckets_by_label["Senior"] or {}).get("selected_count") or 0), 1)

    def test_groups_workspace_apply_auto_context_selection_supports_add_remove_and_set(self):
        self.ins_programmed_a.categoria = "Alevi"
        self.ins_programmed_a.save(update_fields=["categoria"])
        self.ins_free_a.categoria = "Alevi"
        self.ins_free_a.save(update_fields=["categoria"])
        self.ins_programmed_b.categoria = "Senior"
        self.ins_programmed_b.save(update_fields=["categoria"])
        self.ins_other.categoria = "Infantil"
        self.ins_other.save(update_fields=["categoria"])
        self.ins_free_b.categoria = "Senior"
        self.ins_free_b.save(update_fields=["categoria"])

        resolve_resp = self._post_groups_contract(
            "workspace",
            {
                "operation": "resolve_auto_context",
                "selected_ids": [self.ins_programmed_b.id],
                "sort_context_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "workspace_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
                "source_scope": "competition_all",
            },
        )
        self.assertEqual(resolve_resp.status_code, 200)
        resolve_data = resolve_resp.json()
        bucket_keys_by_label = {
            bucket.get("label"): bucket.get("key")
            for bucket in (resolve_data.get("buckets") or [])
        }

        add_resp = self._post_groups_contract(
            "workspace",
            {
                "operation": "apply_auto_context_selection",
                "selection_mode": "add",
                "bucket_keys": [bucket_keys_by_label["Alevi"]],
                "selected_ids": [self.ins_programmed_b.id],
                "sort_context_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "workspace_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
                "source_scope": "competition_all",
            },
        )
        self.assertEqual(add_resp.status_code, 200)
        add_data = add_resp.json()
        self.assertEqual(
            add_data.get("selected_ids"),
            [self.ins_programmed_b.id, self.ins_programmed_a.id, self.ins_free_a.id],
        )

        remove_resp = self._post_groups_contract(
            "workspace",
            {
                "operation": "apply_auto_context_selection",
                "selection_mode": "remove",
                "bucket_keys": [bucket_keys_by_label["Alevi"]],
                "selected_ids": add_data.get("selected_ids"),
                "sort_context_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "workspace_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
                "source_scope": "competition_all",
            },
        )
        self.assertEqual(remove_resp.status_code, 200)
        remove_data = remove_resp.json()
        self.assertEqual(remove_data.get("selected_ids"), [self.ins_programmed_b.id])

        set_resp = self._post_groups_contract(
            "workspace",
            {
                "operation": "apply_auto_context_selection",
                "selection_mode": "set",
                "bucket_keys": [bucket_keys_by_label["Infantil"]],
                "selected_ids": remove_data.get("selected_ids"),
                "sort_context_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "workspace_filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": ["categoria"],
                "source_scope": "competition_all",
            },
        )
        self.assertEqual(set_resp.status_code, 200)
        set_data = set_resp.json()
        self.assertEqual(set_data.get("selected_ids"), [self.ins_other.id])

    def test_groups_workspace_filtered_scope_respects_column_filters(self):
        self.ins_free_a.entitat = "Club Filtrat"
        self.ins_free_a.save(update_fields=["entitat"])
        self.ins_free_b.entitat = "Club Altre"
        self.ins_free_b.save(update_fields=["entitat"])

        resp = self._post_groups_contract(
            "workspace",
            {
                "scope": "filtered",
                "selected_ids": [],
                "filters": {
                    "q": "",
                    "categoria": "",
                    "subcategoria": "",
                    "entitat": "",
                    "column_filters": {"entitat": ["Club Filtrat"]},
                    "group_state": "unassigned",
                },
                "page": 1,
                "page_size": 25,
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("filters", {}).get("column_filters"), {"entitat": ["Club Filtrat"]})
        self.assertEqual(
            [row.get("id") for row in (data.get("candidates") or [])],
            [self.ins_free_a.id],
        )
        self.assertEqual(int((data.get("paging") or {}).get("total") or 0), 1)

    def test_groups_workspace_filtered_scope_supports_multiselect_fields_and_group_ids(self):
        self.ins_programmed_a.categoria = "Alevi"
        self.ins_programmed_a.entitat = "Club A"
        self.ins_programmed_a.save(update_fields=["categoria", "entitat"])
        self.ins_programmed_b.categoria = "Infantil"
        self.ins_programmed_b.entitat = "Club C"
        self.ins_programmed_b.save(update_fields=["categoria", "entitat"])
        self.ins_other.categoria = "Infantil"
        self.ins_other.entitat = "Club B"
        self.ins_other.save(update_fields=["categoria", "entitat"])
        self.ins_free_a.categoria = "Infantil"
        self.ins_free_a.entitat = "Club B"
        self.ins_free_a.save(update_fields=["categoria", "entitat"])

        resp = self._post_groups_contract(
            "workspace",
            {
                "scope": "filtered",
                "selected_ids": [],
                "filters": {
                    "q": "",
                    "categoria": "",
                    "subcategoria": "",
                    "entitat": "",
                    "categories": ["Alevi", "Infantil"],
                    "entitats": ["Club B"],
                    "group_ids": [self.programmed_group.id, self.other_group.id],
                    "group_state": "assigned",
                },
                "page": 1,
                "page_size": 25,
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("filters", {}).get("categories"), ["Alevi", "Infantil"])
        self.assertEqual(data.get("filters", {}).get("entitats"), ["Club B"])
        self.assertEqual(data.get("filters", {}).get("group_ids"), [self.programmed_group.id, self.other_group.id])
        self.assertEqual(
            [row.get("id") for row in (data.get("candidates") or [])],
            [self.ins_other.id],
        )
        self.assertEqual(int((data.get("paging") or {}).get("total") or 0), 1)

    def test_groups_workspace_filter_options_keep_other_categories_visible_after_filtering_one(self):
        self.ins_programmed_a.categoria = "Alevi"
        self.ins_programmed_a.save(update_fields=["categoria"])
        self.ins_other.categoria = "Infantil"
        self.ins_other.save(update_fields=["categoria"])
        self.ins_free_a.categoria = "Juvenil"
        self.ins_free_a.save(update_fields=["categoria"])

        resp = self._post_groups_contract(
            "workspace",
            {
                "scope": "filtered",
                "selected_ids": [],
                "filters": {
                    "q": "",
                    "categoria": "",
                    "subcategoria": "",
                    "entitat": "",
                    "categories": ["Alevi"],
                    "group_state": "all",
                },
                "page": 1,
                "page_size": 25,
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(
            sorted(data.get("filter_options", {}).get("categories") or []),
            ["Alevi", "Infantil", "Juvenil"],
        )
        self.assertEqual(
            [row.get("id") for row in (data.get("candidates") or [])],
            [self.ins_programmed_a.id],
        )

    def test_groups_detail_contract_returns_members_and_state_flags(self):
        resp = self._post_groups_contract(
            "detail",
            {"group_id": self.programmed_group.id},
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        group_data = data.get("group") or {}
        members = data.get("members") or group_data.get("members") or []

        self.assertEqual(int(group_data.get("id") or data.get("group_id") or 0), self.programmed_group.id)
        self.assertEqual(group_data.get("label") or group_data.get("nom") or data.get("group_label"), "Final")
        self.assertTrue(group_data.get("is_programmed", data.get("is_programmed")))
        self.assertEqual([member.get("nom") for member in members], ["Programmed A", "Programmed B"])

    def test_groups_detail_contract_supports_member_pagination(self):
        resp = self._post_groups_contract(
            "detail",
            {"group_id": self.programmed_group.id, "page": 2, "page_size": 1},
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        group_data = data.get("group") or {}
        members = data.get("members") or group_data.get("members") or []

        self.assertEqual(int(group_data.get("members_total") or 0), 2)
        self.assertEqual(int(group_data.get("members_page") or 0), 2)
        self.assertEqual(int(group_data.get("members_page_size") or 0), 1)
        self.assertEqual(int(group_data.get("members_total_pages") or 0), 2)
        self.assertTrue(group_data.get("members_has_prev"))
        self.assertFalse(group_data.get("members_has_next"))
        self.assertEqual([member.get("nom") for member in members], ["Programmed B"])

    def test_groups_detail_contract_returns_consistent_empty_pagination(self):
        empty_group = GrupCompeticio.objects.create(
            competicio=self.comp,
            legacy_num=9,
            display_num=9,
            nom="Empty detail",
            actiu=True,
        )

        resp = self._post_groups_contract(
            "detail",
            {"group_id": empty_group.id},
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        group_data = data.get("group") or {}

        self.assertEqual(group_data.get("members"), [])
        self.assertEqual(int(group_data.get("members_total") or 0), 0)
        self.assertEqual(int(group_data.get("members_page") or 0), 1)
        self.assertEqual(int(group_data.get("members_total_pages") or 0), 1)
        self.assertFalse(group_data.get("members_has_prev"))
        self.assertFalse(group_data.get("members_has_next"))

    def test_groups_preview_contract_reports_reduced_and_removed_programmed_groups(self):
        single_group = GrupCompeticio.objects.create(
            competicio=self.comp,
            legacy_num=4,
            display_num=4,
            nom="Single",
            actiu=True,
        )
        single_member = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Single Member",
            ordre_sortida=6,
            grup=4,
        )
        self._attach_rotation_to_group(single_group)

        resp = self._post_groups_contract(
            "preview",
            {
                "scope": "selected",
                "selected_ids": [self.ins_programmed_a.id],
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "action": "unassign",
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        preview = data.get("preview") or data
        existing_groups = preview.get("existing_groups") or []
        self.assertTrue(existing_groups)
        self.assertTrue(
            any(row.get("impact_kind") == "reduced" for row in existing_groups)
            or any(row.get("impact_kind") == "removed" for row in existing_groups)
        )

        resp_removed = self._post_groups_contract(
            "preview",
            {
                "scope": "selected",
                "selected_ids": [single_member.id],
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "action": "unassign",
            },
        )
        self.assertEqual(resp_removed.status_code, 200)
        removed_preview = resp_removed.json().get("preview") or resp_removed.json()
        removed_groups = removed_preview.get("existing_groups") or []
        self.assertTrue(any(row.get("impact_kind") == "removed" for row in removed_groups))

    def test_groups_preview_uses_selected_ids_even_when_legacy_filtered_scope_is_sent(self):
        resp = self._post_groups_contract(
            "preview",
            {
                "scope": "filtered",
                "selected_ids": [self.ins_free_a.id],
                "filters": {
                    "q": "",
                    "categoria": "",
                    "subcategoria": "",
                    "entitat": "",
                    "group_state": "unassigned",
                },
                "action": "create",
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        preview = data.get("preview") or {}
        self.assertEqual(int((preview.get("selection") or {}).get("count") or 0), 1)
        self.assertEqual(int(preview.get("target_ids_count") or 0), 1)
        self.assertEqual(
            [row.get("members_count") for row in (preview.get("planned_groups") or [])],
            [1],
        )

    def test_groups_preview_per_bucket_with_bucket_selection_mode_none_returns_empty_plan(self):
        self.ins_free_a.categoria = "Alevi"
        self.ins_free_a.save(update_fields=["categoria"])
        self.ins_free_b.categoria = "Infantil"
        self.ins_free_b.save(update_fields=["categoria"])

        resp = self._post_json(
            "inscripcions_groups_from_sort",
            self._groups_payload(
                strategy="per_bucket",
                preview_only=True,
                scope="selected",
                selected_ids=[self.ins_free_a.id, self.ins_free_b.id],
                group_by=["categoria"],
                selected_keys=[],
                bucket_selection_mode="none",
            ),
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(int(data.get("buckets_total") or 0), 2)
        self.assertEqual(int(data.get("buckets_applied") or 0), 0)
        preview = data.get("preview") or {}
        self.assertEqual(int(preview.get("groups_total") or 0), 0)
        self.assertEqual(int(preview.get("members_total") or 0), 0)

    def test_groups_create_contract_assigns_selected_ids_to_new_group(self):
        expected_group_num = next_group_display_num(self.comp)
        resp = self._post_groups_contract(
            "create",
            {
                "scope": "selected",
                "selected_ids": [self.ins_free_a.id, self.ins_free_b.id],
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertIn("history", data)

        created_group = GrupCompeticio.objects.get(competicio=self.comp, display_num=expected_group_num)
        self.ins_free_a.refresh_from_db()
        self.ins_free_b.refresh_from_db()
        self.assertEqual(self.ins_free_a.grup, expected_group_num)
        self.assertEqual(self.ins_free_b.grup, expected_group_num)
        self.assertEqual(self.ins_free_a.ordre_competicio, 1)
        self.assertEqual(self.ins_free_b.ordre_competicio, 2)
        self.assertEqual(created_group.actiu, True)

    def test_groups_assign_contract_warns_when_programmed_group_is_reduced_but_not_emptied(self):
        resp = self._post_groups_contract(
            "assign",
            {
                "group_id": self.other_group.id,
                "scope": "selected",
                "selected_ids": [self.ins_programmed_a.id],
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            },
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertIn("history", data)
        self.assertTrue(data.get("warnings") or data.get("warning") or data.get("notice"))

        self.ins_programmed_a.refresh_from_db()
        self.ins_programmed_b.refresh_from_db()
        self.assertEqual(self.ins_programmed_a.grup, 2)
        self.assertEqual(self.ins_programmed_b.grup, 1)

    def test_groups_unassign_contract_blocks_when_programmed_group_would_be_emptied(self):
        single_group = GrupCompeticio.objects.create(
            competicio=self.comp,
            legacy_num=5,
            display_num=5,
            nom="Programmed Single",
            actiu=True,
        )
        single_member = Inscripcio.objects.create(
            competicio=self.comp,
            nom_i_cognoms="Programmed Single Member",
            ordre_sortida=7,
            grup=5,
        )
        self._attach_rotation_to_group(single_group)

        resp = self._post_groups_contract(
            "unassign",
            {
                "scope": "selected",
                "selected_ids": [single_member.id],
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            },
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("program", resp.content.decode("utf-8").lower())

    def test_groups_delete_contract_deactivates_empty_group_only(self):
        resp = self._post_groups_contract(
            "delete",
            {"group_id": self.empty_group.id},
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertIn("history", data)

        self.empty_group.refresh_from_db()
        self.assertFalse(self.empty_group.actiu)

    def test_groups_delete_empty_contract_deactivates_all_empty_groups_only(self):
        extra_empty_group = GrupCompeticio.objects.create(
            competicio=self.comp,
            legacy_num=6,
            display_num=6,
            nom="Extra Empty",
            actiu=True,
        )

        resp = self._post_groups_contract("delete-empty", {})

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("deleted"), 2)

        self.empty_group.refresh_from_db()
        extra_empty_group.refresh_from_db()
        self.programmed_group.refresh_from_db()
        self.other_group.refresh_from_db()

        self.assertFalse(self.empty_group.actiu)
        self.assertFalse(extra_empty_group.actiu)
        self.assertTrue(self.programmed_group.actiu)
        self.assertTrue(self.other_group.actiu)

    def test_groups_delete_all_contract_deactivates_non_programmed_groups_only(self):
        resp = self._post_groups_contract("delete-all", {})

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(int(data.get("deleted") or 0), 2)
        self.assertEqual(int(data.get("protected") or 0), 1)
        self.assertEqual(
            [row.get("label") for row in (data.get("protected_groups") or [])],
            [group_label(self.programmed_group)],
        )

        self.programmed_group.refresh_from_db()
        self.other_group.refresh_from_db()
        self.empty_group.refresh_from_db()
        self.ins_programmed_a.refresh_from_db()
        self.ins_programmed_b.refresh_from_db()
        self.ins_other.refresh_from_db()

        self.assertTrue(self.programmed_group.actiu)
        self.assertFalse(self.other_group.actiu)
        self.assertFalse(self.empty_group.actiu)
        self.assertEqual(self.ins_programmed_a.grup_competicio_id, self.programmed_group.id)
        self.assertEqual(self.ins_programmed_b.grup_competicio_id, self.programmed_group.id)
        self.assertIsNone(self.ins_other.grup_competicio_id)
        self.assertIsNone(self.ins_other.grup)
        self.assertIsNone(self.ins_other.ordre_competicio)
