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
from ...services.inscripcions import media_matching
from ...services.inscripcions.media_matching import (
    build_inscripcio_media_match_candidates,
    build_inscripcio_media_match_candidate_index,
    match_media_files_to_inscripcions,
)
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
from ...services.classificacions.builder import scoreable_codes_by_app_id as _scoreable_codes_by_app_id
from ...services.classificacions.compute import DEFAULT_SCHEMA, compute_classificacio
from ...services.classificacions.export import _normalize_excel_cell
from ...services.classificacions.partitions import normalize_schema_legacy_team_birth_partition
from ...services.classificacions.validation import (
    build_metric_meta_for_comp_aparell as _build_metric_meta_for_comp_aparell,
    build_scoreable_meta_for_schema as _build_scoreable_meta_for_schema,
    validate_particions_schema as _validate_particions_schema,
    validate_schema_for_competicio as _validate_schema_for_competicio,
)
from ...services.classificacions.classificacio_templates import (
    normalize_particions_schema as _normalize_particions_schema,
    schema_to_template_schema as _schema_to_template_schema,
    template_schema_to_competicio_schema as _template_schema_to_competicio_schema,
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


from ...views.inscripcions.listing import _serialize_listing_media_item

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

    def test_media_matching_uses_shortlist_and_keeps_id_tie_break(self):
        candidates = build_inscripcio_media_match_candidates(
            [
                SimpleNamespace(
                    id=7,
                    nom_i_cognoms="LUCIA POZO SANCHEZ",
                    entitat="Club A",
                    subcategoria="GEN",
                    sexe="F",
                ),
                SimpleNamespace(
                    id=3,
                    nom_i_cognoms="LUCIA POZO SANCHEZ",
                    entitat="Club A",
                    subcategoria="GEN",
                    sexe="F",
                ),
                SimpleNamespace(
                    id=11,
                    nom_i_cognoms="MARC GOMEZ",
                    entitat="Escola Nord",
                    subcategoria="INF",
                    sexe="M",
                ),
            ]
        )
        candidate_index = build_inscripcio_media_match_candidate_index(candidates)
        real_score_candidate = media_matching._score_candidate
        scored_ids = []

        def wrapped_score_candidate(file_tokens, file_sexe_key, candidate, cfg, *, include_field_scores=True):
            scored_ids.append(candidate.inscripcio_id)
            return real_score_candidate(
                file_tokens,
                file_sexe_key,
                candidate,
                cfg,
                include_field_scores=include_field_scores,
            )

        files = [
            {
                "key": "0",
                "filename": "1 - -LUCIA POZO SANCHEZ-Club-A-GEN-F.mp3",
                "relative_path": "music/1 - -LUCIA POZO SANCHEZ-Club-A-GEN-F.mp3",
                "size": 1234,
            }
        ]

        with patch.object(media_matching, "_score_candidate", side_effect=wrapped_score_candidate):
            rows = match_media_files_to_inscripcions(
                files,
                candidates,
                candidate_index=candidate_index,
                top_k=3,
            )

        self.assertEqual(rows[0].get("suggested_inscripcio_id"), 3)
        self.assertEqual(sorted(scored_ids), [3, 3, 7])
        self.assertNotIn(11, scored_ids)

    def test_media_matching_ignores_overly_common_shortlist_tokens(self):
        raw_candidates = [
            SimpleNamespace(
                id=index,
                nom_i_cognoms=f"COMMON NAME {index}",
                entitat="Shared Club",
                subcategoria="GEN",
                sexe="F",
            )
            for index in range(1, 81)
        ]
        raw_candidates.append(
            SimpleNamespace(
                id=999,
                nom_i_cognoms="COMMON TARGET SPECIAL",
                entitat="Shared Club",
                subcategoria="GEN",
                sexe="F",
            )
        )
        candidates = build_inscripcio_media_match_candidates(raw_candidates)
        candidate_index = build_inscripcio_media_match_candidate_index(candidates)
        real_score_candidate = media_matching._score_candidate
        scored_ids = []

        def wrapped_score_candidate(file_tokens, file_sexe_key, candidate, cfg, *, include_field_scores=True):
            scored_ids.append(candidate.inscripcio_id)
            return real_score_candidate(
                file_tokens,
                file_sexe_key,
                candidate,
                cfg,
                include_field_scores=include_field_scores,
            )

        with patch.object(media_matching, "_score_candidate", side_effect=wrapped_score_candidate):
            rows = match_media_files_to_inscripcions(
                [
                    {
                        "key": "0",
                        "filename": "COMMON TARGET SPECIAL - Shared Club.mp3",
                        "relative_path": "audio/COMMON TARGET SPECIAL - Shared Club.mp3",
                        "size": 1234,
                    }
                ],
                candidates,
                candidate_index=candidate_index,
                top_k=3,
            )

        self.assertEqual(rows[0].get("suggested_inscripcio_id"), 999)
        self.assertIn(999, scored_ids)
        self.assertLess(len(set(scored_ids)), len(candidates))

    def test_media_matching_falls_back_to_full_scan_without_useful_tokens(self):
        candidates = build_inscripcio_media_match_candidates(
            [
                SimpleNamespace(
                    id=1,
                    nom_i_cognoms="LUCIA POZO SANCHEZ",
                    entitat="Club A",
                    subcategoria="GEN",
                    sexe="F",
                ),
                SimpleNamespace(
                    id=2,
                    nom_i_cognoms="MARTA LOPEZ",
                    entitat="Club B",
                    subcategoria="INF",
                    sexe="F",
                ),
                SimpleNamespace(
                    id=3,
                    nom_i_cognoms="JORDI PEREZ",
                    entitat="Escola Nord",
                    subcategoria="PRO",
                    sexe="M",
                ),
            ]
        )
        candidate_index = build_inscripcio_media_match_candidate_index(candidates)
        real_score_candidate = media_matching._score_candidate
        scored_ids = []

        def wrapped_score_candidate(file_tokens, file_sexe_key, candidate, cfg, *, include_field_scores=True):
            scored_ids.append(candidate.inscripcio_id)
            return real_score_candidate(
                file_tokens,
                file_sexe_key,
                candidate,
                cfg,
                include_field_scores=include_field_scores,
            )

        files = [
            {
                "key": "0",
                "filename": "unknown.mp3",
                "relative_path": "music/unknown.mp3",
                "size": 1234,
            }
        ]

        with patch.object(media_matching, "_score_candidate", side_effect=wrapped_score_candidate):
            rows = match_media_files_to_inscripcions(
                files,
                candidates,
                candidate_index=candidate_index,
                top_k=3,
            )

        self.assertEqual(rows[0].get("suggested_inscripcio_id"), 1)
        self.assertEqual(sorted(scored_ids), [1, 1, 2, 3])

class InscripcionsListingMediaUrlTests(_BaseTrampoliDataMixin, TestCase):
    def test_listing_media_item_uses_registered_route(self):
        item = InscripcioMedia(
            id=9,
            competicio_id=43,
            inscripcio_id=12,
            tipus=InscripcioMedia.Tipus.AUDIO,
            mime_type="audio/mpeg",
            original_filename="prova.mp3",
            file_size_bytes=123,
            is_primary=True,
            source=InscripcioMedia.Source.MANUAL,
        )

        payload = _serialize_listing_media_item(item)

        self.assertEqual(
            payload["url"],
            reverse("inscripcions_media_file", kwargs={"pk": 43, "media_id": 9}),
        )
