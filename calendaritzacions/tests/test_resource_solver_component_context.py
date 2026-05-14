import json
import unittest

from calendaritzacions.domain.phases import PRIMERA_FASE
from calendaritzacions.engine.variants.resource_solver.component_context import (
    filter_context_by_team_ids,
    split_context_by_components,
    validate_component_split,
)
from calendaritzacions.engine.variants.resource_solver.config import ResourceSolverConfig
from calendaritzacions.engine.variants.resource_solver.decomposition import DependencyComponent
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


def make_context(teams, groups_by_team):
    group_ids = sorted({group_id for values in groups_by_team.values() for group_id in values})
    groups = tuple(
        GroupSpec(group_id, 2, 8, 4, "primera_fase")
        for group_id in group_ids
    )
    candidates = tuple(
        Candidate(
            candidate_id=f"{team.team_id}_{group_id}_{number}",
            team_id=team.team_id,
            group_id=group_id,
            number=number,
            seed_request_original="",
            potential_home_rounds=(1,),
            opponent_number_by_round={1: 2},
            potential_resources=(),
        )
        for team in teams
        for group_id in groups_by_team[team.team_id]
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
            team_ids=tuple(
                team.team_id
                for team in teams
                if build_base_resources([team]).get(resource_id) is not None
            ),
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


def component(component_id, team_ids):
    return DependencyComponent(
        component_id=component_id,
        team_ids=tuple(team_ids),
        competition_keys=(),
        resource_keys=(),
        linkage_keys=(),
        node_count=0,
        edge_count=0,
    )


class ResourceSolverComponentContextTests(unittest.TestCase):
    def test_filter_context_by_team_ids_keeps_only_component_data(self):
        context = make_context(
            [make_team("T1"), make_team("T2")],
            {"T1": ("G1",), "T2": ("G2",)},
        )

        subcontext = filter_context_by_team_ids(context, {"T1"})

        self.assertEqual([team.team_id for team in subcontext.teams], ["T1"])
        self.assertEqual([group.group_id for group in subcontext.groups], ["G1"])
        self.assertEqual({candidate.team_id for candidate in subcontext.candidates}, {"T1"})
        self.assertEqual(len(subcontext.base_resources), 1)

    def test_split_context_by_components_returns_component_mapping(self):
        context = make_context(
            [make_team("T1"), make_team("T2")],
            {"T1": ("G1",), "T2": ("G2",)},
        )

        subcontexts = split_context_by_components(
            context,
            [component("C001", ("T1",)), component("C002", ("T2",))],
        )

        self.assertEqual(set(subcontexts), {"C001", "C002"})
        self.assertEqual([team.team_id for team in subcontexts["C002"].teams], ["T2"])

    def test_validate_component_split_accepts_two_independent_components(self):
        context = make_context(
            [make_team("T1"), make_team("T2")],
            {"T1": ("G1",), "T2": ("G2",)},
        )

        payload = validate_component_split(
            context,
            [component("C001", ("T1",)), component("C002", ("T2",))],
        )

        json.dumps(payload)
        self.assertEqual(payload["status"], "valid")
        self.assertEqual(payload["errors"], [])
        self.assertEqual(payload["counts"]["subcontexts"]["teams"], 2)
        self.assertEqual(payload["counts"]["subcontexts"]["candidates"], 4)
        self.assertEqual(payload["counts"]["subcontexts"]["groups"], 2)

    def test_validate_component_split_detects_shared_group(self):
        context = make_context(
            [make_team("T1"), make_team("T2")],
            {"T1": ("G1",), "T2": ("G1",)},
        )

        payload = validate_component_split(
            context,
            [component("C001", ("T1",)), component("C002", ("T2",))],
        )

        self.assertEqual(payload["status"], "invalid")
        self.assertIn("shared_groups", _error_codes(payload))
        self.assertIn("total_mismatch", _error_codes(payload))

    def test_validate_component_split_detects_shared_resource_bridge(self):
        teams = [
            make_team("T1", venue="Pavello", day="Dilluns", time="18:00"),
            make_team("T2", venue="Pavello", day="Dilluns", time="18:00"),
        ]
        context = make_context(teams, {"T1": ("G1",), "T2": ("G2",)})

        payload = validate_component_split(
            context,
            [component("C001", ("T1",)), component("C002", ("T2",))],
        )

        self.assertEqual(payload["status"], "invalid")
        self.assertIn("shared_resources", _error_codes(payload))

    def test_validate_component_split_detects_shared_linkage_bridge(self):
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
                linkage_side="fora",
            ),
        ]
        context = make_context(teams, {"T1": ("G1",), "T2": ("G2",)})

        payload = validate_component_split(
            context,
            [component("C001", ("T1",)), component("C002", ("T2",))],
        )

        self.assertEqual(payload["status"], "invalid")
        self.assertIn("shared_linkages", _error_codes(payload))

    def test_validate_component_split_detects_missing_duplicate_and_orphan_candidates(self):
        context = make_context(
            [make_team("T1"), make_team("T2")],
            {"T1": ("G1",), "T2": ("G2",)},
        )

        payload = validate_component_split(
            context,
            [component("C001", ("T1",)), component("C002", ("T1",))],
        )

        self.assertEqual(payload["status"], "invalid")
        codes = _error_codes(payload)
        self.assertIn("duplicate_teams", codes)
        self.assertIn("missing_teams", codes)
        self.assertIn("orphan_candidates", codes)

    def test_validate_component_split_detects_declared_unknown_team(self):
        context = make_context(
            [make_team("T1"), make_team("T2")],
            {"T1": ("G1",), "T2": ("G2",)},
        )

        payload = validate_component_split(
            context,
            [component("C001", ("T1",)), component("C002", ("T2", "T999"))],
        )

        self.assertEqual(payload["status"], "invalid")
        self.assertIn("unknown_declared_teams", _error_codes(payload))


def _error_codes(payload):
    return {error["code"] for error in payload["errors"]}


if __name__ == "__main__":
    unittest.main()
