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
from .models import Competicio, GrupCompeticio, Inscripcio, InscripcioMedia
from .models_judging import (
    JudgeConversation,
    JudgeConversationMessage,
    JudgeDeviceToken,
    PublicLiveToken,
)
from .models_classificacions import ClassificacioConfig, ClassificacioTemplateGlobal
from .models_rotacions import (
    RotacioAssignacio,
    RotacioAssignacioGrup,
    RotacioEstacio,
    RotacioFranja,
)
from .models_scoring import ScoringSchema, ScoreEntry, ScoreEntryVideo, ScoreEntryVideoEvent
from .models_trampoli import (
    Aparell,
    CompeticioAparell,
    InscripcioAparellExclusio,
)
from .models import CompeticioMembership
from .scoring_engine import ScoringEngine
from .views import (
    _split_custom_sort_tokens,
    renumber_groups_for_competicio,
    get_competicio_custom_sort_rank_map,
    sort_records_by_field_stable,
)
from .views_classificacions import (
    _build_scoreable_meta_for_schema,
    _normalize_particions_schema,
    _schema_to_template_schema,
    _template_schema_to_competicio_schema,
    _validate_schema_for_competicio,
    _validate_particions_schema,
)
from .services.services_classificacions_2 import compute_classificacio


class _BaseTrampoliDataMixin:
    def _create_competicio(self, nom="Comp"):
        return Competicio.objects.create(
            nom=nom,
            tipus=Competicio.Tipus.TRAMPOLI,
        )

    def _ensure_default_aparell_owner(self):
        owner = getattr(self, "_default_aparell_owner", None)
        if owner is not None:
            return owner
        User = get_user_model()
        owner = User.objects.create_user(
            username=f"ap_owner_{self.__class__.__name__.lower()}",
            password="testpass123",
            email=f"ap-owner-{self.__class__.__name__.lower()}@example.com",
        )
        self._default_aparell_owner = owner
        return owner

    def _create_aparell(self, codi, nom, owner=None):
        owner = owner or getattr(self, "user", None) or self._ensure_default_aparell_owner()
        return Aparell.objects.create(codi=codi, nom=nom, actiu=True, created_by=owner)

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


class ScoringEngineAliasResolutionTests(TestCase):
    def test_computed_var_alias_can_be_used_before_definition_order(self):
        schema = {
            "fields": [
                {"code": "A", "var": "a", "type": "number"},
            ],
            "computed": [
                # Deliberadament abans que C1 per provar ordre topo + alias var.
                {"code": "C2", "formula": "u + 2"},
                {"code": "C1", "var": "u", "formula": "a + 1"},
                {"code": "TOTAL", "formula": "C2"},
            ],
        }

        result = ScoringEngine(schema).compute({"A": 3})

        self.assertEqual(result.outputs.get("C1"), 4)
        self.assertEqual(result.outputs.get("C2"), 6)
        self.assertEqual(float(result.total), 6.0)


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

    def _post_history(self, direction):
        url_name = "inscripcions_history_undo" if direction == "undo" else "inscripcions_history_redo"
        url = reverse(url_name, kwargs={"pk": self.comp.id})
        return self.client.post(url, data="{}", content_type="application/json")

    def _groups_payload(self, **overrides):
        payload = {
            "source": "sort",
            "strategy": "count",
            "group_count": 1,
            "preview_only": True,
            "filters": {"q": "", "categoria": "", "subcategoria": "", "entitat": ""},
            "group_by": [],
        }
        payload.update(overrides)
        return payload

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

        source_map = {row.get("label"): row for row in existing.get("sources") or []}
        self.assertEqual(source_map["Totes les inscripcions filtrades"]["moving_count"], 1)
        self.assertEqual(source_map["Totes les inscripcions filtrades"]["remaining_count"], 0)
        self.assertEqual(source_map["Fora del filtre actual"]["moving_count"], 0)
        self.assertEqual(source_map["Fora del filtre actual"]["remaining_count"], 1)
        self.assertEqual(source_map["Fora del filtre actual"]["count"], 1)
        self.assertEqual(preview.get("existing_members_total"), 2)

        self.assertEqual(staying.grup, 1)

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


class ScoringMediaPlaybackContextTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Media Notes")
        self.ins = self._create_inscripcio(self.comp, "Participant Reproductor")

        self.app = self._create_aparell("TRAMP_MEDIA", "Tramp Media")
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)

        User = get_user_model()
        self.user = User.objects.create_user(
            username="scoring_media_owner",
            password="testpass123",
            email="scoring-media-owner@example.com",
        )
        CompeticioMembership.objects.create(
            user=self.user,
            competicio=self.comp,
            role=CompeticioMembership.Role.OWNER,
            is_active=True,
        )
        self.client.force_login(self.user)

    def test_media_context_orders_tracks_and_keeps_judge_video_separate(self):
        InscripcioMedia.objects.create(
            competicio=self.comp,
            inscripcio=self.ins,
            fitxer=SimpleUploadedFile("a-main.mp3", b"aaa", content_type="audio/mpeg"),
            tipus=InscripcioMedia.Tipus.AUDIO,
            mime_type="audio/mpeg",
            original_filename="a-main.mp3",
            file_size_bytes=3,
            is_primary=True,
        )
        InscripcioMedia.objects.create(
            competicio=self.comp,
            inscripcio=self.ins,
            fitxer=SimpleUploadedFile("a-alt.mp3", b"bbb", content_type="audio/mpeg"),
            tipus=InscripcioMedia.Tipus.AUDIO,
            mime_type="audio/mpeg",
            original_filename="a-alt.mp3",
            file_size_bytes=3,
            is_primary=False,
        )
        InscripcioMedia.objects.create(
            competicio=self.comp,
            inscripcio=self.ins,
            fitxer=SimpleUploadedFile("v-main.mp4", b"1111", content_type="video/mp4"),
            tipus=InscripcioMedia.Tipus.VIDEO,
            mime_type="video/mp4",
            original_filename="v-main.mp4",
            file_size_bytes=4,
            is_primary=True,
        )
        InscripcioMedia.objects.create(
            competicio=self.comp,
            inscripcio=self.ins,
            fitxer=SimpleUploadedFile("v-alt.mp4", b"2222", content_type="video/mp4"),
            tipus=InscripcioMedia.Tipus.VIDEO,
            mime_type="video/mp4",
            original_filename="v-alt.mp4",
            file_size_bytes=4,
            is_primary=False,
        )

        entry = ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={},
            outputs={},
            total=0,
        )
        ScoreEntryVideo.objects.create(
            score_entry=entry,
            video_file=SimpleUploadedFile("judge.mp4", b"3333", content_type="video/mp4"),
            status=ScoreEntryVideo.Status.READY,
            file_size_bytes=4,
            mime_type="video/mp4",
            original_filename="judge.mp4",
        )

        url = reverse("scoring_media_context", kwargs={"pk": self.comp.id})
        res = self.client.get(
            url,
            {
                "inscripcio_id": self.ins.id,
                "comp_aparell_id": self.comp_app.id,
                "exercici": 1,
            },
        )
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertTrue(payload.get("ok"))

        media = payload.get("media", {})
        self.assertEqual((media.get("audio_primary") or {}).get("original_filename"), "a-main.mp3")
        self.assertEqual(
            [x.get("original_filename") for x in media.get("audio_others", [])],
            ["a-alt.mp3"],
        )
        self.assertEqual((media.get("video_primary") or {}).get("original_filename"), "v-main.mp4")
        self.assertEqual(
            [x.get("original_filename") for x in media.get("video_others", [])],
            ["v-alt.mp4"],
        )
        self.assertEqual((payload.get("judge_video") or {}).get("original_filename"), "judge.mp4")

    def test_media_context_rejects_foreign_comp_aparell(self):
        other_comp = self._create_competicio("Comp Altre Media")
        other_app = self._create_aparell("TRAMP_MEDIA_X", "Tramp Media X")
        other_comp_app = self._create_comp_aparell(other_comp, other_app, ordre=1, actiu=True)

        url = reverse("scoring_media_context", kwargs={"pk": self.comp.id})
        res = self.client.get(
            url,
            {
                "inscripcio_id": self.ins.id,
                "comp_aparell_id": other_comp_app.id,
                "exercici": 1,
            },
        )
        self.assertEqual(res.status_code, 400)

    def test_scoring_notes_home_context_includes_media_counts_and_judge_presence(self):
        ins_without_media = self._create_inscripcio(self.comp, "Participant Sense Media", ordre=2, grup=1)

        InscripcioMedia.objects.create(
            competicio=self.comp,
            inscripcio=self.ins,
            fitxer=SimpleUploadedFile("ctx-audio.mp3", b"aaa", content_type="audio/mpeg"),
            tipus=InscripcioMedia.Tipus.AUDIO,
            mime_type="audio/mpeg",
            original_filename="ctx-audio.mp3",
            file_size_bytes=3,
            is_primary=True,
        )
        InscripcioMedia.objects.create(
            competicio=self.comp,
            inscripcio=self.ins,
            fitxer=SimpleUploadedFile("ctx-video.mp4", b"bbbb", content_type="video/mp4"),
            tipus=InscripcioMedia.Tipus.VIDEO,
            mime_type="video/mp4",
            original_filename="ctx-video.mp4",
            file_size_bytes=4,
            is_primary=True,
        )

        entry = ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins,
            exercici=1,
            comp_aparell=self.comp_app,
            inputs={},
            outputs={},
            total=0,
        )
        ScoreEntryVideo.objects.create(
            score_entry=entry,
            video_file=SimpleUploadedFile("ctx-judge.mp4", b"cccc", content_type="video/mp4"),
            status=ScoreEntryVideo.Status.READY,
            file_size_bytes=4,
            mime_type="video/mp4",
            original_filename="ctx-judge.mp4",
        )

        url = reverse("scoring_notes_home", kwargs={"pk": self.comp.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

        media_counts = res.context["media_counts_by_inscripcio"]
        self.assertEqual(media_counts[str(self.ins.id)]["audio"], 1)
        self.assertEqual(media_counts[str(self.ins.id)]["video"], 1)
        self.assertEqual(media_counts[str(ins_without_media.id)]["audio"], 0)
        self.assertEqual(media_counts[str(ins_without_media.id)]["video"], 0)

        judge_map = res.context["judge_video_presence_by_key"]
        self.assertEqual(int(judge_map.get(f"{self.ins.id}|1|{self.comp_app.id}") or 0), 1)
        self.assertEqual(int(judge_map.get(f"{ins_without_media.id}|1|{self.comp_app.id}") or 0), 0)


class ScoringAndJudgeExclusionFlowTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Flux")
        self.app = self._create_aparell("TRAMP_FLOW", "Tramp Flow")
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)
        self.comp_app.nombre_exercicis = 3
        self.comp_app.save(update_fields=["nombre_exercicis"])
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
            can_record_video=True,
            is_active=True,
        )
        User = get_user_model()
        self.user = User.objects.create_user(
            username="scoring_exclusion_owner",
            password="testpass123",
            email="scoring-exclusion-owner@example.com",
        )
        CompeticioMembership.objects.create(
            user=self.user,
            competicio=self.comp,
            role=CompeticioMembership.Role.OWNER,
            is_active=True,
        )
        self.client.force_login(self.user)

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

    def test_judge_portal_supports_ex_query_and_selector(self):
        portal_url = reverse("judge_portal", kwargs={"token": self.token.id})
        portal_res = self.client.get(portal_url, {"ex": 2})
        self.assertEqual(portal_res.status_code, 200)
        body = portal_res.content.decode("utf-8")
        self.assertIn("const EXERCICI = 2;", body)
        self.assertIn("href=\"?ex=1\"", body)
        self.assertIn("href=\"?ex=3\"", body)

    def test_judge_portal_hides_video_controls_when_video_disabled(self):
        self.token.can_record_video = False
        self.token.save(update_fields=["can_record_video"])
        portal_url = reverse("judge_portal", kwargs={"token": self.token.id})
        portal_res = self.client.get(portal_url, {"ex": 1})
        self.assertEqual(portal_res.status_code, 200)
        body = portal_res.content.decode("utf-8")
        self.assertNotIn('id="video-rec-btn-', body)
        self.assertIn("Gravacio desactivada per aquest QR.", body)

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

    def test_judge_save_partial_clamps_exercici_to_aparell_max(self):
        save_url = reverse("judge_save_partial", kwargs={"token": self.token.id})
        save_res = self.client.post(
            save_url,
            data=json.dumps(
                {
                    "inscripcio_id": self.ins_allowed.id,
                    "exercici": 99,
                    "inputs_patch": {
                        "E": [0.2, 0.3, 0.4, 0.5, 0.6],
                    },
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(save_res.status_code, 200)
        entry = ScoreEntry.objects.get(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            inscripcio=self.ins_allowed,
            exercici=3,
        )
        self.assertIsNotNone(entry)
        self.assertFalse(
            ScoreEntry.objects.filter(
                competicio=self.comp,
                comp_aparell=self.comp_app,
                inscripcio=self.ins_allowed,
                exercici=99,
            ).exists()
        )

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


class RotationOrderingDisplayTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Rotations Display")
        self.app_prior = self._create_aparell("ROT_PRIOR", "Rotation Prior")
        self.app = self._create_aparell("ROT_APP", "Rotation App")
        self.comp_app_prior = self._create_comp_aparell(self.comp, self.app_prior, ordre=1, actiu=True)
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)

        self.ins_1 = self._create_inscripcio(self.comp, "Participant 1", ordre=1, grup=1)
        self.ins_2 = self._create_inscripcio(self.comp, "Participant 2", ordre=2, grup=1)
        self.ins_3 = self._create_inscripcio(self.comp, "Participant 3", ordre=3, grup=1)

        group = self.ins_1.grup_competicio
        Inscripcio.objects.filter(pk=self.ins_1.pk).update(ordre_competicio=2)
        Inscripcio.objects.filter(pk=self.ins_2.pk).update(ordre_competicio=1)
        Inscripcio.objects.filter(pk=self.ins_3.pk).update(ordre_competicio=3)
        self.ins_1.refresh_from_db()
        self.ins_2.refresh_from_db()
        self.ins_3.refresh_from_db()

        self.franja_1 = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici="09:00",
            hora_fi="09:30",
            ordre=1,
            titol="Franja 1",
        )
        self.franja_2 = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici="09:30",
            hora_fi="10:00",
            ordre=2,
            titol="Franja 2",
        )
        self.franja_3 = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici="10:00",
            hora_fi="10:30",
            ordre=3,
            titol="Franja 3",
        )
        self.estacio_prior = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=self.comp_app_prior,
            ordre=1,
            actiu=True,
        )
        self.estacio = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=self.comp_app,
            ordre=2,
            actiu=True,
        )
        assignacio_0 = RotacioAssignacio.objects.create(
            competicio=self.comp,
            franja=self.franja_1,
            estacio=self.estacio_prior,
        )
        RotacioAssignacioGrup.objects.create(assignacio=assignacio_0, grup=group, ordre=1)
        assignacio = RotacioAssignacio.objects.create(
            competicio=self.comp,
            franja=self.franja_2,
            estacio=self.estacio,
        )
        RotacioAssignacioGrup.objects.create(assignacio=assignacio, grup=group, ordre=1)
        assignacio_2 = RotacioAssignacio.objects.create(
            competicio=self.comp,
            franja=self.franja_3,
            estacio=self.estacio,
        )
        RotacioAssignacioGrup.objects.create(assignacio=assignacio_2, grup=group, ordre=1)

        self.comp.inscripcions_view = {
            "rotacions_order_modes": {
                str(self.franja_2.id): "rotate",
                str(self.franja_3.id): "rotate",
            }
        }
        self.comp.save(update_fields=["inscripcions_view"])

        self.token = JudgeDeviceToken.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            label="Judge Rotation",
            permissions=[{"field_code": "E", "judge_index": 1}],
            is_active=True,
        )
        User = get_user_model()
        self.user = User.objects.create_user(
            username="rotation_display_owner",
            password="testpass123",
            email="rotation-display-owner@example.com",
        )
        CompeticioMembership.objects.create(
            user=self.user,
            competicio=self.comp,
            role=CompeticioMembership.Role.OWNER,
            is_active=True,
        )
        self.client.force_login(self.user)

    def test_rotation_shift_restarts_for_group_first_franja_and_advances_locally(self):
        scoring_url = reverse("scoring_notes_home", kwargs={"pk": self.comp.id})

        first_res = self.client.get(scoring_url, {"franja": self.franja_2.id})
        self.assertEqual(first_res.status_code, 200)
        first_rank_map = first_res.context["rotation_rank_map"]
        self.assertEqual(first_rank_map[f"{self.comp_app.id}|{self.ins_3.id}"], 1)
        self.assertEqual(first_rank_map[f"{self.comp_app.id}|{self.ins_2.id}"], 2)
        self.assertEqual(first_rank_map[f"{self.comp_app.id}|{self.ins_1.id}"], 3)

        second_res = self.client.get(scoring_url, {"franja": self.franja_3.id})
        self.assertEqual(second_res.status_code, 200)
        second_rank_map = second_res.context["rotation_rank_map"]
        self.assertEqual(second_rank_map[f"{self.comp_app.id}|{self.ins_2.id}"], 1)
        self.assertEqual(second_rank_map[f"{self.comp_app.id}|{self.ins_1.id}"], 2)
        self.assertEqual(second_rank_map[f"{self.comp_app.id}|{self.ins_3.id}"], 3)

        portal_url = reverse("judge_portal", kwargs={"token": self.token.id})
        portal_res = self.client.get(portal_url)
        self.assertEqual(portal_res.status_code, 200)

        block = portal_res.context["group_blocks"][0]
        self.assertEqual(
            [ins.nom_i_cognoms for ins in block["list"]],
            ["Participant 3", "Participant 2", "Participant 1"],
        )
        self.assertEqual(
            [ins.rotation_order_display for ins in block["list"]],
            [3, 1, 2],
        )

        body = portal_res.content.decode("utf-8")
        self.assertIn("Participant 3", body)
        self.assertIn("Ordre 3", body)
        self.assertIn("Ordre 1", body)
        self.assertIn("Ordre 2", body)


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

    def _selected_total_schema(self, app_ids=None, mode_resultat="score"):
        selected = list(app_ids or [self.comp_app_a.id, self.comp_app_b.id])
        schema = self._base_cfg_schema()
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": selected}
        schema["puntuacio"]["camps_per_aparell"] = {str(app_id): ["total"] for app_id in selected}
        schema["puntuacio"]["mode_resultat_aparells"] = mode_resultat
        schema["puntuacio"]["victories"] = {
            "punts_victoria": 1,
            "punts_empat": 0.5,
            "sense_nota_mode": "skip",
            "desempat_comparacio": [],
        }
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

    def test_classificacio_save_rejects_negative_exercicis_max_per_participant(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="classif_max_pp_editor",
            password="testpass123",
            email="classif-max-pp-editor@example.com",
        )
        CompeticioMembership.objects.create(
            user=user,
            competicio=self.comp,
            role=CompeticioMembership.Role.EDITOR,
            is_active=True,
        )
        self.client.force_login(user)

        payload = {
            "nom": "Cfg max per participant invalid",
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
                    "exercicis": {"mode": "millor_n", "best_n": 2, "max_per_participant": -1},
                    "exercicis_best_n": 2,
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
        self.assertTrue(any("puntuacio.exercicis.max_per_participant" in e for e in body.get("errors", [])))

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

    def test_compute_classificacio_main_exercicis_respects_max_per_participant(self):
        self.comp_app_a.nombre_exercicis = 2
        self.comp_app_a.save(update_fields=["nombre_exercicis"])

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
            total=8.0,
        )
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
            total=5.0,
        )

        schema = self._base_cfg_schema()
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": [self.comp_app_a.id]}
        schema["puntuacio"]["camps_per_aparell"] = {str(self.comp_app_a.id): ["total"]}
        schema["puntuacio"]["exercicis"] = {
            "mode": "millor_n",
            "best_n": 2,
            "max_per_participant": 1,
        }
        schema["puntuacio"]["agregacio_camps"] = "sum"
        schema["puntuacio"]["agregacio_exercicis"] = "sum"
        schema["puntuacio"]["agregacio_aparells"] = "sum"

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Main max per participant",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        out = compute_classificacio(self.comp, cfg)
        rows = out.get("global", [])
        self.assertEqual(len(rows), 2)
        points_by_name = {r["participant"]: r["punts"] for r in rows}
        self.assertEqual(points_by_name.get("Participant A"), 9.0)
        self.assertEqual(points_by_name.get("Participant B"), 6.0)

    def test_compute_classificacio_tie_exercicis_respects_max_per_participant(self):
        self.comp_app_a.nombre_exercicis = 2
        self.comp_app_a.save(update_fields=["nombre_exercicis"])

        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=6.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
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
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=7.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=2,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=3.0,
        )

        schema = self._base_cfg_schema()
        schema["puntuacio"]["aparells"] = {"mode": "seleccionar", "ids": [self.comp_app_a.id]}
        schema["puntuacio"]["camps_per_aparell"] = {str(self.comp_app_a.id): ["total"]}
        schema["puntuacio"]["exercicis"] = {"mode": "tots"}
        schema["puntuacio"]["agregacio_camps"] = "sum"
        schema["puntuacio"]["agregacio_exercicis"] = "sum"
        schema["puntuacio"]["agregacio_aparells"] = "sum"
        schema["desempat"] = [
            {
                "camps": ["total"],
                "ordre": "desc",
                "scope": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                    "exercicis": {"mode": "millor_n", "best_n": 2, "max_per_participant": 1},
                },
                "agregacio_camps": "sum",
                "agregacio_exercicis": "sum",
                "agregacio_aparells": "sum",
            }
        ]

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Tie max per participant",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        out = compute_classificacio(self.comp, cfg)
        rows = out.get("global", [])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["participant"], "Participant B")
        self.assertEqual(rows[1]["participant"], "Participant A")

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

    def test_compute_classificacio_supports_conditional_partition_on_parent_group(self):
        ins_c = self._create_inscripcio(self.comp, "Participant C", ordre=3)

        self.ins_a.categoria = "ALEVI"
        self.ins_a.subcategoria = "N1"
        self.ins_a.save(update_fields=["categoria", "subcategoria"])
        self.ins_b.categoria = "PREBENJAMI"
        self.ins_b.subcategoria = "N2"
        self.ins_b.save(update_fields=["categoria", "subcategoria"])
        ins_c.categoria = "INFANTIL"
        ins_c.subcategoria = "N3"
        ins_c.save(update_fields=["categoria", "subcategoria"])

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
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=ins_c,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=7.0,
        )

        schema = self._valid_partition_schema()
        schema["particions"] = ["categoria", "subcategoria"]
        schema["particions_v2"] = [
            {"code": "categoria", "apply_mode": "all"},
            {"code": "subcategoria", "apply_mode": "some_parents", "parent_values": ["Base"]},
        ]
        schema["particions_custom"] = {
            "categoria": {
                "mode": "custom",
                "grups": [
                    {"key": "base", "label": "Base", "values": ["ALEVI", "PREBENJAMI"]},
                    {"key": "grans", "label": "Grans", "values": ["INFANTIL"]},
                ],
            }
        }
        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Particio condicional",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        out = compute_classificacio(self.comp, cfg)
        self.assertEqual(
            set(out.keys()),
            {"categoria:Base|subcategoria:N1", "categoria:Base|subcategoria:N2", "categoria:Grans"},
        )
        self.assertEqual(out["categoria:Grans"][0]["participant"], "Participant C")

    def test_normalize_particions_schema_populates_particions_v2_from_legacy_list(self):
        schema = self._valid_partition_schema()
        schema["particions"] = ["categoria", "subcategoria"]

        normalized = _normalize_particions_schema(schema)
        self.assertEqual(normalized.get("particions"), ["categoria", "subcategoria"])
        self.assertEqual(
            normalized.get("particions_v2"),
            [
                {"code": "categoria", "apply_mode": "all", "parent_values": []},
                {"code": "subcategoria", "apply_mode": "all", "parent_values": []},
            ],
        )

    def test_validate_particions_schema_rejects_conditional_partition_without_parent_values(self):
        schema = self._valid_partition_schema()
        schema["particions_v2"] = [
            {"code": "categoria", "apply_mode": "all"},
            {"code": "subcategoria", "apply_mode": "some_parents", "parent_values": []},
        ]
        normalized = _normalize_particions_schema(schema)
        errors = _validate_particions_schema(self.comp, normalized)
        self.assertTrue(any("parent_values" in e for e in errors))

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

    def test_compute_classificacio_victories_single_app_matches_order(self):
        schema = self._selected_total_schema([self.comp_app_a.id], mode_resultat="victories")

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
            total=7.0,
        )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Victories 1 app",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        self.assertEqual([r["participant"] for r in rows], ["Participant A", "Participant B"])
        self.assertEqual(rows[0]["by_app_base"][self.comp_app_a.id], 9.0)
        self.assertEqual(rows[0]["by_app"][self.comp_app_a.id], 1.0)
        self.assertEqual(rows[0]["punts"], 1.0)
        self.assertEqual(rows[1]["by_app"][self.comp_app_a.id], 0.0)
        self.assertEqual(rows[1]["punts"], 0.0)

    def test_compute_classificacio_victories_multiple_apps_aggregates_after_duels(self):
        ins_c = self._create_inscripcio(self.comp, "Participant C", ordre=3)
        schema = self._selected_total_schema(
            [self.comp_app_a.id, self.comp_app_b.id],
            mode_resultat="victories",
        )

        scores = {
            self.ins_a.id: {self.comp_app_a.id: 100.0, self.comp_app_b.id: 1.0},
            self.ins_b.id: {self.comp_app_a.id: 60.0, self.comp_app_b.id: 60.0},
            ins_c.id: {self.comp_app_a.id: 59.0, self.comp_app_b.id: 59.0},
        }
        for ins_id, per_app in scores.items():
            ins = Inscripcio.objects.get(pk=ins_id)
            for app_id, total in per_app.items():
                comp_app = self.comp_app_a if app_id == self.comp_app_a.id else self.comp_app_b
                ScoreEntry.objects.create(
                    competicio=self.comp,
                    inscripcio=ins,
                    exercici=1,
                    comp_aparell=comp_app,
                    inputs={},
                    outputs={},
                    total=total,
                )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Victories 2 apps",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        self.assertEqual([r["participant"] for r in rows], ["Participant B", "Participant A", "Participant C"])
        self.assertEqual(rows[0]["punts"], 3.0)
        self.assertEqual(rows[1]["punts"], 2.0)
        self.assertEqual(rows[2]["punts"], 1.0)

    def test_compute_classificacio_victories_internal_tie_break_uses_compare_tie(self):
        schema = self._selected_total_schema([self.comp_app_a.id], mode_resultat="victories")
        schema["puntuacio"]["victories"]["desempat_comparacio"] = [
            {
                "camp": "E",
                "camps": ["E"],
                "agregacio_camps": "hereta",
                "ordre": "desc",
                "scope": {"exercicis": {"mode": "hereta"}},
            }
        ]

        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={"E": 9.0},
            outputs={},
            total=10.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={"E": 8.0},
            outputs={},
            total=10.0,
        )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Victories compare tie",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        self.assertEqual([r["participant"] for r in rows], ["Participant A", "Participant B"])
        self.assertEqual(rows[0]["punts"], 1.0)
        self.assertEqual(rows[1]["punts"], 0.0)

    def test_compute_classificacio_victories_unresolved_tie_gives_half_points(self):
        schema = self._selected_total_schema([self.comp_app_a.id], mode_resultat="victories")

        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_a,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=10.0,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_b,
            exercici=1,
            comp_aparell=self.comp_app_a,
            inputs={},
            outputs={},
            total=10.0,
        )

        cfg = ClassificacioConfig.objects.create(
            competicio=self.comp,
            nom="Victories tied",
            activa=True,
            ordre=1,
            tipus="individual",
            schema=schema,
        )

        rows = compute_classificacio(self.comp, cfg).get("global", [])
        self.assertEqual(rows[0]["punts"], 0.5)
        self.assertEqual(rows[1]["punts"], 0.5)
        self.assertEqual(rows[0]["by_app"][self.comp_app_a.id], 0.5)
        self.assertEqual(rows[1]["by_app"][self.comp_app_a.id], 0.5)

    def test_classificacio_save_rejects_victories_for_non_individual(self):
        schema = self._selected_total_schema([self.comp_app_a.id], mode_resultat="victories")
        _, errors = _validate_schema_for_competicio(self.comp, schema, tipus="entitat")
        self.assertTrue(any("mode_resultat_aparells='victories'" in e for e in errors))

    def test_classificacio_save_rejects_victories_compare_tie_scope_aparells(self):
        schema = self._selected_total_schema([self.comp_app_a.id], mode_resultat="victories")
        schema["puntuacio"]["victories"]["desempat_comparacio"] = [
            {
                "camps": ["total"],
                "ordre": "desc",
                "scope": {
                    "aparells": {"mode": "seleccionar", "ids": [self.comp_app_a.id]},
                    "exercicis": {"mode": "hereta"},
                },
            }
        ]
        _, errors = _validate_schema_for_competicio(self.comp, schema, tipus="individual")
        self.assertTrue(any("scope.aparells no esta permes" in e for e in errors))

    def test_classificacio_save_rejects_victories_compare_tie_scope_participants(self):
        schema = self._selected_total_schema([self.comp_app_a.id], mode_resultat="victories")
        schema["puntuacio"]["victories"]["desempat_comparacio"] = [
            {
                "camps": ["total"],
                "ordre": "desc",
                "scope": {
                    "participants": {"mode": "tots"},
                    "exercicis": {"mode": "hereta"},
                },
            }
        ]
        _, errors = _validate_schema_for_competicio(self.comp, schema, tipus="individual")
        self.assertTrue(any("scope.participants no esta permes" in e for e in errors))


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


class ClassificacioTemplateFlowTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp_source = self._create_competicio("Comp Templates Source")
        self.comp_target = self._create_competicio("Comp Templates Target")

        self.app = self._create_aparell("TPL_APP", "Template App")
        self.source_app = self._create_comp_aparell(self.comp_source, self.app, ordre=1, actiu=True)
        self.target_app = self._create_comp_aparell(self.comp_target, self.app, ordre=1, actiu=True)

        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "fields": [
                    {"code": "E_total", "type": "number"},
                ],
                "computed": [],
            },
        )

        self.cfg_source = ClassificacioConfig.objects.create(
            competicio=self.comp_source,
            nom="Cfg Source",
            activa=True,
            ordre=1,
            tipus="individual",
            schema={
                "particions": ["categoria"],
                "filtres": {},
                "puntuacio": {
                    "aparells": {"mode": "seleccionar", "ids": [self.source_app.id]},
                    "camps_per_aparell": {str(self.source_app.id): ["E_total"]},
                    "agregacio_camps": "sum",
                    "exercicis": {"mode": "tots"},
                    "exercicis_best_n": 1,
                    "mode_seleccio_exercicis": "per_aparell_global",
                    "exercicis_per_aparell": {},
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
                        {"type": "builtin", "key": "posicio", "label": "#", "align": "left"},
                        {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                        {"type": "builtin", "key": "punts", "label": "Punts", "align": "right", "decimals": 3},
                    ],
                },
            },
        )

        User = get_user_model()
        self.editor_user = User.objects.create_user(
            username="tpl_editor_user",
            password="testpass123",
            email="tpl-editor@example.com",
        )
        self.other_user = User.objects.create_user(
            username="tpl_other_user",
            password="testpass123",
            email="tpl-other@example.com",
        )

        CompeticioMembership.objects.create(
            user=self.editor_user,
            competicio=self.comp_source,
            role=CompeticioMembership.Role.EDITOR,
            is_active=True,
        )
        CompeticioMembership.objects.create(
            user=self.editor_user,
            competicio=self.comp_target,
            role=CompeticioMembership.Role.EDITOR,
            is_active=True,
        )
        CompeticioMembership.objects.create(
            user=self.other_user,
            competicio=self.comp_source,
            role=CompeticioMembership.Role.EDITOR,
            is_active=True,
        )
        CompeticioMembership.objects.create(
            user=self.other_user,
            competicio=self.comp_target,
            role=CompeticioMembership.Role.EDITOR,
            is_active=True,
        )

    def _post_json_as(self, user, url_name, comp_id, payload):
        self.client.force_login(user)
        url = reverse(url_name, kwargs={"pk": comp_id})
        return self.client.post(url, data=json.dumps(payload), content_type="application/json")

    def test_editor_with_classificacions_edit_can_save_global_template(self):
        res = self._post_json_as(
            self.editor_user,
            "classificacio_template_save",
            self.comp_source.id,
            {"cfg_id": self.cfg_source.id, "nom": "TPL 1"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("ok"))

    def test_template_schema_helpers_preserve_victories_config(self):
        schema = json.loads(json.dumps(self.cfg_source.schema or {}))
        schema["puntuacio"]["mode_resultat_aparells"] = "victories"
        schema["puntuacio"]["victories"] = {
            "punts_victoria": 1,
            "punts_empat": 0,
            "sense_nota_mode": "skip",
            "desempat_comparacio": [
                {
                    "camp": "E_total",
                    "camps": ["E_total"],
                    "agregacio_camps": "hereta",
                    "ordre": "desc",
                    "scope": {"exercicis": {"mode": "hereta"}},
                }
            ],
        }

        schema_tpl, warnings = _schema_to_template_schema(self.comp_source, schema)
        self.assertFalse(warnings)
        self.assertEqual(
            ((schema_tpl.get("puntuacio") or {}).get("mode_resultat_aparells")),
            "victories",
        )

        schema_local, mapping_warnings, mapping = _template_schema_to_competicio_schema(self.comp_target, schema_tpl)
        self.assertFalse(mapping_warnings)
        self.assertEqual(mapping.get(self.app.codi), self.target_app.id)
        punt = (schema_local.get("puntuacio") or {})
        self.assertEqual(punt.get("mode_resultat_aparells"), "victories")
        self.assertEqual((punt.get("aparells") or {}).get("ids"), [self.target_app.id])
        self.assertEqual(
            ((((punt.get("victories") or {}).get("desempat_comparacio")) or [])[0] or {}).get("camps"),
            ["E_total"],
        )

    def test_global_template_can_be_saved_validated_and_applied(self):
        save_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_save",
            self.comp_source.id,
            {"cfg_id": self.cfg_source.id, "nom": "TPL Rapid"},
        )
        self.assertEqual(save_res.status_code, 200)
        save_body = save_res.json()
        self.assertTrue(save_body.get("ok"))
        template_id = save_body.get("template", {}).get("id")
        self.assertTrue(template_id)

        tpl = ClassificacioTemplateGlobal.objects.get(pk=template_id)
        tpl_schema = (tpl.payload or {}).get("schema") or {}
        self.assertEqual(
            ((tpl_schema.get("puntuacio") or {}).get("aparells") or {}).get("ids"),
            [self.app.codi],
        )

        validate_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_validate",
            self.comp_target.id,
            {"template_id": template_id},
        )
        self.assertEqual(validate_res.status_code, 200)
        validate_body = validate_res.json()
        self.assertTrue(validate_body.get("compatible"))

        apply_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_apply",
            self.comp_target.id,
            {"template_id": template_id, "nom": "Aplicada Target", "activa": False},
        )
        self.assertEqual(apply_res.status_code, 200)
        apply_body = apply_res.json()
        self.assertTrue(apply_body.get("ok"))
        cfg = apply_body.get("cfg") or {}
        self.assertEqual(cfg.get("nom"), "Aplicada Target")

        punt = ((cfg.get("schema") or {}).get("puntuacio") or {})
        self.assertEqual((punt.get("aparells") or {}).get("ids"), [self.target_app.id])
        self.assertEqual((punt.get("camps_per_aparell") or {}).get(str(self.target_app.id)), ["E_total"])

        tpl.refresh_from_db()
        self.assertEqual(tpl.uses_count, 1)
        self.assertIsNotNone(tpl.last_used_at)

    def test_template_apply_requires_ack_for_non_strict_fallback(self):
        save_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_save",
            self.comp_source.id,
            {"cfg_id": self.cfg_source.id, "nom": "TPL Ack"},
        )
        self.assertEqual(save_res.status_code, 200)
        template_id = save_res.json().get("template", {}).get("id")
        self.assertTrue(template_id)

        res = self._post_json_as(
            self.editor_user,
            "classificacio_template_apply",
            self.comp_target.id,
            {
                "template_id": template_id,
                "nom": "Aplicada sense ack",
                "activa": False,
                "fallback_mode": "assistit",
            },
        )
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertFalse(body.get("ok"))
        self.assertEqual(body.get("phase"), "assistit")
        self.assertIn("confirmar", str(body.get("error", "")).lower())

    def test_template_apply_fallback_chain_strict_assistit_force(self):
        save_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_save",
            self.comp_source.id,
            {"cfg_id": self.cfg_source.id, "nom": "TPL Fallback Chain"},
        )
        self.assertEqual(save_res.status_code, 200)
        template_id = save_res.json().get("template", {}).get("id")
        self.assertTrue(template_id)

        tpl = ClassificacioTemplateGlobal.objects.get(pk=template_id)
        payload = json.loads(json.dumps(tpl.payload or {}))
        schema = payload.get("schema") or {}
        schema["particions"] = ["categoria"]
        schema["particions_custom"] = {
            "categoria": {
                "mode": "custom",
                "grups": [
                    {"label": "Bloc 1", "values": ["ALEVI"]},
                    {"label": "Bloc 2", "values": ["ALEVI"]},
                ],
            }
        }
        payload["schema"] = schema
        tpl.payload = payload
        tpl.save(update_fields=["payload", "updated_at"])

        strict_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_apply",
            self.comp_target.id,
            {
                "template_id": template_id,
                "nom": "Aplicada strict",
                "activa": False,
                "fallback_mode": "strict",
            },
        )
        self.assertEqual(strict_res.status_code, 400)
        strict_body = strict_res.json()
        self.assertFalse(strict_body.get("compatible"))
        self.assertEqual(strict_body.get("phase"), "strict")
        self.assertEqual(strict_body.get("next_fallback"), "assistit")
        self.assertTrue(strict_body.get("can_try_next"))

        assistit_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_apply",
            self.comp_target.id,
            {
                "template_id": template_id,
                "nom": "Aplicada assistit",
                "activa": False,
                "fallback_mode": "assistit",
                "ack_warning": True,
            },
        )
        self.assertEqual(assistit_res.status_code, 400)
        assistit_body = assistit_res.json()
        self.assertFalse(assistit_body.get("compatible"))
        self.assertEqual(assistit_body.get("phase"), "assistit")
        self.assertEqual(assistit_body.get("next_fallback"), "force")
        self.assertTrue(assistit_body.get("can_try_next"))

        force_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_apply",
            self.comp_target.id,
            {
                "template_id": template_id,
                "nom": "Aplicada force",
                "activa": False,
                "fallback_mode": "force",
                "ack_warning": True,
            },
        )
        self.assertEqual(force_res.status_code, 200)
        force_body = force_res.json()
        self.assertTrue(force_body.get("ok"))
        cfg = force_body.get("cfg") or {}
        self.assertEqual(cfg.get("nom"), "Aplicada force")
        self.assertEqual(
            (((cfg.get("schema") or {}).get("puntuacio") or {}).get("aparells") or {}).get("ids"),
            [self.target_app.id],
        )
        self.assertEqual(
            (((cfg.get("schema") or {}).get("puntuacio") or {}).get("camps_per_aparell") or {}).get(str(self.target_app.id)),
            ["total"],
        )

    def test_template_list_only_shows_owner_templates(self):
        own = self._post_json_as(
            self.editor_user,
            "classificacio_template_save",
            self.comp_source.id,
            {"cfg_id": self.cfg_source.id, "nom": "TPL Owner"},
        )
        self.assertEqual(own.status_code, 200)
        own_id = own.json().get("template", {}).get("id")
        self.assertTrue(own_id)

        foreign = self._post_json_as(
            self.other_user,
            "classificacio_template_save",
            self.comp_source.id,
            {"cfg_id": self.cfg_source.id, "nom": "TPL Foreign"},
        )
        self.assertEqual(foreign.status_code, 200)
        foreign_id = foreign.json().get("template", {}).get("id")
        self.assertTrue(foreign_id)

        self.client.force_login(self.editor_user)
        list_url = reverse("classificacio_template_list", kwargs={"pk": self.comp_source.id})
        res = self.client.get(list_url)
        self.assertEqual(res.status_code, 200)
        ids = {int(t["id"]) for t in (res.json().get("templates") or [])}
        self.assertIn(int(own_id), ids)
        self.assertNotIn(int(foreign_id), ids)

    def test_cannot_use_or_update_foreign_template_by_id(self):
        foreign = self._post_json_as(
            self.other_user,
            "classificacio_template_save",
            self.comp_source.id,
            {"cfg_id": self.cfg_source.id, "nom": "TPL Foreign Locked"},
        )
        self.assertEqual(foreign.status_code, 200)
        foreign_id = foreign.json().get("template", {}).get("id")
        self.assertTrue(foreign_id)

        validate_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_validate",
            self.comp_target.id,
            {"template_id": foreign_id},
        )
        self.assertEqual(validate_res.status_code, 404)

        apply_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_apply",
            self.comp_target.id,
            {"template_id": foreign_id, "nom": "No hauria d'aplicar"},
        )
        self.assertEqual(apply_res.status_code, 404)

        update_res = self._post_json_as(
            self.editor_user,
            "classificacio_template_save",
            self.comp_source.id,
            {"cfg_id": self.cfg_source.id, "template_id": foreign_id, "nom": "No hauria d'editar"},
        )
        self.assertEqual(update_res.status_code, 404)


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
            can_record_video=True,
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

    def test_video_endpoints_return_403_when_token_video_disabled(self):
        token_no_video = JudgeDeviceToken.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            label="Judge No Video",
            permissions=[{"field_code": "E", "judge_index": 1}],
            is_active=True,
        )
        status_url = reverse("judge_video_status", kwargs={"token": token_no_video.id})
        upload_url = reverse("judge_video_upload", kwargs={"token": token_no_video.id})
        delete_url = reverse("judge_video_delete", kwargs={"token": token_no_video.id})

        status_res = self.client.get(status_url, {"inscripcio_id": self.ins_allowed.id, "exercici": 1})
        self.assertEqual(status_res.status_code, 403)
        self.assertEqual(status_res.json().get("reason"), "video_disabled")

        upload_res = self.client.post(
            upload_url,
            data={
                "inscripcio_id": self.ins_allowed.id,
                "exercici": 1,
                "video_file": self._sample_video(),
            },
        )
        self.assertEqual(upload_res.status_code, 403)
        self.assertEqual(upload_res.json().get("reason"), "video_disabled")

        delete_res = self.client.post(
            delete_url,
            data={
                "inscripcio_id": self.ins_allowed.id,
                "exercici": 1,
            },
        )
        self.assertEqual(delete_res.status_code, 403)
        self.assertEqual(delete_res.json().get("reason"), "video_disabled")

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
        self.other_comp = self._create_competicio("Comp Privada")
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

    def test_created_list_shows_only_user_membership_competitions(self):
        url = reverse("created")
        self.client.force_login(self.readonly_user)
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, self.comp.nom)
        self.assertNotContains(res, self.other_comp.nom)

    def test_competicions_manager_group_without_membership_cannot_open_foreign_competition(self):
        url = reverse("inscripcions_list", kwargs={"pk": self.other_comp.id})
        self.client.force_login(self.manager_user)
        res = self.client.get(url)
        self.assertEqual(res.status_code, 403)

    def test_create_competition_assigns_owner_membership_to_creator(self):
        url = reverse("create")
        self.client.force_login(self.readonly_user)
        res = self.client.post(
            url,
            data={
                "nom": "Comp Creada Usuari",
                "tipus": Competicio.Tipus.TRAMPOLI,
                "data": "",
            },
        )
        self.assertEqual(res.status_code, 302)

        created_comp = Competicio.objects.get(nom="Comp Creada Usuari")
        membership = CompeticioMembership.objects.get(
            user=self.readonly_user,
            competicio=created_comp,
        )
        self.assertEqual(membership.role, CompeticioMembership.Role.OWNER)
        self.assertTrue(membership.is_active)
        self.assertEqual(membership.granted_by_id, self.readonly_user.id)

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


class JudgeMessagingFlowTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Missatgeria")
        self.app = self._create_aparell("TRAMP_MSG", "Trampoli Msg")
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)

        self.token = JudgeDeviceToken.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            label="Judge Msg A",
            permissions=[{"field_code": "E", "judge_index": 1}],
            is_active=True,
        )

        User = get_user_model()
        self.manager_user = User.objects.create_user(
            username="judge_msg_manager",
            password="testpass123",
            email="judge-msg-manager@example.com",
        )
        self.readonly_user = User.objects.create_user(
            username="judge_msg_readonly",
            password="testpass123",
            email="judge-msg-readonly@example.com",
        )
        CompeticioMembership.objects.create(
            user=self.manager_user,
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

    def test_quick_support_creates_requested_conversation_without_explicit_text(self):
        url = reverse("judge_request_support", kwargs={"token": self.token.id})
        res = self.client.post(
            url,
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertTrue(payload.get("ok"))
        self.assertTrue(payload.get("quick"))

        conv = JudgeConversation.objects.get(judge_token=self.token)
        self.assertEqual(conv.status, JudgeConversation.Status.REQUESTED)
        self.assertGreaterEqual(conv.unread_for_org, 1)

        msg = JudgeConversationMessage.objects.get(conversation=conv)
        self.assertEqual(msg.message_type, JudgeConversationMessage.MessageType.SUPPORT_REQUEST_QUICK)
        self.assertIn("assistencia", (msg.text or "").lower())

    def test_quick_support_has_cooldown(self):
        url = reverse("judge_request_support", kwargs={"token": self.token.id})
        first = self.client.post(url, data=json.dumps({}), content_type="application/json")
        self.assertEqual(first.status_code, 200)

        second = self.client.post(url, data=json.dumps({}), content_type="application/json")
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json().get("reason"), "cooldown")

    def test_judge_updates_include_org_instruction(self):
        request_url = reverse("judge_request_support", kwargs={"token": self.token.id})
        self.client.post(request_url, data=json.dumps({}), content_type="application/json")

        send_url = reverse("judge_messages_send_org", kwargs={"competicio_id": self.comp.id})
        self.client.force_login(self.manager_user)
        send_res = self.client.post(
            send_url,
            data=json.dumps(
                {
                    "judge_token_id": str(self.token.id),
                    "message_type": "instruction",
                    "text": "Reinicia tauleta i revisa connexio.",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(send_res.status_code, 200)
        self.client.logout()

        updates_url = reverse("judge_messages_updates", kwargs={"token": self.token.id})
        updates_res = self.client.get(updates_url)
        self.assertEqual(updates_res.status_code, 200)
        rows = updates_res.json().get("messages", [])
        self.assertTrue(any("Reinicia tauleta" in (x.get("text") or "") for x in rows))

    def test_org_hub_requires_judge_messages_capability(self):
        hub_url = reverse("judge_messages_hub", kwargs={"competicio_id": self.comp.id})

        self.client.force_login(self.manager_user)
        ok_res = self.client.get(hub_url)
        self.assertEqual(ok_res.status_code, 200)
        self.client.logout()

        self.client.force_login(self.readonly_user)
        denied_res = self.client.get(hub_url)
        self.assertEqual(denied_res.status_code, 403)

    def test_org_can_open_conversation_by_token_and_mark_resolved(self):
        send_url = reverse("judge_messages_send_org", kwargs={"competicio_id": self.comp.id})
        self.client.force_login(self.manager_user)
        send_res = self.client.post(
            send_url,
            data=json.dumps(
                {
                    "judge_token_id": str(self.token.id),
                    "message_type": "instruction",
                    "text": "Passa al mode offline.",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(send_res.status_code, 200)
        conv_id = send_res.json().get("conversation", {}).get("id")
        self.assertTrue(conv_id)

        status_url = reverse("judge_messages_set_status_org", kwargs={"competicio_id": self.comp.id})
        status_res = self.client.post(
            status_url,
            data=json.dumps({"conversation_id": conv_id, "status": "resolved"}),
            content_type="application/json",
        )
        self.assertEqual(status_res.status_code, 200)
        conv = JudgeConversation.objects.get(pk=conv_id)
        self.assertEqual(conv.status, JudgeConversation.Status.RESOLVED)
        self.assertTrue(conv.resolved_at is not None)


class AparellOwnershipIsolationTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        User = get_user_model()
        self.user_a = User.objects.create_user(
            username="ap_owner_a",
            password="testpass123",
            email="ap-owner-a@example.com",
        )
        self.user_b = User.objects.create_user(
            username="ap_owner_b",
            password="testpass123",
            email="ap-owner-b@example.com",
        )

        self.comp = self._create_competicio("Comp Aparell Owners")
        CompeticioMembership.objects.create(
            user=self.user_a,
            competicio=self.comp,
            role=CompeticioMembership.Role.EDITOR,
            is_active=True,
        )

    def test_two_users_can_create_same_aparell_code(self):
        ap_a = self._create_aparell("TRA", "Aparell TRA A", owner=self.user_a)
        ap_b = self._create_aparell("TRA", "Aparell TRA B", owner=self.user_b)
        self.assertNotEqual(ap_a.id, ap_b.id)

    def test_cannot_attach_foreign_aparell_to_competition(self):
        self._create_aparell("TRA", "Aparell propi", owner=self.user_a)
        foreign = self._create_aparell("TRA", "Aparell aliè", owner=self.user_b)

        self.client.force_login(self.user_a)
        url = reverse("trampoli_aparell_create", kwargs={"pk": self.comp.id})
        res = self.client.post(url, data={"aparell": foreign.id, "nombre_exercicis": 1})
        self.assertEqual(res.status_code, 200)
        self.assertIn("form", res.context)
        self.assertIn("aparell", res.context["form"].errors)
        self.assertFalse(
            CompeticioAparell.objects.filter(competicio=self.comp, aparell=foreign).exists()
        )

    def test_cannot_edit_foreign_aparell_catalog_entry(self):
        foreign = self._create_aparell("TRA", "Aparell aliè", owner=self.user_b)
        self.client.force_login(self.user_a)
        url = reverse("aparell_update", kwargs={"pk": foreign.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 404)

    def test_can_delete_own_global_aparell_when_unused(self):
        own = self._create_aparell("DEL", "Aparell eliminable", owner=self.user_a)
        self.client.force_login(self.user_a)
        url = reverse("aparell_delete", kwargs={"pk": own.id})
        res = self.client.post(url)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, reverse("aparells_list"))
        self.assertFalse(Aparell.objects.filter(pk=own.id).exists())

    def test_cannot_delete_own_global_aparell_when_used_in_competition(self):
        own = self._create_aparell("USE", "Aparell en us", owner=self.user_a)
        self._create_comp_aparell(self.comp, own, ordre=1, actiu=True)
        self.client.force_login(self.user_a)
        url = reverse("aparell_delete", kwargs={"pk": own.id})
        res = self.client.post(url)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, reverse("aparells_list"))
        self.assertTrue(Aparell.objects.filter(pk=own.id).exists())

    def test_cannot_delete_foreign_global_aparell(self):
        foreign = self._create_aparell("ALI", "Aparell alie", owner=self.user_b)
        self.client.force_login(self.user_a)
        url = reverse("aparell_delete", kwargs={"pk": foreign.id})
        res = self.client.post(url)
        self.assertEqual(res.status_code, 404)
        self.assertTrue(Aparell.objects.filter(pk=foreign.id).exists())

    def test_superuser_sees_owner_in_global_aparell_catalog(self):
        self._create_aparell("OWN1", "Aparell owner b", owner=self.user_b)
        User = get_user_model()
        admin = User.objects.create_superuser(
            username="ap_owner_admin_global",
            password="testpass123",
            email="ap-owner-admin-global@example.com",
        )
        self.client.force_login(admin)
        res = self.client.get(reverse("aparells_list"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Creat per")
        self.assertContains(res, self.user_b.username)

    def test_superuser_sees_owner_in_competicio_aparells_list(self):
        app_b = self._create_aparell("OWN2", "Aparell owner b comp", owner=self.user_b)
        self._create_comp_aparell(self.comp, app_b, ordre=1, actiu=True)
        User = get_user_model()
        admin = User.objects.create_superuser(
            username="ap_owner_admin_comp",
            password="testpass123",
            email="ap-owner-admin-comp@example.com",
        )
        self.client.force_login(admin)
        res = self.client.get(reverse("trampoli_aparells_list", kwargs={"pk": self.comp.id}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Creat per")
        self.assertContains(res, self.user_b.username)
