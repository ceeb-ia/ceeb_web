import unittest
from types import SimpleNamespace
from unittest.mock import patch

from calendaritzacions.domain.phases import PRIMERA_FASE
from calendaritzacions.engine.config import EngineConfig
from calendaritzacions.engine.variants.resource_solver.config import (
    ResourceSolverConfig,
    coerce_resource_solver_config,
)
from calendaritzacions.engine.variants.resource_solver.conflict_repair import (
    build_linkage_repair_blocks,
    build_initial_components,
    build_repair_blocks,
    context_with_residual_capacities,
    detect_conflict_hubs,
    detect_linkage_conflicts,
    frozen_usage_by_resource,
    linkage_buckets,
    merge_assignments,
    team_to_initial_component,
)
from calendaritzacions.engine.variants.resource_solver.conflict_repair_service import (
    _add_assignment_hint,
    _repair_linkage_blocks,
    _repair_block_solve_limit,
    _repair_blocks,
    _repair_deadline_at,
    _result_from_assignments,
    _with_internal_solve_limit,
)
from calendaritzacions.engine.variants.resource_solver.solution import build_solution
from calendaritzacions.engine.variants.resource_solver.types import (
    Assignment,
    BaseResource,
    Candidate,
    CapacityEstimate,
    GroupSpec,
    SolverContext,
    TeamRecord,
)


class ResourceSolverConflictRepairTests(unittest.TestCase):
    def test_initial_components_ignore_shared_resources(self):
        context = _context()

        components = build_initial_components(context)

        self.assertEqual(len(components), 2)
        self.assertEqual([component.team_ids for component in components], [("T1", "T2"), ("T3", "T4")])

    def test_small_linkage_is_cut_and_registered_for_repair(self):
        context = _context(linked=True)

        components = build_initial_components(context)
        result = _result_with_two_locals(context)
        conflicts = detect_linkage_conflicts(context, result, components)
        blocks = build_linkage_repair_blocks(context, components, conflicts)

        self.assertEqual(len(components), 2)
        self.assertEqual(tuple(linkage_buckets(context).values()), (("T1", "T3"),))
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].component_ids, ("I001", "I002"))
        self.assertEqual(conflicts[0].mismatch_count, 7)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].initial_component_ids, ("I001", "I002"))

    def test_hard_level_split_separates_a_from_non_a_inside_competition(self):
        context = _context(
            levels={"T1": "A", "T2": "A", "T3": "B", "T4": "C"},
            config=ResourceSolverConfig(competition_grouping="league", level_constraint_mode="hard"),
            same_league=True,
        )

        components = build_initial_components(context)

        self.assertEqual(len(components), 2)
        self.assertEqual([component.team_ids for component in components], [("T1", "T2"), ("T3", "T4")])
        self.assertTrue(any("level_family|A" in component.competition_keys[0] for component in components))
        self.assertTrue(any("level_family|no-A" in component.competition_keys[0] for component in components))

    def test_conflict_hub_builds_repair_block(self):
        context = _context(capacity=1)
        result = _result_with_two_locals(context)
        components = build_initial_components(context)
        hubs = detect_conflict_hubs(context, result, team_to_initial_component(components))

        blocks = build_repair_blocks(context, components, hubs)

        self.assertEqual(len(hubs), 1)
        self.assertEqual(hubs[0].resource_id, "R|J1")
        self.assertEqual(hubs[0].excess, 1)
        self.assertEqual(hubs[0].component_ids, ("I001", "I002"))
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].initial_component_ids, ("I001", "I002"))

    def test_residual_capacities_discount_frozen_usage(self):
        context = _context(capacity=3)
        result = _result_with_two_locals(context)
        frozen = frozen_usage_by_resource(result, repair_team_ids=("T1", "T2"))

        residual = context_with_residual_capacities(context, frozen)

        self.assertEqual(frozen, {"R|J1": 1})
        self.assertEqual(residual.capacities["R|J1"].capacity, 2)
        self.assertEqual(residual.capacities["R|J1"].method, "conflict_repair_residual")

    def test_merge_assignments_replaces_only_repaired_block(self):
        context = _context()
        components = build_initial_components(context)
        repaired = (
            Assignment("T1", "G1", 2),
            Assignment("T2", "G1", 1),
        )

        merged = merge_assignments(
            context,
            initial_assignments=_assignments(),
            repaired_assignments_by_block={"R001": repaired},
            repair_blocks=[
                SimpleNamespace(block_id="R001", team_ids=("T1", "T2")),
                SimpleNamespace(block_id="R002", team_ids=("T3", "T4")),
            ],
        )

        by_team = {assignment.team_id: assignment for assignment in merged}
        self.assertEqual(by_team["T1"].number, 2)
        self.assertEqual(by_team["T2"].number, 1)
        self.assertEqual(by_team["T3"].number, 1)
        self.assertEqual(by_team["T4"].number, 2)
        self.assertEqual(len(components), 2)

    def test_new_engine_name_defaults_to_input_linkage(self):
        config = coerce_resource_solver_config(EngineConfig(name="resource_solver_conflict_repair"))

        self.assertEqual(config.linkage_mode, "input")

    def test_conflict_repair_result_recomputes_entity_excess_after_merge(self):
        context = _context(same_entity=True)

        result = _result_from_assignments(
            context=context,
            assignments=_assignments(),
            status="OPTIMAL",
        )

        self.assertEqual(result.entity_excess, {("Club", "G1"): 1, ("Club", "G2"): 1})

    def test_internal_solve_limit_caps_conflict_repair_subproblems(self):
        context = _context()
        context = SolverContext(
            teams=context.teams,
            phase=context.phase,
            phase_name=context.phase_name,
            base_resources=context.base_resources,
            capacities=context.capacities,
            pressure=context.pressure,
            groups=context.groups,
            candidates=context.candidates,
            config=ResourceSolverConfig(
                time_limit_seconds=14400,
                internal_solve_time_limit_seconds=300,
                repair_solve_time_limit_seconds=300,
                competition_grouping="league",
            ),
        )

        capped = _with_internal_solve_limit(context)

        self.assertEqual(capped.config.time_limit_seconds, 300)
        self.assertEqual(context.config.time_limit_seconds, 14400)

    def test_repair_block_uses_initial_assignment_as_fallback_on_unknown(self):
        context = _context(capacity=1)
        initial_result = _result_with_two_locals(context)
        block = SimpleNamespace(
            block_id="R001",
            team_ids=("T1", "T2"),
            conflict_resource_ids=("R|J1",),
            initial_component_ids=("I001",),
        )
        built_model = SimpleNamespace(backend="stub", model=None, variables=None, summary={})

        with patch(
            "calendaritzacions.engine.variants.resource_solver.conflict_repair_service.build_solver_model",
            return_value=built_model,
        ), patch(
            "calendaritzacions.engine.variants.resource_solver.conflict_repair_service.solve_model",
            return_value=SimpleNamespace(status="UNKNOWN", assignments=(), logs=("timeout",)),
        ):
            repaired, records = _repair_blocks(
                context=context,
                initial_result=initial_result,
                repair_blocks=(block,),
            )

        self.assertEqual(
            [(assignment.team_id, assignment.group_id, assignment.number) for assignment in repaired["R001"]],
            [("T1", "G1", 1), ("T2", "G1", 2)],
        )
        self.assertEqual(records[0]["status"], "UNKNOWN")
        self.assertTrue(records[0]["fallback_used"])
        self.assertFalse(records[0]["accepted"])
        self.assertEqual(records[0]["selected_assignment_count"], 2)

    def test_linkage_repair_uses_fallback_on_unknown(self):
        context = _context(linked=True)
        components = build_initial_components(context)
        initial_result = _result_with_two_locals(context)
        conflicts = detect_linkage_conflicts(context, initial_result, components)
        blocks = build_linkage_repair_blocks(context, components, conflicts)
        built_model = SimpleNamespace(backend="stub", model=None, variables=None, summary={})

        with patch(
            "calendaritzacions.engine.variants.resource_solver.conflict_repair_service.build_solver_model",
            return_value=built_model,
        ), patch(
            "calendaritzacions.engine.variants.resource_solver.conflict_repair_service.solve_model",
            return_value=SimpleNamespace(status="UNKNOWN", assignments=(), logs=("timeout",)),
        ):
            repaired, records = _repair_linkage_blocks(
                context=context,
                initial_components=components,
                initial_result=initial_result,
                linkage_blocks=blocks,
            )

        self.assertEqual(set(repaired), {"L001"})
        self.assertEqual(records[0]["stage"], "linkage_repair")
        self.assertEqual(records[0]["fallback_linkage_mismatches"], 7)
        self.assertTrue(records[0]["fallback_used"])
        self.assertFalse(records[0]["accepted"])

    def test_assignment_hint_marks_selected_candidate(self):
        context = _context()
        added_hints = []

        class ModelStub:
            def AddHint(self, variable, value):
                added_hints.append((variable, value))

        variables = SimpleNamespace(
            x={candidate.candidate_id: f"var-{candidate.candidate_id}" for candidate in context.candidates},
            candidate_by_id={candidate.candidate_id: candidate for candidate in context.candidates},
        )
        built_model = SimpleNamespace(model=ModelStub(), variables=variables)

        added = _add_assignment_hint(
            built_model,
            (Assignment("T1", "G1", 1), Assignment("T2", "G1", 2)),
        )

        self.assertTrue(added)
        self.assertIn(("var-T1-G1-1", 1), added_hints)
        self.assertIn(("var-T1-G1-2", 0), added_hints)

    def test_repair_deadline_skips_blocks_and_keeps_fallback(self):
        context = _context(capacity=1)
        initial_result = _result_with_two_locals(context)
        blocks = (
            SimpleNamespace(
                block_id="R001",
                team_ids=("T1", "T2"),
                conflict_resource_ids=("R|J1",),
                initial_component_ids=("I001",),
            ),
            SimpleNamespace(
                block_id="R002",
                team_ids=("T3", "T4"),
                conflict_resource_ids=("R|J1",),
                initial_component_ids=("I002",),
            ),
        )

        with patch(
            "calendaritzacions.engine.variants.resource_solver.conflict_repair_service.build_solver_model",
        ) as build_solver:
            repaired, records = _repair_blocks(
                context=context,
                initial_result=initial_result,
                repair_blocks=blocks,
                repair_deadline_at=0.0,
            )

        self.assertFalse(build_solver.called)
        self.assertEqual(set(repaired), {"R001", "R002"})
        self.assertTrue(all(record["fallback_used"] for record in records))
        self.assertTrue(all(record["skipped_due_deadline"] for record in records))
        self.assertEqual([record["status"] for record in records], ["SKIPPED_GLOBAL_DEADLINE", "SKIPPED_GLOBAL_DEADLINE"])

    def test_repair_block_limit_splits_remaining_time_across_blocks(self):
        context = _context()
        context = SolverContext(
            teams=context.teams,
            phase=context.phase,
            phase_name=context.phase_name,
            base_resources=context.base_resources,
            capacities=context.capacities,
            pressure=context.pressure,
            groups=context.groups,
            candidates=context.candidates,
            config=ResourceSolverConfig(
                repair_solve_time_limit_seconds=3600,
                competition_grouping="league",
            ),
        )

        with patch(
            "calendaritzacions.engine.variants.resource_solver.conflict_repair_service.perf_counter",
            return_value=100.0,
        ):
            limit = _repair_block_solve_limit(
                context=context,
                repair_deadline_at=3700.0,
                remaining_blocks=2,
            )

        self.assertEqual(limit, 1800.0)

    def test_repair_deadline_reserves_finalization_margin(self):
        deadline = _repair_deadline_at(
            100.0,
            SimpleNamespace(worker_time_limit_seconds=86400, finalization_margin_seconds=1800),
        )

        self.assertEqual(deadline, 84700.0)


def _context(capacity=10, linked=False, same_entity=False, levels=None, config=None, same_league=False) -> SolverContext:
    base_resource = BaseResource("R", "Pista", "Divendres", "18:00")
    level_by_team = levels or {}
    teams = (
        TeamRecord(
            "T1",
            "Team 1",
            "Club" if same_entity else "Club 1",
            "League A",
            venue="Pista",
            day="Divendres",
            time="18:00",
            level=level_by_team.get("T1", ""),
            linkage_group="L1" if linked else "",
            linkage_side="casa" if linked else "",
        ),
        TeamRecord("T2", "Team 2", "Club" if same_entity else "Club 2", "League A", venue="Pista", day="Divendres", time="18:00", level=level_by_team.get("T2", "")),
        TeamRecord(
            "T3",
            "Team 3",
            "Club" if same_entity else "Club 3",
            "League A" if same_league else "League B",
            venue="Pista",
            day="Divendres",
            time="18:00",
            level=level_by_team.get("T3", ""),
            linkage_group="L1" if linked else "",
            linkage_side="fora" if linked else "",
        ),
        TeamRecord("T4", "Team 4", "Club" if same_entity else "Club 4", "League A" if same_league else "League B", venue="Pista", day="Divendres", time="18:00", level=level_by_team.get("T4", "")),
    )
    groups = (
        GroupSpec("G1", 2, 2, 2, "primera_fase", numbers=(1, 2)),
        GroupSpec("G2", 2, 2, 2, "primera_fase", numbers=(1, 2)),
    )
    return SolverContext(
        teams=teams,
        phase=PRIMERA_FASE,
        phase_name="primera_fase",
        base_resources={base_resource.resource_id: base_resource},
        capacities={
            base_resource.resource_id: CapacityEstimate(base_resource.resource_id, capacity, "test", len(teams))
        },
        pressure=(),
        groups=groups,
        candidates=(
            _candidate("T1", "G1", 1),
            _candidate("T1", "G1", 2),
            _candidate("T2", "G1", 1),
            _candidate("T2", "G1", 2),
            _candidate("T3", "G2", 1),
            _candidate("T3", "G2", 2),
            _candidate("T4", "G2", 1),
            _candidate("T4", "G2", 2),
        ),
        config=config or ResourceSolverConfig(competition_grouping="league"),
    )


def _candidate(team_id, group_id, number):
    return Candidate(
        candidate_id=f"{team_id}-{group_id}-{number}",
        team_id=team_id,
        group_id=group_id,
        number=number,
        seed_request_original="",
        potential_home_rounds=(1,) if number == 1 else (),
        opponent_number_by_round={1: 2},
        potential_resources=("R|J1",) if number == 1 else (),
    )


def _assignments():
    return (
        Assignment("T1", "G1", 1),
        Assignment("T2", "G1", 2),
        Assignment("T3", "G2", 1),
        Assignment("T4", "G2", 2),
    )


def _result_with_two_locals(context):
    return build_solution(
        SimpleNamespace(status="OPTIMAL", assignments=_assignments()),
        context,
    )


if __name__ == "__main__":
    unittest.main()
