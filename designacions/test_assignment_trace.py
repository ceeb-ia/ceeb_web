from __future__ import annotations

from datetime import date

from django.test import TestCase

from designacions.models import Assignment, AssignmentTrace, DesignationRun, Match, Referee
from designacions.services.assignment_explainer import _assignment_origin_payload
from designacions.views import _mark_assignment_trace_manual


class AssignmentTraceTests(TestCase):
    def setUp(self):
        self.run = DesignationRun.objects.create(name="trace", task_id="trace-task")
        self.match = Match.objects.create(
            run=self.run,
            code="P1",
            engine_id="M1",
            date=date(2026, 5, 2),
            hour_raw="18:00",
            venue="Maristes",
        )
        self.referee = Referee.objects.create(code="T1", name="Tutor 1")
        self.assignment = Assignment.objects.create(run=self.run, match=self.match, referee=self.referee)

    def test_assignment_trace_origin_payload_uses_human_label(self):
        AssignmentTrace.objects.create(
            run=self.run,
            assignment=self.assignment,
            match=self.match,
            referee=self.referee,
            engine_name="phased_route_solver",
            stage="individual_rescue:3",
            phase_name="individual_rescue:3",
            rescue_kind="individual_rescue",
            rescue_iteration=3,
            route_id="R1",
            candidate_id="C1",
            tutor_id="T1",
            route_match_ids=["M1"],
            route_match_codes=["P1"],
            route_size=1,
        )

        payload = _assignment_origin_payload(Assignment.objects.select_related("trace").get(id=self.assignment.id))

        self.assertTrue(payload["available"])
        self.assertEqual(payload["label"], "Recuperacio individual")
        self.assertEqual(payload["stage"], "individual_rescue:3")

    def test_assignment_origin_payload_degrades_without_trace(self):
        payload = _assignment_origin_payload(self.assignment)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["label"], "Origen no disponible")

    def test_deleting_run_cascades_trace(self):
        AssignmentTrace.objects.create(
            run=self.run,
            assignment=self.assignment,
            match=self.match,
            referee=self.referee,
            engine_name="legacy",
            stage="initial",
        )

        self.run.delete()

        self.assertEqual(AssignmentTrace.objects.count(), 0)

    def test_manual_assignment_update_marks_existing_trace(self):
        AssignmentTrace.objects.create(
            run=self.run,
            assignment=self.assignment,
            match=self.match,
            referee=self.referee,
            engine_name="phased_route_solver",
            stage="general",
            route_id="R1",
            route_match_codes=["P1"],
        )

        _mark_assignment_trace_manual(self.run, self.assignment, previous_referee_id=None)

        trace = AssignmentTrace.objects.get(assignment=self.assignment)
        self.assertEqual(trace.stage, "manual_override")
        self.assertEqual(trace.referee_id, self.referee.id)
        self.assertIn("manual_override", trace.warning_codes)
        self.assertEqual(trace.debug_payload["previous_stage"], "general")
