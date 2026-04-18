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

from ... import live_cache
from ...access import user_has_competicio_capability
from ...forms import CompeticioAparellForm
from ...models import (
    Competicio,
    Equip,
    EquipContext,
    GrupCompeticio,
    Inscripcio,
    InscripcioEquipAssignacio,
    InscripcioMedia,
)
from ...models.judging import (
    JudgeConversation,
    JudgeConversationMessage,
    JudgeDeviceToken,
    PublicLiveToken,
)
from ...models.classificacions import ClassificacioConfig, ClassificacioTemplateGlobal
from ...models.rotacions import (
    RotacioAssignacio,
    RotacioAssignacioGrup,
    RotacioAssignacioSerieEquip,
    RotacioEstacio,
    RotacioFranja,
)
from ...models.scoring import (
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
from ...models.competicio import (
    Aparell,
    CompeticioAparell,
    CompeticioAparellEquipContextSource,
    InscripcioAparellExclusio,
)
from ...models import CompeticioMembership
from ...scoring_engine import ScoringEngine
from ...services.inscripcions.groups import renumber_groups_for_competicio
from ...services.inscripcions.sorting import (
    _split_custom_sort_tokens,
    sort_records_by_field_stable,
)
from ...services.inscripcions.history import (
    apply_inscripcions_history_snapshot,
    capture_inscripcions_history_snapshot,
)
from ...services.inscripcions.queries import (
    COLUMN_FILTER_EMPTY_TOKEN,
    _build_inscripcions_filtered_qs,
    build_inscripcions_sort_context_key,
    get_competicio_custom_sort_rank_map,
)
from ...services.classificacions.classificacio_templates import (
    normalize_particions_schema as _normalize_particions_schema,
    schema_to_template_schema as _schema_to_template_schema,
    validate_template_schema_global as _validate_template_schema_global,
    template_schema_to_competicio_schema as _template_schema_to_competicio_schema_service,
)
from ...services.classificacions.builder import (
    prepare_schema_for_builder_hydration,
    scoreable_codes_by_app_id as _scoreable_codes_by_app_id,
)
from ...services.classificacions.compute import DEFAULT_SCHEMA, compute_classificacio
from ...services.classificacions.export import _normalize_excel_cell
from ...services.classificacions.partitions import normalize_schema_legacy_team_birth_partition
from ...services.classificacions.validation import (
    build_metric_meta_for_comp_aparell as _build_metric_meta_for_comp_aparell,
    build_scoreable_meta_for_schema as _build_scoreable_meta_for_schema,
    validate_particions_schema as _validate_particions_schema,
    validate_schema_for_competicio as _validate_schema_for_competicio,
)
from ...views.classificacions.builder import ClassificacionsHome
from ...services.shared.competition_groups import (
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
from ...services.scoring.team_scoring import (
    build_permission_label,
    build_team_subjects_for_comp_aparell,
    resolve_permission_runtime_entries,
    runtime_schema_for_comp_aparell,
)
from ...services.teams.team_series import safe_deactivate_empty_serie
from ...views.judge.admin import _member_slot_choices, _validate_permission_row
from ...templatetags.competicio_extras import (
    DEFAULT_COMPETITION_BACKGROUND,
    get_competicio_background_url_from_request,
)

from ..base import _BaseTrampoliDataMixin


def _template_schema_to_competicio_schema(*args, **kwargs):
    schema_local, mapping_warnings, mapping, _compat_meta = _template_schema_to_competicio_schema_service(
        *args,
        **kwargs,
    )
    return schema_local, mapping_warnings, mapping


class GlobalClassificacioTemplateManagementTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="global_tpl_owner",
            password="testpass123",
            email="global-tpl-owner@example.com",
        )
        self.other_user = User.objects.create_user(
            username="global_tpl_other",
            password="testpass123",
            email="global-tpl-other@example.com",
        )
        self.admin_user = User.objects.create_superuser(
            username="global_tpl_admin",
            password="testpass123",
            email="global-tpl-admin@example.com",
        )
        manager_group = Group.objects.get_or_create(name="competicions_manager")[0]
        self.user.groups.add(manager_group)
        self.other_user.groups.add(manager_group)
        self.app = self._create_aparell("TRAMP_GLOB", "Tramp Global", owner=self.user)
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "fields": [
                    {"code": "E", "label": "Execucio", "type": "number"},
                ],
                "computed": [
                    {"code": "TOTAL", "formula": "E"},
                ],
            },
        )
        self.team_app = self._create_aparell("SYNC_GLOB", "Sync Global", owner=self.user)
        self.team_app.competition_unit = Aparell.CompetitionUnit.TEAM
        self.team_app.save(update_fields=["competition_unit"])
        ScoringSchema.objects.create(
            aparell=self.team_app,
            schema={
                "meta": {"subject_mode": "team"},
                "fields": [
                    {
                        "code": "E",
                        "label": "Execucio",
                        "scope": "member",
                        "type": "matrix",
                        "shape": "judge_x_item",
                        "judges": {"count": 3},
                        "items": {"count": 5},
                    },
                    {
                        "code": "SYNC",
                        "label": "Sync",
                        "scope": "shared",
                        "type": "number",
                    },
                ],
                "computed": [
                    {
                        "code": "E_mem",
                        "label": "Execucio membre",
                        "formula": "row_custom_compute('E', '1 - x')",
                    },
                    {
                        "code": "E_by_judge",
                        "label": "Execucio by judge",
                        "formula": "row_custom_compute('E', '1 - x', return_mode='by_judge')",
                    },
                ],
            },
        )
        self.comp = self._create_competicio("Comp Global Templates")
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)
        CompeticioMembership.objects.create(
            user=self.user,
            competicio=self.comp,
            role=CompeticioMembership.Role.EDITOR,
            is_active=True,
        )

    def _build_global_schema_payload(self, app_id):
        schema = json.loads(json.dumps(DEFAULT_SCHEMA))
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": [app_id]}
        schema["puntuacio"]["camps_per_aparell"] = {str(app_id): ["total"]}
        schema["presentacio"]["columnes"] = [
            {"type": "builtin", "key": "posicio", "label": "#", "align": "left"},
            {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
            {"type": "builtin", "key": "punts", "label": "Punts", "align": "right", "decimals": 3},
        ]
        return schema

    def _build_global_native_team_schema_payload(self, app_id):
        schema = self._build_global_schema_payload(app_id)
        schema["equips"] = {
            "context_code": "native",
            "team_mode": "native_team",
        }
        return schema

    def test_owner_can_create_list_and_delete_global_template(self):
        self.client.force_login(self.user)
        save_url = reverse("classificacio_template_global_save")
        payload = {
            "nom": "Plantilla Global 1",
            "slug": "plantilla-global-1",
            "activa": True,
            "tipus": "individual",
            "schema": self._build_global_schema_payload(self.app.id),
        }
        res = self.client.post(save_url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body.get("ok"))
        cfg = body.get("cfg") or {}
        tpl = ClassificacioTemplateGlobal.objects.get(pk=cfg.get("id"))
        self.assertEqual(((tpl.payload or {}).get("schema") or {}).get("puntuacio", {}).get("aparells", {}).get("ids"), [self.app.codi])
        self.assertEqual(tpl.slug, "plantilla-global-1")

        list_url = reverse("classificacio_template_global_list")
        list_res = self.client.get(list_url)
        self.assertEqual(list_res.status_code, 200)
        self.assertContains(list_res, "Plantilla Global 1")

        delete_url = reverse("classificacio_template_global_delete", kwargs={"pk": tpl.id})
        delete_res = self.client.post(
            delete_url,
            data=json.dumps({}),
            content_type="application/json",
            HTTP_ACCEPT="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(delete_res.status_code, 200)
        self.assertFalse(ClassificacioTemplateGlobal.objects.filter(pk=tpl.id).exists())

    def test_global_template_save_roundtrips_presentacio_detall_schema(self):
        self.client.force_login(self.user)
        save_url = reverse("classificacio_template_global_save")
        schema = self._build_global_schema_payload(self.app.id)
        schema["equips"] = {
            "context_code": "ctx-finals",
            "assignment_source": {"mode": "context", "context_code": "ctx-finals", "fallback": "native"},
            "team_mode": "derived_from_individual",
        }
        schema["presentacio"]["detall"] = {
            "enabled": True,
            "default_open": True,
            "sections": [
                {
                    "type": "members_table",
                    "label": "Detall",
                    "aparell_id": self.app.id,
                    "columns": [
                        {"type": "builtin", "key": "participant", "label": "Participant", "align": "left"},
                        {
                            "type": "raw",
                            "key": "detail_total",
                            "label": "Total",
                            "align": "right",
                            "decimals": 3,
                            "source": {"aparell_id": self.app.id, "exercici": 1, "camp": "total", "jutges": {"ids": []}},
                        },
                    ],
                }
            ],
        }
        res = self.client.post(
            save_url,
            data=json.dumps(
                {
                    "nom": "Plantilla Global Detail",
                    "slug": "plantilla-global-detail",
                    "activa": True,
                    "tipus": "equips",
                    "schema": schema,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body.get("ok"))

        cfg = body.get("cfg") or {}
        detail_ui_section = (((((cfg.get("schema") or {}).get("presentacio") or {}).get("detall") or {}).get("sections")) or [])[0]
        detail_ui = detail_ui_section["columns"]
        self.assertEqual(detail_ui_section["aparell_id"], self.app.id)
        self.assertEqual(detail_ui[1]["source"]["aparell_id"], self.app.id)

        tpl = ClassificacioTemplateGlobal.objects.get(pk=cfg.get("id"))
        detail_tpl = (((tpl.payload or {}).get("schema") or {}).get("presentacio") or {}).get("detall") or {}
        self.assertTrue(detail_tpl.get("enabled"))
        detail_tpl_section = (detail_tpl.get("sections") or [])[0] or {}
        detail_tpl_cols = detail_tpl_section.get("columns") or []
        self.assertEqual(detail_tpl_section.get("aparell_codi"), self.app.codi)
        self.assertEqual(detail_tpl_cols[1]["source"]["aparell_codi"], self.app.codi)
        self.assertIn("total", tpl.requirements.get("presentacio_raw_camps") or [])

    def test_global_template_save_returns_error_details_for_invalid_detail_section_field(self):
        self.client.force_login(self.user)
        save_url = reverse("classificacio_template_global_save")
        schema = self._build_global_schema_payload(self.app.id)
        schema["presentacio"]["detall"] = {
            "enabled": True,
            "sections": [
                {
                    "type": "exercise_table",
                    "label": "Exercicis",
                    "aparell_id": self.app.id,
                    "columns": [
                        {"type": "builtin", "key": "exercise_index", "label": "Ex.", "align": "left"},
                        {
                            "type": "raw",
                            "key": "detail_bad",
                            "label": "Camp invalid",
                            "align": "right",
                            "decimals": 3,
                            "source": {"aparell_id": self.app.id, "exercici": 1, "camp": "NO_EXISTEIX", "jutges": {"ids": []}},
                        },
                    ],
                }
            ],
        }
        res = self.client.post(
            save_url,
            data=json.dumps(
                {
                    "nom": "Plantilla Global Error Detail",
                    "slug": "plantilla-global-error-detail",
                    "activa": True,
                    "tipus": "individual",
                    "schema": schema,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)
        body = res.json()
        details = body.get("error_details") or []
        self.assertTrue(any(item.get("path") == "presentacio.detall.sections[0].columns[1].source.camp" for item in details))

    def test_global_template_save_defers_detail_exercise_range_validation_until_competicio(self):
        self.client.force_login(self.user)
        save_url = reverse("classificacio_template_global_save")
        schema = self._build_global_schema_payload(self.app.id)
        schema["presentacio"]["detall"] = {
            "enabled": True,
            "sections": [
                {
                    "type": "exercise_table",
                    "label": "Exercicis",
                    "aparell_id": self.app.id,
                    "columns": [
                        {"type": "builtin", "key": "exercise_index", "label": "Ex.", "align": "left"},
                        {
                            "type": "raw",
                            "key": "detail_total",
                            "label": "Total",
                            "align": "right",
                            "decimals": 3,
                            "source": {"aparell_id": self.app.id, "exercici": 99, "camp": "TOTAL", "jutges": {"ids": []}},
                        },
                    ],
                }
            ],
        }
        save_res = self.client.post(
            save_url,
            data=json.dumps(
                {
                    "nom": "Plantilla Global Exercise Deferred",
                    "slug": "plantilla-global-exercise-deferred",
                    "activa": True,
                    "tipus": "individual",
                    "schema": schema,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(save_res.status_code, 200)
        tpl_id = (save_res.json().get("cfg") or {}).get("id")
        self.assertTrue(tpl_id)

        validate_res = self.client.post(
            reverse("classificacio_template_validate", kwargs={"pk": self.comp.id}),
            data=json.dumps({"template_id": tpl_id}),
            content_type="application/json",
        )
        self.assertEqual(validate_res.status_code, 200)
        validate_body = validate_res.json()
        self.assertFalse(validate_body.get("compatible"))
        self.assertTrue(
            any("source.exercici" in str(err or "") or "fora de rang" in str(err or "") for err in validate_body.get("blocking_errors", []))
        )

    def test_global_builder_context_exposes_displayable_member_fields_for_native_team(self):
        self.client.force_login(self.user)
        res = self.client.get(reverse("classificacio_template_global_create"))
        self.assertEqual(res.status_code, 200)

        options = res.context["aparell_field_options"][str(self.team_app.id)]
        by_code = {item["code"]: item for item in options}
        self.assertEqual(
            next(item for item in res.context["aparells"] if item["id"] == self.team_app.id)["competition_unit"],
            "team",
        )
        self.assertIn("E", by_code)
        self.assertFalse(by_code["E"]["scoreable"])
        self.assertTrue(by_code["E"]["member_dependent"])
        self.assertTrue(by_code["E"]["detail_displayable"])
        self.assertEqual(by_code["E"]["detail_display_kind"], "judge_rows")
        self.assertTrue(by_code["E_mem"]["detail_displayable"])
        self.assertEqual(by_code["E_mem"]["detail_display_kind"], "scalar")

    def test_global_template_save_accepts_native_team_team_members_table_display_only_member_field(self):
        self.client.force_login(self.user)
        save_url = reverse("classificacio_template_global_save")
        schema = self._build_global_native_team_schema_payload(self.team_app.id)
        schema["presentacio"]["detall"] = {
            "enabled": True,
            "sections": [
                {
                    "type": "team_members_table",
                    "label": "Notes per membre",
                    "aparell_id": self.team_app.id,
                    "columns": [
                        {
                            "type": "raw",
                            "key": "member_exec",
                            "label": "Exec",
                            "align": "right",
                            "decimals": 3,
                            "source": {
                                "aparell_id": self.team_app.id,
                                "exercise_mode": "fixed",
                                "exercici": 1,
                                "camp": "E",
                                "jutges": {"ids": []},
                            },
                        },
                    ],
                }
            ],
        }

        res = self.client.post(
            save_url,
            data=json.dumps(
                {
                    "nom": "Plantilla Global Team Member Detail",
                    "slug": "plantilla-global-team-member-detail",
                    "activa": True,
                    "tipus": "equips",
                    "schema": schema,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body.get("ok"))
        detail_ui_section = (((((body.get("cfg") or {}).get("schema") or {}).get("presentacio") or {}).get("detall") or {}).get("sections") or [])[0]
        self.assertEqual((((detail_ui_section or {}).get("columns") or [])[0].get("source") or {}).get("exercise_mode"), "fixed")
        tpl = ClassificacioTemplateGlobal.objects.get(pk=(body.get("cfg") or {}).get("id"))
        detail_tpl_section = (((((tpl.payload or {}).get("schema") or {}).get("presentacio") or {}).get("detall") or {}).get("sections") or [])[0]
        self.assertEqual((((detail_tpl_section or {}).get("columns") or [])[0].get("source") or {}).get("exercise_mode"), "fixed")

    def test_global_template_save_infers_team_members_table_section_app_from_single_raw_app(self):
        self.client.force_login(self.user)
        save_url = reverse("classificacio_template_global_save")
        schema = self._build_global_native_team_schema_payload(self.team_app.id)
        schema["presentacio"]["detall"] = {
            "enabled": True,
            "sections": [
                {
                    "type": "team_members_table",
                    "label": "Notes per membre",
                    "columns": [
                        {
                            "type": "raw",
                            "key": "member_exec",
                            "label": "Exec",
                            "align": "right",
                            "decimals": 3,
                            "source": {"aparell_id": self.team_app.id, "exercici": 1, "camp": "E", "jutges": {"ids": []}},
                        },
                    ],
                }
            ],
        }

        res = self.client.post(
            save_url,
            data=json.dumps(
                {
                    "nom": "Plantilla Global Team Member Detail Inferred App",
                    "slug": "plantilla-global-team-member-detail-inferred-app",
                    "activa": True,
                    "tipus": "equips",
                    "schema": schema,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body.get("ok"))
        section = (((((body.get("cfg") or {}).get("schema") or {}).get("presentacio") or {}).get("detall") or {}).get("sections") or [])[0]
        self.assertEqual((section or {}).get("aparell_id"), self.team_app.id)

    def test_global_template_save_rejects_native_team_team_members_table_shared_field(self):
        self.client.force_login(self.user)
        save_url = reverse("classificacio_template_global_save")
        schema = self._build_global_native_team_schema_payload(self.team_app.id)
        schema["presentacio"]["detall"] = {
            "enabled": True,
            "sections": [
                {
                    "type": "team_members_table",
                    "label": "Notes per membre",
                    "aparell_id": self.team_app.id,
                    "columns": [
                        {
                            "type": "raw",
                            "key": "team_sync",
                            "label": "Sync",
                            "align": "right",
                            "decimals": 3,
                            "source": {"aparell_id": self.team_app.id, "exercici": 1, "camp": "SYNC", "jutges": {"ids": []}},
                        },
                    ],
                }
            ],
        }

        res = self.client.post(
            save_url,
            data=json.dumps(
                {
                    "nom": "Plantilla Global Team Shared Reject",
                    "slug": "plantilla-global-team-shared-reject",
                    "activa": True,
                    "tipus": "equips",
                    "schema": schema,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertTrue(any("team_members_table" in err for err in (res.json().get("errors") or [])))

    def test_global_template_save_rejects_native_team_team_members_table_non_displayable_field(self):
        self.client.force_login(self.user)
        save_url = reverse("classificacio_template_global_save")
        schema = self._build_global_native_team_schema_payload(self.team_app.id)
        schema["presentacio"]["detall"] = {
            "enabled": True,
            "sections": [
                {
                    "type": "team_members_table",
                    "label": "Notes per membre",
                    "aparell_id": self.team_app.id,
                    "columns": [
                        {
                            "type": "raw",
                            "key": "member_exec_bad",
                            "label": "Exec by judge",
                            "align": "right",
                            "decimals": 3,
                            "source": {"aparell_id": self.team_app.id, "exercici": 1, "camp": "E_by_judge", "jutges": {"ids": []}},
                        },
                    ],
                }
            ],
        }

        res = self.client.post(
            save_url,
            data=json.dumps(
                {
                    "nom": "Plantilla Global Team Non Displayable Reject",
                    "slug": "plantilla-global-team-non-displayable-reject",
                    "activa": True,
                    "tipus": "equips",
                    "schema": schema,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertTrue(any("no es visualitzable a team_members_table" in err for err in (res.json().get("errors") or [])))

    def test_global_template_save_rejects_native_team_team_metrics_member_field(self):
        self.client.force_login(self.user)
        save_url = reverse("classificacio_template_global_save")
        schema = self._build_global_native_team_schema_payload(self.team_app.id)
        schema["presentacio"]["detall"] = {
            "enabled": True,
            "sections": [
                {
                    "type": "team_metrics",
                    "label": "Notes equip",
                    "aparell_id": self.team_app.id,
                    "columns": [
                        {
                            "type": "raw",
                            "key": "member_exec",
                            "label": "Exec",
                            "align": "right",
                            "decimals": 3,
                            "source": {"aparell_id": self.team_app.id, "exercici": 1, "camp": "E_mem", "jutges": {"ids": []}},
                        },
                    ],
                }
            ],
        }

        res = self.client.post(
            save_url,
            data=json.dumps(
                {
                    "nom": "Plantilla Global Team Metrics Reject",
                    "slug": "plantilla-global-team-metrics-reject",
                    "activa": True,
                    "tipus": "equips",
                    "schema": schema,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertTrue(any("team_metrics" in err for err in (res.json().get("errors") or [])))

    def test_global_template_save_rejects_native_team_main_column_member_field(self):
        self.client.force_login(self.user)
        save_url = reverse("classificacio_template_global_save")
        schema = self._build_global_native_team_schema_payload(self.team_app.id)
        schema["presentacio"]["columnes"] = [
            {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
            {
                "type": "raw",
                "key": "member_exec",
                "label": "Exec",
                "align": "right",
                "decimals": 3,
                "source": {"aparell_id": self.team_app.id, "exercici": 1, "camp": "E_mem", "jutges": {"ids": []}},
            },
        ]

        res = self.client.post(
            save_url,
            data=json.dumps(
                {
                    "nom": "Plantilla Global Team Main Reject",
                    "slug": "plantilla-global-team-main-reject",
                    "activa": True,
                    "tipus": "equips",
                    "schema": schema,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertTrue(any("camps individuals per membre" in err for err in (res.json().get("errors") or [])))

    def test_owner_list_hides_foreign_templates_and_admin_sees_both(self):
        own_tpl = ClassificacioTemplateGlobal.objects.create(
            nom="Tpl Own",
            slug="tpl-own",
            tipus="individual",
            activa=True,
            payload={"schema": {}},
            requirements={},
            created_by=self.user,
        )
        foreign_tpl = ClassificacioTemplateGlobal.objects.create(
            nom="Tpl Foreign",
            slug="tpl-foreign",
            tipus="individual",
            activa=True,
            payload={"schema": {}},
            requirements={},
            created_by=self.other_user,
        )

        list_url = reverse("classificacio_template_global_list")

        self.client.force_login(self.user)
        owner_res = self.client.get(list_url)
        self.assertContains(owner_res, own_tpl.nom)
        self.assertNotContains(owner_res, foreign_tpl.nom)

        self.client.force_login(self.admin_user)
        admin_res = self.client.get(list_url)
        self.assertContains(admin_res, own_tpl.nom)
        self.assertContains(admin_res, foreign_tpl.nom)

    def test_foreign_user_cannot_delete_template(self):
        tpl = ClassificacioTemplateGlobal.objects.create(
            nom="Tpl Locked",
            slug="tpl-locked",
            tipus="individual",
            activa=True,
            payload={"schema": {}},
            requirements={},
            created_by=self.user,
        )
        self.client.force_login(self.other_user)
        delete_url = reverse("classificacio_template_global_delete", kwargs={"pk": tpl.id})
        res = self.client.post(delete_url, data=json.dumps({}), content_type="application/json", HTTP_ACCEPT="application/json")
        self.assertEqual(res.status_code, 404)

    def test_owner_can_update_global_template_and_version_increments(self):
        tpl = ClassificacioTemplateGlobal.objects.create(
            nom="Tpl Editable",
            slug="tpl-editable",
            tipus="individual",
            activa=True,
            payload={"schema": {"puntuacio": {"aparells": {"mode": "seleccionar", "ids": [self.app.codi]}}}},
            requirements={},
            created_by=self.user,
        )
        self.client.force_login(self.user)
        save_url = reverse("classificacio_template_global_save")
        payload = {
            "id": tpl.id,
            "nom": "Tpl Editable V2",
            "slug": "tpl-editable-v2",
            "activa": False,
            "tipus": "individual",
            "schema": self._build_global_schema_payload(self.app.id),
        }
        res = self.client.post(save_url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 200)
        tpl.refresh_from_db()
        self.assertEqual(tpl.nom, "Tpl Editable V2")
        self.assertEqual(tpl.slug, "tpl-editable-v2")
        self.assertFalse(tpl.activa)
        self.assertEqual(tpl.version, 2)

    def test_global_validation_rejects_invalid_fields(self):
        self.client.force_login(self.user)
        save_url = reverse("classificacio_template_global_save")
        schema = self._build_global_schema_payload(self.app.id)
        schema["particions_v2"] = [{"code": "custom_excel", "apply_mode": "all", "parent_values": []}]
        schema["particions"] = ["custom_excel"]
        schema["puntuacio"]["camps_per_aparell"] = {str(self.app.id): ["NOT_SCOREABLE"]}
        res = self.client.post(
            save_url,
            data=json.dumps(
                {
                    "nom": "Tpl Invalid",
                    "slug": "tpl-invalid",
                    "activa": True,
                    "tipus": "individual",
                    "schema": schema,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertFalse(body.get("ok"))
        self.assertTrue(any("camp no permes" in err for err in body.get("errors", [])))
        self.assertTrue(any("no es puntuable" in err for err in body.get("errors", [])))

    def test_global_template_save_tracks_extended_team_requirements(self):
        self.client.force_login(self.user)
        save_url = reverse("classificacio_template_global_save")
        schema = self._build_global_schema_payload(self.app.id)
        schema["puntuacio"]["exercise_selection_scope"] = "team_pool"
        schema["equips"] = {
            "context_code": "ctx-finals",
            "assignment_source": {"mode": "context", "context_code": "ctx-finals", "fallback": "native"},
            "team_mode": "derived_from_individual",
            "particions_manuals": [
                {"key": "manual_1", "label": "Bloc A", "equips_noms": ["Equip A", "Equip B"]},
            ],
        }
        res = self.client.post(
            save_url,
            data=json.dumps(
                {
                    "nom": "Tpl Equips Portable",
                    "slug": "tpl-equips-portable",
                    "activa": True,
                    "tipus": "equips",
                    "schema": schema,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        tpl = ClassificacioTemplateGlobal.objects.get(slug="tpl-equips-portable")
        req = tpl.requirements or {}
        self.assertEqual(req.get("tipus"), "equips")
        self.assertEqual(req.get("team_mode"), "derived_from_individual")
        self.assertEqual(req.get("context_code"), "ctx-finals")
        self.assertTrue(req.get("uses_manual_team_partitions"))
        self.assertTrue(req.get("uses_exercise_selection_scope"))
        self.assertEqual(req.get("exercise_selection_scope"), "team_pool")
        self.assertEqual(req.get("exercise_selection_scope_modes"), ["team_pool"])
        self.assertEqual(
            ((((tpl.payload or {}).get("schema") or {}).get("equips") or {}).get("particions_manuals") or [])[0].get("equips_noms"),
            ["Equip A", "Equip B"],
        )

    def test_global_edit_preserves_legacy_extra_fields(self):
        legacy_schema = {
            "particions": ["custom_excel"],
            "particions_v2": [{"code": "custom_excel", "apply_mode": "all", "parent_values": []}],
            "particions_custom": {
                "custom_excel": {
                    "mode": "custom",
                    "fallback_label": "Altres",
                    "grups": [{"key": "grp_1", "label": "Bloc X", "values": ["A"]}],
                }
            },
            "filtres": {"custom_excel_in": ["A"]},
            "puntuacio": {
                "aparells": {"mode": "seleccionar", "ids": [self.app.codi]},
                "camps_per_aparell": {self.app.codi: ["total"]},
                "legacy_score_meta": {"origin": "legacy"},
            },
            "presentacio": {
                "legacy_presentacio_flag": True,
                "columnes": [
                    {"type": "builtin", "key": "posicio", "label": "#", "align": "left"},
                    {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                    {"type": "builtin", "key": "punts", "label": "Punts", "align": "right", "decimals": 3},
                ]
            },
            "equips": {
                "legacy_equips_flag": "keep-me",
            },
            "legacy_root_blob": {"foo": "bar"},
        }
        tpl = ClassificacioTemplateGlobal.objects.create(
            nom="Tpl Legacy",
            slug="tpl-legacy",
            tipus="individual",
            activa=True,
            payload={"schema": legacy_schema},
            requirements={},
            created_by=self.user,
        )
        self.client.force_login(self.user)
        res = self.client.post(
            reverse("classificacio_template_global_save"),
            data=json.dumps(
                {
                    "id": tpl.id,
                    "nom": "Tpl Legacy Updated",
                    "slug": "tpl-legacy-updated",
                    "activa": True,
                    "tipus": "individual",
                    "schema": self._build_global_schema_payload(self.app.id),
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        tpl.refresh_from_db()
        saved_schema = (tpl.payload or {}).get("schema") or {}
        self.assertEqual(saved_schema.get("filtres", {}).get("custom_excel_in"), ["A"])
        self.assertIn("custom_excel", saved_schema.get("particions", []))
        self.assertIn("custom_excel", saved_schema.get("particions_custom", {}))
        self.assertEqual(saved_schema.get("legacy_root_blob"), {"foo": "bar"})
        self.assertTrue((saved_schema.get("presentacio") or {}).get("legacy_presentacio_flag"))
        self.assertEqual((saved_schema.get("puntuacio") or {}).get("legacy_score_meta"), {"origin": "legacy"})
        self.assertEqual((saved_schema.get("equips") or {}).get("legacy_equips_flag"), "keep-me")

    def test_global_template_appears_in_competition_template_list(self):
        tpl = ClassificacioTemplateGlobal.objects.create(
            nom="Tpl For Competition",
            slug="tpl-for-competition",
            tipus="individual",
            activa=True,
            payload={"schema": {"puntuacio": {"aparells": {"mode": "seleccionar", "ids": [self.app.codi]}}}},
            requirements={},
            created_by=self.user,
        )
        self.client.force_login(self.user)
        url = reverse("classificacio_template_list", kwargs={"pk": self.comp.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        ids = {int(item["id"]) for item in (res.json().get("templates") or [])}
        self.assertIn(tpl.id, ids)

    def test_global_builder_create_renders_builder_json_contract(self):
        self.client.force_login(self.user)
        url = reverse("classificacio_template_global_create")
        res = self.client.get(url)
        content = res.content.decode("utf-8")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'id="can-manage-global-templates"')
        self.assertContains(res, 'id="builder-save-url"')
        self.assertContains(res, 'id="builder-delete-url-pattern"')
        self.assertContains(res, 'id="builder-preview-url-pattern"')
        self.assertContains(res, 'id="builder-enable-template-library"')
        self.assertContains(res, 'id="builder-can-preview"')
        self.assertContains(res, 'id="builder-selected-id"')
        self.assertContains(res, 'id="builder-auto-add-new"')
        self.assertContains(res, 'id="victoryConfigBox"')
        self.assertContains(res, 'id="sVictoryModeCamps"')
        self.assertContains(res, 'id="sVictoryModeExercicis"')
        self.assertContains(res, 'id="puntuacioSummaryText"')
        self.assertNotContains(res, 'id="participantSelectionCard"')
        self.assertContains(res, 'data-app-participants-mode')
        self.assertContains(res, 'data-app-agregacio-participants')
        self.assertContains(res, 'class="builder-summary-box__text"')
        self.assertNotContains(res, 'id="exSelectionSummary"')
        self.assertContains(res, 'id="candidateScopeHint"')
        self.assertContains(res, 'id="classifHelpDrawer"')
        self.assertContains(res, 'id="classif-builder-back-to-top"')
        self.assertContains(res, "classificacions_builder_help.css")
        self.assertContains(res, "classificacions_builder_help.js")
        self.assertContains(res, 'data-help-key="global_overview"')
        self.assertContains(res, 'data-help-key="desempat_overview"')
        self.assertNotContains(res, '<option value="entitat">Per entitat</option>', html=True)
        self.assertContains(res, 'id="appStaleBanner"')
        self.assertContains(res, "function pruneSchemaAppReferences(schema, allowedIds)")
        self.assertContains(res, "function renderAppStaleWarningBanner(schema, selectedIds)")
        self.assertContains(res, 'buildAparellChecks(selectedCompatibleIds, { includeStale: false });')
        self.assertContains(res, 'const selected = getSingleCompatibleAppId(selectedAppId);')
        self.assertContains(res, '<option value="" ${selected ? "" : "selected"}>Selecciona aparell</option>')
        self.assertContains(res, "refreshTipusUI({ includeStale: false, dropInvalidSelection: true });")
        self.assertContains(res, 'function runSafeHydrationRender(label, renderFn)')
        self.assertContains(res, 'runSafeHydrationRender("columnes", () => {')
        self.assertContains(res, 'runSafeHydrationRender("desempat", () => {')
        self.assertContains(res, 'runSafeHydrationRender("per aparell", () => {')
        self.assertContains(res, 'state.rehydrationIssues = [];')
        self.assertContains(res, "function buildTieCanonicalForSaveFromRow(")
        self.assertContains(res, "function readTieBuilderState(")
        self.assertContains(res, "function readTieCanonicalForSave(")
        self.assertContains(res, "function isMemberSelectionAggregationAvailable()")
        self.assertContains(res, "function _getPerAppParticipantsForUi(punt, appId)")
        self.assertContains(res, "function _copyPuntuacioParticipantsCfg(rawCfg)")
        self.assertContains(res, "function _buildMemberSelectionSegment(perAppEntries)")
        self.assertContains(res, "let desempat = readTieCanonicalForSave(true);")
        self.assertContains(res, "renderTieUI(readTieBuilderState(true));")
        self.assertNotContains(res, "renderTieUI(readTieUI(true));")
        self.assertContains(res, "delete canonical.pipeline.exercicis;")
        self.assertContains(res, "delete canonical.pipeline.exercicis_per_aparell;")
        self.assertContains(res, "delete canonical.pipeline.mode_seleccio_exercicis;")
        self.assertContains(res, "delete canonical.pipeline.participants;")
        self.assertContains(res, "participants_per_aparell")
        self.assertContains(res, "agregacio_participants_per_aparell")
        self.assertEqual(content.count("function buildTieAppScopeOptionsHTML("), 1)
        self.assertContains(res, "function _buildPretractamentSegment(punt, perAppEntries)")
        self.assertContains(res, "function _buildScoreSelectionSegment({")
        self.assertContains(res, "function _buildVictoriesComparisonSegment(victoriesCfg)")
        self.assertNotContains(res, "function buildPuntuacioLiveSummary({")
        self.assertContains(res, "5. Seleccio i agregacio entre membres")
        self.assertContains(res, "5. Combinacio final entre aparells")
        self.assertContains(res, "function previewRenderTeamRawDetailCell(v, col)")
        self.assertContains(res, "En equips derivats, les columnes de camp mostren un resum i el detall per membres de l'equip.")
        self.assertContains(res, "En equips amb nota nativa, les columnes de camp mostren el valor d'equip i nomÃ©s sÃ³n representables per aparells d'equip.")

    def test_validate_template_schema_global_member_selection_step_is_contextual(self):
        schema = {
            "puntuacio": {
                "aparells": {"mode": "seleccionar", "ids": [self.app.codi]},
                "exercise_selection_scope": "per_member",
                "participants_per_aparell": {
                    self.app.codi: {"mode": "millor_1"},
                },
                "agregacio_participants_per_aparell": {
                    self.app.codi: "avg",
                },
            },
            "equips": {
                "team_mode": "derived_from_individual",
            },
        }
        meta = {
            self.app.codi: _build_scoreable_meta_for_schema(
                (ScoringSchema.objects.get(aparell=self.app).schema or {}),
                strict_unknown=True,
            )
        }

        normalized, errors, _details = _validate_template_schema_global(
            schema,
            available_app_codes={self.app.codi},
            field_meta_by_code=meta,
            allowed_particio_codes=set(),
            allowed_filter_keys=set(),
            tipus="equips",
        )
        self.assertFalse(errors)
        punt = normalized.get("puntuacio") or {}
        self.assertEqual(punt.get("participants_per_aparell"), {self.app.codi: {"mode": "millor_1"}})
        self.assertEqual(punt.get("agregacio_participants_per_aparell"), {self.app.codi: "avg"})

    def test_admin_global_builder_edit_is_scoped_to_template_owner_catalog(self):
        own_tpl = ClassificacioTemplateGlobal.objects.create(
            nom="Tpl Owner Scope",
            slug="tpl-owner-scope",
            tipus="individual",
            activa=True,
            payload={"schema": {}},
            requirements={},
            created_by=self.user,
        )
        foreign_app = self._create_aparell("TRAMP_OTHER", "Tramp Other", owner=self.other_user)
        ScoringSchema.objects.create(
            aparell=foreign_app,
            schema={
                "fields": [{"code": "E", "label": "Execucio", "type": "number"}],
                "computed": [{"code": "TOTAL", "formula": "E"}],
            },
        )
        foreign_tpl = ClassificacioTemplateGlobal.objects.create(
            nom="Tpl Foreign Scope",
            slug="tpl-foreign-scope",
            tipus="individual",
            activa=True,
            payload={"schema": {"puntuacio": {"aparells": {"mode": "seleccionar", "ids": [foreign_app.codi]}}}},
            requirements={},
            created_by=self.other_user,
        )

        self.client.force_login(self.admin_user)
        url = reverse("classificacio_template_global_update", kwargs={"pk": foreign_tpl.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, foreign_tpl.nom)
        self.assertNotContains(res, own_tpl.nom)
        self.assertContains(res, foreign_app.nom)
        self.assertNotContains(res, self.app.nom)

    def test_global_builder_edit_exposes_portable_team_context_choices(self):
        tpl = ClassificacioTemplateGlobal.objects.create(
            nom="Tpl Context Portable",
            slug="tpl-context-portable",
            tipus="equips",
            activa=True,
            payload={
                "schema": {
                    "puntuacio": {
                        "aparells": {"mode": "seleccionar", "ids": [self.app.codi]},
                        "camps_per_aparell": {self.app.codi: ["total"]},
                    },
                    "equips": {
                        "context_code": "ctx-finals",
                        "assignment_source": {"mode": "context", "context_code": "ctx-finals", "fallback": "native"},
                        "team_mode": "derived_from_individual",
                        "particions_manuals": [
                            {"key": "manual_1", "label": "Bloc A", "equips_noms": ["Equip A"]},
                        ],
                    },
                    "presentacio": {"columnes": []},
                }
            },
            requirements={},
            created_by=self.user,
        )
        self.client.force_login(self.user)
        res = self.client.get(reverse("classificacio_template_global_update", kwargs={"pk": tpl.id}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "ctx-finals")
        self.assertContains(res, "Equip A")

