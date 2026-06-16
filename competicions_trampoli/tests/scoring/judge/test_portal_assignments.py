import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ...base import _BaseTrampoliDataMixin
from ....models.competicio import CompeticioAparellFase, ProgramUnit, ProgramUnitSlot
from ....models.judging import JudgeDeviceToken, JudgePortalAssignment, PublicLiveToken
from ....models.scoring import ScoreEntry, ScoreEntryVideo, ScoringSchema
from ....services.judging.assignments import (
    effective_assignments_for_token,
    resolve_effective_assignment,
)
from ....services.judging.subject_scope import filter_subject_dicts_by_subject_scope


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

    def test_subject_scope_filters_team_subjects_by_all_member_categories(self):
        inside = self._create_inscripcio(self.competicio, "Infantil dins", ordre=1)
        inside.categoria = "Infantil"
        inside.save(update_fields=["categoria"])
        outside = self._create_inscripcio(self.competicio, "Cadet fora", ordre=2)
        outside.categoria = "Cadet"
        outside.save(update_fields=["categoria"])
        subjects = [
            {
                "subject_kind": "team_unit",
                "subject_id": 1,
                "members": [{"id": inside.id}],
            },
            {
                "subject_kind": "team_unit",
                "subject_id": 2,
                "members": [{"id": outside.id}],
            },
            {
                "subject_kind": "team_unit",
                "subject_id": 3,
                "members": [{"id": inside.id}, {"id": outside.id}],
            },
        ]

        filtered = filter_subject_dicts_by_subject_scope(
            subjects,
            {"mode": "filters", "categoria": ["Infantil"]},
            competicio=self.competicio,
        )

        self.assertEqual([item["subject_id"] for item in filtered], [1])

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

    def _add_phase_slot(self, phase, *, unit_status=ProgramUnit.Status.PUBLISHED):
        unit = ProgramUnit.objects.create(
            fase=phase,
            nom="Final unitat",
            tipus=ProgramUnit.Tipus.BLOCK,
            ordre=1,
            capacity=1,
            status=unit_status,
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

    def test_token_home_exposes_ia_score_pwa_metadata(self):
        JudgePortalAssignment.objects.create(
            judge_token=self.token,
            comp_aparell=self.comp_aparell,
            label="Preliminar",
            ordre=1,
            permissions=[{"field_code": "E", "judge_index": 1}],
        )

        response = self.client.get(reverse("judge_portal", kwargs={"token": self.token.id}))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "judge/portal_home.html")
        self.assertEqual(response.context["judge_pwa_app_name"], "IA Score")
        self.assertContains(
            response,
            f'rel="manifest" href="{reverse("judge_manifest", kwargs={"token": self.token.id})}"',
        )
        self.assertContains(response, 'name="apple-mobile-web-app-title" content="IA Score"')

    def test_judge_manifest_launches_from_token_home(self):
        manifest_url = reverse("judge_manifest", kwargs={"token": self.token.id})
        portal_url = reverse("judge_portal", kwargs={"token": self.token.id})

        response = self.client.get(f"{manifest_url}?ex=2&franja=99&view_mode=competition_order")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["name"], "IA Score")
        self.assertEqual(payload["short_name"], "IA Score")
        self.assertEqual(payload["id"], portal_url)
        self.assertEqual(payload["start_url"], f"{portal_url}?home=1")
        self.assertEqual(payload["scope"], portal_url)
        self.assertIn(reverse("judge_pwa_icon", kwargs={"filename": "icon-192.png"}), payload["icons"][0]["src"])

    def test_single_explicit_assignment_token_still_shows_home(self):
        phase = self._create_phase(estat=CompeticioAparellFase.Estat.PUBLISHED)
        self._add_phase_slot(phase)
        assignment = JudgePortalAssignment.objects.create(
            judge_token=self.token,
            comp_aparell=self.comp_aparell,
            fase=phase,
            label="Final unica",
            ordre=1,
            permissions=[{"field_code": "D", "judge_index": 2}],
        )

        response = self.client.get(reverse("judge_portal", kwargs={"token": self.token.id}))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "judge/portal_home.html")
        self.assertContains(response, "Final unica")
        self.assertContains(
            response,
            reverse("judge_portal_assignment", kwargs={"token": self.token.id, "assignment_id": assignment.id}),
        )

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

    def test_phase_program_unit_group_label_formats_partition_values(self):
        phase = self._create_phase(estat=CompeticioAparellFase.Estat.PUBLISHED)
        unit = self._add_phase_slot(phase)
        unit.partition_key = "categoria:PREBENJAMÍ|subcategoria:MASCULÍ"
        unit.nom = "Final - categoria:PREBENJAMÍ|subcategoria:MASCULÍ"
        unit.save(update_fields=["partition_key", "nom", "updated_at"])
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
        label = response.context["group_blocks"][0]["label"]
        self.assertIn("PREBENJAMÍ | MASCULÍ", label)
        self.assertNotIn("categoria:", label)
        self.assertNotIn("subcategoria:", label)

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

    def test_published_phase_assignment_waits_for_published_unit(self):
        phase = self._create_phase(estat=CompeticioAparellFase.Estat.PUBLISHED)
        self._add_phase_slot(phase, unit_status=ProgramUnit.Status.CONFIRMED)
        assignment = JudgePortalAssignment.objects.create(
            judge_token=self.token,
            comp_aparell=self.comp_aparell,
            fase=phase,
            label="Final no publicada",
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
        self.assertContains(home, "Pendent")
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

    def test_assignment_subject_scope_filters_preliminary_portal_by_category(self):
        self.inscripcio.categoria = "Infantil"
        self.inscripcio.subcategoria = "F"
        self.inscripcio.save(update_fields=["categoria", "subcategoria"])
        outside = self._create_inscripcio(self.competicio, "Cadet fora", ordre=2, grup=2)
        outside.categoria = "Cadet"
        outside.subcategoria = "F"
        outside.save(update_fields=["categoria", "subcategoria"])
        assignment = JudgePortalAssignment.objects.create(
            judge_token=self.token,
            comp_aparell=self.comp_aparell,
            label="Infantil",
            ordre=1,
            permissions=[{"field_code": "D", "judge_index": 1}],
            subject_scope={"mode": "filters", "categoria": ["Infantil"], "subcategoria": ["F"]},
        )

        response = self.client.get(
            reverse(
                "judge_portal_assignment",
                kwargs={"token": self.token.id, "assignment_id": assignment.id},
            )
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual([item["subject_id"] for item in response.context["inscripcions"]], [self.inscripcio.id])
        self.assertContains(response, "Categories: Infantil")

    def test_assignment_subject_scope_filters_phase_slots_by_group(self):
        phase = self._create_phase(estat=CompeticioAparellFase.Estat.PUBLISHED)
        unit = self._add_phase_slot(phase)
        outside = self._create_inscripcio(self.competicio, "Grup fora", ordre=2, grup=2)
        ProgramUnitSlot.objects.create(
            unit=unit,
            slot_index=2,
            ordre=2,
            status=ProgramUnitSlot.Status.FILLED,
            subject_kind="inscripcio",
            subject_id=outside.id,
        )
        assignment = JudgePortalAssignment.objects.create(
            judge_token=self.token,
            comp_aparell=self.comp_aparell,
            fase=phase,
            label="Grup concret",
            ordre=1,
            permissions=[{"field_code": "D", "judge_index": 1}],
            subject_scope={"mode": "filters", "group_ids": [self.inscripcio.grup_competicio_id]},
        )

        response = self.client.get(
            reverse(
                "judge_portal_assignment",
                kwargs={"token": self.token.id, "assignment_id": assignment.id},
            )
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual([item["subject_id"] for item in response.context["inscripcions"]], [self.inscripcio.id])

    def test_assignment_save_rejects_subject_outside_subject_scope(self):
        self.inscripcio.categoria = "Infantil"
        self.inscripcio.save(update_fields=["categoria"])
        outside = self._create_inscripcio(self.competicio, "Cadet fora", ordre=2)
        outside.categoria = "Cadet"
        outside.save(update_fields=["categoria"])
        assignment = JudgePortalAssignment.objects.create(
            judge_token=self.token,
            comp_aparell=self.comp_aparell,
            label="Infantil",
            ordre=1,
            permissions=[{"field_code": "D", "judge_index": 1}],
            subject_scope={"mode": "filters", "categoria": ["Infantil"]},
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
                    "inputs_patch": {"D": 1.2},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["reason"], "subject_outside_assignment_scope")
        self.assertFalse(ScoreEntry.objects.filter(inscripcio=outside).exists())

    def test_updates_respect_assignment_subject_scope(self):
        self.inscripcio.categoria = "Infantil"
        self.inscripcio.save(update_fields=["categoria"])
        outside = self._create_inscripcio(self.competicio, "Cadet fora", ordre=2)
        outside.categoria = "Cadet"
        outside.save(update_fields=["categoria"])
        assignment = JudgePortalAssignment.objects.create(
            judge_token=self.token,
            comp_aparell=self.comp_aparell,
            label="Infantil",
            ordre=1,
            permissions=[{"field_code": "D", "judge_index": 1}],
            subject_scope={"mode": "filters", "categoria": ["Infantil"]},
        )
        ScoreEntry.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            inscripcio=self.inscripcio,
            exercici=1,
            fase=None,
            inputs={"D": 1.0},
            outputs={},
            total=1,
        )
        ScoreEntry.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            inscripcio=outside,
            exercici=1,
            fase=None,
            inputs={"D": 2.0},
            outputs={},
            total=2,
        )

        response = self.client.get(
            reverse("judge_updates", kwargs={"token": self.token.id}),
            {
                "assignment_id": assignment.id,
                "since": "2000-01-01T00:00:00Z",
                "exercici": "1",
            },
        )

        self.assertEqual(response.status_code, 200, response.content)
        updates = response.json()["updates"]
        self.assertEqual([item["subject_id"] for item in updates], [self.inscripcio.id])

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
        self.assertContains(response, "Crear QR")

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

    def test_judges_qr_home_adds_assignment_from_global_view_using_posted_app(self):
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
            reverse("judges_qr_home", kwargs={"competicio_id": self.competicio.id}),
            data={
                "action": "add_assignment",
                "token_id": str(token.id),
                "assignment_comp_aparell_id": str(self.comp_aparell.id),
                "assignment_label": "Final global",
                "fase_id": str(phase.id),
                "ordre": "1",
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
                "form-0-item_count": "2",
            },
        )

        self.assertEqual(response.status_code, 302)
        assignment = JudgePortalAssignment.objects.get(judge_token=token)
        self.assertEqual(assignment.comp_aparell_id, self.comp_aparell.id)
        self.assertEqual(assignment.fase_id, phase.id)
        self.assertEqual(assignment.label, "Final global")
        self.assertEqual(assignment.permissions[0]["item_count"], 2)

    def test_judges_qr_home_rejects_assignment_phase_from_other_app(self):
        other_aparell = self._create_aparell("DMT_QR", "Doble mini QR")
        other_comp_aparell = self._create_comp_aparell(self.competicio, other_aparell, ordre=2)
        other_phase = CompeticioAparellFase.objects.create(
            competicio=self.competicio,
            comp_aparell=other_comp_aparell,
            nom="Final DMT",
            codi="FINAL_DMT",
            ordre=1,
        )
        token = JudgeDeviceToken.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            label="Jutge general",
            permissions=[],
        )

        response = self.client.post(
            reverse("judges_qr_home", kwargs={"competicio_id": self.competicio.id}),
            data={
                "action": "add_assignment",
                "token_id": str(token.id),
                "assignment_comp_aparell_id": str(self.comp_aparell.id),
                "assignment_label": "Fase incorrecta",
                "fase_id": str(other_phase.id),
                "ordre": "1",
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
                "form-0-item_count": "2",
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(JudgePortalAssignment.objects.filter(judge_token=token).exists())

    def test_judges_qr_home_creates_public_live_token_from_unified_screen(self):
        response = self.client.post(
            reverse("judges_qr_home", kwargs={"competicio_id": self.competicio.id}),
            data={
                "action": "create_public_live",
                "label": "Pantalla principal",
                "can_view_media": "1",
            },
        )

        self.assertEqual(response.status_code, 302)
        token = PublicLiveToken.objects.get(competicio=self.competicio, label="Pantalla principal")
        self.assertTrue(token.can_view_media)
        self.assertTrue(token.is_active)

    def test_qr_admin_creates_judge_qr_and_selects_detail(self):
        response = self.client.post(
            reverse("qr_admin_home", kwargs={"competicio_id": self.competicio.id}),
            data={
                "action": "create_judge_qr",
                "label": "Jutge QR admin",
                "can_record_video": "1",
            },
        )

        token = JudgeDeviceToken.objects.get(competicio=self.competicio, label="Jutge QR admin")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("qr_admin_detail", kwargs={"competicio_id": self.competicio.id, "token_id": token.id}))
        self.assertEqual(token.permissions, [])
        self.assertFalse(token.portal_assignments.exists())
        self.assertTrue(token.can_record_video)

    def test_qr_admin_renders_list_and_selected_judge_detail(self):
        token = JudgeDeviceToken.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            label="Jutge detall",
            permissions=[],
        )
        JudgePortalAssignment.objects.create(
            judge_token=token,
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            label="Preliminar E1",
            permissions=[{"field_code": "E", "judge_index": 1}],
        )

        response = self.client.get(
            reverse("qr_admin_detail", kwargs={"competicio_id": self.competicio.id, "token_id": token.id})
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "judge/qr_admin.html")
        self.assertContains(response, "Crear QR")
        self.assertContains(response, "Llistat de QRs")
        self.assertContains(response, "Detall del QR")
        self.assertContains(response, "Preliminar E1")
        self.assertContains(response, 'data-qr-label-edit-toggle')
        self.assertContains(response, 'id="judgeQrLabelForm" class="qr-admin-title-edit-form d-none')
        self.assertContains(response, "Imprimir QRs")
        self.assertNotContains(response, "Imprimir jutges")
        self.assertNotContains(response, "Imprimir publics")

    def test_qr_print_page_includes_judge_and_public_qrs(self):
        judge_token = JudgeDeviceToken.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            label="Jutge imprimible",
            permissions=[{"field_code": "E", "judge_index": 1}],
        )
        public_token = PublicLiveToken.objects.create(
            competicio=self.competicio,
            label="Public imprimible",
            can_view_media=True,
        )

        response = self.client.get(reverse("judges_qr_print", kwargs={"competicio_id": self.competicio.id}))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "judge/print_tokens.html")
        self.assertContains(response, "Jutges")
        self.assertContains(response, "Publics")
        self.assertContains(response, "Jutge imprimible")
        self.assertContains(response, "Public imprimible")
        self.assertContains(response, reverse("judge_qr_png", kwargs={"token": judge_token.id}))
        self.assertContains(response, reverse("public_live_qr_png", kwargs={"token": public_token.id}))

    def test_qr_admin_updates_generated_qr_titles(self):
        judge_token = JudgeDeviceToken.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            label="Jutge antic",
            permissions=[],
        )
        public_token = PublicLiveToken.objects.create(
            competicio=self.competicio,
            label="Public antic",
        )

        judge_response = self.client.post(
            reverse("qr_admin_detail", kwargs={"competicio_id": self.competicio.id, "token_id": judge_token.id}),
            data={
                "action": "update_judge_qr_label",
                "token_id": str(judge_token.id),
                "label": "Jutge nou",
            },
        )
        public_response = self.client.post(
            f"{reverse('qr_admin_home', kwargs={'competicio_id': self.competicio.id})}?public_token={public_token.id}",
            data={
                "action": "update_public_qr_label",
                "token_id": str(public_token.id),
                "label": "Public nou",
            },
        )
        judge_token.refresh_from_db()
        public_token.refresh_from_db()

        self.assertEqual(judge_response.status_code, 302)
        self.assertEqual(judge_response.url, reverse("qr_admin_detail", kwargs={"competicio_id": self.competicio.id, "token_id": judge_token.id}))
        self.assertEqual(judge_token.label, "Jutge nou")
        self.assertEqual(public_response.status_code, 302)
        self.assertEqual(public_response.url, f"{reverse('qr_admin_home', kwargs={'competicio_id': self.competicio.id})}?public_token={public_token.id}")
        self.assertEqual(public_token.label, "Public nou")

    def test_qr_admin_adds_assignment_to_selected_judge_qr(self):
        token = JudgeDeviceToken.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            label="Jutge QR admin",
            permissions=[],
        )
        inscripcio = self._create_inscripcio(self.competicio, "Infantil admin")
        inscripcio.categoria = "Infantil"
        inscripcio.save(update_fields=["categoria"])
        phase = CompeticioAparellFase.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            nom="Final",
            codi="FINAL",
            ordre=1,
        )

        response = self.client.post(
            reverse("qr_admin_detail", kwargs={"competicio_id": self.competicio.id, "token_id": token.id}),
            data={
                "action": "add_assignment",
                "token_id": str(token.id),
                "assignment_comp_aparell_id": str(self.comp_aparell.id),
                "assignment_label": "Final QR admin",
                "fase_id": str(phase.id),
                "ordre": "1",
                "subject_scope_mode": "filters",
                "subject_scope_categoria": ["Infantil"],
                "subject_scope_group_ids": [str(inscripcio.grup_competicio_id)],
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
                "form-0-item_count": "4",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("qr_admin_detail", kwargs={"competicio_id": self.competicio.id, "token_id": token.id}))
        assignment = JudgePortalAssignment.objects.get(judge_token=token)
        self.assertEqual(assignment.comp_aparell_id, self.comp_aparell.id)
        self.assertEqual(assignment.fase_id, phase.id)
        self.assertEqual(assignment.permissions[0]["item_count"], 4)
        self.assertEqual(assignment.subject_scope["categoria"], ["Infantil"])
        self.assertEqual(assignment.subject_scope["group_ids"], [inscripcio.grup_competicio_id])

    def test_qr_admin_revokes_whole_qr_and_deactivates_single_assignment(self):
        token = JudgeDeviceToken.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            label="Jutge QR admin",
            permissions=[],
        )
        assignment = JudgePortalAssignment.objects.create(
            judge_token=token,
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            label="Preliminar",
            permissions=[{"field_code": "E", "judge_index": 1}],
        )

        deactivate = self.client.post(
            reverse("qr_admin_detail", kwargs={"competicio_id": self.competicio.id, "token_id": token.id}),
            data={
                "action": "deactivate_assignment",
                "assignment_id": str(assignment.id),
            },
        )
        assignment.refresh_from_db()

        self.assertEqual(deactivate.status_code, 302)
        self.assertFalse(assignment.is_active)

        revoke = self.client.post(
            reverse("qr_admin_detail", kwargs={"competicio_id": self.competicio.id, "token_id": token.id}),
            data={
                "action": "revoke_judge_qr",
                "token_id": str(token.id),
            },
        )
        token.refresh_from_db()

        self.assertEqual(revoke.status_code, 302)
        self.assertFalse(token.is_active)
        self.assertIsNotNone(token.revoked_at)

    def test_qr_admin_deletes_revoked_qr_and_inactive_assignment_only(self):
        token = JudgeDeviceToken.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            label="Jutge eliminable",
            permissions=[],
        )
        assignment = JudgePortalAssignment.objects.create(
            judge_token=token,
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            label="Acces eliminable",
            permissions=[{"field_code": "E", "judge_index": 1}],
            is_active=False,
        )

        delete_active = self.client.post(
            reverse("qr_admin_detail", kwargs={"competicio_id": self.competicio.id, "token_id": token.id}),
            data={
                "action": "delete_judge_qr",
                "token_id": str(token.id),
            },
        )
        token.refresh_from_db()

        self.assertEqual(delete_active.status_code, 302)
        self.assertTrue(token.is_active)

        delete_assignment = self.client.post(
            reverse("qr_admin_detail", kwargs={"competicio_id": self.competicio.id, "token_id": token.id}),
            data={
                "action": "delete_assignment",
                "assignment_id": str(assignment.id),
            },
        )

        self.assertEqual(delete_assignment.status_code, 302)
        self.assertFalse(JudgePortalAssignment.objects.filter(pk=assignment.id).exists())

        token.revoked_at = timezone.now()
        token.is_active = False
        token.save(update_fields=["revoked_at", "is_active"])

        delete_token = self.client.post(
            reverse("qr_admin_detail", kwargs={"competicio_id": self.competicio.id, "token_id": token.id}),
            data={
                "action": "delete_judge_qr",
                "token_id": str(token.id),
            },
        )

        self.assertEqual(delete_token.status_code, 302)
        self.assertEqual(delete_token.url, reverse("qr_admin_home", kwargs={"competicio_id": self.competicio.id}))
        self.assertFalse(JudgeDeviceToken.objects.filter(pk=token.id).exists())

    def test_qr_admin_deletes_revoked_public_qr(self):
        token = PublicLiveToken.objects.create(
            competicio=self.competicio,
            label="Public eliminable",
            is_active=False,
            revoked_at=timezone.now(),
        )

        response = self.client.post(
            f"{reverse('qr_admin_home', kwargs={'competicio_id': self.competicio.id})}?public_token={token.id}",
            data={
                "action": "delete_public_qr",
                "token_id": str(token.id),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("qr_admin_home", kwargs={"competicio_id": self.competicio.id}))
        self.assertFalse(PublicLiveToken.objects.filter(pk=token.id).exists())
