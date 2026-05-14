import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from calendaritzacions.domain.phases import PRIMERA_FASE
from calendaritzacions.engine.variants.resource_solver.component_persistence import (
    persist_component_subcontexts,
)
from calendaritzacions.engine.variants.resource_solver.config import ResourceSolverConfig
from calendaritzacions.engine.variants.resource_solver.decomposition import (
    DependencyComponent,
    build_decomposition_summary,
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


HAS_DJANGO = importlib.util.find_spec("django") is not None


def configure_django():
    from django.apps import apps
    from django.conf import settings

    if not settings.configured:
        settings.configure(
            INSTALLED_APPS=["django.contrib.contenttypes", "calendaritzacions.django"],
            DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
            SECRET_KEY="tests",
            DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
            USE_TZ=True,
        )
    if not apps.ready:
        import django

        django.setup()


def ensure_test_tables():
    from django.db import connection

    from calendaritzacions.django.models import CalendarizationComponentRun, CalendarizationRun

    existing = set(connection.introspection.table_names())
    with connection.schema_editor() as schema_editor:
        if CalendarizationRun._meta.db_table not in existing:
            schema_editor.create_model(CalendarizationRun)
            existing.add(CalendarizationRun._meta.db_table)
        if CalendarizationComponentRun._meta.db_table not in existing:
            schema_editor.create_model(CalendarizationComponentRun)
            existing.add(CalendarizationComponentRun._meta.db_table)


def make_team(team_id, *, venue=None, day=None, time=None):
    return TeamRecord(
        team_id=team_id,
        name=f"Team {team_id}",
        entity=f"Club {team_id}",
        league_name=f"League {team_id}",
        modality=f"Mod {team_id}",
        category=f"Cat {team_id}",
        subcategory=f"Sub {team_id}",
        venue=venue or f"Pista {team_id}",
        day=day or f"Dia {team_id}",
        time=time or "18:00",
    )


def make_context(teams, groups_by_team, *, decomposition_mode="audit_only"):
    group_ids = sorted({group_id for values in groups_by_team.values() for group_id in values})
    groups = tuple(GroupSpec(group_id, 2, 8, 4, "primera_fase") for group_id in group_ids)
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
            team_ids=tuple(team.team_id for team in teams if build_base_resources([team]).get(resource_id)),
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
        config=ResourceSolverConfig(decomposition_mode=decomposition_mode),
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


@unittest.skipUnless(HAS_DJANGO, "django not installed")
class ResourceSolverComponentPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        configure_django()
        ensure_test_tables()

    def setUp(self):
        self.created_run_ids = []

    def tearDown(self):
        from django.db import connection

        from calendaritzacions.django.models import CalendarizationComponentRun, CalendarizationRun

        if not self.created_run_ids:
            return
        placeholders = ", ".join(["%s"] * len(self.created_run_ids))
        with connection.cursor() as cursor:
            cursor.execute(
                f"DELETE FROM {CalendarizationComponentRun._meta.db_table} WHERE run_id IN ({placeholders})",
                self.created_run_ids,
            )
            cursor.execute(
                f"DELETE FROM {CalendarizationRun._meta.db_table} WHERE id IN ({placeholders})",
                self.created_run_ids,
            )

    def create_run(self):
        from calendaritzacions.django.models import CalendarizationRun

        run = CalendarizationRun.objects.create(input_file="inputs/a.xlsx")
        self.created_run_ids.append(run.pk)
        return run

    def test_persist_component_subcontexts_writes_manifest_contexts_and_db_rows(self):
        from calendaritzacions.django.models import CalendarizationComponentRun
        from calendaritzacions.engine.variants.resource_solver.component_solver import (
            load_component_context_payload,
        )

        run = self.create_run()
        context = make_context(
            [make_team("T1"), make_team("T2")],
            {"T1": ("G1",), "T2": ("G2",)},
        )

        with tempfile.TemporaryDirectory() as directory:
            result = persist_component_subcontexts(
                run=run,
                output_dir=directory,
                context=context,
                summary=build_decomposition_summary(context),
            )

            manifest_path = Path(result["manifest_path"])
            split_path = Path(result["split_validation_path"])
            self.assertEqual(result["status"], "valid")
            self.assertTrue(manifest_path.exists())
            self.assertTrue(split_path.exists())

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["artifact_type"], "resource_solver_component_manifest")
            self.assertEqual(manifest["run_id"], run.pk)
            self.assertEqual(len(manifest["components"]), 2)
            self.assertEqual(CalendarizationComponentRun.objects.filter(run=run).count(), 2)

            first = manifest["components"][0]
            context_path = Path(directory) / first["context_path"]
            payload = json.loads(context_path.read_text(encoding="utf-8"))
            loaded_context = load_component_context_payload(payload)
            self.assertEqual(payload["artifact_type"], "resource_solver_component_context")
            self.assertEqual(len(loaded_context.teams), first["team_count"])

            component_run = CalendarizationComponentRun.objects.get(
                run=run,
                component_id=first["component_id"],
            )
            self.assertEqual(component_run.status, CalendarizationComponentRun.STATUS_PENDING)
            self.assertEqual(component_run.context_path, str(context_path))
            self.assertTrue(Path(component_run.validation_path).exists())

    def test_invalid_split_writes_validation_and_manifest_without_component_rows(self):
        from calendaritzacions.django.models import CalendarizationComponentRun

        run = self.create_run()
        context = make_context(
            [
                make_team("T1", venue="Pavello", day="Dilluns", time="18:00"),
                make_team("T2", venue="Pavello", day="Dilluns", time="18:00"),
            ],
            {"T1": ("G1",), "T2": ("G2",)},
        )

        with tempfile.TemporaryDirectory() as directory:
            result = persist_component_subcontexts(
                run=run,
                output_dir=directory,
                context=context,
                summary=[component("C001", ("T1",)), component("C002", ("T2",))],
            )

            split = json.loads(Path(result["split_validation_path"]).read_text(encoding="utf-8"))
            manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "invalid")
            self.assertEqual(split["status"], "invalid")
            self.assertEqual(manifest["split_validation"]["status"], "invalid")
            self.assertEqual(manifest["components"], [])
            self.assertEqual(CalendarizationComponentRun.objects.filter(run=run).count(), 0)

    def test_service_persist_components_returns_before_global_model(self):
        from calendaritzacions.engine.variants.resource_solver.service import ResourceSolverEngine

        run = self.create_run()
        context = make_context(
            [make_team("T1"), make_team("T2")],
            {"T1": ("G1",), "T2": ("G2",)},
            decomposition_mode="persist_components",
        )
        progress = SimpleNamespace(
            run=run,
            report=lambda _message, _percent=None: None,
            report_artifact=lambda _name, _path: None,
        )

        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "calendaritzacions.engine.variants.resource_solver.input_adapter.build_context_from_dataframe",
                return_value=context,
            ):
                raw_result, returned_context, built_model, audit_paths = ResourceSolverEngine()._run_optional_model_pipeline(
                    input_path=str(Path(directory) / "input.xlsx"),
                    input_df=SimpleNamespace(),
                    config=ResourceSolverConfig(decomposition_mode="persist_components"),
                    progress=progress,
                    logs=[],
                    output_dir=Path(directory),
                )

            self.assertIs(returned_context, context)
            self.assertIsNone(built_model)
            self.assertTrue(raw_result.componentized_without_global_solve)
            self.assertEqual(raw_result.status, "COMPONENTS_PERSISTED")
            self.assertIn("component_manifest", audit_paths)
            self.assertTrue(Path(audit_paths["component_manifest"]).exists())


if __name__ == "__main__":
    unittest.main()
