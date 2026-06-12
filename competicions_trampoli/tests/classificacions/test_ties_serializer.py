from django.test import SimpleTestCase

from ...services.classificacions.ties.context import (
    TIE_CONTRACT_DERIVED_TEAM,
    TIE_CONTRACT_NATIVE_TEAM,
    resolve_tie_context,
)
from ...services.classificacions.ties.pipeline_builder import (
    TIE_INPUT_SOURCE_MAIN_SELECTED_CONTRIBUTORS,
    TIE_INPUT_SOURCE_RAW_EXERCISES,
)
from ...services.classificacions.ties.builder_rehydration import project_tie_for_builder_rehydration
from ...services.classificacions.ties.legacy_projection import project_tie_legacy_projection
from ...services.classificacions.ties.registry import resolve_tie_contract
from ...services.classificacions.ties.serializer_save import serialize_tie_for_save
from ...services.classificacions.ties.validation import materialize_desempat_for_validation
from ...services.classificacions.ties.ui_projection import project_tie_ui_state


class TieSerializerSaveTests(SimpleTestCase):
    def _tie_with_pipeline(self, pipeline, *, tie_id="tie_contract"):
        return {
            "id": tie_id,
            "nom": "Desempat contracte",
            "ordre": "desc",
            "pipeline_version": 1,
            "pipeline": pipeline,
        }

    def _base_pipeline(self, *, app_id=161, exercise_selection_scope="per_member"):
        return {
            "aparells": {"mode": "seleccionar", "ids": [app_id]},
            "camps_per_aparell": {str(app_id): ["TOTAL"]},
            "agregacio_camps_per_aparell": {str(app_id): "sum"},
            "agregacio_camps": "sum",
            "exercicis": {"mode": "tots"},
            "exercise_selection_scope": exercise_selection_scope,
            "mode_seleccio_exercicis": "per_aparell_override",
            "exercicis_per_aparell": {str(app_id): {"mode": "millor_1"}},
            "agregacio_exercicis_per_aparell": {str(app_id): "sum"},
            "agregacio_exercicis": "sum",
            "agregacio_aparells": "sum",
            "mode_resultat_aparells": "score",
            "ordre": "desc",
        }

    def test_resolve_tie_context_detects_derived_team_contract(self):
        tie = {
            "pipeline": {
                "exercise_selection_scope": "team_pool",
            }
        }

        context = resolve_tie_context(tie, tipus="equips", team_mode="derived_from_individual")

        self.assertEqual(context.contract_name, TIE_CONTRACT_DERIVED_TEAM)
        self.assertEqual(resolve_tie_contract(context).name, TIE_CONTRACT_DERIVED_TEAM)
        self.assertTrue(context.is_team)
        self.assertTrue(context.is_derived_team)
        self.assertFalse(context.is_native_team)
        self.assertTrue(context.is_team_pool_scope)
        self.assertEqual(context.input_source_mode, TIE_INPUT_SOURCE_RAW_EXERCISES)

    def test_resolve_tie_context_detects_native_team_contract(self):
        tie = {
            "pipeline": {
                "exercise_selection_scope": "per_member",
            }
        }

        context = resolve_tie_context(tie, tipus="equips", team_mode="native_team")

        self.assertEqual(context.contract_name, TIE_CONTRACT_NATIVE_TEAM)
        self.assertEqual(resolve_tie_contract(context).name, TIE_CONTRACT_NATIVE_TEAM)
        self.assertTrue(context.is_native_team)
        self.assertFalse(context.is_derived_team)
        self.assertFalse(context.is_team_pool_scope)
        self.assertEqual(context.input_source_mode, TIE_INPUT_SOURCE_RAW_EXERCISES)

    def test_resolve_tie_context_reads_input_source_mode_from_pipeline(self):
        tie = {
            "pipeline": {
                "exercise_selection_scope": "per_member",
                "input_source": {"mode": "main_selected_contributors"},
            }
        }

        context = resolve_tie_context(tie, tipus="equips", team_mode="derived_from_individual")

        self.assertEqual(context.input_source_mode, TIE_INPUT_SOURCE_MAIN_SELECTED_CONTRIBUTORS)

    def test_derived_team_serializer_keeps_team_pool_exercise_fields(self):
        raw_tie = {
            "id": "tie_395a11fbe48cb8",
            "nom": "Desempat 1",
            "ordre": "desc",
            "pipeline_version": 1,
            "pipeline": {
                "aparells": {"mode": "seleccionar", "ids": [161]},
                "camps_per_aparell": {"161": ["TOTAL"]},
                "agregacio_camps_per_aparell": {"161": "sum"},
                "agregacio_camps": "sum",
                "exercicis": {"mode": "tots"},
                "exercise_selection_scope": "team_pool",
                "mode_seleccio_exercicis": "per_aparell_override",
                "exercicis_per_aparell": {"161": {"mode": "millor_1"}},
                "agregacio_exercicis_per_aparell": {"161": "sum"},
                "agregacio_exercicis": "sum",
                "participants": {"mode": "tots"},
                "agregacio_participants": "sum",
                "ordre": "desc",
            },
        }

        serialized = serialize_tie_for_save(
            raw_tie,
            tipus="equips",
            team_mode="derived_from_individual",
        )

        pipeline = serialized["pipeline"]
        self.assertEqual(serialized["id"], "tie_395a11fbe48cb8")
        self.assertEqual(serialized["nom"], "Desempat 1")
        self.assertEqual(serialized["ordre"], "desc")
        self.assertEqual(serialized["pipeline_version"], 1)
        self.assertEqual(pipeline["exercise_selection_scope"], "team_pool")
        self.assertEqual(pipeline["exercicis"], {"mode": "tots"})
        self.assertEqual(pipeline["mode_seleccio_exercicis"], "per_aparell_override")
        self.assertEqual(pipeline["exercicis_per_aparell"], {"161": {"mode": "millor_1"}})
        self.assertEqual(pipeline["agregacio_exercicis_per_aparell"], {"161": "sum"})
        self.assertEqual(pipeline["agregacio_exercicis"], "sum")
        self.assertNotIn("participants", pipeline)
        self.assertNotIn("agregacio_participants", pipeline)

    def test_native_team_serializer_strips_participant_fields_but_keeps_scope(self):
        raw_tie = {
            "id": "tie_native_team",
            "nom": "Desempat equip natiu",
            "ordre": "asc",
            "pipeline": {
                "aparells": {"mode": "seleccionar", "ids": [211]},
                "camps_per_aparell": {"211": ["TOTAL"]},
                "agregacio_camps_per_aparell": {"211": "sum"},
                "agregacio_camps": "sum",
                "exercicis": {"mode": "index", "index": 2},
                "exercise_selection_scope": "per_member",
                "mode_seleccio_exercicis": "per_aparell_override",
                "exercicis_per_aparell": {"211": {"mode": "millor_1"}},
                "agregacio_exercicis_per_aparell": {"211": "sum"},
                "agregacio_exercicis": "sum",
                "participants": {"mode": "tots"},
                "agregacio_participants": "sum",
                "ordre": "asc",
            },
        }

        serialized = serialize_tie_for_save(
            raw_tie,
            tipus="equips",
            team_mode="native_team",
        )

        pipeline = serialized["pipeline"]
        self.assertEqual(serialized["id"], "tie_native_team")
        self.assertEqual(serialized["nom"], "Desempat equip natiu")
        self.assertEqual(serialized["ordre"], "asc")
        self.assertEqual(serialized["pipeline_version"], 1)
        self.assertNotIn("exercise_selection_scope", pipeline)
        self.assertEqual(pipeline["exercicis"], {"mode": "index", "index": 2})
        self.assertEqual(pipeline["mode_seleccio_exercicis"], "per_aparell_override")
        self.assertNotIn("participants", pipeline)
        self.assertNotIn("agregacio_participants", pipeline)

    def test_per_member_serializer_keeps_exercise_configuration(self):
        raw_tie = {
            "id": "tie_keep",
            "nom": "Desempat 2",
            "ordre": "asc",
            "pipeline": {
                "aparells": {"mode": "seleccionar", "ids": [161]},
                "camps_per_aparell": {"161": ["TOTAL"]},
                "agregacio_camps_per_aparell": {"161": "sum"},
                "agregacio_camps": "sum",
                "exercicis": {"mode": "index", "index": 2},
                "exercise_selection_scope": "per_member",
                "mode_seleccio_exercicis": "per_aparell_override",
                "exercicis_per_aparell": {"161": {"mode": "millor_1"}},
                "agregacio_exercicis_per_aparell": {"161": "sum"},
                "agregacio_exercicis": "sum",
                "ordre": "asc",
            },
        }

        serialized = serialize_tie_for_save(
            raw_tie,
            tipus="equips",
            team_mode="derived_from_individual",
        )

        pipeline = serialized["pipeline"]
        self.assertEqual(serialized["id"], "tie_keep")
        self.assertEqual(serialized["nom"], "Desempat 2")
        self.assertEqual(serialized["ordre"], "asc")
        self.assertEqual(serialized["pipeline_version"], 1)
        self.assertEqual(pipeline["exercise_selection_scope"], "per_member")
        self.assertEqual(pipeline["input_source"], {"mode": TIE_INPUT_SOURCE_RAW_EXERCISES})
        self.assertEqual(pipeline["exercicis"], {"mode": "index", "index": 2})
        self.assertEqual(pipeline["mode_seleccio_exercicis"], "per_aparell_override")
        self.assertEqual(pipeline["exercicis_per_aparell"], {"161": {"mode": "millor_1"}})
        self.assertEqual(pipeline["agregacio_exercicis_per_aparell"], {"161": "sum"})

    def test_per_member_serializer_keeps_participants_and_drops_stale_team_pool_maps(self):
        pipeline = self._base_pipeline(exercise_selection_scope="per_member")
        pipeline["participants"] = {"mode": "millor_n", "n": 2}
        pipeline["agregacio_participants"] = "avg"
        pipeline["team_pool_mode_per_aparell"] = {"161": "per_exercici"}
        pipeline["team_pool_participants_per_exercici_per_aparell"] = {
            "161": {"1": {"mode": "millor_1"}}
        }

        serialized = serialize_tie_for_save(
            self._tie_with_pipeline(pipeline),
            tipus="equips",
            team_mode="derived_from_individual",
        )

        saved = serialized["pipeline"]
        self.assertEqual(saved["exercise_selection_scope"], "per_member")
        self.assertEqual(saved["participants"], {"mode": "millor_n", "n": 2})
        self.assertEqual(saved["agregacio_participants"], "avg")
        self.assertNotIn("team_pool_mode_per_aparell", saved)
        self.assertNotIn("team_pool_participants_per_exercici_per_aparell", saved)

    def test_team_pool_flat_serializer_keeps_exercises_and_drops_global_participants(self):
        pipeline = self._base_pipeline(exercise_selection_scope="team_pool")
        pipeline["participants"] = {"mode": "millor_1"}
        pipeline["agregacio_participants"] = "max"
        pipeline["team_pool_mode_per_aparell"] = {"161": "flat"}
        pipeline["team_pool_participants_per_exercici_per_aparell"] = {
            "161": {"1": {"mode": "pitjor_1"}}
        }

        serialized = serialize_tie_for_save(
            self._tie_with_pipeline(pipeline),
            tipus="equips",
            team_mode="derived_from_individual",
        )

        saved = serialized["pipeline"]
        self.assertEqual(saved["exercise_selection_scope"], "team_pool")
        self.assertEqual(saved["team_pool_mode_per_aparell"], {"161": "flat"})
        self.assertEqual(saved["exercicis_per_aparell"], {"161": {"mode": "millor_1"}})
        self.assertNotIn("participants", saved)
        self.assertNotIn("agregacio_participants", saved)
        self.assertNotIn("team_pool_participants_per_exercici_per_aparell", saved)

    def test_team_pool_per_exercici_serializer_keeps_per_exercise_buckets(self):
        pipeline = self._base_pipeline(exercise_selection_scope="team_pool")
        pipeline["team_pool_mode_per_aparell"] = {"161": "per_exercici"}
        pipeline["team_pool_participants_per_exercici_per_aparell"] = {
            "161": {
                "1": {"mode": "millor_n", "n": 2},
                "2": {"mode": "millor_1"},
            }
        }
        pipeline["team_pool_agregacio_participants_per_exercici_per_aparell"] = {
            "161": {"1": "sum", "2": "avg"}
        }

        serialized = serialize_tie_for_save(
            self._tie_with_pipeline(pipeline),
            tipus="equips",
            team_mode="derived_from_individual",
        )

        saved = serialized["pipeline"]
        self.assertEqual(saved["team_pool_mode_per_aparell"], {"161": "per_exercici"})
        self.assertEqual(
            saved["team_pool_participants_per_exercici_per_aparell"],
            {
                "161": {
                    "1": {"mode": "millor_n", "n": 2},
                    "2": {"mode": "millor_1"},
                }
            },
        )
        self.assertEqual(
            saved["team_pool_agregacio_participants_per_exercici_per_aparell"],
            {"161": {"1": "sum", "2": "avg"}},
        )

    def test_serializer_keeps_per_exercise_fields_only_for_active_field_mode(self):
        pipeline = self._base_pipeline(app_id=161, exercise_selection_scope="per_member")
        pipeline["aparells"]["ids"] = [161, 162]
        pipeline["camps_per_aparell"]["162"] = ["TOTAL"]
        pipeline["agregacio_camps_per_aparell"]["162"] = "sum"
        pipeline["camps_mode_per_aparell"] = {"161": "per_exercici", "162": "comu"}
        pipeline["camps_per_exercici_per_aparell"] = {
            "161": {"1": ["E"], "2": ["D"]},
            "162": {"1": ["STALE"]},
        }
        pipeline["agregacio_camps_per_exercici_per_aparell"] = {
            "161": {"1": "sum", "2": "max"},
            "162": {"1": "min"},
        }

        serialized = serialize_tie_for_save(
            self._tie_with_pipeline(pipeline),
            tipus="equips",
            team_mode="derived_from_individual",
        )

        saved = serialized["pipeline"]
        self.assertEqual(saved["camps_mode_per_aparell"], {"161": "per_exercici"})
        self.assertEqual(saved["camps_per_exercici_per_aparell"], {"161": {"1": ["E"], "2": ["D"]}})
        self.assertEqual(
            saved["agregacio_camps_per_exercici_per_aparell"],
            {"161": {"1": "sum", "2": "max"}},
        )

    def test_serializer_keeps_explicit_input_source_mode(self):
        raw_tie = {
            "id": "tie_input_source",
            "nom": "Desempat contributors",
            "ordre": "desc",
            "pipeline": {
                "aparells": {"mode": "seleccionar", "ids": [161]},
                "camps_per_aparell": {"161": ["TOTAL"]},
                "agregacio_camps_per_aparell": {"161": "sum"},
                "agregacio_camps": "sum",
                "exercicis": {"mode": "tots"},
                "exercise_selection_scope": "per_member",
                "mode_seleccio_exercicis": "per_aparell_global",
                "agregacio_exercicis": "sum",
                "agregacio_aparells": "sum",
                "input_source": {"mode": "main_selected_contributors"},
                "ordre": "desc",
            },
        }

        serialized = serialize_tie_for_save(
            raw_tie,
            tipus="equips",
            team_mode="derived_from_individual",
        )

        self.assertEqual(
            (serialized.get("pipeline") or {}).get("input_source"),
            {"mode": TIE_INPUT_SOURCE_MAIN_SELECTED_CONTRIBUTORS},
        )

    def test_ui_projection_is_explicit_builder_state_without_mutating_tie(self):
        tie = {
            "id": "tie_ui",
            "nom": "Desempat UI",
            "ordre": "desc",
            "camps": ["TOTAL"],
            "pipeline": {
                "aparells": {"mode": "seleccionar", "ids": [161]},
                "camps_per_aparell": {"161": ["TOTAL"]},
                "agregacio_camps": "sum",
                "exercicis": {"mode": "index", "index": 2},
                "exercise_selection_scope": "per_member",
                "mode_seleccio_exercicis": "per_aparell_override",
                "exercicis_per_aparell": {"161": {"mode": "millor_1"}},
                "agregacio_exercicis_per_aparell": {"161": "max"},
            },
        }
        main_pipeline = {
            "aparells": {"mode": "seleccionar", "ids": [161]},
            "exercicis": {"mode": "tots"},
            "exercise_selection_scope": "per_member",
            "mode_seleccio_exercicis": "per_aparell_global",
        }

        ui = project_tie_ui_state(
            tie,
            main_pipeline=main_pipeline,
            tipus="equips",
            team_mode="derived_from_individual",
        )

        self.assertNotIn("_builder_ui", tie)
        self.assertEqual(ui["app_scope"], {"mode": "hereta"})
        self.assertEqual(ui["camps"], ["TOTAL"])
        self.assertEqual(ui["exercise_selection_scope_ui"], "hereta")
        self.assertEqual(ui["mode_seleccio_exercicis_ui"], "per_aparell_override")
        self.assertEqual(ui["scope_exercicis_ui"], {"mode": "index", "index": 2})
        self.assertEqual(ui["exercicis_per_aparell_ui"], {"161": {"mode": "millor_1"}})
        self.assertEqual(ui["agregacio_exercicis_per_aparell_ui"], {"161": "max"})

    def test_legacy_projection_materializes_mirrors_from_pipeline(self):
        raw_tie = {
            "id": "tie_legacy_projection",
            "nom": "Desempat legacy",
            "ordre": "asc",
            "pipeline": {
                "aparells": {"mode": "seleccionar", "ids": [161]},
                "camps_per_aparell": {"161": ["TOTAL"]},
                "agregacio_camps_per_aparell": {"161": "avg"},
                "agregacio_camps": "sum",
                "exercicis": {"mode": "index", "index": 2},
                "exercise_selection_scope": "per_member",
                "mode_seleccio_exercicis": "per_aparell_global",
                "ordre": "asc",
            },
        }

        projected = project_tie_legacy_projection(
            raw_tie,
            tipus="equips",
            team_mode="derived_from_individual",
            selected_app_ids=[161],
            allow_participants=True,
        )

        self.assertEqual(projected["id"], "tie_legacy_projection")
        self.assertEqual(projected["camps"], ["TOTAL"])
        self.assertEqual(projected["camp"], "TOTAL")
        self.assertEqual(projected["aparell_id"], 161)
        self.assertEqual(projected["agregacio_camps"], "avg")
        self.assertEqual(projected["scope"]["aparells"], {"mode": "seleccionar", "ids": [161]})
        self.assertEqual(
            projected["scope"]["exercicis"],
            {"mode": "index", "best_n": 1, "index": 2, "ids": [], "max_per_participant": 0},
        )

    def test_builder_rehydration_combines_legacy_projection_and_ui_projection(self):
        raw_tie = {
            "id": "tie_builder_projection",
            "nom": "Desempat builder",
            "ordre": "desc",
            "pipeline": {
                "aparells": {"mode": "seleccionar", "ids": [161]},
                "camps_per_aparell": {"161": ["TOTAL"]},
                "agregacio_camps_per_aparell": {"161": "sum"},
                "agregacio_camps": "sum",
                "exercicis": {"mode": "tots"},
                "exercise_selection_scope": "team_pool",
                "participants": {"mode": "tots"},
                "agregacio_participants": "sum",
                "ordre": "desc",
            },
        }
        main_pipeline = {
            "aparells": {"mode": "seleccionar", "ids": [161]},
            "exercicis": {"mode": "tots"},
            "exercise_selection_scope": "team_pool",
            "mode_seleccio_exercicis": "per_aparell_global",
        }

        projected = project_tie_for_builder_rehydration(
            raw_tie,
            tipus="equips",
            team_mode="derived_from_individual",
            selected_main_ids=[161],
            fallback_pipeline=main_pipeline,
        )

        self.assertEqual(projected["camps"], ["TOTAL"])
        self.assertNotIn("participants", projected["scope"])
        self.assertEqual((projected.get("_builder_ui") or {}).get("app_scope"), {"mode": "hereta"})
        self.assertEqual((projected.get("_builder_ui") or {}).get("exercise_selection_scope_ui"), "hereta")
        self.assertIsNone((projected.get("_builder_ui") or {}).get("participants_ui"))

    def test_builder_rehydration_preserves_per_exercise_fields_and_team_pool_buckets(self):
        raw_tie = self._tie_with_pipeline(
            {
                **self._base_pipeline(exercise_selection_scope="team_pool"),
                "camps_mode_per_aparell": {"161": "per_exercici"},
                "camps_per_exercici_per_aparell": {"161": {"1": ["E"], "2": ["D"]}},
                "agregacio_camps_per_exercici_per_aparell": {"161": {"1": "sum", "2": "max"}},
                "team_pool_mode_per_aparell": {"161": "per_exercici"},
                "team_pool_participants_per_exercici_per_aparell": {
                    "161": {"1": {"mode": "millor_1"}}
                },
                "team_pool_agregacio_participants_per_exercici_per_aparell": {
                    "161": {"1": "avg"}
                },
            },
            tie_id="tie_builder_per_exercise",
        )
        main_pipeline = self._base_pipeline(exercise_selection_scope="team_pool")

        projected = project_tie_for_builder_rehydration(
            raw_tie,
            tipus="equips",
            team_mode="derived_from_individual",
            selected_main_ids=[161],
            fallback_pipeline=main_pipeline,
        )

        pipeline = projected.get("pipeline") or {}
        self.assertEqual(pipeline.get("camps_mode_per_aparell"), {"161": "per_exercici"})
        self.assertEqual(pipeline.get("camps_per_exercici_per_aparell"), {"161": {"1": ["E"], "2": ["D"]}})
        self.assertEqual(pipeline.get("team_pool_mode_per_aparell"), {"161": "per_exercici"})
        self.assertEqual(
            pipeline.get("team_pool_participants_per_exercici_per_aparell"),
            {"161": {"1": {"mode": "millor_1"}}},
        )

    def test_validation_materialization_keeps_team_pool_exercises_and_strips_participants(self):
        raw_tie = {
            "id": "tie_validation",
            "nom": "Desempat validacio",
            "ordre": "asc",
            "pipeline": {
                "aparells": {"mode": "seleccionar", "ids": [161]},
                "camps_per_aparell": {"161": ["TOTAL"]},
                "agregacio_camps_per_aparell": {"161": "sum"},
                "agregacio_camps": "sum",
                "exercicis": {"mode": "tots"},
                "exercise_selection_scope": "team_pool",
                "mode_seleccio_exercicis": "per_aparell_global",
                "participants": {"mode": "tots"},
                "agregacio_participants": "sum",
                "ordre": "asc",
            },
        }

        materialized = materialize_desempat_for_validation(
            [raw_tie],
            tipus="equips",
            team_mode="derived_from_individual",
            selected_app_ids=[161],
            allow_participants=True,
            main_scope="team_pool",
        )

        self.assertEqual(len(materialized), 1)
        tie = materialized[0]
        self.assertNotIn("exercise_selection_scope", tie)
        self.assertNotIn("exercise_selection_scope", tie["pipeline"])
        self.assertEqual(tie["pipeline"]["exercicis"]["mode"], "tots")
        self.assertEqual(tie["pipeline"]["mode_seleccio_exercicis"], "per_aparell_global")
        self.assertNotIn("participants", tie["pipeline"])
        self.assertNotIn("agregacio_participants", tie)
        self.assertEqual(tie["scope"]["aparells"], {"mode": "seleccionar", "ids": [161]})
        self.assertNotIn("participants", tie["scope"])

    def test_validation_materialization_strips_native_team_participants(self):
        raw_tie = {
            "id": "tie_native_validation",
            "nom": "Desempat validacio equip natiu",
            "ordre": "desc",
            "pipeline": {
                "aparells": {"mode": "seleccionar", "ids": [211]},
                "camps_per_aparell": {"211": ["TOTAL"]},
                "agregacio_camps_per_aparell": {"211": "sum"},
                "agregacio_camps": "sum",
                "exercicis": {"mode": "tots"},
                "exercise_selection_scope": "per_member",
                "participants": {"mode": "tots"},
                "agregacio_participants": "sum",
                "ordre": "desc",
            },
        }

        materialized = materialize_desempat_for_validation(
            [raw_tie],
            tipus="equips",
            team_mode="native_team",
            selected_app_ids=[211],
            allow_participants=False,
            main_scope="per_member",
        )

        self.assertEqual(len(materialized), 1)
        tie = materialized[0]
        self.assertNotIn("participants", tie)
        self.assertNotIn("agregacio_participants", tie)
        self.assertNotIn("participants", tie["pipeline"])
        self.assertNotIn("agregacio_participants", tie["pipeline"])
