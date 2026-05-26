import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from ...base import _BaseTrampoliDataMixin
from ....models.competicio import CompeticioAparellFase, ProgramUnit, ProgramUnitSlot
from ....models.judging import JudgeDeviceToken, JudgePortalAssignment
from ....models.scoring import ScoreEntry, ScoreEntryVideo, ScoringSchema
from ....services.judging.assignments import (
    effective_assignments_for_token,
    resolve_effective_assignment,
)


class JudgePortalAssignmentModelTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.competicio = self._create_competicio()
        self.aparell = self._create_aparell("TRA", "Trampoli")
        self.comp_aparell = self._create_comp_aparell(self.competicio, self.aparell)
        self.token = JudgeDeviceToken.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            label="Jutge 1",
            permissions=[{"field_code": "E", "judge_index": 1}],
        )

    def _create_phase(self, comp_aparell=None, codi="FINAL"):
        comp_aparell = comp_aparell or self.comp_aparell
        return CompeticioAparellFase.objects.create(
            competicio=comp_aparell.competicio,
            comp_aparell=comp_aparell,
            nom=codi.title(),
            codi=codi,
            ordre=1,
        )

    def test_save_fills_competicio_from_token(self):
        assignment = JudgePortalAssignment.objects.create(
            judge_token=self.token,
            comp_aparell=self.comp_aparell,
            label="Preliminar",
            permissions=[{"field_code": "D", "judge_index": 2}],
        )

        self.assertEqual(assignment.competicio_id, self.competicio.id)
        self.assertIsNone(assignment.fase_id)

    def test_validates_phase_belongs_to_same_competicio_and_app(self):
        other_app = self._create_comp_aparell(self.competicio, self.aparell, ordre=2)
        other_phase = self._create_phase(other_app, codi="FINAL_B")
        assignment = JudgePortalAssignment(
            judge_token=self.token,
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            fase=other_phase,
            permissions=[],
        )

        with self.assertRaises(ValidationError) as ctx:
            assignment.full_clean()

        self.assertIn("fase", ctx.exception.message_dict)

    def test_validates_assignment_competition_matches_token(self):
        other_competicio = self._create_competicio("Alt")
        assignment = JudgePortalAssignment(
            judge_token=self.token,
            competicio=other_competicio,
            comp_aparell=self.comp_aparell,
            permissions=[],
        )

        with self.assertRaises(ValidationError) as ctx:
            assignment.full_clean()

        self.assertIn("competicio", ctx.exception.message_dict)

    def test_permissions_must_be_list(self):
        assignment = JudgePortalAssignment(
            judge_token=self.token,
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            permissions={"field_code": "E"},
        )

        with self.assertRaises(ValidationError) as ctx:
            assignment.full_clean()

        self.assertIn("permissions", ctx.exception.message_dict)


class JudgePortalAssignmentResolutionTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.competicio = self._create_competicio()
        self.aparell = self._create_aparell("TRA", "Trampoli")
        self.comp_aparell = self._create_comp_aparell(self.competicio, self.aparell)
        self.token = JudgeDeviceToken.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            label="Jutge dispositiu",
            permissions=[{"field_code": "E", "judge_index": 1}],
            can_record_video=True,
        )

    def _create_phase(self):
        return CompeticioAparellFase.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            nom="Final",
            codi="FINAL",
            ordre=1,
        )

    def test_token_without_assignments_exposes_legacy_assignment(self):
        assignments = effective_assignments_for_token(self.token)

        self.assertEqual(len(assignments), 1)
        legacy = assignments[0]
        self.assertIsNone(legacy.id)
        self.assertTrue(legacy.is_legacy)
        self.assertEqual(legacy.comp_aparell_id, self.comp_aparell.id)
        self.assertIsNone(legacy.fase_id)
        self.assertEqual(legacy.permissions, [{"field_code": "E", "judge_index": 1}])
        self.assertTrue(legacy.can_record_video)

    def test_explicit_assignments_replace_legacy_scope(self):
        phase = self._create_phase()
        prelim = JudgePortalAssignment.objects.create(
            judge_token=self.token,
            comp_aparell=self.comp_aparell,
            label="Preliminar",
            ordre=1,
            permissions=[{"field_code": "D", "judge_index": 1}],
        )
        final = JudgePortalAssignment.objects.create(
            judge_token=self.token,
            comp_aparell=self.comp_aparell,
            fase=phase,
            label="Final",
            ordre=2,
            permissions=[{"field_code": "E", "judge_index": 2}],
        )

        assignments = effective_assignments_for_token(self.token)

        self.assertEqual([item.id for item in assignments], [prelim.id, final.id])
        self.assertFalse(any(item.is_legacy for item in assignments))
        self.assertEqual(assignments[0].fase_id, None)
        self.assertEqual(assignments[0].permissions, [{"field_code": "D", "judge_index": 1}])
        self.assertEqual(assignments[1].fase_id, phase.id)
        self.assertEqual(assignments[1].permissions, [{"field_code": "E", "judge_index": 2}])

    def test_inactive_explicit_assignment_does_not_fallback_to_legacy(self):
        JudgePortalAssignment.objects.create(
            judge_token=self.token,
            comp_aparell=self.comp_aparell,
            label="Inactiva",
            ordre=1,
            permissions=[],
            is_active=False,
        )

        self.assertEqual(effective_assignments_for_token(self.token), [])
        self.assertEqual(len(effective_assignments_for_token(self.token, include_inactive=True)), 1)

    def test_inactive_token_has_no_effective_assignments(self):
        JudgePortalAssignment.objects.create(
            judge_token=self.token,
            comp_aparell=self.comp_aparell,
            label="Activa",
            ordre=1,
            permissions=[],
        )
        self.token.is_active = False
        self.token.save(update_fields=["is_active"])

        self.assertEqual(effective_assignments_for_token(self.token), [])
        inactive = effective_assignments_for_token(self.token, include_inactive=True)
        self.assertEqual(len(inactive), 1)
        self.assertFalse(inactive[0].is_active)

    def test_resolve_effective_assignment_requires_id_when_multiple_assignments_exist(self):
        first = JudgePortalAssignment.objects.create(
            judge_token=self.token,
            comp_aparell=self.comp_aparell,
            label="A",
            ordre=1,
            permissions=[],
        )
        JudgePortalAssignment.objects.create(
            judge_token=self.token,
            comp_aparell=self.comp_aparell,
            label="B",
            ordre=2,
            permissions=[],
        )

        self.assertIsNone(resolve_effective_assignment(self.token))
        self.assertEqual(resolve_effective_assignment(self.token, first.id).id, first.id)
        self.assertIsNone(resolve_effective_assignment(self.token, 999999))


class JudgePortalAssignmentPortalTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.competicio = self._create_competicio()
        self.aparell = self._create_aparell("TRA", "Trampoli")
        self.comp_aparell = self._create_comp_aparell(self.competicio, self.aparell)
        ScoringSchema.objects.create(
            aparell=self.aparell,
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
                        "label": "Dificultat",
                        "code": "D",
                        "type": "number",
                        "decimals": 1,
                    },
                ],
                "computed": [],
            },
        )
        self.inscripcio = self._create_inscripcio(self.competicio, "Gimnasta 1")
        self.token = JudgeDeviceToken.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            label="Jutge portal",
            permissions=[{"field_code": "E", "judge_index": 1}],
            can_record_video=True,
        )

    def _create_phase(self, *, estat=CompeticioAparellFase.Estat.PLANNED):
        return CompeticioAparellFase.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            nom="Final",
            codi="FINAL",
            ordre=1,
            estat=estat,
        )

    def _add_phase_slot(self, phase):
        unit = ProgramUnit.objects.create(
            fase=phase,
            nom="Final unitat",
            tipus=ProgramUnit.Tipus.BLOCK,
            ordre=1,
            capacity=1,
            status=ProgramUnit.Status.CONFIRMED,
        )
        ProgramUnitSlot.objects.create(
            unit=unit,
            slot_index=1,
            ordre=1,
            status=ProgramUnitSlot.Status.FILLED,
            subject_kind="inscripcio",
            subject_id=self.inscripcio.id,
        )
        return unit

    def test_legacy_token_without_assignments_opens_current_portal(self):
        response = self.client.get(reverse("judge_portal", kwargs={"token": self.token.id}))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "judge/portal.html")
        self.assertEqual(response.context["comp_aparell"], self.comp_aparell)
        self.assertIsNone(response.context["fase"])
        self.assertIsNone(response.context["judge_assignment_id"])
        self.assertEqual(response.context["permissions"][0]["field_code"], "E")
        self.assertEqual(response.context["permissions"][0]["judge_index"], 1)

    def test_multi_assignment_token_shows_home(self):
        JudgePortalAssignment.objects.create(
            judge_token=self.token,
            comp_aparell=self.comp_aparell,
            label="Preliminar",
            ordre=1,
            permissions=[{"field_code": "E", "judge_index": 1}],
        )
        phase = self._create_phase()
        JudgePortalAssignment.objects.create(
            judge_token=self.token,
            comp_aparell=self.comp_aparell,
            fase=phase,
            label="Final",
            ordre=2,
            permissions=[{"field_code": "D", "judge_index": 2}],
        )

        response = self.client.get(reverse("judge_portal", kwargs={"token": self.token.id}))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "judge/portal_home.html")
        self.assertContains(response, "Preliminar")
        self.assertContains(response, "Final")
        self.assertContains(response, "Bloquejada")

    def test_assignment_id_scopes_portal_to_assignment_app_phase_and_permissions(self):
        phase = self._create_phase(estat=CompeticioAparellFase.Estat.PUBLISHED)
        self._add_phase_slot(phase)
        assignment = JudgePortalAssignment.objects.create(
            judge_token=self.token,
            comp_aparell=self.comp_aparell,
            fase=phase,
            label="Final",
            ordre=1,
            permissions=[{"field_code": "D", "judge_index": 2}],
        )

        response = self.client.get(
            reverse(
                "judge_portal_assignment",
                kwargs={"token": self.token.id, "assignment_id": assignment.id},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "judge/portal.html")
        self.assertEqual(response.context["comp_aparell"], self.comp_aparell)
        self.assertEqual(response.context["fase"], phase)
        self.assertEqual(response.context["judge_assignment_id"], assignment.id)
        self.assertEqual(response.context["permissions"][0]["field_code"], "D")
        self.assertEqual(response.context["permissions"][0]["judge_index"], 2)
        self.assertEqual([item["subject_id"] for item in response.context["inscripcions"]], [self.inscripcio.id])
        self.assertIn(f"assignment_id={assignment.id}", response.context["save_url"])
        self.assertIn(f"assignment_id={assignment.id}", response.context["updates_url"])
        self.assertIn(f"assignment_id={assignment.id}", response.context["video_status_url"])

    def test_pending_phase_assignment_is_blocked_on_home_and_direct_url(self):
        phase = self._create_phase(estat=CompeticioAparellFase.Estat.PLANNED)
        assignment = JudgePortalAssignment.objects.create(
            judge_token=self.token,
            comp_aparell=self.comp_aparell,
            fase=phase,
            label="Final pendent",
            ordre=1,
            permissions=[{"field_code": "D", "judge_index": 2}],
        )

        home = self.client.get(reverse("judge_portal", kwargs={"token": self.token.id}))
        direct = self.client.get(
            reverse(
                "judge_portal_assignment",
                kwargs={"token": self.token.id, "assignment_id": assignment.id},
            )
        )

        self.assertEqual(home.status_code, 200)
        self.assertTemplateUsed(home, "judge/portal_home.html")
        self.assertContains(home, "Bloquejada")
        self.assertNotContains(home, reverse("judge_portal_assignment", kwargs={"token": self.token.id, "assignment_id": assignment.id}))
        self.assertEqual(direct.status_code, 403)
        self.assertTemplateUsed(direct, "judge/portal_home.html")

    def test_assignment_save_creates_phase_scoped_score(self):
        phase = self._create_phase(estat=CompeticioAparellFase.Estat.PUBLISHED)
        self._add_phase_slot(phase)
        assignment = JudgePortalAssignment.objects.create(
            judge_token=self.token,
            comp_aparell=self.comp_aparell,
            fase=phase,
            label="Final",
            ordre=1,
            permissions=[{"field_code": "E", "judge_index": 1}],
        )

        response = self.client.post(
            f"{reverse('judge_save_partial', kwargs={'token': self.token.id})}?assignment_id={assignment.id}",
            data=json.dumps(
                {
                    "assignment_id": assignment.id,
                    "inscripcio_id": self.inscripcio.id,
                    "subject_kind": "inscripcio",
                    "subject_id": self.inscripcio.id,
                    "exercici": 1,
                    "inputs_patch": {"E": [0.1, 0.2, 0.3, 0.4, 0.5]},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["assignment_id"], assignment.id)
        self.assertEqual(payload["fase_id"], phase.id)
        entry = ScoreEntry.objects.get(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            inscripcio=self.inscripcio,
            exercici=1,
            fase=phase,
        )
        self.assertEqual(entry.inputs["E"][0], [0.1, 0.2, 0.3, 0.4, 0.5])
        self.assertFalse(
            ScoreEntry.objects.filter(
                competicio=self.competicio,
                comp_aparell=self.comp_aparell,
                inscripcio=self.inscripcio,
                exercici=1,
                fase__isnull=True,
            ).exists()
        )

    def test_assignment_save_rejects_subject_outside_phase_slots(self):
        outside = self._create_inscripcio(self.competicio, "Fora fase", ordre=2)
        phase = self._create_phase(estat=CompeticioAparellFase.Estat.PUBLISHED)
        self._add_phase_slot(phase)
        assignment = JudgePortalAssignment.objects.create(
            judge_token=self.token,
            comp_aparell=self.comp_aparell,
            fase=phase,
            label="Final",
            ordre=1,
            permissions=[{"field_code": "E", "judge_index": 1}],
        )

        response = self.client.post(
            reverse("judge_save_partial", kwargs={"token": self.token.id}),
            data=json.dumps(
                {
                    "assignment_id": assignment.id,
                    "inscripcio_id": outside.id,
                    "subject_kind": "inscripcio",
                    "subject_id": outside.id,
                    "exercici": 1,
                    "inputs_patch": {"E": [0.1, 0.2, 0.3, 0.4, 0.5]},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ScoreEntry.objects.filter(inscripcio=outside, fase=phase).exists())

    def test_updates_filter_phase_assignment_and_legacy_scope_separately(self):
        phase = self._create_phase(estat=CompeticioAparellFase.Estat.PUBLISHED)
        self._add_phase_slot(phase)
        assignment = JudgePortalAssignment.objects.create(
            judge_token=self.token,
            comp_aparell=self.comp_aparell,
            fase=phase,
            label="Final",
            ordre=1,
            permissions=[{"field_code": "E", "judge_index": 1}],
        )
        ScoreEntry.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            inscripcio=self.inscripcio,
            exercici=1,
            fase=None,
            inputs={"E": [[9, 9, 9, 9, 9], None]},
            outputs={},
            total=9,
        )
        phase_entry = ScoreEntry.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            inscripcio=self.inscripcio,
            exercici=1,
            fase=phase,
            inputs={"E": [[1, 2, 3, 4, 5], None]},
            outputs={},
            total=1,
        )

        phase_response = self.client.get(
            reverse("judge_updates", kwargs={"token": self.token.id}),
            {
                "assignment_id": assignment.id,
                "since": "2000-01-01T00:00:00Z",
                "exercici": "1",
            },
        )

        self.assertEqual(phase_response.status_code, 200, phase_response.content)
        phase_updates = phase_response.json()["updates"]
        self.assertEqual([item["fase_id"] for item in phase_updates], [phase.id])
        self.assertEqual(phase_updates[0]["total"], float(phase_entry.total))

        legacy_token = JudgeDeviceToken.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            label="Legacy",
            permissions=[{"field_code": "E", "judge_index": 1}],
        )
        legacy_response = self.client.get(
            reverse("judge_updates", kwargs={"token": legacy_token.id}),
            {"since": "2000-01-01T00:00:00Z", "exercici": "1"},
        )

        self.assertEqual(legacy_response.status_code, 200, legacy_response.content)
        legacy_updates = legacy_response.json()["updates"]
        self.assertEqual([item["fase_id"] for item in legacy_updates], [None])

    def test_video_status_uses_phase_scoped_score_for_assignment(self):
        phase = self._create_phase(estat=CompeticioAparellFase.Estat.PUBLISHED)
        self._add_phase_slot(phase)
        assignment = JudgePortalAssignment.objects.create(
            judge_token=self.token,
            comp_aparell=self.comp_aparell,
            fase=phase,
            label="Final",
            ordre=1,
            permissions=[{"field_code": "E", "judge_index": 1}],
        )
        ScoreEntry.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            inscripcio=self.inscripcio,
            exercici=1,
            fase=None,
            inputs={},
            outputs={},
            total=0,
        )
        phase_entry = ScoreEntry.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            inscripcio=self.inscripcio,
            exercici=1,
            fase=phase,
            inputs={},
            outputs={},
            total=0,
        )
        ScoreEntryVideo.objects.create(
            score_entry=phase_entry,
            video_file=SimpleUploadedFile("phase.mp4", b"phase-video", content_type="video/mp4"),
            status=ScoreEntryVideo.Status.READY,
            mime_type="video/mp4",
            original_filename="phase.mp4",
        )

        response = self.client.get(
            reverse("judge_video_status", kwargs={"token": self.token.id}),
            {
                "assignment_id": assignment.id,
                "subject_kind": "inscripcio",
                "subject_id": self.inscripcio.id,
                "exercici": "1",
            },
        )

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertTrue(payload["has_video"])
        self.assertEqual(payload["score_entry_id"], phase_entry.id)
        self.assertIn(f"assignment_id={assignment.id}", payload["video"]["url"])


class JudgePortalAssignmentAdminUiTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.competicio = self._create_competicio("Comp QRs")
        self._login_competicio_user(self.competicio, role="owner", username_prefix="judge_qr_ui")
        self.aparell = self._create_aparell("TRA_QR", "Trampoli QR")
        self.comp_aparell = self._create_comp_aparell(self.competicio, self.aparell)
        ScoringSchema.objects.create(
            aparell=self.aparell,
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
                    },
                ],
                "computed": [],
            },
        )

    def test_judges_qr_home_is_global_and_creates_general_device(self):
        response = self.client.get(reverse("judges_qr_home", kwargs={"competicio_id": self.competicio.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tots els aparells")
        self.assertContains(response, "Crear QR general")

        create = self.client.post(
            reverse("judges_qr_home", kwargs={"competicio_id": self.competicio.id}),
            data={
                "action": "create_device",
                "label": "Jutge general",
                "can_record_video": "1",
            },
        )

        self.assertEqual(create.status_code, 302)
        token = JudgeDeviceToken.objects.get(label="Jutge general")
        self.assertEqual(token.comp_aparell_id, self.comp_aparell.id)
        self.assertEqual(token.permissions, [])
        self.assertTrue(token.can_record_video)
        self.assertFalse(JudgePortalAssignment.objects.filter(judge_token=token).exists())

    def test_judges_qr_home_adds_assignment_to_existing_device(self):
        token = JudgeDeviceToken.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            label="Jutge general",
            permissions=[],
        )
        phase = CompeticioAparellFase.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            nom="Final",
            codi="FINAL",
            ordre=1,
        )

        response = self.client.post(
            f"{reverse('judges_qr_home', kwargs={'competicio_id': self.competicio.id})}?comp_aparell={self.comp_aparell.id}",
            data={
                "action": "add_assignment",
                "token_id": str(token.id),
                "assignment_label": "Final E1",
                "fase_id": str(phase.id),
                "ordre": "2",
                "form-TOTAL_FORMS": "1",
                "form-INITIAL_FORMS": "0",
                "form-MIN_NUM_FORMS": "0",
                "form-MAX_NUM_FORMS": "15",
                "form-0-field_code": "E",
                "form-0-scope": "shared",
                "form-0-member_mode": "all",
                "form-0-member_slots": "",
                "form-0-judge_index": "1",
                "form-0-item_start": "1",
                "form-0-item_count": "3",
            },
        )

        self.assertEqual(response.status_code, 302)
        assignment = JudgePortalAssignment.objects.get(judge_token=token)
        self.assertEqual(assignment.comp_aparell_id, self.comp_aparell.id)
        self.assertEqual(assignment.fase_id, phase.id)
        self.assertEqual(assignment.label, "Final E1")
        self.assertEqual(assignment.ordre, 2)
        self.assertEqual(assignment.permissions[0]["field_code"], "E")
        self.assertEqual(assignment.permissions[0]["item_count"], 3)
