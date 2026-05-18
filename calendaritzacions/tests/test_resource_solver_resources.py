import importlib.util
import unittest

from calendaritzacions.engine.variants.resource_solver.capacities import (
    build_resource_pressure,
    estimate_capacities,
    estimate_capacity_from_demand,
)
from calendaritzacions.engine.config import EngineConfig
from calendaritzacions.engine.variants.resource_solver.config import ResourceSolverConfig, coerce_resource_solver_config
from calendaritzacions.engine.variants.resource_solver.resources import (
    build_base_resources,
    normalize_hour_slot,
)
from calendaritzacions.engine.variants.resource_solver.types import TeamRecord

HAS_PANDAS = importlib.util.find_spec("pandas") is not None

if HAS_PANDAS:
    import pandas as pd
    from calendaritzacions.engine.variants.resource_solver.input_adapter import (
        build_context_from_dataframe,
        build_team_records,
    )


class ResourceSolverResourcesTests(unittest.TestCase):
    def test_normalizes_times_to_hourly_slots(self):
        self.assertEqual(normalize_hour_slot("18:00"), "18:00")
        self.assertEqual(normalize_hour_slot("18:15"), "18:00")
        self.assertEqual(normalize_hour_slot("18:30"), "18:00")
        self.assertEqual(normalize_hour_slot("18:45"), "18:00")
        self.assertEqual(normalize_hour_slot("19:00"), "19:00")
        self.assertEqual(normalize_hour_slot("19:30"), "19:00")
        self.assertEqual(normalize_hour_slot(0.75), "18:00")

    def test_resource_solver_config_includes_linkage_defaults(self):
        config = ResourceSolverConfig()

        self.assertEqual(config.linkage_mode, "off")
        self.assertEqual(config.linkage_violation_weight, 100_000)
        self.assertEqual(config.linkage_max_group_size, 2)

    def test_linkage_variant_uses_input_linkage_mode(self):
        config = coerce_resource_solver_config(EngineConfig(name="resource_solver_linkage"))
        catalan_config = coerce_resource_solver_config(EngineConfig(name="resource_solver_vinculacio"))
        explicit_config = coerce_resource_solver_config(
            EngineConfig(
                name="resource_solver",
                resource_solver_linkage_mode="simulated",
                resource_solver_decomposition_mode="persist_components",
            )
        )

        self.assertEqual(config.linkage_mode, "input")
        self.assertEqual(catalan_config.linkage_mode, "input")
        self.assertEqual(explicit_config.linkage_mode, "simulated")
        self.assertEqual(explicit_config.decomposition_mode, "persist_components")

    @unittest.skipUnless(HAS_PANDAS, "pandas not installed")
    def test_build_team_records_normalizes_resources_and_deduplicates_teams(self):
        df = pd.DataFrame(
            [
                {
                    "Id": "A",
                    "Nom": " Equip A ",
                    "Entitat": " Club ",
                    "Nom Lliga": "Lliga",
                    "Pista joc": " Pavello 1 ",
                    "Dia partit": "divendres",
                    "Horari partit": "18:30",
                    "N\u00fam. sorteig": "CASA",
                },
                {
                    "Id": "A",
                    "Nom": "Equip A duplicat",
                    "Entitat": "Club",
                    "Nom Lliga": "Lliga",
                    "Pista joc": "Pavello 2",
                    "Dia partit": "Dissabte",
                    "Horari partit": "20:00",
                    "N\u00fam. sorteig": 6,
                },
                {
                    "Id": "B",
                    "Nom": "Equip B",
                    "Entitat": "Club",
                    "Nom Lliga": "Lliga",
                    "Pista joc": "",
                    "Dia partit": None,
                    "Horari partit": "",
                },
            ]
        )

        teams = build_team_records(df)

        self.assertEqual([team.team_id for team in teams], ["A", "B"])
        self.assertEqual(teams[0].name, "Equip A")
        self.assertEqual(teams[0].venue, "Pavello 1")
        self.assertEqual(teams[0].day, "Divendres")
        self.assertEqual(teams[0].time, "18:00")
        self.assertEqual(teams[0].seed_request_original, "CASA")
        self.assertEqual(teams[1].venue, "(sense pista)")
        self.assertEqual(teams[1].day, "(sense dia)")
        self.assertEqual(teams[1].time, "(sense hora)")

    @unittest.skipUnless(HAS_PANDAS, "pandas not installed")
    def test_build_team_records_reads_linkage_group_and_side_request(self):
        row = _team_row(0, "Futbol", "Benjami", "Mixt", "Lliga")
        row["Grup vinculaci\u00f3"] = " V1 "
        row["Peticio"] = "fora"

        teams = build_team_records(pd.DataFrame([row]))

        self.assertEqual(getattr(teams[0], "linkage_group"), "v1")
        self.assertEqual(getattr(teams[0], "linkage_side"), "fora")
        self.assertEqual(getattr(teams[0], "linkage_source"), "input")

    @unittest.skipUnless(HAS_PANDAS, "pandas not installed")
    def test_context_applies_linkage_modes(self):
        rows = []
        for index in range(4):
            row = _team_row(index, "Futbol", "Benjami", "Mixt", "Lliga")
            row["Grup vinculacio"] = "INPUT-A" if index < 2 else "INPUT-B"
            row["Peticio"] = "Casa" if index % 2 == 0 else "Fora"
            rows.append(row)

        input_context = build_context_from_dataframe(
            pd.DataFrame(rows),
            ResourceSolverConfig(linkage_mode="input"),
        )
        off_context = build_context_from_dataframe(
            pd.DataFrame(rows),
            ResourceSolverConfig(linkage_mode="off"),
        )
        simulated_context = build_context_from_dataframe(
            pd.DataFrame(rows),
            ResourceSolverConfig(linkage_mode="simulated", linkage_max_group_size=2),
        )

        self.assertEqual(
            [getattr(team, "linkage_group") for team in input_context.teams],
            ["input-a", "input-a", "input-b", "input-b"],
        )
        self.assertEqual(
            [getattr(team, "linkage_side") for team in input_context.teams],
            ["casa", "fora", "casa", "fora"],
        )
        self.assertEqual(
            [getattr(team, "linkage_group") for team in off_context.teams],
            ["", "", "", ""],
        )
        self.assertEqual(
            [getattr(team, "linkage_side") for team in off_context.teams],
            ["", "", "", ""],
        )
        self.assertEqual([getattr(team, "linkage_group") for team in simulated_context.teams], ["", "", "", ""])

        simulated_rows = [
            _team_row(index, "Futbol", "Benjami", "Mixt", "Lliga")
            for index in range(5)
        ]
        simulated_context = build_context_from_dataframe(
            pd.DataFrame(simulated_rows),
            ResourceSolverConfig(linkage_mode="simulated", linkage_max_group_size=2),
        )
        linked = [team for team in simulated_context.teams if getattr(team, "linkage_group")]

        self.assertEqual(len(linked), 2)
        self.assertEqual({team.linkage_group for team in linked}, {"link-pavello-divendres-001"})
        self.assertEqual([team.linkage_side for team in linked], ["casa", "casa"])

    @unittest.skipUnless(HAS_PANDAS, "pandas not installed")
    def test_context_builds_groups_per_modality_category_subcategory(self):
        rows = []
        for index in range(4):
            rows.append(_team_row(index, "Futbol", "Benjami", "Mixt", "Lliga compartida"))
        for index in range(4, 21):
            rows.append(_team_row(index, "Futbol", "Alevi", "Mixt", "Lliga compartida"))

        context = build_context_from_dataframe(pd.DataFrame(rows), ResourceSolverConfig(linkage_mode="off"))
        groups_by_team = _candidate_groups_by_team(context)

        small_groups = groups_by_team["T0"]
        large_groups = groups_by_team["T4"]
        self.assertEqual(len(small_groups), 1)
        self.assertEqual(len(large_groups), 3)
        self.assertTrue(small_groups.isdisjoint(large_groups))

    @unittest.skipUnless(HAS_PANDAS, "pandas not installed")
    def test_context_falls_back_to_league_when_competition_fields_are_incomplete(self):
        rows = [
            _team_row(index, "Futbol", "Benjami", "", "Lliga fallback")
            for index in range(9)
        ]

        context = build_context_from_dataframe(pd.DataFrame(rows), ResourceSolverConfig(linkage_mode="off"))
        groups_by_team = _candidate_groups_by_team(context)

        self.assertEqual(len(groups_by_team["T0"]), 2)

    def test_estimates_capacity_and_builds_pressure_from_unique_teams(self):
        teams = tuple(
            TeamRecord(
                team_id=f"T{index}",
                name=f"Team {index}",
                entity="Club",
                league_name="Lliga",
                venue="P1",
                day="Divendres",
                time="18:00",
            )
            for index in range(6)
        )
        resources = build_base_resources(teams)
        capacities = estimate_capacities(resources, teams, ResourceSolverConfig())
        pressure = build_resource_pressure(resources, teams, capacities)

        self.assertEqual(estimate_capacity_from_demand(1), 1)
        self.assertEqual(estimate_capacity_from_demand(2), 1)
        self.assertEqual(estimate_capacity_from_demand(3), 2)
        self.assertEqual(estimate_capacity_from_demand(4), 2)
        self.assertEqual(estimate_capacity_from_demand(5), 3)
        self.assertEqual(estimate_capacity_from_demand(6), 3)
        self.assertEqual(estimate_capacity_from_demand(7), 4)
        self.assertEqual(estimate_capacity_from_demand(8), 4)
        self.assertEqual(len(resources), 1)
        resource_id = next(iter(resources))
        self.assertEqual(capacities[resource_id].demand_count, 6)
        self.assertEqual(capacities[resource_id].capacity, 3)
        self.assertEqual(capacities[resource_id].method, "ceil_half_min_one")
        self.assertEqual(pressure[0].demand_count, 6)
        self.assertEqual(pressure[0].estimated_capacity, 3)
        self.assertEqual(pressure[0].pressure, 2.0)
        self.assertTrue(pressure[0].is_critical)
        self.assertEqual(pressure[0].team_ids, ("T0", "T1", "T2", "T3", "T4", "T5"))

def _team_row(index, modality, category, subcategory, league_name):
    return {
        "Id": f"T{index}",
        "Nom": f"Equip {index}",
        "Entitat": f"Club {index}",
        "Nom Lliga": league_name,
        "Modalitat": modality,
        "Categoria": category,
        "Subcategoria": subcategory,
        "Nivell": "Nivell A",
        "Dia partit": "Divendres",
        "Horari partit": "18:00",
        "Pista joc": "Pavello",
    }


def _candidate_groups_by_team(context):
    groups_by_team = {team.team_id: set() for team in context.teams}
    for candidate in context.candidates:
        groups_by_team[candidate.team_id].add(candidate.group_id)
    return groups_by_team


if __name__ == "__main__":
    unittest.main()
