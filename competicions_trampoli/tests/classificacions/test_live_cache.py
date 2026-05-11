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


class LiveClassificacionsRedisCacheTests(_BaseTrampoliDataMixin, TestCase):
    class FakeRedis:
        def __init__(self):
            self.store = {}

        def get(self, key):
            return self.store.get(key)

        def set(self, key, value, nx=False, ex=None):
            if nx and key in self.store:
                return False
            self.store[key] = value
            return True

        def delete(self, key):
            self.store.pop(key, None)
            return 1

    def setUp(self):
        self.comp = self._create_competicio("Comp Live Cache")
        self.app = self._create_aparell("TRAMP_LIVE_CACHE", "Tramp Live Cache")
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)
        self.ins = self._create_inscripcio(self.comp, "Participant Cache", ordre=1)
        self.cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="General",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=self._schema(),
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={},
            outputs={},
            total=9.8,
        )
        self.token = PublicLiveToken.objects.create(
            competicio=self.comp,
            label="Pantalla cache",
            is_active=True,
        )
        User = get_user_model()
        self.user = User.objects.create_user(
            username="live_cache_user",
            password="testpass123",
            email="live-cache@example.com",
        )
        self.editor_user = User.objects.create_user(
            username="live_cache_editor",
            password="testpass123",
            email="live-cache-editor@example.com",
        )
        CompeticioMembership.objects.create(
            user=self.user,
            competicio=self.comp,
            role=CompeticioMembership.Role.READONLY,
            is_active=True,
        )
        CompeticioMembership.objects.create(
            user=self.editor_user,
            competicio=self.comp,
            role=CompeticioMembership.Role.CLASSIFICACIONS,
            is_active=True,
        )

    def _schema(self):
        return {
            "filtres": {},
            "puntuacio": {
                "aparells": {"mode": "seleccionar", "ids": [self.comp_app.id]},
                "camps_per_aparell": {str(self.comp_app.id): ["total"]},
                "agregacio_camps": "sum",
                "exercicis": {"mode": "tots"},
                "exercicis_best_n": 1,
                "agregacio_exercicis": "sum",
                "agregacio_aparells": "sum",
                "ordre": "desc",
                "camp": "total",
                "agregacio": "sum",
                "best_n": 1,
            },
            "desempat": [],
            "presentacio": {
                "columnes": [
                    {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                    {"type": "builtin", "key": "punts", "label": "Punts", "align": "right", "decimals": 3},
                ],
            },
        }

    def _public_url(self):
        return reverse("public_live_classificacions_data", kwargs={"token": self.token.id})

    def _internal_url(self):
        return reverse("classificacions_live_data", kwargs={"pk": self.comp.id})

    def _reorder_url(self):
        return reverse("classificacio_reorder", kwargs={"pk": self.comp.id})

    def _snapshot_payload(self):
        return {
            "ok": True,
            "changed": True,
            "stamp": timezone.now().isoformat(),
            "competicio": {"id": self.comp.id, "nom": self.comp.nom},
            "cfgs": [
                {
                    "id": self.cfg.id,
                    "nom": self.cfg.nom,
                    "tipus": self.cfg.tipus,
                    "columns": [
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                        {"type": "builtin", "key": "punts", "label": "Punts", "align": "right", "decimals": 3},
                    ],
                    "parts": [
                        {
                            "particio": "global",
                            "rows": [{"participant": "Participant Cache", "punts": 9.8, "posicio": 1}],
                        }
                    ],
                }
            ],
        }

    def _snapshot_blob(self, generated_at=None):
        payload = self._snapshot_payload()
        payload["generated_at"] = (generated_at or timezone.now()).isoformat()
        return json.dumps(payload)

    def test_internal_live_view_exposes_poll_ms_and_internal_data_url_bootstrap(self):
        self.client.force_login(self.user)
        res = self.client.get(reverse("classificacions_live", kwargs={"pk": self.comp.id}))

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["poll_ms"], 4000)
        self.assertFalse(res.context["is_public"])
        self.assertContains(res, 'id="poll-ms"', status_code=200)
        self.assertContains(
            res,
            reverse("classificacions_live_data", kwargs={"pk": self.comp.id}),
            status_code=200,
        )

    def test_loop_live_view_clamps_polling_params_and_uses_internal_data_url(self):
        self.client.force_login(self.user)
        res = self.client.get(
            reverse("classificacions_loop_live", kwargs={"pk": self.comp.id}),
            {
                "poll_ms": 5,
                "slide_ms": 999999,
                "rows": 1,
                "transition": "spin",
            },
        )

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["poll_ms"], 1000)
        self.assertEqual(res.context["slide_ms"], 120000)
        self.assertEqual(res.context["rows_per_page"], 3)
        self.assertEqual(res.context["transition"], "fade")
        self.assertContains(res, 'id="loop-poll-ms"', status_code=200)
        self.assertContains(res, 'id="loop-slide-ms"', status_code=200)
        self.assertContains(res, 'id="loop-data-url"', status_code=200)
        self.assertContains(
            res,
            reverse("classificacions_live_data", kwargs={"pk": self.comp.id}),
            status_code=200,
        )

    def test_public_loop_live_exposes_public_data_url_and_media_capability(self):
        self.token.can_view_media = True
        self.token.save(update_fields=["can_view_media"])

        res = self.client.get(reverse("public_live_loop", kwargs={"token": self.token.id}))

        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.context["is_public"])
        self.assertTrue(res.context["public_token_can_view_media"])
        self.assertEqual(
            res.context["data_url"],
            f"http://testserver{reverse('public_live_classificacions_data', kwargs={'token': self.token.id})}",
        )
        self.assertContains(
            res,
            reverse("public_live_classificacions_data", kwargs={"token": self.token.id}),
            status_code=200,
        )

    def test_loop_live_shows_empty_state_when_no_active_classificacions(self):
        self.cfg.activa = False
        self.cfg.save(update_fields=["activa"])
        self.client.force_login(self.user)

        res = self.client.get(reverse("classificacions_loop_live", kwargs={"pk": self.comp.id}))

        self.assertEqual(res.status_code, 200)
        self.assertContains(
            res,
            "No hi ha cap classificacio activa. Quan n'hi hagi, apareixeran automaticament.",
            status_code=200,
        )

    def test_first_get_computes_and_second_get_uses_cache(self):
        fake_redis = self.FakeRedis()
        compute_result = {
            "global": [{"participant": "Participant Cache", "punts": 9.8, "posicio": 1}]
        }
        cache_key = live_cache.live_cache_key(self.comp.id)
        with patch("competicions_trampoli.live_cache._live_redis_client", return_value=fake_redis):
            with patch("competicions_trampoli.views.classificacions.live.compute_classificacio", return_value=compute_result) as mocked_compute:
                res_1 = self.client.get(self._public_url())
                res_2 = self.client.get(self._public_url())

        self.assertEqual(res_1.status_code, 200)
        self.assertEqual(res_2.status_code, 200)
        self.assertEqual(mocked_compute.call_count, 1)
        self.assertIn(cache_key, fake_redis.store)
        self.assertEqual(res_1["X-Live-Cache"], "miss")
        self.assertEqual(res_2["X-Live-Cache"], "hit")
        self.assertEqual(
            res_2.json().get("cfgs", [])[0].get("parts", [])[0].get("rows", [])[0].get("participant"),
            "Participant Cache",
        )

    def test_public_and_internal_live_share_same_snapshot(self):
        fake_redis = self.FakeRedis()
        compute_result = {
            "global": [{"participant": "Participant Cache", "punts": 9.8, "posicio": 1}]
        }
        self.client.force_login(self.user)
        with patch("competicions_trampoli.live_cache._live_redis_client", return_value=fake_redis):
            with patch("competicions_trampoli.views.classificacions.live.compute_classificacio", return_value=compute_result) as mocked_compute:
                public_res = self.client.get(self._public_url())
                internal_res = self.client.get(self._internal_url())

        self.assertEqual(public_res.status_code, 200)
        self.assertEqual(internal_res.status_code, 200)
        self.assertEqual(mocked_compute.call_count, 1)
        self.assertEqual(public_res["X-Live-Cache"], "miss")
        self.assertEqual(internal_res["X-Live-Cache"], "hit")
        self.assertIn("permissions", public_res.json())
        self.assertNotIn("permissions", internal_res.json())

    def test_public_live_filters_unpublished_active_classificacions(self):
        ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Control intern",
            activa=True,
            publicada=False,
            ordre=2,
            tipus="individual",
            schema=self._schema(),
        )
        fake_redis = self.FakeRedis()
        compute_result = {
            "global": [{"participant": "Participant Cache", "punts": 9.8, "posicio": 1}]
        }
        self.client.force_login(self.user)
        with patch("competicions_trampoli.live_cache._live_redis_client", return_value=fake_redis):
            with patch("competicions_trampoli.views.classificacions.live.compute_classificacio", return_value=compute_result):
                public_res = self.client.get(self._public_url())
                internal_res = self.client.get(self._internal_url())

        self.assertEqual(public_res.status_code, 200)
        self.assertEqual(internal_res.status_code, 200)
        self.assertEqual([cfg["nom"] for cfg in public_res.json().get("cfgs", [])], ["General"])
        self.assertEqual(
            [cfg["nom"] for cfg in internal_res.json().get("cfgs", [])],
            ["General", "Control intern"],
        )

    def test_since_is_served_from_cached_stamp_without_recompute(self):
        fake_redis = self.FakeRedis()
        compute_result = {
            "global": [{"participant": "Participant Cache", "punts": 9.8, "posicio": 1}]
        }
        with patch("competicions_trampoli.live_cache._live_redis_client", return_value=fake_redis):
            with patch("competicions_trampoli.views.classificacions.live.compute_classificacio", return_value=compute_result) as mocked_compute:
                first_res = self.client.get(self._public_url())
                stamp = first_res.json()["stamp"]
                second_res = self.client.get(self._public_url(), {"since": stamp})

        self.assertEqual(first_res.status_code, 200)
        self.assertEqual(second_res.status_code, 200)
        self.assertEqual(mocked_compute.call_count, 1)
        self.assertFalse(second_res.json()["changed"])
        self.assertEqual(second_res.json()["stamp"], stamp)
        self.assertEqual(second_res.json().get("permissions", {}).get("can_view_media"), False)

    def test_internal_since_is_served_from_cached_stamp_without_recompute(self):
        fake_redis = self.FakeRedis()
        compute_result = {
            "global": [{"participant": "Participant Cache", "punts": 9.8, "posicio": 1}]
        }
        self.client.force_login(self.user)
        with patch("competicions_trampoli.live_cache._live_redis_client", return_value=fake_redis):
            with patch("competicions_trampoli.views.classificacions.live.compute_classificacio", return_value=compute_result) as mocked_compute:
                first_res = self.client.get(self._internal_url())
                stamp = first_res.json()["stamp"]
                second_res = self.client.get(self._internal_url(), {"since": stamp})

        self.assertEqual(first_res.status_code, 200)
        self.assertEqual(second_res.status_code, 200)
        self.assertEqual(mocked_compute.call_count, 1)
        self.assertFalse(second_res.json()["changed"])
        self.assertEqual(second_res.json()["stamp"], stamp)
        self.assertNotIn("permissions", second_res.json())

    def test_dirty_refresh_with_since_returns_changed_true_and_new_snapshot_stamp(self):
        fake_redis = self.FakeRedis()
        old_stamp = "2026-03-29T10:00:00+00:00"
        snapshot = self._snapshot_payload()
        snapshot["stamp"] = old_stamp
        snapshot["generated_at"] = (timezone.now() - timedelta(seconds=1)).isoformat()
        fake_redis.set(live_cache.live_cache_key(self.comp.id), json.dumps(snapshot))
        fake_redis.set(live_cache.live_dirty_key(self.comp.id), "dirty-1")

        compute_result = {
            "global": [{"participant": "Participant Cache", "punts": 9.9, "posicio": 1}]
        }

        with patch("competicions_trampoli.live_cache._live_redis_client", return_value=fake_redis):
            with patch("competicions_trampoli.views.classificacions.live.compute_classificacio", return_value=compute_result):
                res = self.client.get(self._public_url(), {"since": old_stamp})

        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertTrue(payload["changed"])
        self.assertNotEqual(payload["stamp"], old_stamp)
        self.assertEqual(payload.get("cfgs", [])[0].get("parts", [])[0].get("rows", [])[0].get("punts"), 9.9)
        self.assertEqual(res["X-Live-Cache"], "refresh")

    def test_lock_contention_waits_for_snapshot_without_recompute(self):
        fake_redis = self.FakeRedis()
        fake_redis.set(live_cache.live_lock_key(self.comp.id), "busy")
        waited_snapshot = json.loads(self._snapshot_blob())
        with patch("competicions_trampoli.live_cache._live_redis_client", return_value=fake_redis):
            with patch("competicions_trampoli.live_cache._wait_for_live_snapshot", return_value=waited_snapshot):
                with patch("competicions_trampoli.views.classificacions.live.compute_classificacio") as mocked_compute:
                    res = self.client.get(self._public_url())

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["X-Live-Cache"], "wait-hit")
        mocked_compute.assert_not_called()

    def test_stale_snapshot_is_served_when_refresh_lock_is_busy(self):
        fake_redis = self.FakeRedis()
        fake_redis.set(
            live_cache.live_cache_key(self.comp.id),
            self._snapshot_blob(generated_at=timezone.now() - timedelta(seconds=10)),
        )
        fake_redis.set(live_cache.live_lock_key(self.comp.id), "busy")
        with patch("competicions_trampoli.live_cache._live_redis_client", return_value=fake_redis):
            with patch("competicions_trampoli.views.classificacions.live.compute_classificacio") as mocked_compute:
                res = self.client.get(self._public_url())

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["X-Live-Cache"], "stale")
        mocked_compute.assert_not_called()

    def test_redis_failure_falls_back_to_direct_compute(self):
        compute_result = {
            "global": [{"participant": "Participant Cache", "punts": 9.8, "posicio": 1}]
        }
        with patch(
            "competicions_trampoli.live_cache._live_redis_client",
            side_effect=RuntimeError("redis down"),
        ):
            with patch("competicions_trampoli.views.classificacions.live.compute_classificacio", return_value=compute_result) as mocked_compute:
                res = self.client.get(self._public_url())

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["X-Live-Cache"], "fallback")
        self.assertEqual(mocked_compute.call_count, 1)

    def test_fresh_snapshot_with_dirty_forces_refresh_and_clears_dirty(self):
        fake_redis = self.FakeRedis()
        fake_redis.set(live_cache.live_cache_key(self.comp.id), self._snapshot_blob())
        dirty_key = live_cache.live_dirty_key(self.comp.id)
        fake_redis.set(dirty_key, "dirty-1")
        compute_result = {
            "global": [{"participant": "Participant Cache", "punts": 9.8, "posicio": 1}]
        }
        with patch("competicions_trampoli.live_cache._live_redis_client", return_value=fake_redis):
            with patch("competicions_trampoli.views.classificacions.live.compute_classificacio", return_value=compute_result) as mocked_compute:
                res = self.client.get(self._public_url())

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["X-Live-Cache"], "refresh")
        self.assertEqual(mocked_compute.call_count, 1)
        self.assertNotIn(dirty_key, fake_redis.store)

    def test_dirty_marker_changed_during_refresh_is_preserved(self):
        fake_redis = self.FakeRedis()
        fake_redis.set(live_cache.live_cache_key(self.comp.id), self._snapshot_blob())
        dirty_key = live_cache.live_dirty_key(self.comp.id)
        fake_redis.set(dirty_key, "dirty-1")

        def compute_payload(competicio, since_raw=None):
            fake_redis.set(dirty_key, "dirty-2")
            return self._snapshot_payload()

        with patch("competicions_trampoli.live_cache._live_redis_client", return_value=fake_redis):
            payload, source = live_cache.get_live_payload_cached(
                self.comp,
                compute_payload=compute_payload,
                since_raw=None,
            )

        self.assertEqual(source, "refresh")
        self.assertTrue(payload.get("ok"))
        self.assertEqual(fake_redis.get(dirty_key), "dirty-2")

    def test_scoreentry_signal_marks_dirty_after_commit(self):
        fake_redis = self.FakeRedis()
        with patch("competicions_trampoli.live_cache._live_redis_client", return_value=fake_redis):
            with self.captureOnCommitCallbacks(execute=True):
                ScoreEntry.objects.create(
                    competicio=self.comp,
                    inscripcio=self.ins,
                    exercici=2,
                    comp_aparell=self.comp_app,
                    inputs={},
                    outputs={},
                    total=8.4,
                )

        self.assertIsNotNone(fake_redis.get(live_cache.live_dirty_key(self.comp.id)))

    def test_teamscoreentry_signal_marks_dirty_after_commit(self):
        team_ctx = EquipContext.objects.create(
            competicio=self.comp,
            code="parelles-live",
            nom="Parelles live",
        )
        self.app.competition_unit = Aparell.CompetitionUnit.TEAM
        self.app.save(update_fields=["competition_unit"])
        CompeticioAparellEquipContextSource.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            context=team_ctx,
        )
        equip = self._create_equip(self.comp, "Equip live", context=team_ctx)
        ins_b = self._create_inscripcio(self.comp, "Participant Cache 2", ordre=2)
        self._assign_equip(self.comp, self.ins, equip, context=team_ctx)
        self._assign_equip(self.comp, ins_b, equip, context=team_ctx)
        team_subjects, _issues = build_team_subjects_for_comp_aparell(self.comp, self.comp_app)
        team_subject_id = next(
            item["subject_id"]
            for item in team_subjects
            if int(item.get("equip_id") or 0) == equip.id
        )

        fake_redis = self.FakeRedis()
        with patch("competicions_trampoli.live_cache._live_redis_client", return_value=fake_redis):
            with self.captureOnCommitCallbacks(execute=True):
                TeamScoreEntry.objects.create(
                    competicio=self.comp,
                    team_subject_id=team_subject_id,
                    exercici=1,
                    comp_aparell=self.comp_app,
                    inputs={},
                    outputs={},
                    total=8.4,
                )

        self.assertIsNotNone(fake_redis.get(live_cache.live_dirty_key(self.comp.id)))

    def test_teamscoreentry_change_refreshes_cached_live_snapshot(self):
        snapshot = json.loads(self._snapshot_blob())
        stamp = snapshot["stamp"]
        fake_redis = self.FakeRedis()
        fake_redis.set(live_cache.live_cache_key(self.comp.id), json.dumps(snapshot))

        team_ctx = EquipContext.objects.create(
            competicio=self.comp,
            code="parelles-live-cache",
            nom="Parelles live cache",
        )
        self.app.competition_unit = Aparell.CompetitionUnit.TEAM
        self.app.save(update_fields=["competition_unit"])
        CompeticioAparellEquipContextSource.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            context=team_ctx,
        )
        equip = self._create_equip(self.comp, "Equip live cache", context=team_ctx)
        ins_b = self._create_inscripcio(self.comp, "Participant Cache 2", ordre=2)
        self._assign_equip(self.comp, self.ins, equip, context=team_ctx)
        self._assign_equip(self.comp, ins_b, equip, context=team_ctx)
        team_subjects, _issues = build_team_subjects_for_comp_aparell(self.comp, self.comp_app)
        team_subject_id = next(
            item["subject_id"]
            for item in team_subjects
            if int(item.get("equip_id") or 0) == equip.id
        )

        with patch("competicions_trampoli.live_cache._live_redis_client", return_value=fake_redis):
            with self.captureOnCommitCallbacks(execute=True):
                TeamScoreEntry.objects.create(
                    competicio=self.comp,
                    team_subject_id=team_subject_id,
                    exercici=1,
                    comp_aparell=self.comp_app,
                    inputs={},
                    outputs={},
                    total=8.4,
                )
            res = self.client.get(self._public_url(), {"since": stamp})

        self.assertEqual(res.status_code, 200)
        self.assertNotEqual(res["X-Live-Cache"], "hit")
        self.assertTrue(res.json()["changed"])
        self.assertNotEqual(res.json()["stamp"], stamp)

    def test_classificacioconfig_signal_marks_dirty_after_commit(self):
        fake_redis = self.FakeRedis()
        with patch("competicions_trampoli.live_cache._live_redis_client", return_value=fake_redis):
            with self.captureOnCommitCallbacks(execute=True):
                self.cfg.nom = "General Dirty"
                self.cfg.save(update_fields=["nom"])

        self.assertIsNotNone(fake_redis.get(live_cache.live_dirty_key(self.comp.id)))

    def test_classificacio_reorder_marks_dirty_after_bulk_update(self):
        fake_redis = self.FakeRedis()
        cfg_2 = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Segona",
            activa=True,
            ordre=2,
            tipus="individual",
            schema=self._schema(),
        )
        self.client.force_login(self.editor_user)
        with patch("competicions_trampoli.live_cache._live_redis_client", return_value=fake_redis):
            with self.captureOnCommitCallbacks(execute=True):
                res = self.client.post(
                    self._reorder_url(),
                    data=json.dumps({"order": [cfg_2.id, self.cfg.id]}),
                    content_type="application/json",
                )

        self.assertEqual(res.status_code, 200)
        self.assertIsNotNone(fake_redis.get(live_cache.live_dirty_key(self.comp.id)))
