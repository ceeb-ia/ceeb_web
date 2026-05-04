from __future__ import annotations

from datetime import date

from django.test import TestCase
from django.test import RequestFactory

from designacions.models import Assignment, Availability, DesignationRun, Match, Referee
from designacions.services.run_analytics import build_run_analytics
from designacions.views import export_analytics_pdf_view


class RunAnalyticsTests(TestCase):
    def test_phase_rows_include_considered_matches_and_cumulative_coverage(self):
        run = DesignationRun.objects.create(
            name="analytics phases",
            task_id="analytics-phases",
            result_summary={
                "phase_solver_summary": [
                    {
                        "phase_summaries": [
                            {
                                "phase_name": "high",
                                "pending_fragment_count_before": 3,
                                "pending_match_count_before": 5,
                                "selected_match_count": 2,
                                "selected_route_count": 1,
                                "route_candidate_count": 7,
                                "viable_route_candidate_count": 4,
                            }
                        ]
                    }
                ]
            },
        )
        referee = Referee.objects.create(code="T1", name="Tutor 1")
        for index in range(5):
            match = Match.objects.create(
                run=run,
                code=f"M{index + 1}",
                date=date(2026, 5, 2),
                hour_raw="17:00",
            )
            Assignment.objects.create(run=run, match=match, referee=referee)

        analytics = build_run_analytics(run)

        row = analytics["origin_rows"][0]
        self.assertEqual(row["considered_matches"], 5)
        self.assertEqual(row["matches"], 2)
        self.assertEqual(row["phase_coverage_pct"], 40.0)
        self.assertEqual(row["cumulative_matches"], 2)
        self.assertEqual(row["cumulative_pct"], 40.0)
        self.assertEqual(analytics["charts"]["phase_progress"]["considered"], [5])

    def test_hour_pressure_separates_exact_occupancy_from_nearby_gap_blocks(self):
        run = DesignationRun.objects.create(
            name="analytics gaps",
            task_id="analytics-gaps",
            params={"availability_end_buffer_min": 0, "gap_same_pitch_min": 60},
        )
        referees = [
            Referee.objects.create(code=f"T{index}", name=f"Tutor {index}")
            for index in range(1, 4)
        ]
        for referee in referees:
            Availability.objects.create(
                run=run,
                referee=referee,
                raw={"Data": "2026-05-02", "Hora Inici": "17:00", "Hora Fi": "20:00"},
            )

        match_1700 = Match.objects.create(run=run, code="M1700", date=date(2026, 5, 2), hour_raw="17:00")
        Assignment.objects.create(run=run, match=match_1700, referee=referees[0])
        for index, referee in enumerate(referees[1:], start=1):
            match = Match.objects.create(
                run=run,
                code=f"M1730-{index}",
                date=date(2026, 5, 2),
                hour_raw="17:30",
            )
            Assignment.objects.create(run=run, match=match, referee=referee)

        analytics = build_run_analytics(run)
        row_1730 = next(row for row in analytics["demand_by_hour"] if row["label"] == "17:30")

        self.assertEqual(row_1730["total"], 2)
        self.assertEqual(row_1730["schedule_available_tutors"], 3)
        self.assertEqual(row_1730["occupied_tutors"], 2)
        self.assertEqual(row_1730["gap_blocked_tutors"], 3)
        self.assertEqual(row_1730["gap_blocked_other_tutors"], 1)
        self.assertEqual(row_1730["free_effective_tutors"], 0)

    def test_hour_pressure_marks_free_tutors_missing_level(self):
        run = DesignationRun.objects.create(
            name="analytics missing level",
            task_id="analytics-missing-level",
            params={"availability_end_buffer_min": 0, "gap_same_pitch_min": 60},
        )
        with_level = Referee.objects.create(code="TL", name="Tutor Level", level="NIVELLA1")
        missing_level = Referee.objects.create(code="TM", name="Tutor Missing")
        for referee, level in ((with_level, "NIVELLA1"), (missing_level, None)):
            Availability.objects.create(
                run=run,
                referee=referee,
                raw={
                    "Data": "2026-05-02",
                    "Hora Inici": "17:00",
                    "Hora Fi": "20:00",
                    "Nivell": level,
                },
            )
        match = Match.objects.create(run=run, code="M1", date=date(2026, 5, 2), hour_raw="18:00")
        Assignment.objects.create(run=run, match=match)

        analytics = build_run_analytics(run)
        row = next(row for row in analytics["demand_by_hour"] if row["label"] == "18:00")

        self.assertEqual(row["free_effective_tutors"], 2)
        self.assertEqual(row["free_effective_tutors_with_level"], 1)
        self.assertEqual(row["free_effective_tutors_missing_level"], 1)
        point = analytics["unassigned_analysis"]["viability_points"][0]
        self.assertEqual(point["viable_count"], 1)
        self.assertEqual(point["manual_only_missing_level_count"], 1)

    def test_export_analytics_pdf_returns_pdf_response(self):
        run = DesignationRun.objects.create(
            name="analytics pdf",
            task_id="analytics-pdf",
            status="done",
        )
        referee = Referee.objects.create(code="TPDF", name="Tutor PDF", level="NIVELLA1")
        Availability.objects.create(
            run=run,
            referee=referee,
            raw={"Data": "2026-05-02", "Hora Inici": "17:00", "Hora Fi": "20:00", "Nivell": "NIVELLA1"},
        )
        match = Match.objects.create(run=run, code="MPDF", date=date(2026, 5, 2), hour_raw="18:00")
        Assignment.objects.create(run=run, match=match, referee=referee)

        request = RequestFactory().get(f"/designacions/run/{run.id}/analytics/export.pdf")
        response = export_analytics_pdf_view(request, run.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(f"analitica_run_{run.id}.pdf", response["Content-Disposition"])
        self.assertTrue(bytes(response.content).startswith(b"%PDF"))
