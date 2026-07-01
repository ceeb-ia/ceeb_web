import json
from importlib import import_module

from django.test import TestCase
from django.urls import reverse

from ...base import _BaseTrampoliDataMixin
from ....models.judging import JudgeDeviceToken, JudgePortalAssignment, JudgeScoreSubmission
from ....models.scoring import ScoreEntry, ScoringSchema
from ....services.judging.supervision import validate_single_supervisor_per_field
from ....views.judge.admin import _validate_permission_row
from ....views.judge.permissions import _normalize_permissions


class JudgePermissionRoleContractTests(TestCase):
    def setUp(self):
        self.schema_by_code = {
            "E": {
                "label": "Execucio",
                "code": "E",
                "type": "matrix",
                "shape": "judge_x_item",
                "judges": {"count": 2},
                "items": {"count": 5},
                "decimals": 1,
            },
        }

    def test_permission_row_defaults_to_standard_role(self):
        permission = _validate_permission_row(
            self.schema_by_code,
            {
                "field_code": "E",
                "judge_index": 1,
                "item_start": 1,
                "item_count": "",
            },
        )

        self.assertEqual(permission["role"], "standard")

    def test_permission_row_accepts_supervisor_role(self):
        permission = _validate_permission_row(
            self.schema_by_code,
            {
                "field_code": "E",
                "judge_index": 1,
                "item_start": 1,
                "item_count": "",
                "role": "supervisor",
            },
        )

        self.assertEqual(permission["role"], "supervisor")

    def test_runtime_permission_normalization_preserves_role(self):
        permissions = _normalize_permissions(
            [
                {"field_code": "E", "judge_index": 1},
                {"field_code": "E", "judge_index": 2, "role": "supervisor"},
            ]
        )

        self.assertEqual(permissions[0]["role"], "standard")
        self.assertEqual(permissions[1]["role"], "supervisor")


class JudgeSupervisionFlowTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.client.raise_request_exception = False
        self.competicio = self._create_competicio("Comp supervisio jutges")
        self.aparell = self._create_aparell("TRA_SUP", "Trampoli supervisio")
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
        self.inscripcio = self._create_inscripcio(self.competicio, "Gimnasta supervisat")
        self.standard_token = JudgeDeviceToken.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            label="Jutge standard",
            permissions=[],
        )
        self.standard_assignment = JudgePortalAssignment.objects.create(
            judge_token=self.standard_token,
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            label="Standard E1",
            ordre=1,
            permissions=[
                {
                    "field_code": "E",
                    "judge_index": 1,
                    "item_start": 1,
                    "item_count": None,
                    "role": "standard",
                }
            ],
        )
        self.supervisor_token = JudgeDeviceToken.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            label="Supervisor E1",
            permissions=[],
        )
        self.supervisor_assignment = JudgePortalAssignment.objects.create(
            judge_token=self.supervisor_token,
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            label="Supervisor E1",
            ordre=1,
            permissions=[
                {
                    "field_code": "E",
                    "judge_index": 1,
                    "item_start": 1,
                    "item_count": None,
                    "role": "supervisor",
                }
            ],
        )

    def _standard_submission_payload(self, values=None):
        values = values or [0.1, 0.2, 0.3, 0.4, 0.5]
        return {
            "assignment_id": self.standard_assignment.id,
            "inscripcio_id": self.inscripcio.id,
            "subject_kind": "inscripcio",
            "subject_id": self.inscripcio.id,
            "exercici": 1,
            "inputs_patch": {"E": values},
        }

    def test_standard_judge_with_supervisor_creates_pending_submission_not_score_entry(self):
        response = self.client.post(
            reverse("judge_save_partial", kwargs={"token": self.standard_token.id}),
            data=json.dumps(self._standard_submission_payload()),
            content_type="application/json",
        )

        self.assertNotEqual(
            response.status_code,
            500,
            "judge_save_partial returned 500; a supervised standard submission should create a pending "
            "JudgeScoreSubmission instead of crashing.",
        )
        self.assertIn(response.status_code, {200, 202}, response.content)
        data = response.json()
        self.assertEqual(data.get("publication_status"), "pending")
        self.assertTrue(data.get("requires_supervision"))
        self.assertTrue(data.get("pending_submission_ids"))
        self.assertFalse(
            ScoreEntry.objects.filter(
                competicio=self.competicio,
                comp_aparell=self.comp_aparell,
                inscripcio=self.inscripcio,
                exercici=1,
                fase__isnull=True,
            ).exists(),
            "A standard judge submission covered by a supervisor must stay pending and not publish ScoreEntry.",
        )
        submissions = JudgeScoreSubmission.objects.filter(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            submitted_by_token=self.standard_token,
            submitted_by_assignment=self.standard_assignment,
            subject_kind="inscripcio",
            subject_id=self.inscripcio.id,
            exercici=1,
            field_code="E",
            judge_index=1,
            status=JudgeScoreSubmission.Status.PENDING,
        )
        self.assertEqual(
            submissions.count(),
            1,
            "A standard judge submission covered by a supervisor must create exactly one pending JudgeScoreSubmission.",
        )
        submission = submissions.get()
        self.assertEqual(submission.inputs_patch, {"E": [0.1, 0.2, 0.3, 0.4, 0.5]})
        self.assertEqual(submission.normalized_inputs_patch.get("E"), [0.1, 0.2, 0.3, 0.4, 0.5])

    def test_supervisor_approval_publishes_pending_submission_to_score_entry(self):
        submission = JudgeScoreSubmission.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            fase=None,
            submitted_by_token=self.standard_token,
            submitted_by_assignment=self.standard_assignment,
            subject_kind="inscripcio",
            subject_id=self.inscripcio.id,
            exercici=1,
            field_code="E",
            runtime_field_code="E",
            judge_index=1,
            item_start=1,
            item_count=None,
            inputs_patch={"E": [0.6, 0.7, 0.8, 0.9, 1.0]},
            normalized_inputs_patch={"E": [0.6, 0.7, 0.8, 0.9, 1.0]},
            status=JudgeScoreSubmission.Status.PENDING,
        )

        approve = self._approval_service()
        try:
            approve(
                submission=submission,
                supervisor_token=self.supervisor_token,
                supervisor_assignment=self.supervisor_assignment,
            )
        except Exception as exc:  # pragma: no cover - failure output documents pending integration.
            self.fail(f"Approval service raised {type(exc).__name__}: {exc}")

        submission.refresh_from_db()
        self.assertEqual(submission.status, JudgeScoreSubmission.Status.APPROVED)
        self.assertEqual(submission.reviewed_by_token_id, self.supervisor_token.id)
        self.assertEqual(submission.reviewed_by_assignment_id, self.supervisor_assignment.id)
        self.assertIsNotNone(submission.reviewed_at)
        entry = ScoreEntry.objects.get(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            inscripcio=self.inscripcio,
            exercici=1,
            fase__isnull=True,
        )
        self.assertEqual(entry.inputs["E"][0], [0.6, 0.7, 0.8, 0.9, 1.0])

    def test_duplicate_supervisor_in_same_permission_set_is_rejected(self):
        with self.assertRaisesMessage(ValueError, "mes d'un supervisor"):
            validate_single_supervisor_per_field(
                competicio=self.competicio,
                comp_aparell=self.comp_aparell,
                phase=None,
                permissions=[
                    {"field_code": "E", "judge_index": 1, "role": "supervisor"},
                    {"field_code": "E", "judge_index": 2, "role": "supervisor"},
                ],
            )

    def test_supervisor_portal_exposes_pending_panel(self):
        response = self.client.get(
            reverse(
                "judge_portal_assignment",
                kwargs={"token": self.supervisor_token.id, "assignment_id": self.supervisor_assignment.id},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="judgeSupervisionPanel"')
        self.assertContains(response, "SUPERVISION_PENDING_URL")

    def test_supervision_approve_requires_submission_id(self):
        response = self.client.post(
            reverse("judge_supervision_approve", kwargs={"token": self.supervisor_token.id}),
            data=json.dumps({"assignment_id": self.supervisor_assignment.id}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])

    def test_supervision_approve_rejects_non_object_patch(self):
        submission = JudgeScoreSubmission.objects.create(
            competicio=self.competicio,
            comp_aparell=self.comp_aparell,
            fase=None,
            submitted_by_token=self.standard_token,
            submitted_by_assignment=self.standard_assignment,
            subject_kind="inscripcio",
            subject_id=self.inscripcio.id,
            exercici=1,
            field_code="E",
            runtime_field_code="E",
            judge_index=1,
            item_start=1,
            item_count=None,
            inputs_patch={"E": [0.6, 0.7, 0.8, 0.9, 1.0]},
            normalized_inputs_patch={"E": [0.6, 0.7, 0.8, 0.9, 1.0]},
            status=JudgeScoreSubmission.Status.PENDING,
        )

        response = self.client.post(
            reverse("judge_supervision_approve", kwargs={"token": self.supervisor_token.id}),
            data=json.dumps({
                "assignment_id": self.supervisor_assignment.id,
                "submission_id": submission.id,
                "inputs_patch": ["invalid"],
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])

    def _approval_service(self):
        try:
            module = import_module("competicions_trampoli.services.judging.submissions")
        except ModuleNotFoundError as exc:
            if exc.name == "competicions_trampoli.services.judging.submissions":
                self.fail(
                    "Pending integration: expected "
                    "competicions_trampoli.services.judging.submissions.approve_judge_score_submission"
                )
            raise
        approve = getattr(module, "approve_judge_score_submission", None)
        if approve is None:
            self.fail(
                "Pending integration: expected approve_judge_score_submission in "
                "competicions_trampoli.services.judging.submissions"
            )
        return approve
