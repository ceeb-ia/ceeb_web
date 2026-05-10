import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from calendaritzacions.analysis.run_audit import (
    build_constraints_report,
    build_home_away_resolution_payload,
    build_input_validation_payload,
    build_performance_payload,
    build_run_manifest,
    build_solver_trace,
)


class RunAuditPayloadTests(unittest.TestCase):
    def test_build_run_manifest_returns_json_ready_payload(self):
        payload = build_run_manifest(
            run_id=np.int64(42),
            source=Path("inputs") / "lliga.xlsx",
            started_at=pd.Timestamp("2026-05-05T10:30:00"),
            parameters={
                "segona_fase": np.bool_(True),
                "tolerance": np.float64(2.5),
                "missing": pd.NA,
            },
            inputs=pd.DataFrame(
                [
                    {"equip": "A", "seed": np.int64(1), "note": np.nan},
                    {"equip": "B", "seed": np.int64(2), "note": "ok"},
                ]
            ),
        )

        self.assertEqual(payload["artifact_type"], "run_manifest")
        self.assertEqual(payload["run_id"], 42)
        self.assertEqual(payload["source"], str(Path("inputs") / "lliga.xlsx"))
        self.assertEqual(payload["started_at"], "2026-05-05T10:30:00")
        self.assertIs(payload["parameters"]["segona_fase"], True)
        self.assertIsNone(payload["parameters"]["missing"])
        self.assertEqual(payload["inputs"][0], {"equip": "A", "seed": 1, "note": None})
        json.dumps(payload)

    def test_build_input_validation_payload_tolerates_empty_inputs(self):
        payload = build_input_validation_payload(
            summary=pd.DataFrame(),
            by_category={},
            conflicts=[],
            level_spread=None,
        )

        self.assertEqual(payload["artifact_type"], "input_validation")
        self.assertEqual(payload["summary"], [])
        self.assertEqual(payload["by_category"], {})
        self.assertEqual(payload["conflicts"], [])
        self.assertIsNone(payload["level_spread"])
        json.dumps(payload)

    def test_build_solver_trace_accepts_mapping_and_nested_numpy_values(self):
        payload = build_solver_trace(
            {
                "iterations": pd.DataFrame([{"step": np.int64(1), "cost": np.float32(3.5)}]),
                "choices": pd.Series({"accepted": np.bool_(False), "reason": pd.NA}),
            },
            penalties=np.array([1, 2, 3], dtype=np.int64),
            repairs=("swap", "rebalance"),
        )

        self.assertEqual(payload["artifact_type"], "solver_trace")
        self.assertEqual(payload["iterations"], [{"step": 1, "cost": 3.5}])
        self.assertEqual(payload["choices"], {"accepted": False, "reason": None})
        self.assertEqual(payload["penalties"], [1, 2, 3])
        self.assertEqual(payload["repairs"], ["swap", "rebalance"])
        json.dumps(payload)

    def test_build_home_away_resolution_payload_accepts_tables_and_decisions(self):
        payload = build_home_away_resolution_payload(
            {
                "matches": pd.DataFrame(
                    [
                        {
                            "local": "A",
                            "visitant": "B",
                            "round": np.int64(1),
                            "resolved_at": pd.Timestamp("2026-05-05"),
                        }
                    ]
                )
            },
            decisions={
                "A-B": {
                    "home": "A",
                    "away": "B",
                    "changed": np.bool_(False),
                    "score_delta": np.float64(0.25),
                }
            },
        )

        self.assertEqual(payload["artifact_type"], "home_away_resolution")
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(
            payload["matches"],
            [{"local": "A", "visitant": "B", "round": 1, "resolved_at": "2026-05-05T00:00:00"}],
        )
        self.assertEqual(
            payload["decisions"]["A-B"],
            {"home": "A", "away": "B", "changed": False, "score_delta": 0.25},
        )
        json.dumps(payload)

    def test_build_constraints_report_accepts_dataframes_and_nested_dicts(self):
        payload = build_constraints_report(
            summary=pd.DataFrame(
                [
                    {"constraint": "no_repeat_home", "violations": np.int64(0)},
                    {"constraint": "max_distance", "violations": np.int64(2)},
                ]
            ),
            by_team={
                "A": {"hard": np.int64(0), "soft": np.int64(1), "notes": pd.Series(["ok"])},
                "B": {"hard": np.int64(2), "soft": np.int64(0), "notes": []},
            },
        )

        self.assertEqual(payload["artifact_type"], "constraints_report")
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(
            payload["summary"],
            [
                {"constraint": "no_repeat_home", "violations": 0},
                {"constraint": "max_distance", "violations": 2},
            ],
        )
        self.assertEqual(payload["by_team"]["A"], {"hard": 0, "soft": 1, "notes": {"0": "ok"}})
        json.dumps(payload)

    def test_build_performance_payload_accepts_metrics_and_timings(self):
        payload = build_performance_payload(
            timings=pd.DataFrame(
                [
                    {"phase": "ingestion", "seconds": np.float32(0.5)},
                    {"phase": "solver", "seconds": np.float64(12.75)},
                ]
            ),
            metrics={
                "iterations": np.int64(120),
                "elapsed": pd.Timedelta(seconds=13),
                "memory_mb": np.float64(256.5),
            },
        )

        self.assertEqual(payload["artifact_type"], "performance")
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(
            payload["timings"],
            [{"phase": "ingestion", "seconds": 0.5}, {"phase": "solver", "seconds": 12.75}],
        )
        self.assertEqual(payload["metrics"], {"iterations": 120, "elapsed": "P0DT0H0M13S", "memory_mb": 256.5})
        json.dumps(payload)


if __name__ == "__main__":
    unittest.main()
