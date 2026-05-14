import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from calendaritzacions.domain.phases import PRIMERA_FASE
from calendaritzacions.engine.variants.resource_solver.component_solver import (
    load_component_context_payload,
    solve_component_context,
)
from calendaritzacions.engine.variants.resource_solver.config import ResourceSolverConfig
from calendaritzacions.engine.variants.resource_solver.types import (
    Assignment,
    BaseResource,
    Candidate,
    CapacityEstimate,
    GroupSpec,
    SolverContext,
    TeamRecord,
)


class ResourceSolverComponentSolverTests(unittest.TestCase):
    def test_load_component_context_payload_from_json_file(self):
        context = _context()

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "context.json"
            path.write_text(json.dumps({"context": _context_payload(context)}), encoding="utf-8")

            loaded = load_component_context_payload(path)

        self.assertEqual([team.team_id for team in loaded.teams], ["T1", "T2"])
        self.assertEqual(loaded.phase, PRIMERA_FASE)
        self.assertEqual(loaded.groups[0].numbers, (1, 2))
        self.assertEqual(loaded.candidates[0].potential_home_rounds, (1,))
        self.assertEqual(loaded.candidates[0].opponent_number_by_round, {1: 2})
        self.assertIsInstance(loaded.config, ResourceSolverConfig)

    def test_solve_component_context_writes_partial_artifacts_with_stubs(self):
        context = _context()
        calls = []

        def build_stub(received_context):
            calls.append(("build", received_context))
            return SimpleNamespace(
                context=received_context,
                summary={"backend": "stub", "num_variables": 2},
            )

        def solve_stub(built_model, config):
            calls.append(("solve", built_model, config))
            return SimpleNamespace(
                status="OPTIMAL",
                objective_value=0.0,
                best_bound=0.0,
                wall_time=0.01,
                assignments=(
                    Assignment("T1", "G1", 1),
                    Assignment("T2", "G1", 2),
                ),
                variable_values={"T1-G1-1": 1, "T2-G1-2": 1},
                entity_excess={},
                resource_excess={},
                logs=("stub solver used",),
            )

        with tempfile.TemporaryDirectory() as tmp:
            result = solve_component_context(
                _context_payload(context),
                tmp,
                component_id="C001",
                build_solver_model_func=build_stub,
                solve_model_func=solve_stub,
            )

            model_summary = _read_json(Path(tmp) / "model_summary.json")
            raw_result = _read_json(Path(tmp) / "raw_result.json")
            solution = _read_json(Path(tmp) / "solution_partial.json")
            tmp_files = list(Path(tmp).glob("*.tmp"))

        self.assertEqual([call[0] for call in calls], ["build", "solve"])
        self.assertEqual(result["status"], "OPTIMAL")
        self.assertEqual(model_summary["artifact_type"], "resource_solver_component_model_summary")
        self.assertEqual(model_summary["component_id"], "C001")
        self.assertEqual(model_summary["backend"], "stub")
        self.assertEqual(raw_result["artifact_type"], "resource_solver_component_raw_result")
        self.assertEqual(raw_result["status"], "OPTIMAL")
        self.assertEqual(raw_result["variable_values"], {"T1-G1-1": 1, "T2-G1-2": 1})
        self.assertEqual(solution["artifact_type"], "resource_solver_component_solution_partial")
        self.assertEqual(solution["status"], "OPTIMAL")
        self.assertEqual(
            [(item["team_id"], item["group_id"], item["number"]) for item in solution["assignments"]],
            [("T1", "G1", 1), ("T2", "G1", 2)],
        )
        self.assertEqual(tmp_files, [])


def _context() -> SolverContext:
    base_resource = BaseResource(
        resource_id="Court|Friday|18:00",
        venue="Court",
        day="Friday",
        hour_slot="18:00",
    )
    return SolverContext(
        teams=(
            TeamRecord("T1", "Team 1", "Club A", "League", venue="Court", day="Friday", time="18:00"),
            TeamRecord("T2", "Team 2", "Club B", "League", venue="Court", day="Friday", time="18:00"),
        ),
        phase=PRIMERA_FASE,
        phase_name="primera_fase",
        base_resources={base_resource.resource_id: base_resource},
        capacities={
            base_resource.resource_id: CapacityEstimate(
                base_resource_id=base_resource.resource_id,
                capacity=1,
                method="test",
                demand_count=2,
            )
        },
        pressure=(),
        groups=(
            GroupSpec("G1", 2, 2, 2, "primera_fase", numbers=(1, 2)),
        ),
        candidates=(
            Candidate(
                candidate_id="T1-G1-1",
                team_id="T1",
                group_id="G1",
                number=1,
                seed_request_original="",
                potential_home_rounds=(1,),
                opponent_number_by_round={1: 2},
                potential_resources=(base_resource.resource_id,),
            ),
            Candidate(
                candidate_id="T2-G1-2",
                team_id="T2",
                group_id="G1",
                number=2,
                seed_request_original="",
                potential_home_rounds=(),
                opponent_number_by_round={1: 1},
                potential_resources=(),
            ),
        ),
        config=ResourceSolverConfig(time_limit_seconds=5.0, num_search_workers=1),
    )


def _context_payload(context: SolverContext) -> dict:
    payload = asdict(context)
    payload["phase"] = [
        [[home, away] for home, away in round_matches]
        for round_matches in context.phase
    ]
    return payload


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
