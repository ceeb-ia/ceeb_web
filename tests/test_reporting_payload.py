import tempfile
import unittest
from pathlib import Path

import pandas as pd

from calendaritzacions.analysis.kpi_payload import build_kpis_payload
from calendaritzacions.reporting.legacy_excel_writer import write_legacy_workbook


class ReportingPayloadTests(unittest.TestCase):
    def test_write_legacy_workbook_creates_xlsx_and_returns_incidents(self):
        resultats_totals = [
            pd.DataFrame(
                [
                    {
                        "_Categoria": "Lliga 1",
                        "Id": "E1",
                        "Nom": "Equip 1",
                        "Entitat": "Club",
                        "Grup": "G1",
                    }
                ]
            )
        ]

        with tempfile.TemporaryDirectory() as tmp:
            excel_path = Path(tmp) / "assignacions_test.xlsx"

            df_incidents = write_legacy_workbook(
                str(excel_path),
                resultats_totals=resultats_totals,
                info_totals=[],
                metrics_pack={},
                df_val_count_summary=pd.DataFrame(),
                df_val_entity_conflicts=pd.DataFrame(),
                df_val_level_spread=pd.DataFrame(),
            )

            self.assertTrue(excel_path.exists())
            self.assertGreater(excel_path.stat().st_size, 0)
            self.assertTrue(df_incidents.empty)

    def test_build_kpis_payload_preserves_legacy_sections(self):
        payload = build_kpis_payload(
            nom_fitxer="entrada",
            segona_fase_bool=False,
            fase=[1, 2, 3],
            excel_path="assignacions_entrada.xlsx",
            metrics_pack={
                "kpi_global": pd.DataFrame([{"Metrica": "Equips totals input", "Valor": 1}]),
                "analysis": pd.DataFrame([{"Nom": "Equip 1", "Categoria": "Lliga 1"}]),
            },
            df_info=pd.DataFrame([{"categoria": "Lliga 1"}]),
            df_val_count_summary=pd.DataFrame(),
            df_val_count_by_cat=pd.DataFrame(),
            df_val_entity_conflicts=pd.DataFrame(),
            df_val_level_spread=pd.DataFrame(),
            df_incidents=pd.DataFrame(),
        )

        self.assertEqual(payload["input_file"], "entrada")
        self.assertEqual(payload["fase"], "primera_fase")
        self.assertEqual(payload["jornades"], 3)
        self.assertEqual(payload["excel_path"], "assignacions_entrada.xlsx")
        self.assertEqual(payload["kpi_global"][0]["Metrica"], "Equips totals input")
        self.assertEqual(payload["analysis_rows"][0]["Equip"], "Equip 1")


if __name__ == "__main__":
    unittest.main()
