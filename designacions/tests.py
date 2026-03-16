import os
import tempfile
from datetime import date, time

import pandas as pd
from django.test import SimpleTestCase, TestCase
from openpyxl import load_workbook

from .models import Assignment, Availability, DesignationRun, Match, Referee
from .main_fixed import _availability_penalty_for_subgroup, _build_daily_subgroups, _build_tutor_working_id
from .services.excel_export import export_run_to_excel


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
