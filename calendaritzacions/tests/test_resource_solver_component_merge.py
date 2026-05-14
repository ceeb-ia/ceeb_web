import json
import tempfile
import unittest
from pathlib import Path

from calendaritzacions.engine.variants.resource_solver.component_merge import (
    ComponentMergeValidationError,
    merge_component_results,
)


class ResourceSolverComponentMergeTests(unittest.TestCase):
    def test_merge_component_results_combines_valid_partial_artifacts_from_paths(self):
        context = _context(["T1", "T2"], [("T1", "G1", 1), ("T2", "G2", 1)])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            c001 = _write_component(root, "C001", "OPTIMAL", 10, 1.5, [_assignment("T1", "G1", 1)])
            c002 = _write_component(root, "C002", "FEASIBLE", 2.5, 0.25, [_assignment("T2", "G2", 1)])
            output_dir = root / "merged"

            payload = merge_component_results(
                context,
                [c002, c001],
                component_ids=["C001", "C002"],
                output_dir=output_dir,
            )

            raw_file = _read_json(output_dir / "merged_raw_result.json")
            solution_file = _read_json(output_dir / "merged_solution.json")
            validation_file = _read_json(output_dir / "component_merge_validation.json")

        self.assertEqual(payload["status"], "FEASIBLE")
        self.assertEqual(payload["validation"]["status"], "valid")
        self.assertEqual(payload["raw_result"]["objective_value"], 12.5)
        self.assertEqual(payload["raw_result"]["wall_time"], 1.75)
        self.assertEqual(
            [(item["team_id"], item["group_id"], item["number"]) for item in payload["solution"]["assignments"]],
            [("T1", "G1", 1), ("T2", "G2", 1)],
        )
        self.assertEqual(raw_file["status"], "FEASIBLE")
        self.assertEqual(solution_file["artifact_type"], "resource_solver_merged_solution")
        self.assertEqual(validation_file["status"], "valid")

    def test_merge_status_is_conservative_and_objective_requires_all_numeric(self):
        context = _context(["T1", "T2"], [("T1", "G1", 1), ("T2", "G2", 1)])
        result = merge_component_results(
            context,
            [
                _component_payload("C001", "OPTIMAL", 3, 1.0, [_assignment("T1", "G1", 1)]),
                _component_payload("C002", "TIME_LIMIT", None, 2.0, [_assignment("T2", "G2", 1)]),
            ],
        )

        self.assertEqual(result["status"], "UNKNOWN")
        self.assertIsNone(result["raw_result"]["objective_value"])
        self.assertEqual(result["raw_result"]["wall_time"], 3.0)

    def test_infeasible_status_dominates(self):
        context = _context(["T1", "T2"], [("T1", "G1", 1), ("T2", "G2", 1)])
        result = merge_component_results(
            context,
            [
                _component_payload("C001", "INFEASIBLE", 0, 1.0, [_assignment("T1", "G1", 1)]),
                _component_payload("C002", "UNKNOWN", 0, 2.0, [_assignment("T2", "G2", 1)]),
            ],
        )

        self.assertEqual(result["status"], "INFEASIBLE")

    def test_infeasible_component_can_merge_without_assignments(self):
        context = _context(["T1", "T2"], [("T1", "G1", 1), ("T2", "G2", 1)])

        result = merge_component_results(
            context,
            [
                _component_payload("C001", "INFEASIBLE", 0, 1.0, []),
                _component_payload("C002", "OPTIMAL", 0, 1.0, []),
            ],
            component_ids=["C001", "C002"],
        )

        self.assertEqual(result["status"], "INFEASIBLE")
        self.assertEqual(result["validation"]["status"], "valid")

    def test_merge_rejects_duplicate_and_absent_team_assignments(self):
        context = _context(["T1", "T2"], [("T1", "G1", 1), ("T2", "G2", 1)])

        with self.assertRaises(ComponentMergeValidationError) as raised:
            merge_component_results(
                context,
                [
                    _component_payload("C001", "OPTIMAL", 0, 1.0, [_assignment("T1", "G1", 1)]),
                    _component_payload("C002", "OPTIMAL", 0, 1.0, [_assignment("T1", "G1", 1)]),
                ],
            )

        errors = _errors_by_code(raised.exception.payload["validation"])
        self.assertEqual(errors["duplicate_team_assignment"], ["T1"])
        self.assertEqual(errors["absent_team_assignment"], ["T2"])

    def test_merge_rejects_unknown_assignment(self):
        context = _context(["T1"], [("T1", "G1", 1)])

        with self.assertRaises(ComponentMergeValidationError) as raised:
            merge_component_results(
                context,
                [_component_payload("C001", "OPTIMAL", 0, 1.0, [_assignment("T1", "G9", 7)])],
            )

        errors = _errors_by_code(raised.exception.payload["validation"])
        self.assertEqual(errors["unknown_assignment"], [{"team_id": "T1", "group_id": "G9", "number": 7}])

    def test_merge_writes_validation_when_invalid_but_not_merged_outputs(self):
        context = _context(["T1", "T2"], [("T1", "G1", 1), ("T2", "G2", 1)])

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "merged"
            with self.assertRaises(ComponentMergeValidationError):
                merge_component_results(
                    context,
                    [_component_payload("C001", "OPTIMAL", 0, 1.0, [_assignment("T1", "G1", 1)])],
                    component_ids=["C001", "C002"],
                    output_dir=output_dir,
                )

            validation = _read_json(output_dir / "component_merge_validation.json")
            raw_exists = (output_dir / "merged_raw_result.json").exists()
            solution_exists = (output_dir / "merged_solution.json").exists()

        self.assertEqual(validation["status"], "invalid")
        self.assertIn("missing_component", _errors_by_code(validation))
        self.assertFalse(raw_exists)
        self.assertFalse(solution_exists)


def _context(team_ids, assignment_keys):
    return {
        "teams": [{"team_id": team_id} for team_id in team_ids],
        "candidates": [
            {"team_id": team_id, "group_id": group_id, "number": number}
            for team_id, group_id, number in assignment_keys
        ],
    }


def _component_payload(component_id, status, objective_value, wall_time, assignments):
    raw_result = {
        "artifact_type": "resource_solver_component_raw_result",
        "component_id": component_id,
        "status": status,
        "objective_value": objective_value,
        "wall_time": wall_time,
        "logs": [f"raw {component_id}"],
    }
    solution = {
        "artifact_type": "resource_solver_component_solution_partial",
        "component_id": component_id,
        "status": status,
        "objective_value": objective_value,
        "wall_time": wall_time,
        "assignments": assignments,
        "real_matches": [],
        "resource_usage": [],
        "group_summary": [],
        "entity_excess": {},
        "logs": [f"solution {component_id}"],
    }
    return {
        "artifact_type": "resource_solver_component_solve",
        "component_id": component_id,
        "raw_result": raw_result,
        "solution_partial": solution,
    }


def _write_component(root, component_id, status, objective_value, wall_time, assignments):
    directory = root / component_id / "attempt_001"
    directory.mkdir(parents=True)
    payload = _component_payload(component_id, status, objective_value, wall_time, assignments)
    (directory / "raw_result.json").write_text(json.dumps(payload["raw_result"]), encoding="utf-8")
    (directory / "solution_partial.json").write_text(json.dumps(payload["solution_partial"]), encoding="utf-8")
    return directory


def _assignment(team_id, group_id, number):
    return {"team_id": team_id, "group_id": group_id, "number": number}


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _errors_by_code(validation):
    return {item["code"]: item["items"] for item in validation["errors"]}


if __name__ == "__main__":
    unittest.main()
