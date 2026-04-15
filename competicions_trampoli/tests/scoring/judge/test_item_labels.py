import json

from django.test import TestCase
from django.urls import reverse

from ....models.competicio import CompeticioAparell
from ....models.judging import JudgeDeviceToken
from ....models.scoring import ScoringSchema
from ...base import _BaseTrampoliDataMixin


class JudgeItemLabelsAdminTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp item labels")
        self.user = self._login_competicio_user(self.comp, role="owner", username_prefix="judge_item_labels")
        self.app = self._create_aparell("TRAMP_ITEM_LABELS", "Tramp item labels")
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)
        ScoringSchema.objects.create(
            comp_aparell=self.comp_app,
            schema={
                "fields": [
                    {
                        "code": "E",
                        "label": "Execucio",
                        "type": "matrix",
                        "judges": {"count": 2},
                        "items": {"count": 5},
                    },
                    {
                        "code": "DD",
                        "label": "Dificultat",
                        "type": "number",
                    },
                ],
                "computed": [],
            },
        )

    def test_comp_aparell_defaults_judge_ui_config_empty(self):
        comp_aparell = CompeticioAparell.objects.get(pk=self.comp_app.pk)
        self.assertEqual(comp_aparell.judge_ui_config, {})

    def test_judge_admin_saves_matrix_item_labels_on_comp_aparell(self):
        response = self.client.post(
            f"{reverse('judges_qr_home', kwargs={'competicio_id': self.comp.id})}?comp_aparell={self.comp_app.id}",
            data={
                "action": "save_item_labels",
                "field_code": "E",
                "item_labels_json": json.dumps(["Element 1", "Element 2", "Element 3", "Element 4", "Inestabilitat"]),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.comp_app.refresh_from_db()
        self.assertEqual(
            self.comp_app.judge_ui_config,
            {
                "field_item_labels": {
                    "E": ["Element 1", "Element 2", "Element 3", "Element 4", "Inestabilitat"],
                }
            },
        )
        self.assertContains(response, "Noms d&#x27;items desats.")
        self.assertEqual(response.context["schema_field_catalog"][0]["items_count"], 5)
        self.assertEqual(
            response.context["schema_field_catalog"][0]["item_labels"],
            ["Element 1", "Element 2", "Element 3", "Element 4", "Inestabilitat"],
        )

    def test_judge_admin_rejects_unknown_field_item_labels(self):
        response = self.client.post(
            f"{reverse('judges_qr_home', kwargs={'competicio_id': self.comp.id})}?comp_aparell={self.comp_app.id}",
            data={
                "action": "save_item_labels",
                "field_code": "UNKNOWN",
                "item_labels_json": json.dumps(["Element 1"]),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.comp_app.refresh_from_db()
        self.assertEqual(self.comp_app.judge_ui_config, {})
        self.assertContains(response, "El camp seleccionat no existeix al schema.")

    def test_judge_admin_rejects_non_matrix_item_labels(self):
        response = self.client.post(
            f"{reverse('judges_qr_home', kwargs={'competicio_id': self.comp.id})}?comp_aparell={self.comp_app.id}",
            data={
                "action": "save_item_labels",
                "field_code": "DD",
                "item_labels_json": json.dumps(["Dificultat"]),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.comp_app.refresh_from_db()
        self.assertEqual(self.comp_app.judge_ui_config, {})
        self.assertContains(response, "Nomes es poden configurar noms d&#x27;items per camps matrix.")


class JudgeItemLabelsPortalTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp portal item labels")
        self.app = self._create_aparell("TRAMP_PORTAL_LABELS", "Tramp portal labels")
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)
        ScoringSchema.objects.create(
            comp_aparell=self.comp_app,
            schema={
                "fields": [
                    {
                        "code": "E",
                        "label": "Execucio",
                        "type": "matrix",
                        "judges": {"count": 2},
                        "items": {"count": 3},
                    },
                ],
                "computed": [],
            },
        )
        self.ins = self._create_inscripcio(self.comp, "Allowed", ordre=1)
        self.token = JudgeDeviceToken.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            label="Judge item labels",
            permissions=[{"field_code": "E", "judge_index": 1}],
            is_active=True,
        )

    def test_judge_portal_keeps_item_fallback_without_custom_labels(self):
        response = self.client.get(reverse("judge_portal", kwargs={"token": self.token.id}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["judge_item_labels_map"], {})
        body = response.content.decode("utf-8")
        self.assertIn('const ITEM_LABELS_BY_FIELD = JSON.parse(document.getElementById("judge-item-labels-data").textContent || "{}");', body)
        self.assertIn("return configured || `Item ${idx1}`;", body)
        self.assertIn("getItemDisplayLabel(perm.field_code, idx1)", body)

    def test_judge_portal_exposes_custom_item_labels_with_partial_fallback(self):
        self.comp_app.judge_ui_config = {
            "field_item_labels": {
                "E": ["Element 1", "", "Inestabilitat"],
            }
        }
        self.comp_app.save(update_fields=["judge_ui_config"])

        response = self.client.get(reverse("judge_portal", kwargs={"token": self.token.id}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["judge_item_labels_map"],
            {"E": ["Element 1", "", "Inestabilitat"]},
        )
        body = response.content.decode("utf-8")
        self.assertIn("Element 1", body)
        self.assertIn("Inestabilitat", body)
        self.assertIn("return configured || `Item ${idx1}`;", body)
