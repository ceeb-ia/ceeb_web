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

from .... import live_cache
from ....access import user_has_competicio_capability
from ....forms import CompeticioAparellForm
from ....models import (
    Competicio,
    Equip,
    EquipContext,
    GrupCompeticio,
    Inscripcio,
    InscripcioEquipAssignacio,
    InscripcioMedia,
)
from ....models.judging import (
    JudgeConversation,
    JudgeConversationMessage,
    JudgeDeviceToken,
    PublicLiveToken,
)
from ....models.classificacions import ClassificacioConfig, ClassificacioTemplateGlobal
from ....models.rotacions import (
    RotacioAssignacio,
    RotacioAssignacioGrup,
    RotacioAssignacioSerieEquip,
    RotacioEstacio,
    RotacioFranja,
)
from ....models.scoring import (
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
from ....models.competicio import (
    Aparell,
    CompeticioAparell,
    CompeticioAparellEquipContextSource,
    InscripcioAparellExclusio,
)
from ....models import CompeticioMembership
from ....scoring_engine import ScoringEngine
from ....services.inscripcions.groups import renumber_groups_for_competicio
from ....services.inscripcions.sorting import (
    _split_custom_sort_tokens,
    sort_records_by_field_stable,
)
from ....services.inscripcions.history import (
    apply_inscripcions_history_snapshot,
    capture_inscripcions_history_snapshot,
)
from ....services.inscripcions.queries import (
    COLUMN_FILTER_EMPTY_TOKEN,
    _build_inscripcions_filtered_qs,
    _resolve_group_creation_buckets,
    build_inscripcions_sort_context_key,
    get_competicio_custom_sort_rank_map,
)
from ....services.classificacions.builder import scoreable_codes_by_app_id as _scoreable_codes_by_app_id
from ....services.classificacions.compute import DEFAULT_SCHEMA, compute_classificacio
from ....services.classificacions.export import _normalize_excel_cell
from ....services.classificacions.partitions import normalize_schema_legacy_team_birth_partition
from ....services.classificacions.validation import (
    build_metric_meta_for_comp_aparell as _build_metric_meta_for_comp_aparell,
    build_scoreable_meta_for_schema as _build_scoreable_meta_for_schema,
    validate_particions_schema as _validate_particions_schema,
    validate_schema_for_competicio as _validate_schema_for_competicio,
)
from ....services.classificacions.classificacio_templates import (
    normalize_particions_schema as _normalize_particions_schema,
    schema_to_template_schema as _schema_to_template_schema,
    template_schema_to_competicio_schema as _template_schema_to_competicio_schema,
)
from ....views.classificacions.builder import ClassificacionsHome
from ....services.shared.competition_groups import (
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
from ....services.scoring.team_scoring import (
    build_permission_label,
    build_team_subjects_for_comp_aparell,
    resolve_permission_runtime_entries,
    runtime_schema_for_comp_aparell,
)
from ....services.teams.team_series import safe_deactivate_empty_serie
from ....views.judge.admin import _member_slot_choices, _validate_permission_row
from ....templatetags.competicio_extras import (
    DEFAULT_COMPETITION_BACKGROUND,
    get_competicio_background_url_from_request,
)

from ...base import _BaseTrampoliDataMixin



from ._base import InscripcionsSortFlowBaseMixin


class InscripcionsSortBirthRangeTests(InscripcionsSortFlowBaseMixin, TestCase):
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
        self.assertContains(response, 'id="panel-grups"')
        self.assertContains(response, 'data-panel-lazy="1"')
        self.assertNotContains(response, 'id="groups-workspace-shell"')

        panel_response = self.client.get(
            reverse("inscripcions_list", kwargs={"pk": self.comp.id}),
            {"__fragments": "panel", "__panel_key": "grups"},
        )
        self.assertEqual(panel_response.status_code, 200)
        panel_html = panel_response.json()["fragments"]["panel"]["html"]
        self.assertIn('id="groups-workspace-shell"', panel_html)
        self.assertIn("Divisions actives:", panel_html)
        self.assertIn("Ordenacions detectades:", panel_html)
        self.assertIn("Resolucio final:", panel_html)
        self.assertNotIn("Base de creacio:", panel_html)
        self.assertNotIn("Crear grups per pestanyes", panel_html)
        self.assertNotIn("Crear grups per ordenacio", panel_html)
        self.assertIn('id="groups-board-filter-q"', panel_html)
        self.assertIn('id="groups-board-filter-categoria"', panel_html)
        self.assertIn('id="groups-board-filter-program-state"', panel_html)
        self.assertIn('id="groups-board-filter-count"', panel_html)
        self.assertIn('id="btn-groups-board-filters-toggle"', panel_html)
        self.assertIn('id="groups-board-filters-panel"', panel_html)

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

