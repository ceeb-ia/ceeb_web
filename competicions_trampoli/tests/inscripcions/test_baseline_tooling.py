import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from competicions_trampoli.services.inscripcions.baseline import (
    aggregate_benchmark_results,
    build_scenario_request,
    create_or_replace_benchmark_dataset,
    ensure_benchmark_user,
    get_benchmark_competicio,
    measure_client_request,
)


class InscripcionsBaselineToolingTests(TestCase):
    def test_aggregate_results_summarizes_non_warmup_runs(self):
        summary = aggregate_benchmark_results(
            [
                {
                    "dataset": "small",
                    "scenario": "get_list",
                    "is_warmup": True,
                    "elapsed_ms": 999,
                    "sql_count": 999,
                    "sql_time_ms": 999,
                    "response_bytes": 999,
                    "status_code": 200,
                },
                {
                    "dataset": "small",
                    "scenario": "get_list",
                    "is_warmup": False,
                    "elapsed_ms": 100,
                    "sql_count": 10,
                    "sql_time_ms": 50,
                    "response_bytes": 1000,
                    "status_code": 200,
                },
                {
                    "dataset": "small",
                    "scenario": "get_list",
                    "is_warmup": False,
                    "elapsed_ms": 200,
                    "sql_count": 20,
                    "sql_time_ms": 70,
                    "response_bytes": 1200,
                    "status_code": 200,
                },
            ]
        )

        self.assertEqual(len(summary), 1)
        row = summary[0]
        self.assertEqual(row["dataset"], "small")
        self.assertEqual(row["scenario"], "get_list")
        self.assertEqual(row["runs"], 2)
        self.assertEqual(row["elapsed_ms_mean"], 150.0)
        self.assertEqual(row["sql_count_mean"], 15.0)
        self.assertEqual(row["status_codes"], [200])

    def test_measure_client_request_returns_expected_shape(self):
        competicio = create_or_replace_benchmark_dataset("small", replace=True)
        user = ensure_benchmark_user()
        client = self.client_class()
        client.force_login(user)

        request_spec = build_scenario_request(competicio, "filter_values")
        result = measure_client_request(client, request_spec)

        self.assertEqual(result["status_code"], 200)
        self.assertIn("elapsed_ms", result)
        self.assertIn("sql_count", result)
        self.assertIn("sql_time_ms", result)
        self.assertIn("response_bytes", result)
        self.assertGreaterEqual(result["response_bytes"], 1)

    def test_generate_benchmark_data_command_creates_canonical_dataset(self):
        call_command("generate_inscripcions_benchmark_data", "--dataset", "small", "--replace")

        competicio = get_benchmark_competicio("small")
        self.assertIsNotNone(competicio)
        self.assertEqual(competicio.inscripcions.count(), 40)
        self.assertEqual(competicio.equip_contexts.count(), 1)
        self.assertGreaterEqual(competicio.equips.count(), 1)
        self.assertGreaterEqual(competicio.grups_competicio.count(), 1)

    def test_benchmark_command_generates_json_artifact(self):
        call_command("generate_inscripcions_benchmark_data", "--dataset", "small", "--replace")

        with tempfile.TemporaryDirectory() as tmpdir:
            call_command(
                "benchmark_inscripcions",
                "--dataset",
                "small",
                "--scenario",
                "get_list",
                "--warmup",
                "0",
                "--repeats",
                "1",
                "--output-dir",
                tmpdir,
                "--format",
                "json",
            )

            output_files = list(Path(tmpdir).glob("*.json"))
            self.assertEqual(len(output_files), 1)
            payload = json.loads(output_files[0].read_text(encoding="utf-8"))
            self.assertIn("metadata", payload)
            self.assertIn("results", payload)
            self.assertIn("summary", payload)
            self.assertEqual(payload["metadata"]["datasets"], ["small"])
            self.assertEqual(payload["metadata"]["scenarios"], ["get_list"])
            self.assertEqual(len(payload["results"]), 1)
            self.assertEqual(payload["results"][0]["dataset"], "small")
            self.assertEqual(payload["results"][0]["scenario"], "get_list")
