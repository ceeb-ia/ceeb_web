import unittest

from calendaritzacions.django.services.audit_presenter import build_audit_presentation


class AuditPresenterTests(unittest.TestCase):
    def test_resource_pressure_builds_cards_chart_table_and_definitions(self):
        presentation = build_audit_presentation(
            "resource_pressure",
            [
                {
                    "venue": "Pista A",
                    "day": "Divendres",
                    "hour_slot": "18:00",
                    "demand_count": 4,
                    "estimated_capacity": 2,
                    "pressure": 2.0,
                    "is_critical": True,
                }
            ],
        )

        self.assertEqual(presentation["title"], "Pressio de pistes i franges")
        self.assertTrue(presentation["cards"])
        self.assertTrue(presentation["charts"])
        self.assertTrue(presentation["tables"])
        definition_names = {item["name"] for item in presentation["definitions"]}
        self.assertIn("Pressio", definition_names)

    def test_resource_solution_summarizes_solver_payload(self):
        presentation = build_audit_presentation(
            "resource_solution",
            {
                "status": "OPTIMAL",
                "assignments": [{"team_id": "T1", "group_id": "G1", "number": 1}],
                "real_matches": [],
                "resource_usage": [{"resource_id": "Pista|D|18|J1", "locals_count": 2, "capacity": 1, "excess": 1}],
                "group_summary": [],
                "entity_excess": {"Club|G1": 1},
            },
            related_payloads={"team_catalog": [{"team_id": "T1", "name": "Equip 1"}]},
        )

        labels = {card["label"]: card["value"] for card in presentation["cards"]}
        self.assertEqual(labels["Estat"], "OPTIMAL")
        self.assertEqual(labels["Assignacions"], 1)
        self.assertEqual(labels["Exces recursos"], 1)
        self.assertTrue(presentation["charts"])
        assignment_table = next(table for table in presentation["tables"] if table["title"] == "Assignacions")
        self.assertEqual(assignment_table["columns"][0]["label"], "Equip")
        self.assertEqual(assignment_table["rows"][0]["team"], "Equip 1")
        usage_table = next(table for table in presentation["tables"] if table["title"] == "Us de recursos")
        self.assertEqual(usage_table["rows"][0]["resource"], "Pista · D · 18 · Jornada 1")


if __name__ == "__main__":
    unittest.main()
