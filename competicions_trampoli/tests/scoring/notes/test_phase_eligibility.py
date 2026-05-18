import json

from django.test import TestCase
from django.urls import reverse

from ....models import CompeticioMembership
from ....models.competicio import CompeticioAparellFase, ProgramUnit, ProgramUnitSlot
from ....models.scoring import ScoreEntry, ScoringSchema
from ....services.fases import SlotSubject, create_program_unit_from_subjects
from ...base import _BaseTrampoliDataMixin


class NotesPhaseEligibilityTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp notes phase eligibility")
        self.user = self._login_competicio_user(
            self.comp,
            role=CompeticioMembership.Role.OWNER,
            username_prefix="notes_phase_owner",
        )
        self.app = self._create_aparell("TRA_PHASE", "Trampoli phase")
        self.comp_app = self._create_comp_aparell(self.comp, self.app, ordre=1, actiu=True)
        ScoringSchema.objects.create(
            aparell=self.app,
            schema={
                "fields": [
                    {"label": "Execucio", "code": "E", "type": "number", "min": 0, "max": 10},
                ],
                "computed": [],
            },
        )
        self.ins_1 = self._create_inscripcio(self.comp, "Participant 1", ordre=1, grup=1)
        self.ins_2 = self._create_inscripcio(self.comp, "Participant 2", ordre=2, grup=1)

    def _create_phase(self, *, estat=CompeticioAparellFase.Estat.PUBLISHED, codi="FINAL"):
        return CompeticioAparellFase.objects.create(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            nom=codi.title(),
            codi=codi,
            ordre=2,
            estat=estat,
        )

    def _create_unit(self, phase, subjects, *, status=ProgramUnit.Status.PUBLISHED, nom="Final unit"):
        return create_program_unit_from_subjects(
            fase=phase,
            nom=nom,
            subjects=subjects,
            status=status,
        )

    def test_unpublished_phase_unit_is_not_in_manifest_or_notes_table(self):
        phase = self._create_phase(estat=CompeticioAparellFase.Estat.CONFIRMED)
        unit = self._create_unit(
            phase,
            [SlotSubject("inscripcio", self.ins_1.id)],
            status=ProgramUnit.Status.CONFIRMED,
        )

        manifest = self.client.get(reverse("scoring_notes_manifest", kwargs={"pk": self.comp.id}))

        self.assertEqual(manifest.status_code, 200)
        payload = manifest.json()
        unit_keys = {str(row["key"]) for row in payload["units"]}
        self.assertNotIn(f"phase:{phase.id}:unit:{unit.id}", unit_keys)
        self.assertNotIn(phase.id, [row["id"] for row in payload["phases_by_app"][str(self.comp_app.id)] if row["id"]])

        table = self.client.get(
            reverse("scoring_notes_table", kwargs={"pk": self.comp.id}),
            {
                "comp_aparell_id": self.comp_app.id,
                "fase_id": phase.id,
                "exercici": 1,
                "unit_key": f"phase:{phase.id}:unit:{unit.id}",
            },
        )

        self.assertNotEqual(table.status_code, 200)
        self.assertFalse(table.json()["ok"])

    def test_published_phase_unit_is_in_manifest_and_table_loads_subjects(self):
        phase = self._create_phase(estat=CompeticioAparellFase.Estat.PUBLISHED)
        unit = self._create_unit(
            phase,
            [SlotSubject("inscripcio", self.ins_1.id), SlotSubject("inscripcio", self.ins_2.id)],
            status=ProgramUnit.Status.PUBLISHED,
        )

        manifest = self.client.get(reverse("scoring_notes_manifest", kwargs={"pk": self.comp.id}))

        self.assertEqual(manifest.status_code, 200)
        manifest_payload = manifest.json()
        phase_payload = manifest_payload["phases_by_app"][str(self.comp_app.id)]
        self.assertIn(phase.id, [row["id"] for row in phase_payload if row["id"]])
        manifest_unit = next(
            row for row in manifest_payload["units"] if row["key"] == f"phase:{phase.id}:unit:{unit.id}"
        )
        self.assertEqual(manifest_unit["count"], 2)
        self.assertEqual(manifest_unit["phase_id"], phase.id)

        table = self.client.get(
            reverse("scoring_notes_table", kwargs={"pk": self.comp.id}),
            {
                "comp_aparell_id": self.comp_app.id,
                "fase_id": phase.id,
                "exercici": 1,
                "unit_key": f"phase:{phase.id}:unit:{unit.id}",
            },
        )

        self.assertEqual(table.status_code, 200)
        table_payload = table.json()
        self.assertTrue(table_payload["ok"])
        self.assertEqual(table_payload["context"]["fase_id"], phase.id)
        self.assertEqual([row["subject_id"] for row in table_payload["subjects"]], [self.ins_1.id, self.ins_2.id])

    def test_pending_decision_slot_is_not_scoreable(self):
        phase = self._create_phase(estat=CompeticioAparellFase.Estat.PUBLISHED)
        unit = self._create_unit(
            phase,
            [
                SlotSubject("inscripcio", self.ins_1.id),
                SlotSubject(
                    "inscripcio",
                    self.ins_2.id,
                    status=ProgramUnitSlot.Status.PENDING_DECISION,
                ),
            ],
            status=ProgramUnit.Status.PUBLISHED,
        )

        table = self.client.get(
            reverse("scoring_notes_table", kwargs={"pk": self.comp.id}),
            {
                "comp_aparell_id": self.comp_app.id,
                "fase_id": phase.id,
                "exercici": 1,
                "unit_key": f"phase:{phase.id}:unit:{unit.id}",
            },
        )

        self.assertEqual(table.status_code, 200)
        payload = table.json()
        self.assertEqual([row["subject_id"] for row in payload["subjects"]], [self.ins_1.id])

    def test_scoring_save_partial_rejects_subject_outside_published_phase_slots(self):
        phase = self._create_phase(estat=CompeticioAparellFase.Estat.PUBLISHED)
        self._create_unit(
            phase,
            [SlotSubject("inscripcio", self.ins_1.id)],
            status=ProgramUnit.Status.PUBLISHED,
        )

        response = self.client.post(
            reverse("scoring_save_partial", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "inscripcio_id": self.ins_2.id,
                    "comp_aparell_id": self.comp_app.id,
                    "fase_id": phase.id,
                    "exercici": 1,
                    "inputs_patch": {"E": 8.5},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()["ok"])
        self.assertFalse(
            ScoreEntry.objects.filter(
                competicio=self.comp,
                comp_aparell=self.comp_app,
                fase=phase,
                inscripcio=self.ins_2,
            ).exists()
        )

    def test_legacy_scoring_save_partial_without_phase_id_still_works(self):
        response = self.client.post(
            reverse("scoring_save_partial", kwargs={"pk": self.comp.id}),
            data=json.dumps(
                {
                    "inscripcio_id": self.ins_1.id,
                    "comp_aparell_id": self.comp_app.id,
                    "exercici": 1,
                    "inputs_patch": {"E": 7.25},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["fase_id"])
        entry = ScoreEntry.objects.get(
            competicio=self.comp,
            comp_aparell=self.comp_app,
            inscripcio=self.ins_1,
            exercici=1,
            fase__isnull=True,
        )
        self.assertEqual(entry.inputs["E"], 7.25)
