import json
import unittest

from calendaritzacions.domain.phases import PRIMERA_FASE
from calendaritzacions.engine.variants.resource_solver.config import ResourceSolverConfig
from calendaritzacions.engine.variants.resource_solver.decomposition import (
    build_decomposition_summary,
    dependency_components_payload,
    dependency_edges_payload,
    dependency_summary_payload,
)
from calendaritzacions.engine.variants.resource_solver.resources import build_base_resources
from calendaritzacions.engine.variants.resource_solver.types import (
    Candidate,
    CapacityEstimate,
    GroupSpec,
    PressureRow,
    SolverContext,
    TeamRecord,
)


def make_team(
    team_id,
    *,
    league_name=None,
    modality=None,
    category=None,
    subcategory=None,
    venue=None,
    day=None,
    time=None,
    linkage_group="",
    linkage_side="",
):
    suffix = team_id.removeprefix("T")
    return TeamRecord(
        team_id=team_id,
        name=f"Team {team_id}",
        entity=f"Club {team_id}",
        league_name=league_name or f"League {suffix}",
        modality=modality or f"Mod {suffix}",
        category=category or f"Cat {suffix}",
        subcategory=subcategory or f"Sub {suffix}",
        venue=venue or f"Pista {suffix}",
        day=day or f"Dia {suffix}",
        time=time or "18:00",
        linkage_group=linkage_group,
        linkage_side=linkage_side,
        linkage_source="test" if linkage_group else "",
    )


def make_context(teams):
    groups = (
        GroupSpec("G1", 2, 8, 4, "primera_fase"),
        GroupSpec("G2", 2, 8, 4, "primera_fase"),
    )
    candidates = tuple(
        Candidate(
            candidate_id=f"{team.team_id}_{group.group_id}_{number}",
            team_id=team.team_id,
            group_id=group.group_id,
            number=number,
            seed_request_original="",
            potential_home_rounds=(1,),
            opponent_number_by_round={1: 2},
            potential_resources=(),
        )
        for team in teams
        for group in groups
        for number in (1, 2)
    )
    base_resources = build_base_resources(teams)
    capacities = {
        resource_id: CapacityEstimate(resource_id, 4, "test", 1)
        for resource_id in base_resources
    }
    pressure = tuple(
        PressureRow(
            base_resource_id=resource_id,
            venue=resource.venue,
            day=resource.day,
            hour_slot=resource.hour_slot,
            team_ids=tuple(team.team_id for team in teams),
            demand_count=1,
            estimated_capacity=4,
            pressure=0.25,
            capacity_method="test",
            is_critical=False,
        )
        for resource_id, resource in base_resources.items()
    )
    return SolverContext(
        teams=tuple(teams),
        phase=PRIMERA_FASE,
        phase_name="primera_fase",
        base_resources=base_resources,
        capacities=capacities,
        pressure=pressure,
        groups=groups,
        candidates=candidates,
        config=ResourceSolverConfig(),
    )


class ResourceSolverDecompositionTests(unittest.TestCase):
    def test_components_remain_separated_without_shared_dependencies(self):
        context = make_context([make_team("T1"), make_team("T2")])

        summary = build_decomposition_summary(context)

        self.assertEqual(len(summary.components), 2)
        self.assertEqual([component.team_ids for component in summary.components], [("T1",), ("T2",)])
        self.assertEqual(summary.team_count, 2)
        self.assertEqual(summary.competition_count, 2)
        self.assertEqual(summary.resource_count, 2)
        self.assertEqual(summary.linkage_count, 0)
        self.assertEqual(summary.group_count, 2)
        self.assertEqual(summary.candidate_count, 8)
        self.assertEqual(summary.estimated_x_variables, 8)
        self.assertEqual(summary.edge_counts, {"competition": 2, "resource": 2})

    def test_shared_resource_joins_components(self):
        teams = [
            make_team("T1", venue="Pavello", day="Dilluns", time="18:00"),
            make_team("T2", venue="Pavello", day="Dilluns", time="18:00"),
        ]
        context = make_context(teams)

        summary = build_decomposition_summary(context)

        self.assertEqual(len(summary.components), 1)
        self.assertEqual(summary.components[0].team_ids, ("T1", "T2"))
        self.assertEqual(summary.resource_count, 1)

    def test_valid_linkage_joins_components(self):
        teams = [
            make_team(
                "T1",
                venue="Pavello",
                day="Dilluns",
                time="18:00",
                linkage_group="Grup A",
                linkage_side="casa",
            ),
            make_team(
                "T2",
                venue="Pavello",
                day="Dimarts",
                time="19:00",
                linkage_group=" Grup A ",
                linkage_side="fora",
            ),
        ]
        context = make_context(teams)

        summary = build_decomposition_summary(context)

        self.assertEqual(len(summary.components), 1)
        self.assertEqual(summary.components[0].team_ids, ("T1", "T2"))
        self.assertEqual(summary.linkage_count, 1)
        self.assertEqual(summary.edge_counts["linkage"], 2)

    def test_indifferent_linkage_side_does_not_join_components(self):
        teams = [
            make_team(
                "T1",
                venue="Pavello",
                day="Dilluns",
                time="18:00",
                linkage_group="L1",
                linkage_side="casa",
            ),
            make_team(
                "T2",
                venue="Pavello",
                day="Dimarts",
                time="19:00",
                linkage_group="L1",
                linkage_side="indiferent",
            ),
        ]
        context = make_context(teams)

        summary = build_decomposition_summary(context)

        self.assertEqual(len(summary.components), 2)
        self.assertEqual(summary.linkage_count, 0)
        self.assertNotIn("linkage", summary.edge_counts)

    def test_payloads_are_json_ready(self):
        context = make_context(
            [
                make_team("T1", venue="P", day="D", time="18:00"),
                make_team("T2", venue="P", day="D", time="18:00"),
            ]
        )
        summary = build_decomposition_summary(context)

        summary_payload = dependency_summary_payload(summary)
        components_payload = dependency_components_payload(summary)
        edges_payload = dependency_edges_payload(summary, max_edges_per_component=2)

        json.dumps(summary_payload)
        json.dumps(components_payload)
        json.dumps(edges_payload)
        self.assertIsInstance(components_payload[0]["team_ids"], list)
        self.assertLessEqual(len(edges_payload), 2)
        self.assertEqual(summary_payload["component_count"], 1)
        self.assertEqual(summary_payload["max_resource_pressure"], 0.25)
        self.assertEqual(summary_payload["artifact_type"], "resource_solver_dependency_decomposition")
        self.assertIn("candidate", summary_payload["audit_guide"])
        self.assertIn("interpretation", components_payload[0])


if __name__ == "__main__":
    unittest.main()
