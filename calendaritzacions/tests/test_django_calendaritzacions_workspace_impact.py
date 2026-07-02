import importlib.util

HAS_DJANGO = importlib.util.find_spec("django") is not None


if HAS_DJANGO:
    from django.test import TestCase
else:  # pragma: no cover
    TestCase = object


class DjangoCalendarizationWorkspaceImpactTests(TestCase):
    def test_workspace_impact_aggregates_affected_teams(self):
        if not HAS_DJANGO:
            self.skipTest("django not installed")

        from calendaritzacions.django.models import (
            AssignmentWorkspace,
            CalendarizationRun,
            WorkspaceAssignment,
            WorkspaceResourceIncident,
            WorkspaceResourceMatch,
        )
        from calendaritzacions.django.services.workspace_impact import get_workspace_impact_view

        run = CalendarizationRun.objects.create(
            input_file="inputs/test.xlsx",
            input_name="test.xlsx",
            engine_name=CalendarizationRun.ENGINE_RESOURCE_SOLVER,
            phase=CalendarizationRun.PHASE_FIRST,
            status=CalendarizationRun.STATUS_SUCCESS,
        )
        workspace = AssignmentWorkspace.objects.create(run=run, name="Workspace")
        WorkspaceAssignment.objects.bulk_create(
            [
                WorkspaceAssignment(
                    workspace=workspace,
                    run=run,
                    team_id="A",
                    team_name="Equip A",
                    entity="Club",
                    group_id="G1",
                    assigned_number=1,
                    payload={"team": {"league_name": "Lliga 1", "modality": "Futbol", "category": "Mini", "level": "A"}},
                ),
                WorkspaceAssignment(
                    workspace=workspace,
                    run=run,
                    team_id="B",
                    team_name="Equip B",
                    entity="Club",
                    group_id="G1",
                    assigned_number=2,
                    payload={"team": {"league_name": "Lliga 1", "modality": "Futbol", "category": "Mini", "level": "A"}},
                ),
                WorkspaceAssignment(
                    workspace=workspace,
                    run=run,
                    team_id="C",
                    team_name="Equip C",
                    entity="Altre",
                    group_id="G1",
                    assigned_number=3,
                    payload={"team": {"league_name": "Lliga 2", "modality": "Basquet", "category": "Cadet", "level": "B"}},
                ),
            ]
        )
        WorkspaceResourceMatch.objects.bulk_create(
            [
                WorkspaceResourceMatch(
                    workspace=workspace,
                    run=run,
                    round_index=1,
                    group_id="G1",
                    home_team_id="A",
                    away_team_id="B",
                    home_resource_id="pista-a|divendres|18-00|J1",
                ),
                WorkspaceResourceMatch(
                    workspace=workspace,
                    run=run,
                    round_index=2,
                    group_id="G1",
                    home_team_id="C",
                    away_team_id="A",
                    home_resource_id="pista-b|dissabte|10-00|J2",
                ),
            ]
        )
        WorkspaceResourceIncident.objects.create(
            workspace=workspace,
            run=run,
            incident_type=WorkspaceResourceIncident.TYPE_RESOURCE_EXCESS,
            severity=2,
            resource_id="pista-a|divendres|18-00|J1",
            excess=2,
            locals_count=3,
            capacity=1,
            team_ids=["A", "C"],
            payload={"league_counts": {"Lliga 1 / Futbol / Mini": 1, "Lliga 2 / Basquet / Cadet": 1}},
        )
        WorkspaceResourceIncident.objects.create(
            workspace=workspace,
            run=run,
            incident_type=WorkspaceResourceIncident.TYPE_ASSIGNMENT_CONFLICT,
            severity=1,
            resource_id="G1|Club",
            excess=1,
            locals_count=2,
            capacity=1,
            team_ids=["A", "B"],
            payload={"entity": "Club", "group_id": "G1", "league_counts": {"Lliga 1 / Futbol / Mini": 2}},
        )

        impact = get_workspace_impact_view(workspace)

        kpis = {item["key"]: item["value"] for item in impact["kpis"]}
        kpis_by_key = {item["key"]: item for item in impact["kpis"]}
        self.assertNotIn("affected_teams", kpis)
        self.assertEqual(kpis["affected_incidents"], 2)
        self.assertEqual(kpis["affected_entities"], 2)
        self.assertEqual(kpis["affected_team_ratio"], "100%")
        self.assertEqual(kpis_by_key["affected_team_ratio"]["subtitle"], "3 de 3 equips")
        self.assertEqual(kpis["entity_conflict_team_ratio"], "66.7%")
        self.assertEqual(kpis["affected_match_ratio"], "50%")
        self.assertEqual(kpis["affected_linkage_ratio"], "0%")
        self.assertEqual(kpis["avg_impact_score"], "6.3")
        self.assertNotIn("avg_severity_per_team", kpis)
        self.assertNotIn("excess_per_team", kpis)
        self.assertNotIn("severity_total", kpis)
        self.assertEqual(impact["total_matches"], 2)
        self.assertEqual(impact["total_linkages"], 0)
        self.assertEqual(len(impact["affected_rows"]), 4)
        self.assertTrue(any(row["team_id"] == "A" and row["match_ids"] for row in impact["affected_rows"]))
        self.assertEqual(impact["modality_rows"][0]["label"], "Futbol")
        self.assertEqual(impact["modality_rows"][0]["team_count"], 2)
        self.assertEqual(impact["modality_rows"][0]["impact_score_per_team"], 8.75)
        self.assertEqual(impact["modality_rows"][0]["impact_score_avg"], 8.75)
        self.assertEqual(impact["type_rows"][0]["incident_count"], 1)
        self.assertTrue(any(item["token"] == "futbol" for item in impact["filters"]["modalities"]))
        self.assertTrue(any(row["team_id"] == "A" and row["impact"] == "7.5/10 (exces 2, sev. 2)" for row in impact["affected_rows"]))
        self.assertTrue(any(row["team_id"] == "A" and row["type_key"] == "assignment_conflict" for row in impact["affected_rows"]))

    def test_workspace_impact_empty_payload_shape(self):
        if not HAS_DJANGO:
            self.skipTest("django not installed")

        from calendaritzacions.django.models import AssignmentWorkspace, CalendarizationRun
        from calendaritzacions.django.services.workspace_impact import get_workspace_impact_view

        run = CalendarizationRun.objects.create(
            input_file="inputs/test.xlsx",
            input_name="test.xlsx",
            engine_name=CalendarizationRun.ENGINE_RESOURCE_SOLVER,
            phase=CalendarizationRun.PHASE_FIRST,
            status=CalendarizationRun.STATUS_SUCCESS,
        )
        workspace = AssignmentWorkspace.objects.create(run=run, name="Workspace")

        impact = get_workspace_impact_view(workspace)

        self.assertEqual(impact["affected_rows"], [])
        self.assertEqual(impact["modality_rows"], [])
        self.assertIn("modalities", impact["filters"])

    def test_workspace_impact_reports_affected_linkage_ratio(self):
        if not HAS_DJANGO:
            self.skipTest("django not installed")

        from calendaritzacions.django.models import (
            AssignmentWorkspace,
            CalendarizationRun,
            WorkspaceAssignment,
            WorkspaceResourceIncident,
        )
        from calendaritzacions.django.services.workspace_impact import get_workspace_impact_view

        run = CalendarizationRun.objects.create(
            input_file="inputs/test.xlsx",
            input_name="test.xlsx",
            engine_name=CalendarizationRun.ENGINE_RESOURCE_SOLVER,
            phase=CalendarizationRun.PHASE_FIRST,
            status=CalendarizationRun.STATUS_SUCCESS,
        )
        workspace = AssignmentWorkspace.objects.create(run=run, name="Workspace")
        for team_id, linkage_group in (("A", "LG-1"), ("B", "LG-1"), ("C", "LG-2")):
            WorkspaceAssignment.objects.create(
                workspace=workspace,
                run=run,
                team_id=team_id,
                team_name=f"Equip {team_id}",
                entity="Club",
                group_id="G1",
                assigned_number=1,
                payload={"team": {"league_name": "Lliga", "modality": "Futbol", "category": "Mini", "linkage_group": linkage_group}},
            )
        WorkspaceResourceIncident.objects.create(
            workspace=workspace,
            run=run,
            incident_type=WorkspaceResourceIncident.TYPE_LINKAGE_VIOLATION,
            severity=1,
            team_ids=["A", "B"],
            payload={"linkage_group": "LG-1"},
        )

        impact = get_workspace_impact_view(workspace)

        kpis = {item["key"]: item for item in impact["kpis"]}
        self.assertEqual(impact["total_linkages"], 2)
        self.assertEqual(kpis["affected_linkage_ratio"]["value"], "50%")
        self.assertEqual(kpis["affected_linkage_ratio"]["subtitle"], "1 de 2 linkages")
