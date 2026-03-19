import os
import tempfile
from datetime import date, time
from unittest.mock import patch

import pandas as pd
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from openpyxl import load_workbook

from .models import Assignment, Availability, DesignationRun, Match, Referee
from .main_fixed import _availability_penalty_for_subgroup, _build_daily_subgroups, _build_tutor_working_id, _safe_position_int
from .consulta_resultats import xml_to_dataframe
from .services.excel_export import export_run_to_excel
from .services.manual_assignment import build_top_proposals_for_assignments, diagnose_assignment_for_referee


class DesignacionsDateAwareHelpersTests(SimpleTestCase):
    def test_tutor_working_id_includes_date(self):
        row_day_1 = {
            "Codi Tutor de Joc": "5002 F5",
            "Modalitat": "Futbol Sala",
            "Nivell": "NIVELLA1",
            "Data": "2026-02-24",
        }
        row_day_2 = dict(row_day_1, Data="2026-02-25")

        self.assertNotEqual(_build_tutor_working_id(row_day_1), _build_tutor_working_id(row_day_2))

    def test_daily_subgroups_do_not_mix_same_hour_from_different_days(self):
        df = pd.DataFrame(
            [
                {
                    "ID": "P1",
                    "Data": "2026-02-24",
                    "Hora": time(18, 0),
                    "Pista joc": "Pista 1",
                    "cluster": 7,
                },
                {
                    "ID": "P2",
                    "Data": "2026-02-25",
                    "Hora": time(18, 0),
                    "Pista joc": "Pista 1",
                    "cluster": 7,
                },
            ]
        )

        subgrups = _build_daily_subgroups(df, gap_same_pitch_min=60, gap_diff_pitch_min=75, max_partits_subgrup=3)

        self.assertEqual(len(subgrups), 2)
        self.assertEqual({subgrup[0]["ID"] for subgrup in subgrups}, {"P1", "P2"})

    def test_availability_penalty_blocks_other_day_reuse(self):
        tutor_row = {
            "Data": "2026-02-24",
            "Hora Inici": time(17, 0),
            "Hora Fi": time(21, 0),
        }
        subgrup = [
            {
                "Data": "2026-02-25",
                "__match_datetime": pd.Timestamp("2026-02-25 18:00:00"),
            }
        ]

        penalty = _availability_penalty_for_subgroup(tutor_row, subgrup, availability_end_buffer_min=60)

        self.assertGreaterEqual(penalty, 1e6)

    def test_availability_penalty_respects_same_day_window(self):
        tutor_row = {
            "Data": "2026-02-24",
            "Hora Inici": time(17, 0),
            "Hora Fi": time(21, 0),
        }
        subgrup = [
            {
                "Data": "2026-02-24",
                "__match_datetime": pd.Timestamp("2026-02-24 18:00:00"),
            },
            {
                "Data": "2026-02-24",
                "__match_datetime": pd.Timestamp("2026-02-24 19:00:00"),
            },
        ]

        penalty = _availability_penalty_for_subgroup(tutor_row, subgrup, availability_end_buffer_min=60)

        self.assertEqual(penalty, 0.0)

    def test_xml_to_dataframe_returns_empty_dataframe_when_group_is_missing(self):
        parsed = {
            "grups": [
                {
                    "info": {"nomGrup": "GRUP 01"},
                    "equips_all": [{"NomEquipMostrar": "Equip A"}],
                }
            ]
        }

        df = xml_to_dataframe(parsed, grup="GRUP INEXISTENT")

        self.assertTrue(df.empty)

    def test_safe_position_int_returns_default_for_nan(self):
        self.assertEqual(_safe_position_int(float("nan")), -1)
        self.assertEqual(_safe_position_int(pd.NA), -1)
        self.assertEqual(_safe_position_int(None), -1)


class DesignacionsExcelExportTests(TestCase):
    def setUp(self):
        self.run = DesignationRun.objects.create(task_id="task-export-tests")

        self.ref_blank_level = Referee.objects.create(
            code="5001 F5",
            name="Tutor Sense Nivell",
            level="",
            modality="Futbol Sala",
            transport="Metro",
            active=True,
        )
        self.ref_grouped = Referee.objects.create(
            code="5002 F5",
            name="Tutor Agrupat",
            level="NIVELLA1",
            modality="Futbol Sala",
            transport="Cotxe",
            active=True,
        )
        self.ref_unassigned = Referee.objects.create(
            code="5003 F5",
            name="Tutor Sense Partits",
            level="NIVELLB1",
            modality="Futbol Sala",
            transport="Bus",
            active=True,
        )

        Availability.objects.create(
            run=self.run,
            referee=self.ref_grouped,
            raw={"Data": "2026-02-24", "Hora Inici": "17:00:00", "Hora Fi": "21:00:00"},
        )
        Availability.objects.create(
            run=self.run,
            referee=self.ref_grouped,
            raw={"Data": "2026-02-25", "Hora Inici": "18:00:00", "Hora Fi": "22:00:00"},
        )
        Availability.objects.create(
            run=self.run,
            referee=self.ref_blank_level,
            raw={"Data": "2026-02-24"},
        )

        match_blank_level = Match.objects.create(
            run=self.run,
            code="M-10",
            equip_local="Equip Local 1",
            equip_visitant="Equip Visitant 1",
            category="JUNIOR",
            date=date(2026, 2, 25),
            hour_raw="18:00:00",
            venue="Pista 1",
            municipality="Barcelona",
        )
        match_grouped_early = Match.objects.create(
            run=self.run,
            code="M-25",
            equip_local="Equip Local 2",
            equip_visitant="Equip Visitant 2",
            category="CADET",
            date=date(2026, 2, 24),
            hour_raw="18:30:00",
            venue="Pista 2",
            municipality="Barcelona",
        )
        match_grouped_late = Match.objects.create(
            run=self.run,
            code="M-30",
            equip_local="Equip Local 3",
            equip_visitant="Equip Visitant 3",
            category="INFANTIL",
            date=date(2026, 2, 25),
            hour_raw="19:00:00",
            venue="Pista 3",
            municipality="Barcelona",
        )
        match_unassigned = Match.objects.create(
            run=self.run,
            code="M-99",
            equip_local="Equip Local 4",
            equip_visitant="Equip Visitant 4",
            category="ALEVI",
            date=date(2026, 2, 26),
            hour_raw="20:15:00",
            venue="Pista 4",
            municipality="Badalona",
        )

        Assignment.objects.create(
            run=self.run,
            match=match_blank_level,
            referee=self.ref_blank_level,
            note="Revisar nivell",
            locked=True,
        )
        Assignment.objects.create(
            run=self.run,
            match=match_grouped_early,
            referee=self.ref_grouped,
            note="Primer partit",
            locked=False,
        )
        Assignment.objects.create(
            run=self.run,
            match=match_grouped_late,
            referee=self.ref_grouped,
            note="Segon partit",
            locked=False,
        )
        Assignment.objects.create(
            run=self.run,
            match=match_unassigned,
            referee=None,
            note="Pendent",
            locked=False,
        )

    def _export_workbook(self):
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            path = tmp.name
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        export_run_to_excel(self.run, path)
        return load_workbook(path)

    def test_export_creates_expected_sheets_and_headers(self):
        wb = self._export_workbook()

        self.assertEqual(
            wb.sheetnames,
            [
                "Assignacions",
                "Partits sense assignar",
                "Tutors sense assignar",
                "Tutors sense nivell",
            ],
        )

        ws = wb["Assignacions"]
        headers = [ws.cell(1, idx).value for idx in range(1, 15)]
        self.assertEqual(
            headers,
            [
                "Tutor Codi",
                "Tutor",
                "Nivell Tutor",
                "Hora Inici Tutor",
                "Hora Fi Tutor",
                "Data Partit",
                "Hora Partit",
                "Codi Partit",
                "Equip local",
                "Equip visitant",
                "Pista",
                "Categoria",
                "Nota",
                "Bloquejat",
            ],
        )
        self.assertEqual(ws.freeze_panes, "A2")
        self.assertEqual(ws.auto_filter.ref, "A1:N4")

    def test_assignacions_sheet_is_sorted_grouped_and_styled(self):
        wb = self._export_workbook()
        ws = wb["Assignacions"]

        exported_rows = [
            (ws["A2"].value, ws["H2"].value),
            (ws["A3"].value, ws["H3"].value),
            (ws["A4"].value, ws["H4"].value),
        ]
        self.assertEqual(
            exported_rows,
            [
                ("5001 F5", "M-10"),
                ("5002 F5", "M-25"),
                ("5002 F5", "M-30"),
            ],
        )

        self.assertEqual(ws["F2"].number_format, "dd/mm/yyyy")
        self.assertEqual(ws["G2"].number_format, "hh:mm")
        self.assertEqual(ws["D2"].value, "-")
        self.assertEqual(ws["D3"].number_format, "hh:mm")
        self.assertEqual(ws["D3"].value, time(17, 0))
        self.assertEqual(ws["D4"].value, time(18, 0))
        self.assertEqual(ws["E3"].value, time(21, 0))
        self.assertEqual(ws["E4"].value, time(22, 0))
        self.assertEqual(ws["N2"].value, "Si")
        self.assertNotEqual(ws["A2"].fill.fgColor.rgb, ws["B2"].fill.fgColor.rgb)
        self.assertGreater(ws.column_dimensions["B"].width, 20)

    def test_secondary_sheets_include_unassigned_and_needs_review_data(self):
        wb = self._export_workbook()

        ws_unassigned_matches = wb["Partits sense assignar"]
        self.assertEqual(ws_unassigned_matches.max_row, 2)
        self.assertEqual(ws_unassigned_matches["A2"].value, "M-99")
        self.assertEqual(ws_unassigned_matches["I2"].value, "Pendent")

        ws_unassigned_refs = wb["Tutors sense assignar"]
        self.assertEqual(ws_unassigned_refs.max_row, 2)
        self.assertEqual(ws_unassigned_refs["A2"].value, "5003 F5")
        self.assertEqual(ws_unassigned_refs["B2"].value, "Tutor Sense Partits")

        ws_needs_review = wb["Tutors sense nivell"]
        self.assertEqual(ws_needs_review.max_row, 2)
        self.assertEqual(ws_needs_review["A2"].value, "5001 F5")
        self.assertEqual(ws_needs_review["D2"].value, 1)

    def test_export_handles_empty_run(self):
        empty_run = DesignationRun.objects.create(task_id="task-export-empty")

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            path = tmp.name
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))

        export_run_to_excel(empty_run, path)
        wb = load_workbook(path)

        self.assertEqual(wb["Assignacions"].max_row, 1)
        self.assertEqual(wb["Assignacions"].auto_filter.ref, "A1:N1")
        self.assertEqual(wb["Partits sense assignar"].max_row, 1)


class DesignacionsManualAssignmentsTests(TestCase):
    def setUp(self):
        self.run = DesignationRun.objects.create(
            task_id="task-manual-assignments",
            params={
                "gap_same_pitch_min": 60,
                "gap_diff_pitch_min": 75,
                "availability_end_buffer_min": 60,
            },
        )

        self.ref_best = self._create_referee("5001 F5", "Tutor Millor", "NIVELLA1")
        self.ref_conflict_same = self._create_referee("5002 F5", "Tutor Mateixa Pista", "NIVELLA1")
        self.ref_modality = self._create_referee("5003 F5", "Tutor Modalitat", "NIVELLA1", modality="Basquet")
        self.ref_conflict_diff = self._create_referee("5004 F5", "Tutor Altra Pista", "NIVELLA1")
        self.ref_display = self._create_referee("5005 F5", "Tutor Amb Dues Disponibilitats", "NIVELLB1")
        self.ref_second = self._create_referee("5006 F5", "Tutor Segon", "NIVELLB1")
        self.ref_third = self._create_referee("5007 F5", "Tutor Tercer", "NIVELLC1")
        self.ref_fourth = self._create_referee("5008 F5", "Tutor Quart", "D")

        self._add_availability(self.ref_best, "2026-03-01", "17:00:00", "22:00:00")
        self._add_availability(self.ref_conflict_same, "2026-03-01", "17:00:00", "22:00:00")
        self._add_availability(self.ref_modality, "2026-03-01", "17:00:00", "22:00:00")
        self._add_availability(self.ref_conflict_diff, "2026-03-01", "17:00:00", "22:00:00")
        self._add_availability(self.ref_display, "2026-03-01", "16:00:00", "21:00:00")
        self._add_availability(self.ref_display, "2026-03-02", "18:00:00", "23:00:00")
        self._add_availability(self.ref_second, "2026-03-01", "17:00:00", "22:00:00")
        self._add_availability(self.ref_third, "2026-03-01", "17:00:00", "22:00:00")
        self._add_availability(self.ref_fourth, "2026-03-01", "17:00:00", "22:00:00")

        self.target_match = self._create_match("M-100", date(2026, 3, 1), "18:00:00", "Pista A", category="SÈNIOR")
        self.target_assignment = Assignment.objects.create(run=self.run, match=self.target_match, referee=None, note="Pendent")

        self.same_pitch_match = self._create_match("M-200", date(2026, 3, 1), "17:15:00", "Pista A", category="SÈNIOR")
        Assignment.objects.create(run=self.run, match=self.same_pitch_match, referee=self.ref_conflict_same)

        self.diff_pitch_match = self._create_match("M-210", date(2026, 3, 1), "17:00:00", "Pista B", category="SÈNIOR")
        Assignment.objects.create(run=self.run, match=self.diff_pitch_match, referee=self.ref_conflict_diff)

        self.display_match = self._create_match("M-300", date(2026, 3, 2), "19:00:00", "Pista C", category="INFANTIL")
        self.display_assignment = Assignment.objects.create(run=self.run, match=self.display_match, referee=self.ref_display)

    def _create_referee(self, code, name, level, modality="Futbol Sala"):
        return Referee.objects.create(
            code=code,
            name=name,
            level=level,
            modality=modality,
            transport="Cotxe",
            active=True,
        )

    def _add_availability(self, referee, availability_date, start, end):
        Availability.objects.create(
            run=self.run,
            referee=referee,
            raw={"Data": availability_date, "Hora Inici": start, "Hora Fi": end},
        )

    def _create_match(self, code, match_date, hour_raw, venue, category="CADET", modality="Futbol Sala"):
        return Match.objects.create(
            run=self.run,
            code=code,
            equip_local=f"{code} Local",
            equip_visitant=f"{code} Visitant",
            category=category,
            modality=modality,
            date=match_date,
            hour_raw=hour_raw,
            venue=venue,
            municipality="Barcelona",
        )

    def test_diagnosis_marks_valid_candidate_with_cost(self):
        diagnosis = diagnose_assignment_for_referee(self.run, self.target_assignment, self.ref_best)

        self.assertTrue(diagnosis["is_valid"])
        self.assertIsNotNone(diagnosis["cost"])
        self.assertEqual(diagnosis["warning_reasons"], [])

    def test_diagnosis_marks_modality_mismatch_as_warning(self):
        diagnosis = diagnose_assignment_for_referee(self.run, self.target_assignment, self.ref_modality)

        self.assertFalse(diagnosis["is_valid"])
        self.assertIn("modality_mismatch", diagnosis["warning_reasons"])

    def test_diagnosis_detects_same_pitch_conflict(self):
        diagnosis = diagnose_assignment_for_referee(self.run, self.target_assignment, self.ref_conflict_same)

        self.assertFalse(diagnosis["is_valid"])
        self.assertIn("time_conflict_same_pitch", diagnosis["warning_reasons"])

    def test_diagnosis_detects_diff_pitch_conflict(self):
        diagnosis = diagnose_assignment_for_referee(self.run, self.target_assignment, self.ref_conflict_diff)

        self.assertFalse(diagnosis["is_valid"])
        self.assertIn("time_conflict_diff_pitch", diagnosis["warning_reasons"])

    def test_top_proposals_only_use_unassigned_tutors_and_limit_to_three(self):
        proposals = build_top_proposals_for_assignments(self.run, [self.target_assignment])

        proposal_codes = [item["referee"].code for item in proposals[self.target_assignment.id]]
        self.assertEqual(proposal_codes, ["5001 F5", "5006 F5", "5007 F5"])
        self.assertNotIn("5002 F5", proposal_codes)
        self.assertNotIn("5004 F5", proposal_codes)
        self.assertEqual(len(proposal_codes), 3)

    def test_assignments_view_exposes_top_proposals_and_date_specific_availability(self):
        response = self.client.get(reverse("designacions_assignments", args=[self.run.id]))

        self.assertEqual(response.status_code, 200)
        proposals = response.context["eligible_proposals_by_assignment"][self.target_assignment.id]
        self.assertEqual([item["referee"].code for item in proposals], ["5001 F5", "5006 F5", "5007 F5"])
        self.assertEqual(
            response.context["availability_by_assignment"][self.display_assignment.id]["Hora Inici"],
            "18:00:00",
        )
        content = response.content.decode("utf-8")
        self.assertIn("Millors Propostes", content)
        self.assertIn("5001 F5", content)
        self.assertIn("5008 F5", content)

    @patch("designacions.views.rebuild_run_map")
    def test_invalid_manual_assignment_is_saved_with_warning(self, rebuild_map_mock):
        response = self.client.post(
            reverse("designacions_update_assignment", args=[self.run.id, self.target_assignment.id]),
            {"referee_id": str(self.ref_modality.id), "note": "Override"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.target_assignment.refresh_from_db()
        self.assertEqual(self.target_assignment.referee_id, self.ref_modality.id)
        self.assertTrue(self.target_assignment.manual_override_warning)
        self.assertIn("Modalitat", self.target_assignment.manual_override_reason)
        rebuild_map_mock.assert_called_once_with(self.run)

    @patch("designacions.views.rebuild_run_map")
    def test_valid_manual_assignment_clears_previous_warning(self, rebuild_map_mock):
        self.target_assignment.referee = self.ref_modality
        self.target_assignment.manual_override_warning = True
        self.target_assignment.manual_override_reason = "Modalitat diferent de la del partit."
        self.target_assignment.save(update_fields=["referee", "manual_override_warning", "manual_override_reason", "updated_at"])

        response = self.client.post(
            reverse("designacions_update_assignment", args=[self.run.id, self.target_assignment.id]),
            {"referee_id": str(self.ref_best.id), "note": "Corregit"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.target_assignment.refresh_from_db()
        self.assertEqual(self.target_assignment.referee_id, self.ref_best.id)
        self.assertFalse(self.target_assignment.manual_override_warning)
        self.assertEqual(self.target_assignment.manual_override_reason, "")
        rebuild_map_mock.assert_called_once_with(self.run)
