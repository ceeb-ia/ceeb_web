import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from calendaritzacions.reporting.resource_solver_decomposition_plots import (
    _limit_interactive_graph,
    write_resource_solver_decomposition_plots,
)


class ResourceSolverDecompositionPlotTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("matplotlib"), "matplotlib not installed")
    def test_decomposition_plots_create_manifest_and_files_for_multiple_components(self):
        summary = {
            "components": [
                {
                    "component_id": "C001",
                    "team_ids": ["T1", "T2", "T3"],
                    "competition_keys": ["Lliga A"],
                    "resource_ids": ["R1", "R2"],
                    "linkage_keys": ["LG1"],
                    "candidate_count": 12,
                },
                {
                    "component_id": "C002",
                    "team_ids": ["T4"],
                    "competition_keys": ["Lliga B"],
                    "resource_ids": ["R3"],
                    "candidate_count": 3,
                },
            ]
        }
        context = SimpleNamespace(
            teams=(
                SimpleNamespace(team_id="T1", league_name="Lliga A", modality="Futbol", category="", subcategory=""),
                SimpleNamespace(team_id="T2", league_name="Lliga A", modality="Futbol", category="", subcategory=""),
                SimpleNamespace(team_id="T3", league_name="Lliga A", modality="Volei", category="", subcategory=""),
                SimpleNamespace(team_id="T4", league_name="Lliga B", modality="Basquet", category="", subcategory=""),
            ),
            candidates=(
                SimpleNamespace(team_id="T1", potential_resources=("R1", "R2")),
                SimpleNamespace(team_id="T2", potential_resources=("R1",)),
                SimpleNamespace(team_id="T3", potential_resources=("R2",)),
                SimpleNamespace(team_id="T4", potential_resources=("R3",)),
            ),
        )

        with tempfile.TemporaryDirectory() as directory:
            plots = write_resource_solver_decomposition_plots(
                Path(directory),
                summary=summary,
                context=context,
                stem="fixture",
            )
            manifest = json.loads(Path(plots["manifest"]).read_text(encoding="utf-8"))

            self.assertEqual(manifest["artifact_type"], "resource_solver_decomposition_plots")
            self.assertIn("component_team_count_histogram", manifest["plots"])
            self.assertIn("top_components_by_teams", manifest["plots"])
            self.assertIn("components_resources_vs_competitions", manifest["plots"])
            self.assertIn("candidate_pareto_by_component", manifest["plots"])
            self.assertIn("top_component_competition_resource_heatmap", manifest["plots"])
            self.assertIn("component_network_C001", manifest["plots"])
            self.assertIn("component_graph_3d", manifest["plots"])
            self.assertIn("component_network_C001", manifest["plot_descriptions"])
            self.assertTrue(manifest["plots"]["component_graph_3d"].endswith(".html"))
            html = Path(manifest["plots"]["component_graph_3d"]).read_text(encoding="utf-8")
            self.assertIn("Math.max(0.8, cameraDistance + z)", html)
            self.assertIn("function graphFrame()", html)
            self.assertIn("(node.x - frame.cx) / frame.radius", html)
            self.assertIn("Arrossega: mou", html)
            self.assertIn("Maj + arrossega: rota", html)
            self.assertIn("panX += (event.clientX - lastX)", html)
            self.assertIn("Math.max(.001, Math.min(12, zoom))", html)
            for plot_id, path in manifest["plots"].items():
                self.assertIn(plot_id, plots)
                self.assertTrue(Path(path).exists(), plot_id)

    @unittest.skipUnless(importlib.util.find_spec("matplotlib"), "matplotlib not installed")
    def test_decomposition_plots_accept_single_component(self):
        summary = {
            "components": [
                {
                    "component_id": "only",
                    "team_count": 4,
                    "competition_count": 1,
                    "resource_count": 2,
                    "linkage_count": 0,
                    "candidate_count": 9,
                }
            ]
        }

        with tempfile.TemporaryDirectory() as directory:
            plots = write_resource_solver_decomposition_plots(Path(directory), summary=summary, stem="single")
            manifest = json.loads(Path(plots["manifest"]).read_text(encoding="utf-8"))

            self.assertIn("candidate_pareto_by_component", plots)
            self.assertEqual(set(manifest["plots"]), set(plots) - {"manifest"})
            for path in plots.values():
                self.assertTrue(Path(path).exists())

    @unittest.skipUnless(importlib.util.find_spec("matplotlib"), "matplotlib not installed")
    def test_decomposition_plots_accept_components_by_size(self):
        summary = {
            "components_by_size": {
                "3": [
                    {
                        "component_id": "C003",
                        "competition_count": 2,
                        "resource_count": 2,
                        "candidate_count": 8,
                    }
                ],
                "1": 2,
            }
        }

        with tempfile.TemporaryDirectory() as directory:
            plots = write_resource_solver_decomposition_plots(Path(directory), summary=summary, stem="by_size")
            manifest = json.loads(Path(plots["manifest"]).read_text(encoding="utf-8"))

            self.assertIn("component_team_count_histogram", plots)
            self.assertIn("top_components_by_teams", plots)
            self.assertIn("components_resources_vs_competitions", plots)
            self.assertEqual(manifest["artifact_type"], "resource_solver_decomposition_plots")

    def test_interactive_graph_limit_keeps_team_sample(self):
        nodes = {}
        edges = []
        for index in range(30):
            nodes[f"competition:C{index}"] = {"kind": "competition", "key": f"C{index}", "label": f"Competition {index}"}
            nodes[f"resource:R{index}"] = {"kind": "resource", "key": f"R{index}", "label": f"Resource {index}"}
            edges.append((f"competition:C{index}", f"resource:R{index}", "resource"))
        for index in range(100):
            nodes[f"team:T{index}"] = {"kind": "team", "key": f"T{index}", "label": f"Team {index}"}
            edges.append((f"team:T{index}", f"competition:C{index % 30}", "competition"))
            edges.append((f"team:T{index}", f"resource:R{index % 30}", "resource"))

        limited, omitted = _limit_interactive_graph({"nodes": nodes, "edges": edges}, 40)

        kinds = [node["kind"] for node in limited["nodes"].values()]
        self.assertEqual(len(limited["nodes"]), 40)
        self.assertGreater(omitted, 0)
        self.assertGreaterEqual(kinds.count("team"), 14)
        self.assertGreater(kinds.count("competition"), 0)
        self.assertGreater(kinds.count("resource"), 0)


if __name__ == "__main__":
    unittest.main()
