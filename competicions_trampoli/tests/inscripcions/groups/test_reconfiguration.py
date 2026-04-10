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


