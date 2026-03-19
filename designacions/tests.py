import json
import os
import tempfile
from datetime import date, time
from unittest.mock import patch

import pandas as pd
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from openpyxl import load_workbook

from .models import Assignment, Availability, DesignationRun, Match, Referee
from .main_fixed import (
    _availability_penalty_for_subgroup,
    _build_daily_subgroups,
    _build_tutor_working_id,
    _run_rescue_assignment,
    _safe_position_int,
    _segment_failed_subgroup,
)
from .consulta_resultats import xml_to_dataframe
from .services.excel_export import export_run_to_excel
from .services.manual_assignment import build_top_proposals_for_assignments, diagnose_assignment_for_referee
from .services.run_scope import load_scoped_run_data
from .tasks import rebuild_run_map_task


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

    def test_load_scoped_run_data_filters_by_modalitat_and_dates(self):
        df_disp = pd.DataFrame(
            [
                {
                    "Codi Tutor de Joc": "5001 F5",
                    "Nom": "Tutor F5",
                    "Categoria": "TUTOR/TUTORA DE JOC",
                    "Modalitat": "Futbol Sala",
                    "Nivell": "NIVELLA1",
                    "Data": "2026-02-24",
                },
                {
                    "Codi Tutor de Joc": "5002 BQ",
                    "Nom": "Tutor BQ",
                    "Categoria": "TUTOR/TUTORA DE JOC",
                    "Modalitat": "Basquet",
                    "Nivell": "NIVELLA1",
                    "Data": "2026-02-24",
                },
                {
                    "Codi Tutor de Joc": "5004 F5",
                    "Nom": "Tutor Sense Nivell",
                    "Categoria": "TUTOR/TUTORA DE JOC",
                    "Modalitat": "Futbol Sala",
                    "Nivell": None,
                    "Data": "2026-02-24",
                },
                {
                    "Codi Tutor de Joc": "5003 F5",
                    "Nom": "Tutor Fora Rang",
                    "Categoria": "TUTOR/TUTORA DE JOC",
                    "Modalitat": "Futbol Sala",
                    "Nivell": "NIVELLA1",
                    "Data": "2026-02-25",
                },
            ]
        )
        df_partits = pd.DataFrame(
            [
                {
                    "Codi": "M-F5",
                    "Modalitat": "Futbol Sala",
                    "Data": "2026-02-24",
                    "Grup": "GRUP 01",
                },
                {
                    "Codi": "M-BQ",
                    "Modalitat": "Basquet",
                    "Data": "2026-02-24",
                    "Grup": "GRUP 01",
                },
                {
                    "Codi": "M-F5-LATE",
                    "Modalitat": "Futbol Sala",
                    "Data": "2026-02-25",
                    "Grup": "GRUP 01",
                },
            ]
        )

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as disp_tmp:
            disp_path = disp_tmp.name
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as partits_tmp:
            partits_path = partits_tmp.name
        self.addCleanup(lambda: os.path.exists(disp_path) and os.unlink(disp_path))
        self.addCleanup(lambda: os.path.exists(partits_path) and os.unlink(partits_path))

        df_disp.to_excel(disp_path, index=False)
        df_partits.to_excel(partits_path, index=False)

        scoped_disp, scoped_partits = load_scoped_run_data(
            disp_path,
            partits_path,
            params={
                "modalitats": ["Futbol Sala"],
                "date_from": "2026-02-24",
                "date_to": "2026-02-24",
            },
        )

        self.assertEqual(scoped_partits["Codi"].tolist(), ["M-F5"])
        self.assertEqual(scoped_disp["Codi Tutor de Joc"].tolist(), ["5001 F5", "5004 F5"])

    def test_segment_failed_subgroup_prefers_contiguous_two_plus_one_split(self):
        subgrup = [
            {
                "ID": "M1",
                "Data": "2026-02-24",
                "__match_datetime": pd.Timestamp("2026-02-24 18:00:00"),
            },
            {
                "ID": "M2",
                "Data": "2026-02-24",
                "__match_datetime": pd.Timestamp("2026-02-24 19:00:00"),
            },
            {
                "ID": "M3",
                "Data": "2026-02-24",
                "__match_datetime": pd.Timestamp("2026-02-24 20:00:00"),
            },
        ]
        candidate_referees = pd.DataFrame([{"ID": "R1"}, {"ID": "R2"}])

        def subgroup_cost_fn(referee_row, segment):
            key = (referee_row["ID"], tuple(item["ID"] for item in segment))
            viable = {
                ("R1", ("M1", "M2")): 10,
                ("R2", ("M3",)): 10,
            }
            return viable.get(key, 1e6)

        segments = _segment_failed_subgroup(subgrup, candidate_referees, subgroup_cost_fn)

        self.assertEqual([[item["ID"] for item in segment] for segment in segments], [["M1", "M2"], ["M3"]])

    def test_run_rescue_assignment_splits_pair_into_individuals_and_recovers_one(self):
        failed_subgroups = [[
            {
                "ID": "M1",
                "Data": "2026-02-24",
                "__match_datetime": pd.Timestamp("2026-02-24 18:00:00"),
            },
            {
                "ID": "M2",
                "Data": "2026-02-24",
                "__match_datetime": pd.Timestamp("2026-02-24 19:00:00"),
            },
        ]]
        candidate_referees = pd.DataFrame([{"ID": "R1"}])

        def subgroup_cost_fn(referee_row, segment):
            key = (referee_row["ID"], tuple(item["ID"] for item in segment))
            viable = {
                ("R1", ("M2",)): 10,
            }
            return viable.get(key, 1e6)

        rescue = _run_rescue_assignment(candidate_referees, failed_subgroups, subgroup_cost_fn)

        self.assertEqual([[item["ID"] for item in segment] for segment in rescue["segments"]], [["M1"], ["M2"]])
        self.assertEqual(len(rescue["pairs"]), 1)
        _, segment_idx = rescue["pairs"][0]
        self.assertEqual([item["ID"] for item in rescue["segments"][segment_idx]], ["M2"])

    def test_run_rescue_assignment_without_idle_referees_returns_no_pairs(self):
        failed_subgroups = [[
            {
                "ID": "M1",
                "Data": "2026-02-24",
                "__match_datetime": pd.Timestamp("2026-02-24 18:00:00"),
            }
        ]]
        candidate_referees = pd.DataFrame(columns=["ID"])

        rescue = _run_rescue_assignment(candidate_referees, failed_subgroups, lambda *_args, **_kwargs: 1e6)

        self.assertEqual(len(rescue["segments"]), 1)
        self.assertEqual(len(rescue["pairs"]), 0)

    def test_run_rescue_assignment_keeps_one_segment_per_tutor(self):
        failed_subgroups = [[
            {
                "ID": "M1",
                "Data": "2026-02-24",
                "__match_datetime": pd.Timestamp("2026-02-24 18:00:00"),
            },
            {
                "ID": "M2",
                "Data": "2026-02-24",
                "__match_datetime": pd.Timestamp("2026-02-24 19:00:00"),
            },
        ]]
        candidate_referees = pd.DataFrame([{"ID": "R1"}])

        def subgroup_cost_fn(referee_row, segment):
            key = (referee_row["ID"], tuple(item["ID"] for item in segment))
            viable = {
                ("R1", ("M1",)): 10,
                ("R1", ("M2",)): 15,
            }
            return viable.get(key, 1e6)

        rescue = _run_rescue_assignment(candidate_referees, failed_subgroups, subgroup_cost_fn)

        self.assertEqual(len(rescue["pairs"]), 1)


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
        Availability.objects.create(
            run=self.run,
            referee=self.ref_unassigned,
            raw={"Data": "2026-02-26", "Hora Inici": "19:00:00", "Hora Fi": "22:00:00"},
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

    def test_top_proposals_include_compatible_assigned_tutors_with_soft_penalty(self):
        proposals = build_top_proposals_for_assignments(self.run, [self.target_assignment])

        proposal_codes = [item["referee"].code for item in proposals[self.target_assignment.id]]
        self.assertEqual(proposal_codes, ["5001 F5", "5006 F5", "5005 F5"])
        self.assertNotIn("5002 F5", proposal_codes)
        self.assertNotIn("5004 F5", proposal_codes)
        self.assertNotIn("5003 F5", proposal_codes)
        self.assertEqual(len(proposal_codes), 3)
        self.assertGreater(proposals[self.target_assignment.id][2]["effective_cost"], proposals[self.target_assignment.id][1]["effective_cost"])

    def test_assignments_view_renders_placeholders_for_manual_loading(self):
        response = self.client.get(reverse("designacions_assignments", args=[self.run.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("eligible_proposals_by_assignment", response.context)
        self.assertNotIn("referee_options_by_assignment", response.context)
        self.assertEqual(
            response.context["availability_by_assignment"][self.display_assignment.id]["Hora Inici"],
            "18:00:00",
        )
        content = response.content.decode("utf-8")
        self.assertIn("Millors Propostes", content)
        self.assertIn("Carrega les propostes en obrir el selector.", content)
        self.assertIn("data-manual-options-url", content)
        self.assertIn("data-update-async-url", content)

    def test_manual_assignment_options_view_returns_top_proposals_and_compatible_referees(self):
        response = self.client.get(
            reverse("designacions_manual_assignment_options", args=[self.run.id, self.target_assignment.id])
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            [item["code"] for item in payload["top_proposals"]],
            ["5001 F5", "5006 F5", "5005 F5"],
        )
        self.assertEqual(
            [item["code"] for item in payload["compatible_referees"]],
            ["5001 F5", "5002 F5", "5004 F5", "5005 F5", "5006 F5", "5007 F5", "5008 F5"],
        )

    def test_manual_assignment_options_view_filters_compatible_referees_by_query(self):
        response = self.client.get(
            reverse("designacions_manual_assignment_options", args=[self.run.id, self.target_assignment.id]),
            {"q": "5006"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["code"] for item in payload["compatible_referees"]], ["5006 F5"])

    @patch("designacions.views.rebuild_run_map_task.delay")
    def test_invalid_manual_assignment_for_other_modality_is_rejected(self, rebuild_map_delay_mock):
        response = self.client.post(
            reverse("designacions_update_assignment", args=[self.run.id, self.target_assignment.id]),
            {"referee_id": str(self.ref_modality.id), "note": "Override"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.target_assignment.refresh_from_db()
        self.assertIsNone(self.target_assignment.referee_id)
        self.assertFalse(self.target_assignment.manual_override_warning)
        self.assertEqual(self.target_assignment.manual_override_reason, "")
        rebuild_map_delay_mock.assert_not_called()

    @patch("designacions.views.rebuild_run_map_task.delay")
    def test_valid_manual_assignment_clears_previous_warning(self, rebuild_map_delay_mock):
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
        self.run.refresh_from_db()
        self.assertEqual(self.run.map_status, "queued")
        rebuild_map_delay_mock.assert_called_once_with(self.run.id)

    @patch("designacions.views.rebuild_run_map_task.delay")
    def test_update_assignment_async_returns_json_and_queues_map(self, rebuild_map_delay_mock):
        response = self.client.post(
            reverse("designacions_update_assignment_async", args=[self.run.id, self.target_assignment.id]),
            data=json.dumps({"referee_id": self.ref_best.id, "note": "Async ok", "locked": False}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.target_assignment.refresh_from_db()
        self.run.refresh_from_db()
        self.assertEqual(self.target_assignment.referee_id, self.ref_best.id)
        self.assertEqual(payload["row_state"], "assigned")
        self.assertFalse(payload["warning"]["active"])
        self.assertEqual(payload["counts"]["assigned"], 4)
        self.assertEqual(self.run.map_status, "queued")
        rebuild_map_delay_mock.assert_called_once_with(self.run.id)

    @patch("designacions.views.rebuild_run_map_task.delay")
    def test_update_assignment_async_returns_warning_payload_when_candidate_is_allowed_but_costly(self, rebuild_map_delay_mock):
        warning_ref = self._create_referee("5010 F5", "Tutor Warning", "NIVELLA1")
        self._add_availability(warning_ref, "2026-03-02", "18:00:00", "22:00:00")

        response = self.client.post(
            reverse("designacions_update_assignment_async", args=[self.run.id, self.target_assignment.id]),
            data=json.dumps({"referee_id": warning_ref.id, "note": "Warning", "locked": False}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.target_assignment.refresh_from_db()
        self.assertEqual(self.target_assignment.referee_id, warning_ref.id)
        self.assertTrue(payload["warning"]["active"])
        self.assertIn("Sense disponibilitat registrada", payload["warning"]["text"])
        rebuild_map_delay_mock.assert_called_once_with(self.run.id)

    @patch("designacions.views.rebuild_run_map_task.delay")
    def test_update_assignment_async_rejects_incompatible_referee(self, rebuild_map_delay_mock):
        response = self.client.post(
            reverse("designacions_update_assignment_async", args=[self.run.id, self.target_assignment.id]),
            data=json.dumps({"referee_id": self.ref_modality.id, "note": "Invalid", "locked": False}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.target_assignment.refresh_from_db()
        self.assertIsNone(self.target_assignment.referee_id)
        rebuild_map_delay_mock.assert_not_called()

    @patch("designacions.views.rebuild_run_map_task.delay")
    def test_update_assignment_async_can_unassign(self, rebuild_map_delay_mock):
        self.target_assignment.referee = self.ref_best
        self.target_assignment.manual_override_warning = True
        self.target_assignment.manual_override_reason = "Old warning"
        self.target_assignment.locked = True
        self.target_assignment.save(update_fields=["referee", "manual_override_warning", "manual_override_reason", "locked", "updated_at"])

        response = self.client.post(
            reverse("designacions_update_assignment_async", args=[self.run.id, self.target_assignment.id]),
            data=json.dumps({"referee_id": None, "note": "Sense assignar", "locked": False}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.target_assignment.refresh_from_db()
        self.assertIsNone(self.target_assignment.referee_id)
        self.assertFalse(self.target_assignment.locked)
        self.assertFalse(self.target_assignment.manual_override_warning)
        self.assertEqual(self.target_assignment.manual_override_reason, "")
        self.assertEqual(payload["row_state"], "unassigned")
        rebuild_map_delay_mock.assert_called_once_with(self.run.id)

    @patch("designacions.tasks.rebuild_run_map", return_value="designacions/maps/run_test.html")
    def test_rebuild_run_map_task_updates_map_status(self, rebuild_run_map_mock):
        self.run.map_status = "queued"
        self.run.save(update_fields=["map_status"])

        result = rebuild_run_map_task.run(self.run.id)

        self.run.refresh_from_db()
        self.assertEqual(self.run.map_status, "ready")
        self.assertEqual(result["run_id"], self.run.id)
        rebuild_run_map_mock.assert_called_once()
