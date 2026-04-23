from django.test import SimpleTestCase

from competicions_trampoli.scoring_engine import ScoringEngine
from competicions_trampoli.services.scoring.judge_presence import (
    build_runtime_inputs_from_canonical,
    persist_inputs_after_compute,
)


class ScoringEngineJudgePresenceTests(SimpleTestCase):
    def test_select_sum_ignores_absent_judges_but_keeps_real_zero(self):
        schema = {
            "fields": [
                {
                    "code": "J",
                    "type": "list",
                    "shape": "judge",
                    "judges": {"count": 3},
                },
            ],
            "computed": [
                {"code": "AVG", "formula": "select_sum(J, select='all', agg='avg')"},
                {"code": "TOTAL", "formula": "AVG"},
            ],
        }

        result = ScoringEngine(schema).compute(
            {
                "J": [0, None, 8],
                "__presence__J": [True, False, True],
            }
        )

        self.assertEqual(result.inputs["J"], [0.0, None, 8.0])
        self.assertEqual(result.outputs["AVG"], 4.0)
        self.assertEqual(result.total, 4.0)

    def test_legacy_eliminar_extrems_does_not_select_absent_zero(self):
        schema = {
            "fields": [
                {
                    "code": "J",
                    "type": "list",
                    "shape": "judge",
                    "judges": {"count": 3},
                },
            ],
            "computed": [
                {"code": "TOTAL", "formula": "select_sum(J, 2, 'eliminar_extrems')"},
            ],
        }

        result = ScoringEngine(schema).compute(
            {
                "J": [1, 9, None],
                "__presence__J": [True, True, False],
            }
        )

        self.assertEqual(result.outputs["TOTAL"], 10.0)

    def test_exec_by_judge_and_row_custom_compute_return_none_for_absent_rows(self):
        schema = {
            "params": {"n_elements": 2},
            "fields": [
                {
                    "code": "E",
                    "type": "matrix",
                    "shape": "judge_x_element",
                    "judges": {"count": 3},
                    "items": {"count": 2},
                    "crash": {"enabled": True},
                },
            ],
            "computed": [
                {"code": "EX", "formula": "exec_by_judge(E, crash('E'), params)"},
                {"code": "ROW", "formula": "row_custom_compute('E', 'x', return_mode='by_judge')"},
                {"code": "TOTAL", "formula": "select_sum(EX, select='all', agg='sum')"},
            ],
        }

        result = ScoringEngine(schema).compute(
            {
                "E": [[0, 0], None, [0.5, 0.5]],
                "__crash__E": [0, None, 0],
                "__presence__E": [True, False, True],
            }
        )

        self.assertEqual(result.inputs["E"][1], None)
        self.assertEqual(result.outputs["EX"][1], None)
        self.assertEqual(result.outputs["ROW"][1], None)
        self.assertEqual(result.outputs["TOTAL"], 3.9)

    def test_single_judge_1x1_matrix_missing_value_computes_as_zero(self):
        schema = {
            "fields": [
                {
                    "code": "DD",
                    "type": "matrix",
                    "shape": "judge_x_item",
                    "judges": {"count": 1},
                    "items": {"count": 1},
                },
            ],
            "computed": [
                {"code": "TOTAL", "formula": "DD + 1"},
            ],
        }

        result = ScoringEngine(schema).compute({})

        self.assertEqual(result.inputs["DD"], [[0.0]])
        self.assertEqual(result.total, 1.0)

    def test_present_multijudge_row_internal_nulls_compute_as_zero(self):
        schema = {
            "fields": [
                {
                    "code": "E",
                    "type": "matrix",
                    "shape": "judge_x_item",
                    "judges": {"count": 2},
                    "items": {"count": 2},
                },
            ],
            "computed": [
                {"code": "ROW", "formula": "row_custom_compute('E', 'x', return_mode='by_judge')"},
                {"code": "TOTAL", "formula": "select_sum(ROW, select='all', agg='sum')"},
            ],
        }

        result = ScoringEngine(schema).compute(
            {
                "E": [[None, None], None],
                "__presence__E": [True, False],
            }
        )

        self.assertEqual(result.inputs["E"], [[0.0, 0.0], None])
        self.assertEqual(result.outputs["ROW"], [0.0, None])
        self.assertEqual(result.total, 0.0)

    def test_absent_presence_preserves_values_in_canonical_but_not_runtime(self):
        schema = {
            "fields": [
                {
                    "code": "E",
                    "type": "matrix",
                    "shape": "judge_x_item",
                    "judges": {"count": 2},
                    "items": {"count": 2},
                    "crash": {"enabled": True},
                },
            ],
            "computed": [
                {"code": "ROW", "formula": "row_custom_compute('E', 'x', return_mode='by_judge')"},
                {"code": "TOTAL", "formula": "select_sum(ROW, select='all', agg='sum')"},
            ],
        }
        canonical = {
            "E": [[1, 2], [3, 4]],
            "__crash__E": [0, 1],
            "__presence__E": [True, False],
        }

        runtime = build_runtime_inputs_from_canonical(canonical, schema)
        result = ScoringEngine(schema).compute(runtime)
        persisted = persist_inputs_after_compute(canonical, result.inputs, schema)

        self.assertEqual(runtime["E"], [[1, 2], None])
        self.assertEqual(runtime["__crash__E"], [0, None])
        self.assertEqual(result.outputs["ROW"], [3.0, None])
        self.assertEqual(result.total, 3.0)
        self.assertEqual(persisted["E"], [[1, 2], [3, 4]])
        self.assertEqual(persisted["__crash__E"], [0, 1])
        self.assertEqual(persisted["__presence__E"], [True, False])
