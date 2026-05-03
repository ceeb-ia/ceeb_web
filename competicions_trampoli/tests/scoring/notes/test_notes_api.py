import json

from django.test import TestCase
from django.urls import reverse

from ....models import CompeticioMembership
from ....models.rotacions import RotacioAssignacio, RotacioAssignacioGrup, RotacioEstacio, RotacioFranja
from ....models.scoring import ScoreEntry, ScoreWarningAcknowledgement, ScoringSchema
from ....services.scoring.notes_units import build_notes_units_context
from ...base import _BaseTrampoliDataMixin


class NotesUnitsApiTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp notes units")
        self.user = self._login_competicio_user(
            self.comp,
            role=CompeticioMembership.Role.OWNER,
            username_prefix="notes_units_owner",
        )
        self.app = self._create_aparell("DMT_NOTES", "Doble minitramp")
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)
        self.ins_1 = self._create_inscripcio(self.comp, "Participant A1", ordre=1, grup=1)
        self.ins_2 = self._create_inscripcio(self.comp, "Participant A2", ordre=2, grup=1)
        self.ins_3 = self._create_inscripcio(self.comp, "Participant B1", ordre=3, grup=2)
        self.group_a = self.ins_1.grup_competicio
        self.group_b = self.ins_3.grup_competicio
        self.franja = RotacioFranja.objects.create(
            competicio=self.comp,
            hora_inici="09:00",
            hora_fi="09:30",
            ordre=1,
            titol="Franja 1",
        )
        self.estacio = RotacioEstacio.objects.create(
            competicio=self.comp,
            tipus="aparell",
            comp_aparell=self.comp_app,
            ordre=1,
            actiu=True,
        )
        self.assignacio = RotacioAssignacio.objects.create(
            competicio=self.comp,
            franja=self.franja,
            estacio=self.estacio,
        )
        RotacioAssignacioGrup.objects.create(assignacio=self.assignacio, grup=self.group_a, ordre=1)
        RotacioAssignacioGrup.objects.create(assignacio=self.assignacio, grup=self.group_b, ordre=2)

    def test_notes_units_keep_multi_group_cell_as_single_unit(self):
        context = build_notes_units_context(self.comp)

        units = context["units"]
        self.assertEqual(len(units), 1)
        unit = units[0]
        expected_key = f"unit:{self.group_a.id}+{self.group_b.id}"
        self.assertEqual(unit["key"], expected_key)
        self.assertEqual(unit["label"], "Grup 1 + Grup 2")
        self.assertEqual(unit["member_keys"], [self.group_a.id, self.group_b.id])
        self.assertEqual(unit["count"], 3)
        self.assertFalse(unit["is_out_of_program"])

    def test_manifest_returns_light_units_without_scores(self):
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_1,
            comp_aparell=self.comp_app,
            exercici=1,
            inputs={"E": 9},
            outputs={"total": 9},
            total=9,
        )

        response = self.client.get(reverse("scoring_notes_manifest", kwargs={"pk": self.comp.id}))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["competition"]["id"], self.comp.id)
        self.assertEqual(len(payload["franges"]), 1)
        self.assertEqual(len(payload["apps"]), 1)
        self.assertEqual(len(payload["units"]), 1)
        self.assertNotIn("scores", payload)
        unit = payload["units"][0]
        self.assertEqual(unit["label"], "Grup 1 + Grup 2")
        self.assertEqual(unit["count"], 3)
        self.assertEqual(payload["initial_context"]["unit_key"], str(unit["key"]))

    def test_lazy_table_returns_combined_subjects_and_scores_for_multi_group_unit(self):
        score = ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_3,
            comp_aparell=self.comp_app,
            exercici=1,
            inputs={"E": 8.5},
            outputs={"total": 8.5},
            total=8.5,
        )
        unit_key = f"unit:{self.group_a.id}+{self.group_b.id}"

        response = self.client.get(
            reverse("scoring_notes_table", kwargs={"pk": self.comp.id}),
            {
                "franja_id": self.franja.id,
                "comp_aparell_id": self.comp_app.id,
                "exercici": 1,
                "unit_key": unit_key,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["unit"]["key"], unit_key)
        self.assertEqual([row["subject_id"] for row in payload["subjects"]], [self.ins_1.id, self.ins_2.id, self.ins_3.id])
        score_key = f"inscripcio:{self.ins_3.id}|1|{self.comp_app.id}"
        self.assertIn(score_key, payload["scores"])
        self.assertEqual(payload["scores"][score_key]["total"], float(score.total))
        self.assertEqual(payload["rotation_rank"][f"{self.comp_app.id}|{self.ins_3.id}"], 3)

    def test_lazy_table_returns_score_warnings_for_out_of_range_values(self):
        ScoringSchema.objects.update_or_create(
            aparell=self.app,
            defaults={
                "schema": {
                    "fields": [
                        {"code": "E", "type": "number", "min": 0, "max": 10},
                    ],
                }
            },
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_1,
            comp_aparell=self.comp_app,
            exercici=1,
            inputs={"E": 12},
            outputs={"total": 12},
            total=12,
        )

        response = self.client.get(
            reverse("scoring_notes_table", kwargs={"pk": self.comp.id}),
            {
                "franja_id": self.franja.id,
                "comp_aparell_id": self.comp_app.id,
                "exercici": 1,
                "unit_key": f"unit:{self.group_a.id}+{self.group_b.id}",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([warning["code"] for warning in payload["warnings"]], ["range_high"])
        warning = payload["warnings"][0]
        self.assertEqual(warning["subject_kind"], "inscripcio")
        self.assertEqual(warning["subject_id"], self.ins_1.id)
        self.assertEqual(warning["comp_aparell_id"], self.comp_app.id)
        self.assertEqual(warning["field_code"], "E")

    def test_warnings_endpoint_aggregates_warning_navigation_metadata(self):
        ScoringSchema.objects.update_or_create(
            aparell=self.app,
            defaults={
                "schema": {
                    "fields": [
                        {"code": "E", "type": "number", "min": 0, "max": 10},
                    ],
                }
            },
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_3,
            comp_aparell=self.comp_app,
            exercici=1,
            inputs={"E": 12},
            outputs={"total": 12},
            total=12,
        )

        response = self.client.get(reverse("scoring_notes_warnings", kwargs={"pk": self.comp.id}))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["raw_count"], 1)
        warning = payload["warnings"][0]
        self.assertEqual(warning["code"], "range_high")
        self.assertEqual(warning["subject"]["id"], self.ins_3.id)
        self.assertEqual(warning["subject"]["name"], "Participant B1")
        self.assertEqual(warning["unit"]["key"], f"unit:{self.group_a.id}+{self.group_b.id}")
        self.assertEqual(warning["app"]["id"], self.comp_app.id)
        self.assertEqual(
            warning["navigation"],
            {
                "franja_id": self.franja.id,
                "comp_aparell_id": self.comp_app.id,
                "exercici": 1,
                "unit_key": f"unit:{self.group_a.id}+{self.group_b.id}",
                "unit_identity": f"franja:{self.franja.id}|{self.comp_app.id}|unit:{self.group_a.id}+{self.group_b.id}",
            },
        )

    def test_warnings_endpoint_groups_multiple_warnings_by_participant(self):
        ScoringSchema.objects.update_or_create(
            aparell=self.app,
            defaults={
                "schema": {
                    "fields": [
                        {"code": "E", "type": "number", "min": 0, "max": 10},
                        {"code": "D", "type": "number", "min": 1, "max": 5},
                    ],
                }
            },
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_1,
            comp_aparell=self.comp_app,
            exercici=1,
            inputs={"E": 12, "D": 0},
            outputs={"total": 12},
            total=12,
        )

        response = self.client.get(reverse("scoring_notes_warnings", kwargs={"pk": self.comp.id}))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["raw_count"], 2)
        warning = payload["warnings"][0]
        self.assertEqual(warning["subject"]["id"], self.ins_1.id)
        self.assertEqual(warning["warning_count"], 2)
        self.assertEqual(warning["code"], "grouped")
        self.assertEqual(len(warning["details"]), 2)
        self.assertEqual(warning["summary"]["fields"], ["E", "D"])

    def test_warnings_endpoint_detects_judge_presence_outlier_in_unit(self):
        ScoringSchema.objects.update_or_create(
            aparell=self.app,
            defaults={
                "schema": {
                    "fields": [
                        {
                            "code": "E",
                            "type": "list",
                            "shape": "judge",
                            "judges": {"count": 2},
                            "min": 0,
                            "max": 10,
                        },
                    ],
                }
            },
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_1,
            comp_aparell=self.comp_app,
            exercici=1,
            inputs={"E": [8, 8], "__presence__E": [True, True]},
            outputs={"total": 16},
            total=16,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_2,
            comp_aparell=self.comp_app,
            exercici=1,
            inputs={"E": [7, 7], "__presence__E": [True, True]},
            outputs={"total": 14},
            total=14,
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_3,
            comp_aparell=self.comp_app,
            exercici=1,
            inputs={"E": [6, None], "__presence__E": [True, False]},
            outputs={"total": 6},
            total=6,
        )

        response = self.client.get(reverse("scoring_notes_warnings", kwargs={"pk": self.comp.id}))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        outlier = next(w for w in payload["warnings"] if w["subject"]["id"] == self.ins_3.id)
        self.assertEqual(outlier["code"], "judge_presence_outlier")
        self.assertEqual(outlier["expected"], {"presence_count": 2, "missing_judges": [2]})

    def test_warning_validate_hides_acknowledged_warning(self):
        ScoringSchema.objects.update_or_create(
            aparell=self.app,
            defaults={
                "schema": {
                    "fields": [
                        {"code": "E", "type": "number", "min": 0, "max": 10},
                    ],
                }
            },
        )
        ScoreEntry.objects.create(
            competicio=self.comp,
            inscripcio=self.ins_1,
            comp_aparell=self.comp_app,
            exercici=1,
            inputs={"E": 12},
            outputs={"total": 12},
            total=12,
        )
        warning_payload = self.client.get(reverse("scoring_notes_warnings", kwargs={"pk": self.comp.id})).json()
        ack_key = warning_payload["warnings"][0]["ack_keys"][0]

        response = self.client.post(
            reverse("scoring_notes_warning_validate", kwargs={"pk": self.comp.id}),
            data=json.dumps({"ack_keys": [ack_key]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertTrue(
            ScoreWarningAcknowledgement.objects.filter(competicio=self.comp, warning_key=ack_key).exists()
        )
        after_payload = self.client.get(reverse("scoring_notes_warnings", kwargs={"pk": self.comp.id})).json()
        self.assertEqual(after_payload["warnings"], [])
