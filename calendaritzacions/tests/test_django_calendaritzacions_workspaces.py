import importlib.util
import json
import tempfile
from pathlib import Path

HAS_DJANGO = importlib.util.find_spec("django") is not None


if HAS_DJANGO:
    from django.test import TestCase
else:  # pragma: no cover
    TestCase = object


class DjangoCalendarizationWorkspaceTests(TestCase):
    def test_workspace_hydrates_resource_excess_and_team_explanation(self):
        if not HAS_DJANGO:
            self.skipTest("django not installed")

        from calendaritzacions.django.models import (
            CalendarizationRun,
            WorkspaceAssignment,
            WorkspaceResourceIncident,
            WorkspaceResourceMatch,
        )
        from calendaritzacions.django.services.workspaces import (
            get_or_create_workspace_for_run,
            get_workspace_incident_detail,
            get_workspace_summary,
            get_workspace_team_detail,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource_solution = root / "resource_solution.json"
            team_catalog = root / "team_catalog.json"
            candidate_catalog = root / "candidate_catalog.json"
            resource_pressure = root / "resource_pressure.json"
            resource_solution.write_text(
                json.dumps(
                    {
                        "status": "FEASIBLE",
                        "assignments": [
                            {"team_id": "A", "group_id": "G1", "number": 1},
                            {"team_id": "B", "group_id": "G1", "number": 2},
                            {"team_id": "C", "group_id": "G1", "number": 3},
                            {"team_id": "D", "group_id": "G1", "number": 4},
                        ],
                        "real_matches": [
                            {
                                "round_index": 1,
                                "group_id": "G1",
                                "home_team_id": "A",
                                "away_team_id": "B",
                                "home_number": 1,
                                "away_number": 2,
                                "resource_id": "pista-a|divendres|18-00|J1",
                            },
                            {
                                "round_index": 1,
                                "group_id": "G1",
                                "home_team_id": "C",
                                "away_team_id": "D",
                                "home_number": 3,
                                "away_number": 4,
                                "resource_id": "pista-a|divendres|18-00|J1",
                            },
                        ],
                        "resource_usage": [
                            {
                                "resource_id": "pista-a|divendres|18-00|J1",
                                "locals_count": 2,
                                "capacity": 1,
                                "excess": 1,
                                "team_ids": ["A", "C"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            team_catalog.write_text(
                json.dumps(
                    [
                        {
                            "team_id": "A",
                            "name": "Equip A",
                            "entity": "Club",
                            "league_name": "Lliga 1",
                            "seed_request_original": float("nan"),
                        },
                        {"team_id": "B", "name": "Equip B", "entity": "Club", "league_name": "Lliga 1"},
                        {"team_id": "C", "name": "Equip C", "entity": "Club", "league_name": "Lliga 1"},
                        {"team_id": "D", "name": "Equip D", "entity": "Club", "league_name": "Lliga 1"},
                    ]
                ),
                encoding="utf-8",
            )
            candidate_catalog.write_text(
                json.dumps(
                    [
                        {
                            "candidate_id": "A-G1-1",
                            "team_id": "A",
                            "group_id": "G1",
                            "number": 1,
                            "potential_home_rounds": [1],
                            "potential_resources": ["pista-a|divendres|18-00|J1"],
                        },
                        {
                            "candidate_id": "A-G1-2",
                            "team_id": "A",
                            "group_id": "G1",
                            "number": 2,
                            "potential_home_rounds": [],
                            "potential_resources": [],
                        },
                    ]
                ),
                encoding="utf-8",
            )
            resource_pressure.write_text(
                json.dumps(
                    [
                        {
                            "resource_id": "pista-a|divendres|18-00",
                            "demand_count": 3,
                            "estimated_capacity": 1,
                            "pressure": 3.0,
                            "is_critical": True,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            run = CalendarizationRun.objects.create(
                input_file="inputs/test.xlsx",
                input_name="test.xlsx",
                engine_name=CalendarizationRun.ENGINE_RESOURCE_SOLVER,
                phase=CalendarizationRun.PHASE_FIRST,
                status=CalendarizationRun.STATUS_SUCCESS,
                audit_paths={
                    "resource_solution": str(resource_solution),
                    "team_catalog": str(team_catalog),
                    "candidate_catalog": str(candidate_catalog),
                    "resource_pressure": str(resource_pressure),
                },
            )

            workspace = get_or_create_workspace_for_run(run)
            summary = get_workspace_summary(workspace)
            incident = WorkspaceResourceIncident.objects.get(workspace=workspace)
            detail = get_workspace_incident_detail(workspace, incident.pk)
            team_detail = get_workspace_team_detail(workspace, "A")

        assignment = WorkspaceAssignment.objects.get(workspace=workspace, team_id="A")
        self.assertEqual(WorkspaceAssignment.objects.filter(workspace=workspace).count(), 4)
        self.assertEqual(assignment.seed_request_original, "")
        self.assertIsNone(assignment.payload["team"]["seed_request_original"])
        self.assertEqual(WorkspaceResourceMatch.objects.filter(workspace=workspace).count(), 2)
        self.assertEqual(incident.excess, 1)
        self.assertEqual(incident.locals_count, 2)
        self.assertEqual(incident.capacity, 1)
        self.assertEqual(incident.team_ids, ["A", "C"])
        self.assertEqual(summary["kpis"][2]["value"], 1)
        self.assertEqual(summary["top_incidents"][0]["title"], "pista-a - divendres - 18-00 - J1")
        self.assertEqual(len(detail["affected_matches"]), 2)
        self.assertEqual(team_detail["number"], 1)
        self.assertIn("grup G1", team_detail["explanation"])
        self.assertEqual(team_detail["home_resources"][0]["incident_status"], "Amb incidencia")
        self.assertEqual(team_detail["home_resources"][0]["sharing_teams"], ["Equip C (C)"])
        self.assertEqual(team_detail["alternatives"][0]["number"], 2)
