from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from competicions_trampoli.services.classificacions.engine.score_values import (
    _apply_simple_agg,
    _field_value_from_entry,
    _get_score_field,
    _numeric_scalar_or_1x1,
    _to_float,
    _try_strict_float,
)


class EngineScoreValuesTests(SimpleTestCase):
    def test_float_conversions_match_legacy_semantics(self):
        self.assertEqual(_to_float(None), 0.0)
        self.assertEqual(_to_float(""), 0.0)
        self.assertEqual(_to_float("3.5"), 3.5)
        self.assertEqual(_to_float("bad"), 0.0)
        self.assertEqual(_try_strict_float(None), None)
        self.assertEqual(_try_strict_float(""), None)
        self.assertEqual(_try_strict_float(" 4.25 "), 4.25)
        self.assertEqual(_try_strict_float(Decimal("7.1")), 7.1)
        self.assertEqual(_try_strict_float(True), 1.0)
        self.assertEqual(_try_strict_float("bad"), None)

    def test_numeric_scalar_or_1x1_and_aggregations(self):
        self.assertEqual(_numeric_scalar_or_1x1(Decimal("5.5")), 5.5)
        self.assertEqual(_numeric_scalar_or_1x1([7.5]), 7.5)
        self.assertEqual(_numeric_scalar_or_1x1([[8.25]]), 8.25)
        self.assertEqual(_numeric_scalar_or_1x1([["9.75"]]), 9.75)
        self.assertIsNone(_numeric_scalar_or_1x1([[1, 2]]))
        self.assertIsNone(_numeric_scalar_or_1x1([1, 2]))
        self.assertEqual(_apply_simple_agg([1, "2", Decimal("3")], "sum"), 6.0)
        self.assertEqual(_apply_simple_agg([1, 2, 4], "avg"), 7.0 / 3.0)
        self.assertEqual(_apply_simple_agg([1, 9, 4], "max"), 9.0)
        self.assertEqual(_apply_simple_agg([1, 9, 4], "min"), 1.0)
        self.assertEqual(_apply_simple_agg([1, 9, 4, 5], "median"), 4.5)
        self.assertEqual(_apply_simple_agg([], "sum"), 0.0)
        self.assertEqual(_apply_simple_agg([1, 2], "unknown"), 3.0)

    def test_field_lookup_and_warning_for_non_scoreable_values(self):
        entry = SimpleNamespace(
            id=11,
            inscripcio_id=22,
            comp_aparell_id=33,
            total=12.3,
            outputs={"TOTAL": [[9.5]], "exec": [8.4], "matrix": [[1, 2]]},
            inputs={"penal": "0.3"},
        )

        self.assertEqual(_field_value_from_entry(entry, "total"), 12.3)
        self.assertEqual(_field_value_from_entry(entry, "TOTAL"), 12.3)
        self.assertEqual(_field_value_from_entry(entry, "exec"), [8.4])
        self.assertEqual(_field_value_from_entry(entry, "penal"), "0.3")
        self.assertIsNone(_field_value_from_entry(entry, "missing"))

        self.assertEqual(_get_score_field(entry, "TOTAL"), 12.3)
        self.assertEqual(_get_score_field(entry, "exec"), 8.4)
        self.assertEqual(_get_score_field(entry, "penal"), 0.3)
        self.assertEqual(_get_score_field(entry, "missing"), 0.0)

        with self.assertLogs(
            "competicions_trampoli.services.classificacions.engine.score_values",
            level="WARNING",
        ) as captured:
            self.assertEqual(_get_score_field(entry, "matrix"), 0.0)

        self.assertEqual(len(captured.output), 1)
        self.assertIn("Classificacio: camp no puntuable", captured.output[0])
        self.assertIn("entry_id=11", captured.output[0])
        self.assertIn("inscripcio_id=22", captured.output[0])
        self.assertIn("comp_aparell_id=33", captured.output[0])
        self.assertIn("camp=matrix", captured.output[0])
