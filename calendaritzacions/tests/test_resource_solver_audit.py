import json
import tempfile
import unittest
from types import SimpleNamespace

from calendaritzacions.domain.phases import PRIMERA_FASE
from calendaritzacions.engine.variants.resource_solver.audit import (
    build_audit_payloads,
    write_audit_payloads,
)
from calendaritzacions.engine.variants.resource_solver.config import ResourceSolverConfig
from calendaritzacions.engine.variants.resource_solver.local_explanations import (
    build_local_explanations,
)
from calendaritzacions.engine.variants.resource_solver.solution import build_solution
from calendaritzacions.engine.variants.resource_solver.types import (
    Assignment,
    BaseResource,
    Candidate,
    CapacityEstimate,
    GroupSpec,
    PressureRow,
    SolverContext,
    TeamRecord,
)


class ResourceSolverAuditTests(unittest.TestCase):
    def test_audit_payloads_are_json_ready_and_written(self):
        context = _context()
        raw_result = SimpleNamespace(
            status="FEASIBLE",
            objective_value=10,
            best_bound=0,
            wall_time=1.2,
            assignments=(Assignment("T1", "G1", 1), Assignment("T2", "G1", 2)),
        )
        result = build_solution(raw_result, context)
        local_explanations = build_local_explanations(result, context)

        payloads = build_audit_payloads(
            result=result,
            context=context,
            raw_result=raw_result,
            built_model=SimpleNamespace(num_variables=16, num_constraints=4),
            local_explanations=local_explanations,
        )

        encoded = json.dumps(payloads)
        self.assertIn("resource_solution", encoded)
        self.assertEqual(
            payloads["solver_explanations"]["optimality"],
            "feasible_solution_without_optimality_proof",
        )
        self.assertEqual(payloads["resource_pressure"][0]["resource_id"], "Court|Friday|18:00")

        with tempfile.TemporaryDirectory() as directory:
            paths = write_audit_payloads(payloads, directory)

        self.assertIn("solver_explanations", paths)
        self.assertTrue(paths["solver_explanations"].endswith("solver_explanations.json"))

    def test_local_explanations_skip_large_blocks(self):
        context = _context(
            config=ResourceSolverConfig(local_explanation_threshold=1),
        )
        result = build_solution(
            SimpleNamespace(assignments=(Assignment("T1", "G1", 1), Assignment("T2", "G1", 2))),
            context,
        )

        explanations = build_local_explanations(result, context)

        self.assertEqual(explanations[0]["enumerated"], False)
        self.assertIn("option_product_above_threshold", explanations[0]["skip_reason"])

    def test_model_objective_terms_do_not_leak_solver_variables(self):
        context = _context()
        raw_result = SimpleNamespace(
            status="FEASIBLE",
            objective_value=10,
            best_bound=0,
            wall_time=1.2,
            assignments=(Assignment("T1", "G1", 1),),
        )
        result = build_solution(raw_result, context)
        built_model = SimpleNamespace(
            objective_terms=[("resource_excess", 100, FakeIntVar("resource_excess_1"))],
            summary={},
        )

        payloads = build_audit_payloads(
            result=result,
            context=context,
            raw_result=raw_result,
            built_model=built_model,
        )

        encoded = json.dumps(payloads)
        self.assertIn("resource_excess", encoded)
        self.assertEqual(payloads["solver_model_summary"]["objective_terms"], {"resource_excess": 1})


def _context(config: ResourceSolverConfig | None = None) -> SolverContext:
    base_resource = BaseResource("Court|Friday|18:00", "Court", "Friday", "18:00")
    return SolverContext(
        teams=(
            TeamRecord("T1", "Team 1", "Club A", "League", venue="Court", day="Friday", time="18:00", seed_request_original=2),
            TeamRecord("T2", "Team 2", "Club B", "League", venue="Court", day="Friday", time="18:00", seed_request_original=2),
        ),
        phase=PRIMERA_FASE,
        phase_name="primera_fase",
        base_resources={base_resource.resource_id: base_resource},
        capacities={
            base_resource.resource_id: CapacityEstimate(base_resource.resource_id, 1, "test", 2),
        },
        pressure=(
            PressureRow(
                base_resource_id=base_resource.resource_id,
                venue="Court",
                day="Friday",
                hour_slot="18:00",
                team_ids=("T1", "T2"),
                demand_count=2,
                estimated_capacity=1,
                pressure=2.0,
                capacity_method="test",
                is_critical=True,
            ),
        ),
        groups=(GroupSpec("G1", 2, 8, 2, "primera_fase"),),
        candidates=(
            Candidate("T1-G1-1", "T1", "G1", 1, 2, (1,), {1: 2}, (base_resource.resource_id,)),
            Candidate("T1-G1-2", "T1", "G1", 2, 2, (2,), {1: 1}, (base_resource.resource_id,)),
            Candidate("T2-G1-1", "T2", "G1", 1, 2, (1,), {1: 2}, (base_resource.resource_id,)),
            Candidate("T2-G1-2", "T2", "G1", 2, 2, (2,), {1: 1}, (base_resource.resource_id,)),
        ),
        config=config or ResourceSolverConfig(),
    )


class FakeIntVar:
    def __init__(self, name: str) -> None:
        self._name = name

    def Name(self) -> str:
        return self._name


if __name__ == "__main__":
    unittest.main()
