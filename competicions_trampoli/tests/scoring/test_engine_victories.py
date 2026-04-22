from django.test import SimpleTestCase

from ...services.classificacions.engine.victories import (
    _apply_victories_per_app_to_rows,
    _compute_victory_points_for_entries,
    _normalize_mode_resultat_aparells,
    _normalize_victories_cfg,
    _row_base_for_app,
    _row_has_app,
)


class VictoriesEngineTests(SimpleTestCase):
    def test_normalize_mode_resultat_aparells_defaults_invalid_to_score(self):
        self.assertEqual(_normalize_mode_resultat_aparells("victories"), "victories")
        self.assertEqual(_normalize_mode_resultat_aparells("broken"), "score")

    def test_normalize_victories_cfg_sanitizes_compare_ties_and_modes(self):
        cfg = _normalize_victories_cfg(
            {
                "punts_victoria": "2",
                "punts_empat": "0.25",
                "sense_nota_mode": "invalid",
                "mode_camps": "weird",
                "mode_exercicis": "broken",
                "mode_seleccio_exercicis_camps_separats": "nope",
                "agregacio_victories_camps": "bad",
                "agregacio_victories_exercicis": "bad",
                "desempat_comparacio": [
                    {
                        "camp": "E",
                        "aparell_id": 99,
                        "agregacio_participants": "avg",
                        "scope": {
                            "exercicis": {"mode": "hereta"},
                            "participants": {"mode": "tots"},
                        },
                    }
                ],
            }
        )

        self.assertEqual(cfg["punts_victoria"], 2.0)
        self.assertEqual(cfg["punts_empat"], 0.25)
        self.assertEqual(cfg["sense_nota_mode"], "skip")
        self.assertEqual(cfg["mode_camps"], "agregat")
        self.assertEqual(cfg["mode_exercicis"], "agregat")
        self.assertEqual(cfg["mode_seleccio_exercicis_camps_separats"], "per_camp")
        self.assertEqual(cfg["agregacio_victories_camps"], "sum")
        self.assertEqual(cfg["agregacio_victories_exercicis"], "sum")
        self.assertEqual(
            cfg["desempat_comparacio"],
            [{"camp": "E", "scope": {"exercicis": {"mode": "hereta"}}}],
        )

    def test_row_base_helpers_accept_int_and_string_app_keys(self):
        row = {"by_app_base": {"1": 9.5}}

        self.assertTrue(_row_has_app(row, 1))
        self.assertEqual(_row_base_for_app(row, 1), 9.5)

    def test_compute_victory_points_for_entries_uses_compare_ties(self):
        victories_cfg = {
            "punts_victoria": 1.0,
            "punts_empat": 0.5,
            "desempat_comparacio": [{"camp": "E", "ordre": "desc"}],
        }
        compare_values = {
            1: 9.0,
            2: 8.0,
        }

        def metric_value_getter(ins_id, crit, **kwargs):
            self.assertEqual(crit["camp"], "E")
            self.assertEqual(kwargs["forced_app_ids"], [1])
            return compare_values[ins_id]

        points = _compute_victory_points_for_entries(
            [
                {"row": {"inscripcio_id": 1}, "base": 10.0},
                {"row": {"inscripcio_id": 2}, "base": 10.0},
            ],
            "desc",
            victories_cfg,
            metric_value_getter,
            forced_app_ids=[1],
        )

        self.assertEqual(points, {1: 1.0, 2: 0.0})

    def test_apply_victories_per_app_to_rows_aggregates_duels_per_app(self):
        rows = [
            {"inscripcio_id": 1, "participant": "A", "by_app_base": {1: 100.0, 2: 1.0}},
            {"inscripcio_id": 2, "participant": "B", "by_app_base": {1: 60.0, 2: 60.0}},
            {"inscripcio_id": 3, "participant": "C", "by_app_base": {1: 59.0, 2: 59.0}},
        ]

        ranked_rows = _apply_victories_per_app_to_rows(
            rows,
            [1, 2],
            "desc",
            "sum",
            {"punts_victoria": 1.0, "punts_empat": 0.5, "desempat_comparacio": []},
            lambda ins_id, crit, **kwargs: 0.0,
        )
        by_name = {row["participant"]: row for row in ranked_rows}

        self.assertEqual(by_name["A"]["by_app"], {1: 2.0, 2: 0.0})
        self.assertEqual(by_name["B"]["by_app"], {1: 1.0, 2: 2.0})
        self.assertEqual(by_name["C"]["by_app"], {1: 0.0, 2: 1.0})
        self.assertEqual(by_name["A"]["score"], 2.0)
        self.assertEqual(by_name["B"]["score"], 3.0)
        self.assertEqual(by_name["C"]["score"], 1.0)
