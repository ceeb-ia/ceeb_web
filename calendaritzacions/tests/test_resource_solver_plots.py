import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from calendaritzacions.domain.phases import PRIMERA_FASE
from calendaritzacions.engine.variants.resource_solver.types import (
    Assignment,
    ResourceSolverResult,
    SolverContext,
    TeamRecord,
)
from calendaritzacions.reporting.resource_solver_plots import write_resource_solver_final_plots


class ResourceSolverPlotTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("matplotlib"), "matplotlib not installed")
    def test_final_plots_include_level_dispersion_manifest_id(self):
        context = SolverContext(
            teams=(
                TeamRecord(team_id="T1", name="Team 1", entity="Club", league_name="Lliga", modality="Futbol", level="A"),
                TeamRecord(team_id="T2", name="Team 2", entity="Club", league_name="Lliga", modality="Futbol", level="C"),
                TeamRecord(team_id="T3", name="Team 3", entity="Club", league_name="Lliga", modality="Volei", level="E"),
                TeamRecord(team_id="T4", name="Team 4", entity="Club", league_name="Lliga", modality="Volei", level=""),
            ),
            phase=PRIMERA_FASE,
            phase_name="primera_fase",
            base_resources={},
            capacities={},
            pressure=(),
            groups=(),
            candidates=(),
            config=SimpleNamespace(),
        )
        result = ResourceSolverResult(
            status="FEASIBLE",
            objective_value=None,
            best_bound=None,
            wall_time=0.0,
            assignments=(
                Assignment(team_id="T1", group_id="Lliga_G1", number=1),
                Assignment(team_id="T2", group_id="Lliga_G1", number=2),
                Assignment(team_id="T3", group_id="Lliga_G2", number=1),
                Assignment(team_id="T4", group_id="Lliga_G2", number=2),
            ),
            real_matches=(),
            resource_usage=(),
            group_summary=(),
            entity_excess={},
        )

        with tempfile.TemporaryDirectory() as directory:
            plots = write_resource_solver_final_plots(Path(directory), result=result, context=context, stem="fixture")
            manifest = json.loads(Path(plots["manifest"]).read_text(encoding="utf-8"))

            self.assertIn("level_dispersion_by_modality", plots)
            self.assertTrue(Path(plots["level_dispersion_by_modality"]).exists())
            self.assertIn("level_dispersion_by_modality", manifest["plots"])


if __name__ == "__main__":
    unittest.main()
