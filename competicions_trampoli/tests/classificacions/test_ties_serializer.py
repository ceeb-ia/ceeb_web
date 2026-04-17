from django.test import SimpleTestCase

from ...services.classificacions.ties.context import (
    TIE_CONTRACT_PER_MEMBER,
    TIE_CONTRACT_TEAM_POOL,
    resolve_tie_context,
)
from ...services.classificacions.ties.serializer_save import serialize_tie_for_save


class TieSerializerSaveTests(SimpleTestCase):
    def test_resolve_tie_context_detects_team_pool(self):
        tie = {
            "pipeline": {
                "exercise_selection_scope": "team_pool",
            }
        }

        context = resolve_tie_context(tie, tipus="equips", team_mode="derived_from_individual")

        self.assertEqual(context.contract_name, TIE_CONTRACT_TEAM_POOL)
        self.assertTrue(context.is_team)
        self.assertTrue(context.is_derived_team)

    def test_team_pool_serializer_strips_per_member_exercise_and_participant_fields(self):
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
        self.assertNotIn("exercicis", pipeline)
        self.assertNotIn("mode_seleccio_exercicis", pipeline)
        self.assertNotIn("exercicis_per_aparell", pipeline)
        self.assertNotIn("agregacio_exercicis_per_aparell", pipeline)
        self.assertNotIn("agregacio_exercicis", pipeline)
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
        self.assertEqual(pipeline["exercicis"], {"mode": "index", "index": 2})
        self.assertEqual(pipeline["mode_seleccio_exercicis"], "per_aparell_override")
        self.assertEqual(pipeline["exercicis_per_aparell"], {"161": {"mode": "millor_1"}})
        self.assertEqual(pipeline["agregacio_exercicis_per_aparell"], {"161": "sum"})
