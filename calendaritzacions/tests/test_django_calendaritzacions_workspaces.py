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
                engine_name=CalendarizationRun.ENGINE_RESOURCE_SOLVER_LINKAGE,
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

    def test_workspace_hydrates_linkage_violation_incidents(self):
        if not HAS_DJANGO:
            self.skipTest("django not installed")

        from calendaritzacions.django.models import CalendarizationRun, WorkspaceResourceIncident
        from calendaritzacions.django.services.workspaces import (
            get_or_create_workspace_for_run,
            get_workspace_incident_detail,
            get_workspace_linkage_view,
            get_workspace_summary,
            get_workspace_venue_round_sheets,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource_solution = root / "resource_solution.json"
            team_catalog = root / "team_catalog.json"
            candidate_catalog = root / "candidate_catalog.json"
            resource_pressure = root / "resource_pressure.json"
            solver_explanations = root / "solver_explanations.json"
            resource_solution.write_text(
                json.dumps(
                    {
                        "status": "FEASIBLE",
                        "assignments": [
                            {"team_id": "A", "group_id": "G1", "number": 1},
                            {"team_id": "B", "group_id": "G1", "number": 2},
                        ],
                        "real_matches": [
                            {
                                "round_index": 1,
                                "group_id": "G1",
                                "home_team_id": "A",
                                "away_team_id": "B",
                                "resource_id": "pista-a|divendres|18-00|J1",
                            }
                        ],
                        "resource_usage": [],
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
                            "entity": "Club A",
                            "league_name": "Lliga 1",
                            "venue": "pista-a",
                            "day": "divendres",
                            "time": "18-00",
                            "linkage_group": "LG-1",
                            "linkage_side": "casa",
                            "linkage_source": "input",
                        },
                        {
                            "team_id": "B",
                            "name": "Equip B",
                            "entity": "Club B",
                            "league_name": "Lliga 1",
                            "venue": "pista-a",
                            "day": "divendres",
                            "time": "19-00",
                            "linkage_group": "LG-1",
                            "linkage_side": "fora",
                            "linkage_source": "input",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            candidate_catalog.write_text(
                json.dumps(
                    [
                        {
                            "team_id": "A",
                            "group_id": "G1",
                            "number": 1,
                            "potential_resources": ["pista-a|divendres|18-00|J1"],
                            "potential_home_rounds": [1],
                        },
                        {
                            "team_id": "B",
                            "group_id": "G1",
                            "number": 2,
                            "potential_resources": [],
                            "potential_home_rounds": [],
                        },
                    ]
                ),
                encoding="utf-8",
            )
            resource_pressure.write_text("[]", encoding="utf-8")
            solver_explanations.write_text(
                json.dumps(
                    {
                        "linkage": {
                            "groups": [
                                {
                                    "venue": "pista-a",
                                    "linkage_group": "LG-1",
                                    "teams": [
                                        {
                                            "team_id": "A",
                                            "team_name": "Equip A",
                                            "assigned_group_id": "G1",
                                            "assigned_number": 1,
                                            "linkage_side": "casa",
                                        },
                                        {
                                            "team_id": "B",
                                            "team_name": "Equip B",
                                            "assigned_group_id": "G1",
                                            "assigned_number": 2,
                                            "linkage_side": "fora",
                                        },
                                    ],
                                }
                            ],
                            "violations": [
                                {
                                    "team_ids": ["A", "B"],
                                    "assigned_numbers": {"A": 1, "B": 2},
                                    "expected_numbers": {"A": "odd", "B": "odd"},
                                    "expected_relation": "same_side",
                                    "linkage_group": "LG-1",
                                    "venue": "pista-a",
                                    "day": "divendres",
                                    "time": "18-00",
                                    "cost": 7,
                                    "severity": "violation",
                                }
                            ],
                            "summary": {
                                "violations": 1,
                                "cost": 7,
                            },
                        }
                    }
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
                    "solver_explanations": str(solver_explanations),
                },
            )

            workspace = get_or_create_workspace_for_run(run)
            incident = WorkspaceResourceIncident.objects.get(
                workspace=workspace,
                incident_type=WorkspaceResourceIncident.TYPE_LINKAGE_VIOLATION,
            )
            summary = get_workspace_summary(workspace)
            detail = get_workspace_incident_detail(workspace, incident.pk)
            linkage_view = get_workspace_linkage_view(workspace)
            venue_sheets = get_workspace_venue_round_sheets(workspace)

        self.assertEqual(incident.team_ids, ["A", "B"])
        self.assertEqual(incident.payload["venue"], "pista-a")
        self.assertEqual(incident.payload["day"], "divendres")
        self.assertEqual(incident.payload["times"], ["18-00"])
        self.assertEqual(incident.payload["linkage_group"], "LG-1")
        self.assertEqual(incident.payload["expected_relation"], "same_side")
        self.assertEqual(incident.payload["teams"][0]["side"], "casa")
        self.assertEqual(incident.payload["teams"][0]["assigned_number"], 1)
        self.assertEqual(incident.payload["violation_cost"], 7.0)
        self.assertEqual(summary["incident_summaries"][0]["type_key"], "linkage_violation")
        self.assertEqual(summary["incident_summaries"][0]["type"], "Linkage violation")
        self.assertIn("same_side", summary["incident_summaries"][0]["summary"])
        self.assertEqual(detail["facts"][3]["value"], "LG-1")
        self.assertEqual(len(detail["team_calendars"]), 2)
        self.assertEqual(detail["team_calendars"][0]["calendar"][0]["side"], "Casa")
        self.assertEqual(summary["assignment_summaries"][0]["linkage_group"], "LG-1")
        self.assertEqual(linkage_view["group_count"], 1)
        self.assertEqual(linkage_view["groups"][0]["status"], "violation")
        self.assertEqual(linkage_view["groups"][0]["teams"][0]["side_label"], "Casa")
        self.assertEqual(venue_sheets["sheets"][0]["linkage_groups"], ["LG-1"])
        self.assertEqual(venue_sheets["sheets"][0]["rows"][0]["matches"][0]["linkage_groups"], ["LG-1"])

    def test_venue_round_sheets_use_max_venue_capacity_for_columns(self):
        if not HAS_DJANGO:
            self.skipTest("django not installed")

        from calendaritzacions.django.models import CalendarizationRun
        from calendaritzacions.django.services.workspaces import (
            get_workspace_calendar_view,
            get_or_create_workspace_for_run,
            get_workspace_venue_round_sheets,
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
                            {"team_id": team_id, "group_id": "G1", "number": index}
                            for index, team_id in enumerate(["A", "B", "C", "D", "E", "F"], start=1)
                        ],
                        "real_matches": [
                            {
                                "round_index": 1,
                                "group_id": "G1",
                                "home_team_id": "A",
                                "away_team_id": "B",
                                "resource_id": "pavello|divendres|18-00|J1",
                            },
                            {
                                "round_index": 1,
                                "group_id": "G1",
                                "home_team_id": "C",
                                "away_team_id": "D",
                                "resource_id": "pavello|divendres|18-00|J1",
                            },
                            {
                                "round_index": 1,
                                "group_id": "G1",
                                "home_team_id": "E",
                                "away_team_id": "F",
                                "resource_id": "pavello|divendres|19-00|J1",
                            },
                        ],
                        "resource_usage": [],
                    }
                ),
                encoding="utf-8",
            )
            team_catalog.write_text(
                json.dumps(
                    [
                        {
                            "team_id": team_id,
                            "name": f"Equip {team_id}",
                            "entity": "Club",
                            "league_name": "Lliga",
                            "modality": "Futbol" if team_id in {"A", "B", "C", "D"} else "Volei",
                        }
                        for team_id in ["A", "B", "C", "D", "E", "F"]
                    ]
                ),
                encoding="utf-8",
            )
            candidate_catalog.write_text("[]", encoding="utf-8")
            resource_pressure.write_text(
                json.dumps(
                    [
                        {
                            "resource_id": "pavello|divendres|18-00",
                            "venue": "Pavello",
                            "day": "Divendres",
                            "hour_slot": "18:00",
                            "teams": ["A", "B", "C", "D"],
                            "demand_count": 4,
                            "estimated_capacity": 2,
                        },
                        {
                            "resource_id": "pavello|divendres|19-00",
                            "venue": "Pavello",
                            "day": "Divendres",
                            "hour_slot": "19:00",
                            "teams": ["A", "B", "C", "D", "E", "F"],
                            "demand_count": 6,
                            "estimated_capacity": 3,
                        },
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
            payload = get_workspace_venue_round_sheets(workspace)
            calendar = get_workspace_calendar_view(workspace)

        sheet = payload["sheets"][0]
        rows_by_hour = {row["hour_slot"]: row for row in sheet["rows"]}
        self.assertEqual(sheet["venue"], "Pavello")
        self.assertEqual(sheet["max_capacity"], 3)
        self.assertEqual(list(sheet["court_columns"]), [1, 2, 3])
        self.assertEqual(sheet["requested_team_count"], 6)
        self.assertEqual(payload["modalities"], [{"label": "Futbol", "token": "futbol"}, {"label": "Volei", "token": "volei"}])
        self.assertEqual(sheet["modality_filter"], "futbol volei")
        self.assertEqual(rows_by_hour["18:00"]["match_count"], 2)
        self.assertEqual(len(list(rows_by_hour["18:00"]["empty_cells"])), 1)
        self.assertEqual(rows_by_hour["19:00"]["estimated_capacity"], 3)
        self.assertEqual(calendar["filters"]["modality"], [{"label": "Futbol", "token": "futbol"}, {"label": "Volei", "token": "volei"}])
        calendar_group = calendar["groups"][0]
        self.assertEqual(calendar_group["group_id"], "G1")
        self.assertEqual(calendar_group["rounds"], [1])
        self.assertEqual(calendar_group["rows"][0]["cells"][0]["side"], "Casa")
        self.assertIn("Equip B", calendar_group["rows"][0]["cells"][0]["opponent"])
        self.assertIn("pavello - divendres - 18-00 - J1", calendar_group["rows"][0]["cells"][0]["resource"])

    def test_workspace_calendar_view_groups_rounds_rests_filters_and_incidents(self):
        if not HAS_DJANGO:
            self.skipTest("django not installed")

        from calendaritzacions.django.models import CalendarizationRun
        from calendaritzacions.django.services.workspaces import (
            get_or_create_workspace_for_run,
            get_workspace_calendar_view,
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
                        ],
                        "real_matches": [
                            {
                                "round_index": 1,
                                "group_id": "G1",
                                "home_team_id": "A",
                                "away_team_id": "B",
                                "resource_id": "pavello|divendres|18-00|J1",
                            },
                            {
                                "round_index": 2,
                                "group_id": "G1",
                                "home_team_id": "C",
                                "away_team_id": "A",
                                "resource_id": "pavello|dissabte|10-00|J2",
                            },
                        ],
                        "resource_usage": [
                            {
                                "resource_id": "pavello|divendres|18-00|J1",
                                "locals_count": 2,
                                "capacity": 1,
                                "excess": 1,
                                "team_ids": ["A"],
                            }
                        ],
                        "group_summary": [
                            {
                                "group_id": "G1",
                                "assigned_numbers": {"1": "A", "2": "B", "3": "C"},
                                "entity_excess": {"Club": 1},
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
                            "modality": "Futbol",
                            "category": "Mini",
                            "subcategory": "Mixt",
                            "level": "A",
                            "venue": "Pavello",
                        },
                        {
                            "team_id": "B",
                            "name": "Equip B",
                            "entity": "Club",
                            "league_name": "Lliga 1",
                            "modality": "Futbol",
                            "category": "Mini",
                            "subcategory": "Mixt",
                            "level": "A",
                            "venue": "Pavello",
                        },
                        {
                            "team_id": "C",
                            "name": "Equip C",
                            "entity": "Altre",
                            "league_name": "Lliga 1",
                            "modality": "Futbol",
                            "category": "Mini",
                            "subcategory": "Mixt",
                            "level": "A",
                            "venue": "Pavello",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            candidate_catalog.write_text("[]", encoding="utf-8")
            resource_pressure.write_text("[]", encoding="utf-8")
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
            payload = get_workspace_calendar_view(workspace)

        self.assertEqual(payload["rounds"], [1, 2])
        self.assertEqual(payload["filters"]["modality"], [{"label": "Futbol", "token": "futbol"}])
        self.assertEqual(payload["filters"]["category"], [{"label": "Mini", "token": "mini"}])
        self.assertEqual(payload["filters"]["subcategory"], [{"label": "Mixt", "token": "mixt"}])
        self.assertEqual(payload["filters"]["level"], [{"label": "A", "token": "a"}])
        self.assertEqual(payload["filters"]["league"], [{"label": "Lliga 1", "token": "lliga-1"}])
        self.assertEqual(payload["filters"]["venue"], [{"label": "Pavello", "token": "pavello"}])
        self.assertEqual(
            payload["filters"]["entity"],
            [{"label": "Altre", "token": "altre"}, {"label": "Club", "token": "club"}],
        )

        group = payload["groups"][0]
        self.assertEqual(group["group_id"], "G1")
        self.assertEqual(group["competition"], "Lliga 1 / Futbol / Mini / Mixt")
        self.assertEqual(group["modality"], "Futbol")
        self.assertEqual(group["category"], "Mini")
        self.assertEqual(group["subcategory"], "Mixt")
        self.assertEqual(group["level"], "A")
        self.assertEqual(group["venue"], "Pavello")
        self.assertEqual(group["rounds"], [1, 2])
        self.assertIn("Equip A", group["filter_text"])
        self.assertEqual([row["team_id"] for row in group["rows"]], ["A", "B", "C"])

        row_a, row_b, row_c = group["rows"]
        self.assertIn("Futbol", row_a["filter_text"])
        self.assertEqual(row_a["cells"][0]["side"], "Casa")
        self.assertEqual(row_a["cells"][0]["opponent_id"], "B")
        self.assertIn("Equip B", row_a["cells"][0]["opponent"])
        self.assertEqual(row_a["cells"][0]["resource"], "pavello - divendres - 18-00 - J1")
        self.assertIsNotNone(row_a["cells"][0]["match_id"])
        self.assertTrue(row_a["cells"][0]["has_resource_incident"])
        self.assertTrue(row_a["cells"][0]["has_entity_incident"])
        self.assertEqual(row_a["cells"][1]["side"], "Fora")
        self.assertEqual(row_a["cells"][1]["resource"], "")

        self.assertEqual(row_b["cells"][0]["side"], "Fora")
        self.assertFalse(row_b["cells"][0]["has_resource_incident"])
        self.assertEqual(row_b["cells"][1]["side"], "Descans")
        self.assertTrue(row_b["cells"][1]["has_entity_incident"])

        self.assertEqual(row_c["cells"][0]["side"], "Descans")
        self.assertFalse(row_c["cells"][0]["has_entity_incident"])
        self.assertEqual(row_c["cells"][1]["side"], "Casa")
        self.assertEqual(row_c["cells"][1]["opponent_id"], "A")

    def test_workspace_materializes_entity_conflicts_with_team_calendars(self):
        if not HAS_DJANGO:
            self.skipTest("django not installed")

        from calendaritzacions.django.models import CalendarizationRun, WorkspaceResourceIncident
        from calendaritzacions.django.services.workspaces import (
            get_or_create_workspace_for_run,
            get_workspace_incident_detail,
            get_workspace_summary,
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
                        ],
                        "real_matches": [
                            {
                                "round_index": 1,
                                "group_id": "G1",
                                "home_team_id": "A",
                                "away_team_id": "B",
                                "resource_id": "pista-a|divendres|18-00|J1",
                            },
                            {
                                "round_index": 2,
                                "group_id": "G1",
                                "home_team_id": "C",
                                "away_team_id": "A",
                                "resource_id": "pista-b|dissabte|19-00|J2",
                            },
                        ],
                        "resource_usage": [],
                        "group_summary": [
                            {
                                "group_id": "G1",
                                "assigned_numbers": {"1": "A", "2": "B", "3": "C"},
                                "empty_numbers": [4, 5, 6, 7, 8],
                                "rests_by_team": {},
                                "entity_excess": {"Club": 1},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            team_catalog.write_text(
                json.dumps(
                    [
                        {"team_id": "A", "name": "Equip A", "entity": "Club", "league_name": "Lliga 1"},
                        {"team_id": "B", "name": "Equip B", "entity": "Club", "league_name": "Lliga 1"},
                        {"team_id": "C", "name": "Equip C", "entity": "Altre", "league_name": "Lliga 1"},
                    ]
                ),
                encoding="utf-8",
            )
            candidate_catalog.write_text("[]", encoding="utf-8")
            resource_pressure.write_text("[]", encoding="utf-8")
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
            incident = WorkspaceResourceIncident.objects.get(
                workspace=workspace,
                incident_type=WorkspaceResourceIncident.TYPE_ASSIGNMENT_CONFLICT,
            )
            detail = get_workspace_incident_detail(workspace, incident.pk)

        self.assertEqual(incident.team_ids, ["A", "B"])
        self.assertEqual(incident.excess, 1)
        self.assertEqual(summary["kpis"][3]["value"], 1)
        self.assertEqual(summary["incident_summaries"][0]["type"], "Conflicte entitat")
        self.assertEqual(len(detail["team_calendars"]), 2)
        self.assertEqual(detail["team_calendars"][0]["team_name"], "Equip A")
        self.assertEqual(detail["team_calendars"][0]["calendar"][0]["side"], "Casa")
