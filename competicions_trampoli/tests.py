import json
from io import BytesIO
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from ceeb_web.auth_groups import GLOBAL_AUTH_GROUPS

from .access import user_has_competicio_capability
from .models import Competicio, Inscripcio
from .models_judging import JudgeDeviceToken, PublicLiveToken
from .models_classificacions import ClassificacioConfig
from .models_scoring import ScoringSchema, ScoreEntry, ScoreEntryVideo, ScoreEntryVideoEvent
from .models_trampoli import (
    Aparell,
    CompeticioAparell,
    InscripcioAparellExclusio,
)
from .models import CompeticioMembership
from .views import (
    _split_custom_sort_tokens,
    renumber_groups_for_competicio,
    get_competicio_custom_sort_rank_map,
    sort_records_by_field_stable,
)
from .views_classificacions import _build_scoreable_meta_for_schema
from .services.services_classificacions_2 import compute_classificacio


class _BaseTrampoliDataMixin:
    def _create_competicio(self, nom="Comp"):
        return Competicio.objects.create(
            nom=nom,
            tipus=Competicio.Tipus.TRAMPOLI,
        )

    def _create_aparell(self, codi, nom):
        return Aparell.objects.create(codi=codi, nom=nom, actiu=True)

    def _create_comp_aparell(self, competicio, aparell, ordre=1, actiu=True):
        return CompeticioAparell.objects.create(
            competicio=competicio,
            aparell=aparell,
            ordre=ordre,
            actiu=actiu,
        )

    def _create_inscripcio(self, competicio, nom, ordre=1, grup=1):
        return Inscripcio.objects.create(
            competicio=competicio,
            nom_i_cognoms=nom,
            ordre_sortida=ordre,
            grup=grup,
        )


class CustomSortOrderFallbackTests(TestCase):
    def _make_row(self, rid, categoria):
        return SimpleNamespace(id=rid, categoria=categoria, extra={})

    def test_custom_order_is_applied_before_default_fallback(self):
        comp = Competicio.objects.create(
            nom="Comp custom sort",
            tipus=Competicio.Tipus.TRAMPOLI,
            inscripcions_view={
                "custom_sort_orders": {
                    "categoria": ["alevi", "infantil", "cadet"],
                }
            },
        )

        rows = [
            self._make_row(1, "cadet"),
            self._make_row(2, "junior"),
            self._make_row(3, "infantil"),
            self._make_row(4, "alevi"),
            self._make_row(5, "benjami"),
        ]

        rank = get_competicio_custom_sort_rank_map(comp, "categoria")
        ordered = sort_records_by_field_stable(
            rows,
            "categoria",
            descending=False,
            custom_rank_map=rank,
        )

        self.assertEqual(
            [r.categoria for r in ordered],
            ["alevi", "infantil", "cadet", "benjami", "junior"],
        )

    def test_without_custom_order_fallback_matches_default_sort(self):
        comp = Competicio.objects.create(
            nom="Comp no custom sort",
            tipus=Competicio.Tipus.TRAMPOLI,
        )

        rows = [
            self._make_row(1, "zeta"),
            self._make_row(2, "beta"),
            self._make_row(3, "alfa"),
        ]

        rank = get_competicio_custom_sort_rank_map(comp, "categoria")
        ordered = sort_records_by_field_stable(
            rows,
            "categoria",
            descending=False,
            custom_rank_map=rank,
        )

        self.assertEqual([r.categoria for r in ordered], ["alfa", "beta", "zeta"])

    def test_split_custom_sort_tokens_separates_active_and_stale(self):
        active, stale = _split_custom_sort_tokens(
            ["alevi", "fantasma", "CADET", "fantasma"],
            {"alevi", "cadet"},
        )
        self.assertEqual(active, ["alevi", "CADET"])
        self.assertEqual(stale, ["fantasma"])


class InscripcionsSortFlowTests(TestCase):
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
        self.assertEqual(i1.grup, 2)

        self.comp.refresh_from_db()
        self.assertEqual(self.comp.inscripcions_view.get("group_names"), {"2": "Dos"})

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
                "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
                "group_by": [],
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))

        i1.refresh_from_db()
        self.assertEqual(i1.grup, 2)

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
        self.assertEqual(comp.inscripcions_view.get("group_names"), {"1": "Beta", "2": "Gamma"})

    def test_renumber_without_groups_clears_group_labels(self):
        comp = Competicio.objects.create(
            nom="Comp labels clear",
            tipus=Competicio.Tipus.TRAMPOLI,
            inscripcions_view={"group_names": {"1": "Orfe", "9": "Fantasma"}},
        )

        renumber_groups_for_competicio(comp)

        comp.refresh_from_db()
        self.assertNotIn("group_names", comp.inscripcions_view or {})


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


class ScoringAndJudgeExclusionFlowTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Flux")
        self.app = self._create_aparell("TRAMP_FLOW", "Tramp Flow")
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "fields": [
                    {
                        "label": "Execucio",
                        "code": "E",
                        "type": "matrix",
                        "shape": "judge_x_item",
                        "judges": {"count": 2},
                        "items": {"count": 5},
                        "decimals": 1,
                        "crash": {"enabled": True},
                    },
                    {
                        "label": "Altre",
                        "code": "X",
                        "type": "matrix",
                        "shape": "judge_x_item",
                        "judges": {"count": 2},
                        "items": {"count": 5},
                        "decimals": 1,
                        "crash": {"enabled": True},
                    },
                ],
                "computed": [],
            },
        )

        self.ins_allowed = self._create_inscripcio(self.comp, "Allowed", ordre=1)
        self.ins_blocked = self._create_inscripcio(self.comp, "Blocked", ordre=2)
        InscripcioAparellExclusio.objects.create(
            inscripcio=self.ins_blocked,
            comp_aparell=self.comp_app,
        )

        self.token = JudgeDeviceToken.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            label="Judge A",
            permissions=[{"field_code": "E", "judge_index": 1}],
            is_active=True,
        )

    def test_scoring_save_partial_returns_403_for_excluded_inscripcio(self):
        url = reverse("scoring_save_partial", kwargs={"pk": self.comp.id})
        r = self.client.post(
            url,
            data=json.dumps(
                {
                    "inscripcio_id": self.ins_blocked.id,
                    "comp_aparell_id": self.comp_app.id,
                    "exercici": 1,
                    "inputs_patch": {},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 403)

    def test_judge_portal_hides_excluded_and_save_returns_403(self):
        portal_url = reverse("judge_portal", kwargs={"token": self.token.id})
        portal_res = self.client.get(portal_url)
        self.assertEqual(portal_res.status_code, 200)
        body = portal_res.content.decode("utf-8")
        self.assertIn("Allowed", body)
        self.assertNotIn("Blocked", body)
        self.assertIn(reverse("judge_video_upload", kwargs={"token": self.token.id}), body)
        self.assertIn(reverse("judge_video_status", kwargs={"token": self.token.id}), body)
        self.assertIn(reverse("judge_video_delete", kwargs={"token": self.token.id}), body)

        save_url = reverse("judge_save_partial", kwargs={"token": self.token.id})
        save_res = self.client.post(
            save_url,
            data=json.dumps(
                {
                    "inscripcio_id": self.ins_blocked.id,
                    "exercici": 1,
                    "inputs_patch": {"E": 1},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(save_res.status_code, 403)

    def test_judge_save_partial_accepts_crash_for_authorized_field(self):
        save_url = reverse("judge_save_partial", kwargs={"token": self.token.id})
        save_res = self.client.post(
            save_url,
            data=json.dumps(
                {
                    "inscripcio_id": self.ins_allowed.id,
                    "exercici": 1,
                    "inputs_patch": {
                        "E": [0.2, 0.3, 0.4, 0.5, 0.6],
                        "__crash__E": [3, 2],
                    },
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(save_res.status_code, 200)
        payload = save_res.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("inputs", {}).get("__crash__E", [None])[0], 3)

        entry = ScoreEntry.objects.get(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            inscripcio=self.ins_allowed,
            exercici=1,
        )
        self.assertEqual(entry.inputs.get("__crash__E", [None, None])[0], 3)
        self.assertEqual(entry.inputs.get("__crash__E", [None, None])[1], 0)

    def test_judge_save_partial_rejects_crash_for_unauthorized_field(self):
        save_url = reverse("judge_save_partial", kwargs={"token": self.token.id})
        save_res = self.client.post(
            save_url,
            data=json.dumps(
                {
                    "inscripcio_id": self.ins_allowed.id,
                    "exercici": 1,
                    "inputs_patch": {"__crash__X": [2, 0]},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(save_res.status_code, 403)

    def test_scoring_updates_omits_excluded_entries(self):
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_allowed,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={},
            outputs={},
            total=1,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_blocked,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={},
            outputs={},
            total=2,
        )

        since = (timezone.now() - timedelta(minutes=10)).isoformat()
        url = reverse("scoring_updates", kwargs={"pk": self.comp.id})
        r = self.client.get(url, {"since": since})

        self.assertEqual(r.status_code, 200)
        payload = r.json()
        updated_ids = {u["inscripcio_id"] for u in payload.get("updates", [])}

        self.assertIn(self.ins_allowed.id, updated_ids)
        self.assertNotIn(self.ins_blocked.id, updated_ids)


class ClassificacioMatrixScalarTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Classificacio")
        self.app_a = self._create_aparell("APP_A", "Aparell A")
        self.app_b = self._create_aparell("APP_B", "Aparell B")
        self.comp_app_a = self._create_comp_aparell(self.comp, self.app_a, ordre=1, actiu=True)
        self.comp_app_b = self._create_comp_aparell(self.comp, self.app_b, ordre=2, actiu=True)

        self.ins_a = self._create_inscripcio(self.comp, "Participant A", ordre=1)
        self.ins_b = self._create_inscripcio(self.comp, "Participant B", ordre=2)

    def _base_cfg_schema(self):
        return {
            "particions": [],
            "filtres": {},
            "puntuacio": {
                "aparells": {"mode": "tots", "ids": []},
                "camps_per_aparell": {
                    str(self.comp_app_a.id): ["X"],
                    str(self.comp_app_b.id): ["Y"],
                },
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
            "presentacio": {"top_n": 0, "mostrar_empats": True},
        }

    def _valid_partition_schema(self):
        schema = self._base_cfg_schema()
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": [self.comp_app_a.id]}
        schema["puntuacio"]["camps_per_aparell"] = {str(self.comp_app_a.id): ["total"]}
        return schema

    def test_compute_classificacio_uses_input_matrix_1x1_as_scalar(self):
        ScoringSchema.objects.create(
            aparell=self.app_a,
            schema={
                "fields": [
                    {"code": "X", "type": "matrix", "shape": "judge_x_item", "judges": {"count": 1}, "items": {"count": 1}}
                ],
                "computed": [],
            },
        )
        ScoringSchema.objects.create(
            aparell=self.app_b,
            schema={
                "fields": [
                    {"code": "Y", "type": "matrix", "shape": "judge_x_item", "judges": {"count": 1}, "items": {"count": 1}}
                ],
                "computed": [],
            },
        )

        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={"X": [[7.5]]},
            outputs={},
            total=0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=1,
            comp_aparell=self.comp_app_b,
            inputs={"Y": [[8.2]]},
            outputs={},
            total=0,
        )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Global A/B",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=self._base_cfg_schema(),
        )
        out = compute_classificacio(self.comp, cfg)
        rows = out.get("global", [])
        points_by_name = {r["participant"]: r["punts"] for r in rows}

        self.assertEqual(points_by_name.get("Participant A"), 7.5)
        self.assertEqual(points_by_name.get("Participant B"), 8.2)

    def test_compute_classificacio_keeps_zero_for_non_1x1_matrix(self):
        ScoringSchema.objects.create(
            aparell=self.app_a,
            schema={
                "fields": [
                    {"code": "X", "type": "matrix", "shape": "judge_x_item", "judges": {"count": 1}, "items": {"count": 2}}
                ],
                "computed": [],
            },
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={"X": [[7.0, 8.0]]},
            outputs={},
            total=0,
        )

        schema = self._base_cfg_schema()
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": [self.comp_app_a.id]}
        schema["puntuacio"]["camps_per_aparell"] = {str(self.comp_app_a.id): ["X"]}
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="No 1x1",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )
        out = compute_classificacio(self.comp, cfg)
        rows = out.get("global", [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["participant"], "Participant A")
        self.assertEqual(rows[0]["punts"], 0.0)

    def test_classificacio_save_rejects_non_1x1_matrix_field(self):
        ScoringSchema.objects.create(
            aparell=self.app_a,
            schema={
                "fields": [
                    {"code": "X", "type": "matrix", "shape": "judge_x_item", "judges": {"count": 2}, "items": {"count": 1}}
                ],
                "computed": [],
            },
        )

        payload = {
            "nom": "Cfg invalida",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": {
                "particions": [],
                "filtres": {},
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                    "camps_per_aparell": {str(self.comp_app_a.id): ["X"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "exercicis_best_n": 1,
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "desempat": [],
                "presentacio": {"top_n": 0, "mostrar_empats": True},
            },
        }
        url = reverse("classificacio_save", kwargs={"pk": self.comp.id})
        res = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertFalse(body.get("ok"))
        self.assertTrue(any("1x1" in e for e in body.get("errors", [])))

    def test_compute_classificacio_uses_input_list_1_as_scalar(self):
        ScoringSchema.objects.create(
            aparell=self.app_a,
            schema={
                "fields": [
                    {"code": "L", "type": "list", "shape": "judge", "judges": {"count": 1}}
                ],
                "computed": [],
            },
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={"L": [7.2]},
            outputs={},
            total=0,
        )

        schema = self._base_cfg_schema()
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": [self.comp_app_a.id]}
        schema["puntuacio"]["camps_per_aparell"] = {str(self.comp_app_a.id): ["L"]}
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Llista 1x1",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )
        out = compute_classificacio(self.comp, cfg)
        rows = out.get("global", [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["participant"], "Participant A")
        self.assertEqual(rows[0]["punts"], 7.2)

    def test_classificacio_save_rejects_non_scalar_computed_main_field(self):
        ScoringSchema.objects.create(
            aparell=self.app_a,
            schema={
                "fields": [
                    {"code": "X", "type": "matrix", "shape": "judge_x_item", "judges": {"count": 1}, "items": {"count": 2}}
                ],
                "computed": [
                    {"code": "X_copy", "label": "X copy", "formula": "X"},
                ],
            },
        )

        payload = {
            "nom": "Cfg computed no escalar",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": {
                "particions": [],
                "filtres": {},
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                    "camps_per_aparell": {str(self.comp_app_a.id): ["X_copy"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "exercicis_best_n": 1,
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "desempat": [],
                "presentacio": {"top_n": 0, "mostrar_empats": True},
            },
        }
        url = reverse("classificacio_save", kwargs={"pk": self.comp.id})
        res = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertFalse(body.get("ok"))
        self.assertTrue(any("X_copy" in e and "no es puntuable directament" in e for e in body.get("errors", [])))

    def test_classificacio_save_rejects_non_scalar_computed_tie_field(self):
        ScoringSchema.objects.create(
            aparell=self.app_a,
            schema={
                "fields": [
                    {"code": "X", "type": "matrix", "shape": "judge_x_item", "judges": {"count": 1}, "items": {"count": 2}}
                ],
                "computed": [
                    {"code": "X_copy", "label": "X copy", "formula": "X"},
                ],
            },
        )

        payload = {
            "nom": "Cfg tie computed no escalar",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": {
                "particions": [],
                "filtres": {},
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                    "camps_per_aparell": {str(self.comp_app_a.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "exercicis_best_n": 1,
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "desempat": [
                    {
                        "camps": ["X_copy"],
                        "ordre": "desc",
                        "scope": {
                            "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                            "exercicis": {"mode": "hereta"},
                        },
                    }
                ],
                "presentacio": {"top_n": 0, "mostrar_empats": True},
            },
        }
        url = reverse("classificacio_save", kwargs={"pk": self.comp.id})
        res = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertFalse(body.get("ok"))
        self.assertTrue(any("desempat[0]" in e and "X_copy" in e and "no es puntuable directament" in e for e in body.get("errors", [])))

    def test_classificacio_save_accepts_row_compute_by_judge_when_single_judge(self):
        schema_obj = {
            "fields": [
                {"code": "E", "type": "matrix", "shape": "judge_x_item", "judges": {"count": 1}, "items": {"count": 3}}
            ],
            "computed": [
                {
                    "code": "E_by_judge",
                    "label": "E by judge",
                    "formula": "row_custom_compute('E', '1 - x', return_mode='by_judge')",
                },
            ],
        }
        meta = _build_scoreable_meta_for_schema(schema_obj, strict_unknown=True)
        self.assertTrue(meta.get("E_by_judge", {}).get("scoreable"))

    def test_classificacio_save_rejects_row_compute_by_judge_when_multiple_judges(self):
        schema_obj = {
            "fields": [
                {"code": "E", "type": "matrix", "shape": "judge_x_item", "judges": {"count": 2}, "items": {"count": 3}}
            ],
            "computed": [
                {
                    "code": "E_by_judge",
                    "label": "E by judge",
                    "formula": "row_custom_compute('E', '1 - x', return_mode='by_judge')",
                },
            ],
        }
        meta = _build_scoreable_meta_for_schema(schema_obj, strict_unknown=True)
        self.assertFalse(meta.get("E_by_judge", {}).get("scoreable"))
        self.assertIn("by_judge", str(meta.get("E_by_judge", {}).get("reason") or ""))

    def test_classificacio_save_accepts_column_compute_by_item_when_count_is_one(self):
        schema_obj = {
            "fields": [
                {"code": "E", "type": "matrix", "shape": "judge_x_item", "judges": {"count": 2}, "items": {"count": 4}}
            ],
            "computed": [
                {
                    "code": "E_by_item",
                    "label": "E by item",
                    "formula": "column_custom_compute('E', '1 - x', return_mode='by_item', count=1)",
                },
            ],
        }
        meta = _build_scoreable_meta_for_schema(schema_obj, strict_unknown=True)
        self.assertTrue(meta.get("E_by_item", {}).get("scoreable"))

    def test_classificacio_save_rejects_column_compute_by_item_when_multiple_items(self):
        schema_obj = {
            "fields": [
                {"code": "E", "type": "matrix", "shape": "judge_x_item", "judges": {"count": 2}, "items": {"count": 4}}
            ],
            "computed": [
                {
                    "code": "E_by_item",
                    "label": "E by item",
                    "formula": "column_custom_compute('E', '1 - x', return_mode='by_item')",
                },
            ],
        }
        meta = _build_scoreable_meta_for_schema(schema_obj, strict_unknown=True)
        self.assertFalse(meta.get("E_by_item", {}).get("scoreable"))
        self.assertIn("by_item", str(meta.get("E_by_item", {}).get("reason") or ""))

    def test_classificacio_save_tie_accepts_row_compute_by_judge_when_single_judge(self):
        schema_obj = {
            "fields": [
                {"code": "E", "type": "matrix", "shape": "judge_x_item", "judges": {"count": 1}, "items": {"count": 3}}
            ],
            "computed": [
                {
                    "code": "E_by_judge",
                    "label": "E by judge",
                    "formula": "row_custom_compute('E', '1 - x', return_mode='by_judge')",
                },
            ],
        }
        strict_meta = _build_scoreable_meta_for_schema(schema_obj, strict_unknown=True)
        ui_meta = _build_scoreable_meta_for_schema(schema_obj, strict_unknown=False)
        self.assertTrue(strict_meta.get("E_by_judge", {}).get("scoreable"))
        self.assertTrue(ui_meta.get("E_by_judge", {}).get("scoreable"))

    def test_classificacio_save_rejects_invalid_tie_exercicis_selection_mode(self):
        payload = {
            "nom": "Cfg tie invalida",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": {
                "particions": [],
                "filtres": {},
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                    "camps_per_aparell": {str(self.comp_app_a.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "exercicis_best_n": 1,
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "desempat": [
                    {
                        "camps": ["total"],
                        "ordre": "desc",
                        "scope": {
                            "aparells": {"mode": "tots"},
                            "exercicis": {"mode": "hereta"},
                        },
                        "mode_seleccio_exercicis": "invalid_mode",
                    }
                ],
                "presentacio": {"top_n": 0, "mostrar_empats": True},
            },
        }
        url = reverse("classificacio_save", kwargs={"pk": self.comp.id})
        res = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertFalse(body.get("ok"))
        self.assertTrue(any("desempat[0].mode_seleccio_exercicis" in e for e in body.get("errors", [])))

    def test_classificacio_save_rejects_main_aparells_mode_tots(self):
        payload = {
            "nom": "Cfg main tots invalid",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": {
                "particions": [],
                "filtres": {},
                "puntuacio": {
                    "aparells": {"mode": "tots", "ids": []},
                    "camps_per_aparell": {
                        str(self.comp_app_a.id): ["total"],
                        str(self.comp_app_b.id): ["total"],
                    },
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "exercicis_best_n": 1,
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "desempat": [],
                "presentacio": {"top_n": 0, "mostrar_empats": True},
            },
        }
        url = reverse("classificacio_save", kwargs={"pk": self.comp.id})
        res = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertFalse(body.get("ok"))
        self.assertTrue(any("puntuacio.aparells.mode='tots'" in e for e in body.get("errors", [])))

    def test_classificacio_save_rejects_tie_aparells_mode_tots(self):
        payload = {
            "nom": "Cfg tie tots invalid",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": {
                "particions": [],
                "filtres": {},
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                    "camps_per_aparell": {str(self.comp_app_a.id): ["total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "exercicis_best_n": 1,
                    "agregacio_exercicis": "sum",
                    "agregacio_aparells": "sum",
                    "ordre": "desc",
                },
                "desempat": [
                    {
                        "camps": ["total"],
                        "ordre": "desc",
                        "scope": {
                            "aparells": {"mode": "tots"},
                            "exercicis": {"mode": "hereta"},
                        },
                    }
                ],
                "presentacio": {"top_n": 0, "mostrar_empats": True},
            },
        }
        url = reverse("classificacio_save", kwargs={"pk": self.comp.id})
        res = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertFalse(body.get("ok"))
        self.assertTrue(any("desempat[0].scope.aparells.mode='tots'" in e for e in body.get("errors", [])))

    def test_compute_classificacio_tie_supports_per_app_override_exercicis(self):
        self.comp_app_a.nombre_exercicis = 2
        self.comp_app_a.save(update_fields=["nombre_exercicis"])
        self.comp_app_b.nombre_exercicis = 2
        self.comp_app_b.save(update_fields=["nombre_exercicis"])

        # Participant A
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=9.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=2,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=1.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=1,
            comp_aparell=self.comp_app_b,
            inputs={},
            outputs={},
            total=5.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=2,
            comp_aparell=self.comp_app_b,
            inputs={},
            outputs={},
            total=5.0,
        )

        # Participant B
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=6.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=2,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=4.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=1,
            comp_aparell=self.comp_app_b,
            inputs={},
            outputs={},
            total=8.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=2,
            comp_aparell=self.comp_app_b,
            inputs={},
            outputs={},
            total=2.0,
        )

        schema = self._base_cfg_schema()
        schema["puntuacio"]["aparells"] = {"mode": "tots", "ids": []}
        schema["puntuacio"]["camps_per_aparell"] = {
            str(self.comp_app_a.id): ["total"],
            str(self.comp_app_b.id): ["total"],
        }
        schema["puntuacio"]["exercicis"] = {"mode": "tots"}
        schema["puntuacio"]["agregacio_camps"] = "sum"
        schema["puntuacio"]["agregacio_exercicis"] = "sum"
        schema["puntuacio"]["agregacio_aparells"] = "sum"
        schema["desempat"] = [
            {
                "camps": ["total"],
                "ordre": "desc",
                "scope": {
                    "aparells": {"mode": "tots"},
                    "exercicis": {"mode": "hereta"},
                },
                "agregacio_camps": "sum",
                "agregacio_exercicis": "sum",
                "agregacio_aparells": "sum",
                "mode_seleccio_exercicis": "per_aparell_override",
                "exercicis_per_aparell": {
                    str(self.comp_app_a.id): {"mode": "millor_1"},
                    str(self.comp_app_b.id): {"mode": "pitjor_1"},
                },
            }
        ]

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Tie per app override",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        out = compute_classificacio(self.comp, cfg)
        rows = out.get("global", [])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["participant"], "Participant A")
        self.assertEqual(rows[1]["participant"], "Participant B")

    def test_compute_classificacio_supports_custom_partition_groups_for_categoria(self):
        self.ins_a.categoria = "ALEVI"
        self.ins_a.save(update_fields=["categoria"])
        self.ins_b.categoria = "PREBENJAMI"
        self.ins_b.save(update_fields=["categoria"])

        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=9.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=8.0,
        )

        schema = self._valid_partition_schema()
        schema["particions"] = ["categoria"]
        schema["particions_custom"] = {
            "categoria": {
                "mode": "custom",
                "grups": [
                    {"key": "base", "label": "Base", "values": ["ALEVI", "PREBENJAMI"]},
                ],
            }
        }
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Particio custom categoria",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        out = compute_classificacio(self.comp, cfg)
        self.assertEqual(list(out.keys()), ["categoria:Base"])
        self.assertEqual(len(out["categoria:Base"]), 2)

    def test_compute_classificacio_supports_partition_by_schema_extra_field(self):
        self.comp.inscripcions_schema = {
            "columns": [
                {"code": "nivell", "label": "Nivell", "kind": "extra"},
            ]
        }
        self.comp.save(update_fields=["inscripcions_schema"])

        self.ins_a.extra = {"nivell": "N1"}
        self.ins_a.save(update_fields=["extra"])
        self.ins_b.extra = {"nivell": "N2"}
        self.ins_b.save(update_fields=["extra"])

        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=9.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=8.0,
        )

        schema = self._valid_partition_schema()
        schema["particions"] = ["nivell"]
        schema["particions_custom"] = {
            "nivell": {
                "mode": "custom",
                "grups": [
                    {"key": "bloc_1", "label": "Bloc 1", "values": ["N1", "N2"]},
                ],
            }
        }
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Particio extra",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        out = compute_classificacio(self.comp, cfg)
        self.assertEqual(list(out.keys()), ["nivell:Bloc 1"])
        self.assertEqual(len(out["nivell:Bloc 1"]), 2)

    def test_classificacio_save_rejects_unknown_partition_field(self):
        payload = {
            "nom": "Cfg particio desconeguda",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": self._valid_partition_schema(),
        }
        payload["schema"]["particions"] = ["camp_inexistent"]
        payload["schema"]["particions_custom"] = {
            "camp_inexistent": {
                "mode": "custom",
                "grups": [{"label": "X", "values": ["A"]}],
            }
        }

        url = reverse("classificacio_save", kwargs={"pk": self.comp.id})
        res = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertFalse(body.get("ok"))
        self.assertTrue(any("camp no perm" in e for e in body.get("errors", [])))

    def test_classificacio_save_rejects_duplicate_custom_partition_values(self):
        payload = {
            "nom": "Cfg particio custom duplicada",
            "activa": True,
            "ordre": 1,
            "tipus": "individual",
            "schema": self._valid_partition_schema(),
        }
        payload["schema"]["particions"] = ["categoria"]
        payload["schema"]["particions_custom"] = {
            "categoria": {
                "mode": "custom",
                "grups": [
                    {"label": "Bloc 1", "values": ["ALEVI"]},
                    {"label": "Bloc 2", "values": ["ALEVI"]},
                ],
            }
        }

        url = reverse("classificacio_save", kwargs={"pk": self.comp.id})
        res = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertFalse(body.get("ok"))
        self.assertTrue(any("valor repetit entre grups" in e for e in body.get("errors", [])))


class ClassificacionsExportExcelTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Export Classificacions")
        self.app = self._create_aparell("TRAMP_EXPORT", "Tramp Export")
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)

        self.ins_a = self._create_inscripcio(self.comp, "Participant A", ordre=1)
        self.ins_b = self._create_inscripcio(self.comp, "Participant B", ordre=2)
        self.ins_c = self._create_inscripcio(self.comp, "Participant C", ordre=3)

        self.ins_a.categoria = "Junior"
        self.ins_a.subcategoria = "Femeni"
        self.ins_a.save(update_fields=["categoria", "subcategoria"])

        self.ins_b.categoria = "Junior"
        self.ins_b.subcategoria = "Femeni"
        self.ins_b.save(update_fields=["categoria", "subcategoria"])

        self.ins_c.categoria = "Senior"
        self.ins_c.subcategoria = "Masculi"
        self.ins_c.save(update_fields=["categoria", "subcategoria"])

        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={},
            outputs={},
            total=9.6,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={},
            outputs={},
            total=8.3,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_c,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={},
            outputs={},
            total=7.1,
        )

        self.cfg_general = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="General",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=self._schema_for_parts([]),
        )
        self.cfg_particions = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Per categories",
            activa=True,
            ordre=2,
            tipus="individual",
            schema=self._schema_for_parts(["categoria", "subcategoria"]),
        )

        User = get_user_model()
        self.user = User.objects.create_user(
            username="classif_export_user",
            password="testpass123",
            email="classif-export@example.com",
        )
        CompeticioMembership.objects.create(
            user=self.user,
            competicio=self.comp,
            role=CompeticioMembership.Role.READONLY,
            is_active=True,
        )

    def _schema_for_parts(self, parts):
        return {
            "particions": parts,
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
                "top_n": 0,
                "mostrar_empats": True,
                "columnes": [
                    {"type": "builtin", "key": "posicio", "label": "Pos.", "align": "left"},
                    {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                    {"type": "builtin", "key": "punts", "label": "Punts", "align": "right", "decimals": 3},
                ],
            },
        }

    def test_export_excel_creates_one_sheet_per_classificacio(self):
        self.client.force_login(self.user)
        url = reverse("classificacions_live_export_excel", kwargs={"pk": self.comp.id})
        res = self.client.get(url)

        self.assertEqual(res.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            res["Content-Type"],
        )

        wb = load_workbook(filename=BytesIO(res.content))
        self.assertEqual(len(wb.sheetnames), 2)

        ws_general = wb[wb.sheetnames[0]]
        ws_parts = wb[wb.sheetnames[1]]

        self.assertIn("General", str(ws_general["A1"].value))
        self.assertIn("Particio:", str(ws_general["A4"].value))
        self.assertEqual(ws_general.freeze_panes, "A6")

        gold_fill = (ws_general["A6"].fill.fgColor.rgb or "").upper()
        silver_fill = (ws_general["A7"].fill.fgColor.rgb or "").upper()
        header_fill = (ws_general["A5"].fill.fgColor.rgb or "").upper()
        self.assertTrue(gold_fill.endswith("F6E27A"))
        self.assertTrue(silver_fill.endswith("E3E8EF"))
        self.assertTrue(header_fill.endswith("E9EEF7"))

        self.assertIn("Particio:", str(ws_parts["A4"].value))
        self.assertIn("/", str(ws_parts["A4"].value))

    def test_export_excel_can_filter_single_cfg_with_cfg_id(self):
        self.client.force_login(self.user)
        url = reverse("classificacions_live_export_excel", kwargs={"pk": self.comp.id})
        res = self.client.get(url, {"cfg_id": self.cfg_particions.id})

        self.assertEqual(res.status_code, 200)
        wb = load_workbook(filename=BytesIO(res.content))
        self.assertEqual(len(wb.sheetnames), 1)
        ws = wb[wb.sheetnames[0]]
        self.assertIn("Per categories", str(ws["A1"].value))

    def test_export_excel_rejects_invalid_cfg_id(self):
        self.client.force_login(self.user)
        url = reverse("classificacions_live_export_excel", kwargs={"pk": self.comp.id})
        res = self.client.get(url, {"cfg_id": "abc"})
        self.assertEqual(res.status_code, 400)


class JudgeVideoApiTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Video")
        self.app = self._create_aparell("TRAMP_VIDEO", "Tramp Video")
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)

        self.ins_allowed = self._create_inscripcio(self.comp, "Allowed", ordre=1)
        self.ins_blocked = self._create_inscripcio(self.comp, "Blocked", ordre=2)
        InscripcioAparellExclusio.objects.create(
            inscripcio=self.ins_blocked,
            comp_aparell=self.comp_app,
        )

        self.token = JudgeDeviceToken.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            label="Judge Video",
            permissions=[{"field_code": "E", "judge_index": 1}],
            is_active=True,
        )
        self._probe_patcher = patch(
            "competicions_trampoli.views_judge._probe_uploaded_video_metadata",
            side_effect=self._fake_probe_uploaded_video_metadata,
        )
        self._probe_patcher.start()
        self.addCleanup(self._probe_patcher.stop)

    @staticmethod
    def _fake_probe_uploaded_video_metadata(uploaded_file):
        from .views_judge import VideoValidationError

        name = (getattr(uploaded_file, "name", "") or "").lower()
        if name.endswith(".txt"):
            raise VideoValidationError(
                "Tipus MIME no permes: text/plain",
                reason="mime_not_allowed",
                payload={"mime_type": "text/plain", "format_name": "text"},
            )
        return {
            "duration_seconds": 12,
            "mime_type": "video/mp4",
            "format_name": "mp4",
            "video_codec": "h264",
        }

    def _sample_video(self, name="routine.mp4", size=1024):
        return SimpleUploadedFile(name, b"\x00" * size, content_type="video/mp4")

    def test_video_upload_creates_scoreentry_and_video(self):
        upload_url = reverse("judge_video_upload", kwargs={"token": self.token.id})
        r = self.client.post(
            upload_url,
            data={
                "inscripcio_id": self.ins_allowed.id,
                "exercici": 1,
                "duration_seconds": 12,
                "video_file": self._sample_video(),
            },
        )
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertTrue(payload.get("ok"))
        self.assertTrue(payload.get("created"))

        entry = ScoreEntry.objects.get(
            competicio=self.comp,
            inscripcio=self.ins_allowed,
            exercici=1,
            comp_aparell=self.comp_app,
        )
        video = ScoreEntryVideo.objects.get(score_entry=entry)
        self.assertEqual(video.status, ScoreEntryVideo.Status.READY)
        self.assertEqual(video.mime_type, "video/mp4")
        self.assertEqual(video.duration_seconds, 12)
        self.assertEqual(video.judge_token_id, self.token.id)
        ev = ScoreEntryVideoEvent.objects.filter(
            action=ScoreEntryVideoEvent.Action.UPLOAD,
            score_entry=entry,
            video=video,
            ok=True,
        ).first()
        self.assertIsNotNone(ev)

    def test_video_status_returns_false_when_absent(self):
        status_url = reverse("judge_video_status", kwargs={"token": self.token.id})
        r = self.client.get(status_url, {"inscripcio_id": self.ins_allowed.id, "exercici": 1})
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertTrue(payload.get("ok"))
        self.assertFalse(payload.get("has_video"))

    def test_video_upload_rejects_excluded_inscripcio(self):
        upload_url = reverse("judge_video_upload", kwargs={"token": self.token.id})
        r = self.client.post(
            upload_url,
            data={
                "inscripcio_id": self.ins_blocked.id,
                "exercici": 1,
                "video_file": self._sample_video(),
            },
        )
        self.assertEqual(r.status_code, 403)
        self.assertTrue(
            ScoreEntryVideoEvent.objects.filter(
                action=ScoreEntryVideoEvent.Action.UPLOAD_REJECTED,
                inscripcio=self.ins_blocked,
                ok=False,
            ).exists()
        )

    def test_video_upload_rejects_invalid_mime(self):
        upload_url = reverse("judge_video_upload", kwargs={"token": self.token.id})
        bad_file = SimpleUploadedFile("routine.txt", b"abc", content_type="text/plain")
        r = self.client.post(
            upload_url,
            data={
                "inscripcio_id": self.ins_allowed.id,
                "exercici": 1,
                "video_file": bad_file,
            },
        )
        self.assertEqual(r.status_code, 400)
        self.assertTrue(
            ScoreEntryVideoEvent.objects.filter(
                action=ScoreEntryVideoEvent.Action.UPLOAD_REJECTED,
                inscripcio=self.ins_allowed,
                ok=False,
            ).exists()
        )

    def test_video_upload_rejects_file_too_large(self):
        old_limit = ScoreEntryVideo.VIDEO_MAX_SIZE_BYTES
        try:
            ScoreEntryVideo.VIDEO_MAX_SIZE_BYTES = 100
            upload_url = reverse("judge_video_upload", kwargs={"token": self.token.id})
            r = self.client.post(
                upload_url,
                data={
                    "inscripcio_id": self.ins_allowed.id,
                    "exercici": 1,
                    "video_file": self._sample_video(size=256),
                },
            )
            self.assertEqual(r.status_code, 400)
            self.assertTrue(
                ScoreEntryVideoEvent.objects.filter(
                    action=ScoreEntryVideoEvent.Action.UPLOAD_REJECTED,
                    inscripcio=self.ins_allowed,
                    ok=False,
                ).exists()
            )
        finally:
            ScoreEntryVideo.VIDEO_MAX_SIZE_BYTES = old_limit

    def test_second_upload_creates_replace_event(self):
        upload_url = reverse("judge_video_upload", kwargs={"token": self.token.id})
        r1 = self.client.post(
            upload_url,
            data={
                "inscripcio_id": self.ins_allowed.id,
                "exercici": 1,
                "video_file": self._sample_video(name="first.mp4", size=1024),
            },
        )
        self.assertEqual(r1.status_code, 200)

        r2 = self.client.post(
            upload_url,
            data={
                "inscripcio_id": self.ins_allowed.id,
                "exercici": 1,
                "video_file": self._sample_video(name="second.mp4", size=1024),
            },
        )
        self.assertEqual(r2.status_code, 200)

        entry = ScoreEntry.objects.get(
            competicio=self.comp,
            inscripcio=self.ins_allowed,
            exercici=1,
            comp_aparell=self.comp_app,
        )
        self.assertTrue(
            ScoreEntryVideoEvent.objects.filter(
                action=ScoreEntryVideoEvent.Action.REPLACE,
                score_entry=entry,
                ok=True,
            ).exists()
        )

    def test_video_delete_removes_existing_capture(self):
        upload_url = reverse("judge_video_upload", kwargs={"token": self.token.id})
        delete_url = reverse("judge_video_delete", kwargs={"token": self.token.id})

        r_upload = self.client.post(
            upload_url,
            data={
                "inscripcio_id": self.ins_allowed.id,
                "exercici": 1,
                "video_file": self._sample_video(),
            },
        )
        self.assertEqual(r_upload.status_code, 200)

        r_delete = self.client.post(
            delete_url,
            data={
                "inscripcio_id": self.ins_allowed.id,
                "exercici": 1,
            },
        )
        self.assertEqual(r_delete.status_code, 200)
        payload = r_delete.json()
        self.assertTrue(payload.get("ok"))
        self.assertTrue(payload.get("deleted"))

        entry = ScoreEntry.objects.get(
            competicio=self.comp,
            inscripcio=self.ins_allowed,
            exercici=1,
            comp_aparell=self.comp_app,
        )
        self.assertFalse(ScoreEntryVideo.objects.filter(score_entry=entry).exists())
        self.assertTrue(
            ScoreEntryVideoEvent.objects.filter(
                action=ScoreEntryVideoEvent.Action.DELETE,
                score_entry=entry,
                ok=True,
            ).exists()
        )


class PublicLiveTokenViewsTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Public Live")
        self.token = PublicLiveToken.objects.create(
            competicio=self.comp,
            label="Pantalla principal",
            is_active=True,
        )

    def test_public_live_portal_renders_public_live_page(self):
        url = reverse("public_live_portal", kwargs={"token": self.token.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        body = res.content.decode("utf-8")
        self.assertIn("Classificacions", body)
        self.assertIn(reverse("public_live_classificacions_data", kwargs={"token": self.token.id}), body)

    def test_public_live_portal_rejects_revoked_token(self):
        self.token.is_active = False
        self.token.revoked_at = timezone.now()
        self.token.save(update_fields=["is_active", "revoked_at"])

        url = reverse("public_live_portal", kwargs={"token": self.token.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 403)

    def test_public_live_qr_png_returns_png(self):
        url = reverse("public_live_qr_png", kwargs={"token": self.token.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "image/png")

    def test_public_live_data_requires_valid_token(self):
        url = reverse("public_live_classificacions_data", kwargs={"token": self.token.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("ok"))
        self.assertEqual(
            res.json().get("permissions", {}).get("can_view_media"),
            False,
        )

    def test_public_live_data_exposes_media_permission_flag(self):
        self.token.can_view_media = True
        self.token.save(update_fields=["can_view_media"])

        url = reverse("public_live_classificacions_data", kwargs={"token": self.token.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("ok"))
        self.assertEqual(
            res.json().get("permissions", {}).get("can_view_media"),
            True,
        )


class CompetitionAccessControlTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Accessos")
        self.app = self._create_aparell("TRAMP_ACCESS", "Tramp Access")
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)

        User = get_user_model()
        self.judge_admin_user = User.objects.create_user(
            username="judge_admin_user",
            password="testpass123",
            email="judge-admin@example.com",
        )
        self.readonly_user = User.objects.create_user(
            username="readonly_user",
            password="testpass123",
            email="readonly@example.com",
        )
        self.manager_user = User.objects.create_user(
            username="manager_user",
            password="testpass123",
            email="manager@example.com",
        )

        for group_name in GLOBAL_AUTH_GROUPS.keys():
            Group.objects.get_or_create(name=group_name)

        competitions_group = Group.objects.get(name="competicions_manager")
        self.manager_user.groups.add(competitions_group)

        CompeticioMembership.objects.create(
            user=self.judge_admin_user,
            competicio=self.comp,
            role=CompeticioMembership.Role.JUDGE_ADMIN,
            is_active=True,
        )
        CompeticioMembership.objects.create(
            user=self.readonly_user,
            competicio=self.comp,
            role=CompeticioMembership.Role.READONLY,
            is_active=True,
        )

    def test_judge_admin_membership_can_manage_qr_but_readonly_cannot(self):
        url = reverse("judges_qr_home", kwargs={"competicio_id": self.comp.id})

        self.client.force_login(self.judge_admin_user)
        ok_res = self.client.get(url)
        self.assertEqual(ok_res.status_code, 200)
        self.client.logout()

        self.client.force_login(self.readonly_user)
        denied_res = self.client.get(url)
        self.assertEqual(denied_res.status_code, 403)

        self.assertTrue(
            user_has_competicio_capability(
                self.judge_admin_user,
                self.comp,
                "judge_tokens.manage",
            )
        )
        self.assertFalse(
            user_has_competicio_capability(
                self.readonly_user,
                self.comp,
                "judge_tokens.manage",
            )
        )

    def test_global_competitions_manager_can_access_global_competitions_pages(self):
        url = reverse("competicions_home")
        self.client.force_login(self.manager_user)
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

    def test_public_live_token_creation_persists_media_permission(self):
        url = reverse("public_live_qr_home", kwargs={"competicio_id": self.comp.id})
        self.client.force_login(self.judge_admin_user)

        res_with_media = self.client.post(
            url,
            data={
                "action": "create",
                "label": "Public A",
                "can_view_media": "1",
            },
        )
        self.assertEqual(res_with_media.status_code, 302)
        token_with_media = PublicLiveToken.objects.get(competicio=self.comp, label="Public A")
        self.assertTrue(token_with_media.can_view_media)

        res_without_media = self.client.post(
            url,
            data={
                "action": "create",
                "label": "Public B",
            },
        )
        self.assertEqual(res_without_media.status_code, 302)
        token_without_media = PublicLiveToken.objects.get(competicio=self.comp, label="Public B")
        self.assertFalse(token_without_media.can_view_media)
