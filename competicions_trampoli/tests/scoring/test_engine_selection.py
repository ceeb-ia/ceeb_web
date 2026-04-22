import unittest

from ...services.classificacions.engine.selection import (
    _normalize_candidate_source_cfg,
    _normalize_candidate_source_mode,
    _normalize_exercicis_cfg,
    _normalize_field_mode,
    _normalize_optional_agg,
    _normalize_participants_cfg,
    _pick_exercicis,
    _pick_exercicis_rows,
    _pick_exercicis_tuples,
    _pick_participants,
)


class EngineSelectionTests(unittest.TestCase):
    def test_pick_exercicis_preserves_legacy_modes(self):
        self.assertEqual(_pick_exercicis([1, "2.5", None], "tots", 3), [1.0, 2.5, 0.0])
        self.assertEqual(_pick_exercicis([1, "2.5", None], "millor_n", 2), [2.5, 1.0])
        self.assertEqual(_pick_exercicis([1, "2.5", None], "pitjor_1", 1), [0.0])
        self.assertEqual(_pick_exercicis([1, 2], "desconegut", 5), [1.0, 2.0])

    def test_pick_exercicis_rows_applies_sorting_and_cap_per_participant(self):
        rows = [
            {"idx": 2, "value": 9.0, "inscripcio_id": 10, "meta": "a"},
            {"idx": 1, "value": 9.0, "inscripcio_id": 10, "meta": "b"},
            {"idx": 3, "value": 8.5, "inscripcio_id": 11, "meta": "c"},
            {"idx": 4, "value": 8.0, "inscripcio_id": 11, "meta": "d"},
        ]

        picked = _pick_exercicis_rows(rows, "millor_n", 3, max_per_participant=1)

        self.assertEqual(
            picked,
            [
                {"idx": 1, "value": 9.0, "inscripcio_id": 10, "meta": "b"},
                {"idx": 3, "value": 8.5, "inscripcio_id": 11, "meta": "c"},
            ],
        )

    def test_pick_exercicis_rows_supports_index_and_lista(self):
        rows = [
            {"idx": 1, "value": 7.0},
            {"idx": 2, "value": 8.0},
            {"idx": 3, "value": 9.0},
        ]

        self.assertEqual(_pick_exercicis_rows(rows, "index", 1, index="2"), [{"idx": 2, "value": 8.0}])
        self.assertEqual(
            _pick_exercicis_rows(rows, "llista", 1, ids=["3", "x", 1]),
            [{"idx": 1, "value": 7.0}, {"idx": 3, "value": 9.0}],
        )

    def test_pick_exercicis_tuples_reuses_row_selection_semantics(self):
        ex_vals = [(2, "8.4"), (1, 9), ("x", 7), (3, None)]

        picked = _pick_exercicis_tuples(ex_vals, "millor_n", 2)

        self.assertEqual(picked, [9.0, 8.4])

    def test_normalize_exercicis_cfg_matches_legacy_fallback_rules(self):
        cfg = _normalize_exercicis_cfg(
            {
                "mode": "INVALID",
                "best_n": "0",
                "index": "bad",
                "ids": "3, x, 2, 0",
                "max_per_participant": "-5",
            },
            fallback={"mode": "millor_n", "best_n": 4, "index": 3, "ids": [5], "max_per_participant": 2},
        )

        self.assertEqual(
            cfg,
            {
                "mode": "millor_n",
                "best_n": 1,
                "index": 1,
                "ids": [3, 2],
                "max_per_participant": 0,
            },
        )

    def test_normalize_candidate_source_cfg_drops_participant_cap_and_normalizes_agg(self):
        cfg = _normalize_candidate_source_cfg(
            {"mode": "millor_n", "best_n": 2, "max_per_participant": 3, "agregacio_exercicis": "BAD"},
            fallback={"agregacio_exercicis": "median"},
        )

        self.assertEqual(
            cfg,
            {
                "mode": "millor_n",
                "best_n": 2,
                "index": 1,
                "ids": [],
                "agregacio_exercicis": "median",
            },
        )

    def test_other_normalizers_and_participant_selection_keep_legacy_semantics(self):
        self.assertEqual(_normalize_candidate_source_mode("TEAM_AGGREGATE"), "team_aggregate")
        self.assertEqual(_normalize_candidate_source_mode("bad"), "raw_exercise")
        self.assertEqual(_normalize_field_mode("PER_EXERCICI"), "per_exercici")
        self.assertEqual(_normalize_field_mode("bad"), "comu")
        self.assertEqual(_normalize_optional_agg("AVG"), "avg")
        self.assertEqual(_normalize_optional_agg("bad"), "")
        self.assertEqual(_pick_participants([1, "3", None], "hereta", 2), [1.0, 3.0, 0.0])
        self.assertEqual(_pick_participants([1, "3", None], "pitjor_n", 2), [0.0, 1.0])
        self.assertEqual(_normalize_participants_cfg({"mode": "millor_n", "best_n": "0"}), {"mode": "millor_n", "n": 1})
        self.assertEqual(_normalize_participants_cfg({"mode": "hereta", "n": 5}), {"mode": "tots"})


if __name__ == "__main__":
    unittest.main()
