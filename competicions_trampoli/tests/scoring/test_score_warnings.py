from django.test import SimpleTestCase

from competicions_trampoli.services.scoring.score_warnings import generate_score_warnings


class ScoreWarningsTests(SimpleTestCase):
    def setUp(self):
        self.subject = {"subject_kind": "inscripcio", "subject_id": 123, "name": "Gimnasta"}
        self.context = {"comp_aparell_id": 45, "exercici": 1}

    def test_range_low_and_high_use_stable_contract(self):
        schema = {
            "fields": [
                {"code": "P", "type": "number", "min": 0, "max": 10},
                {"code": "D", "type": "number", "min": 1, "max": 5},
            ]
        }

        warnings = generate_score_warnings(schema, {"inputs": {"P": 12, "D": "0.5"}}, self.subject, self.context)

        self.assertEqual([w["code"] for w in warnings], ["range_high", "range_low"])
        self.assertEqual(warnings[0]["id"], "range_high:inscripcio:123:45:1:P:-:-:0")
        self.assertEqual(warnings[0]["severity"], "warning")
        self.assertEqual(warnings[0]["message"], "P supera el maxim 10")
        self.assertEqual(warnings[0]["subject_kind"], "inscripcio")
        self.assertEqual(warnings[0]["subject_id"], 123)
        self.assertEqual(warnings[0]["comp_aparell_id"], 45)
        self.assertEqual(warnings[0]["exercici"], 1)
        self.assertEqual(warnings[0]["field_code"], "P")
        self.assertIsNone(warnings[0]["judge"])
        self.assertIsNone(warnings[0]["item"])
        self.assertEqual(warnings[0]["value"], 12)
        self.assertEqual(warnings[0]["expected"], {"min": 0, "max": 10})
        self.assertEqual(set(warnings[0].keys()), {
            "id",
            "severity",
            "code",
            "message",
            "subject_kind",
            "subject_id",
            "comp_aparell_id",
            "exercici",
            "field_code",
            "judge",
            "item",
            "value",
            "expected",
        })

    def test_decimal_precision_for_matrix_value(self):
        schema = {
            "fields": [
                {
                    "code": "E",
                    "type": "matrix",
                    "shape": "judge_x_item",
                    "judges": {"count": 1},
                    "items": {"count": 2},
                    "decimals": 1,
                }
            ]
        }

        warnings = generate_score_warnings(schema, {"E": [["0.25", "0.3"]]}, self.subject, self.context)

        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["code"], "decimal_precision")
        self.assertEqual(warnings[0]["field_code"], "E")
        self.assertEqual(warnings[0]["judge"], 1)
        self.assertEqual(warnings[0]["item"], 1)
        self.assertEqual(warnings[0]["value"], "0.25")
        self.assertEqual(warnings[0]["expected"], {"decimals": 1})

    def test_present_judge_without_value_warns(self):
        schema = {
            "fields": [
                {
                    "code": "J",
                    "type": "list",
                    "shape": "judge",
                    "judges": {"count": 2},
                }
            ]
        }

        warnings = generate_score_warnings(
            schema,
            {"J": [8.5, None], "__presence__J": [True, True]},
            self.subject,
            self.context,
        )

        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["code"], "missing_counting_judge")
        self.assertEqual(warnings[0]["judge"], 2)
        self.assertIsNone(warnings[0]["item"])
        self.assertEqual(warnings[0]["expected"], {"presence": True})

    def test_value_with_absent_judge_warns(self):
        schema = {
            "fields": [
                {
                    "code": "J",
                    "type": "list",
                    "shape": "judge",
                    "judges": {"count": 2},
                }
            ]
        }

        warnings = generate_score_warnings(
            schema,
            {"J": [7.5, 8], "__presence__J": [True, False]},
            self.subject,
            self.context,
        )

        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["code"], "value_without_presence")
        self.assertEqual(warnings[0]["judge"], 2)
        self.assertEqual(warnings[0]["value"], 8)
        self.assertEqual(warnings[0]["expected"], {"presence": False})

    def test_crash_with_later_values_warns_for_blocked_items(self):
        schema = {
            "fields": [
                {
                    "code": "E",
                    "type": "matrix",
                    "shape": "judge_x_item",
                    "judges": {"count": 1},
                    "items": {"count": 4},
                    "crash": {"enabled": True},
                }
            ]
        }

        warnings = generate_score_warnings(
            schema,
            {"E": [[0.1, None, 0.3, 0.4]], "__crash__E": [3]},
            self.subject,
            self.context,
        )

        self.assertEqual([w["code"] for w in warnings], ["crash_inconsistent", "crash_inconsistent"])
        self.assertEqual([w["item"] for w in warnings], [3, 4])
        self.assertEqual(warnings[0]["expected"], {"crash_at": 3, "empty_from_item": 3})

    def test_crash_allows_later_blank_values_for_present_judge(self):
        schema = {
            "fields": [
                {
                    "code": "E",
                    "type": "matrix",
                    "shape": "judge_x_item",
                    "judges": {"count": 1},
                    "items": {"count": 4},
                    "crash": {"enabled": True},
                }
            ]
        }

        warnings = generate_score_warnings(
            schema,
            {"E": [[0.1, 0.2, None, None]], "__crash__E": [3], "__presence__E": [True]},
            self.subject,
            self.context,
        )

        self.assertEqual(warnings, [])

    def test_matrix_presence_checks_missing_cells_and_absent_rows(self):
        schema = {
            "fields": [
                {
                    "code": "E",
                    "type": "matrix",
                    "shape": "judge_x_item",
                    "judges": {"count": 2},
                    "items": {"count": 2},
                }
            ]
        }

        warnings = generate_score_warnings(
            schema,
            {"E": [[1, None], [2, None]], "__presence__E": [True, False]},
            self.subject,
            self.context,
        )

        self.assertEqual([w["code"] for w in warnings], ["missing_counting_judge", "value_without_presence"])
        self.assertEqual(warnings[0]["judge"], 1)
        self.assertEqual(warnings[0]["item"], 2)
        self.assertEqual(warnings[1]["judge"], 2)
        self.assertIsNone(warnings[1]["item"])

    def test_zero_values_do_not_count_as_missing_for_present_judges(self):
        schema = {
            "fields": [
                {
                    "code": "E",
                    "type": "matrix",
                    "shape": "judge_x_item",
                    "judges": {"count": 1},
                    "items": {"count": 2},
                    "min": 0,
                    "max": 10,
                }
            ]
        }

        warnings = generate_score_warnings(
            schema,
            {"E": [[0, "0"]], "__presence__E": [True]},
            self.subject,
            self.context,
        )

        self.assertEqual(warnings, [])

    def test_many_implicit_zero_cells_warn_as_pattern(self):
        schema = {
            "fields": [
                {
                    "code": "E",
                    "type": "matrix",
                    "shape": "judge_x_item",
                    "judges": {"count": 1},
                    "items": {"count": 5},
                    "min": 0,
                    "max": 10,
                }
            ]
        }

        warnings = generate_score_warnings(
            schema,
            {"E": [[None, "", 0, "0", None]], "__presence__E": [True]},
            self.subject,
            self.context,
        )

        self.assertEqual([w["code"] for w in warnings], ["zero_pattern"])
        self.assertEqual(warnings[0]["value"], {"zero_count": 5, "count": 5})
