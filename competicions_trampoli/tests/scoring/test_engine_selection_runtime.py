import unittest
from types import SimpleNamespace

from ...services.classificacions.engine.selection_runtime import (
    EXERCISE_SELECTION_SCOPE_TEAM_POOL,
    SelectionRuntime,
)


def _row(*, app_id, inscripcio_id=None, equip_id=None, exercici, value, by_camp=None):
    return {
        "idx": int(exercici),
        "value": float(value),
        "app_id": int(app_id),
        "app_order": int(app_id),
        "exercici": int(exercici),
        "inscripcio_id": inscripcio_id,
        "equip_id": equip_id,
        "by_camp": dict(by_camp or {}),
    }


class EngineSelectionRuntimeTests(unittest.TestCase):
    def _build_derived_team_runtime(self, **overrides):
        params = {
            "aparells": [SimpleNamespace(id=1, is_team_competition_unit=False)],
            "tipus": "equips",
            "team_mode": "derived_from_individual",
            "base_ex_cfg": {"mode": "millor_1"},
            "candidate_source_mode": "participant_aggregate",
            "candidate_source_cfg": {"mode": "millor_n", "best_n": 2, "agregacio_exercicis": "avg"},
            "exercise_selection_scope": EXERCISE_SELECTION_SCOPE_TEAM_POOL,
            "app_ex_rows_by_ins": {
                1: {
                    101: [
                        _row(app_id=1, inscripcio_id=101, exercici=1, value=8.0, by_camp={"total": 8.0, "E": 3.0}),
                        _row(app_id=1, inscripcio_id=101, exercici=2, value=9.0, by_camp={"total": 9.0, "E": 4.0}),
                    ],
                    202: [
                        _row(app_id=1, inscripcio_id=202, exercici=1, value=7.0, by_camp={"total": 7.0, "E": 2.0}),
                        _row(app_id=1, inscripcio_id=202, exercici=2, value=6.0, by_camp={"total": 6.0, "E": 1.0}),
                    ],
                }
            },
        }
        params.update(overrides)
        return SelectionRuntime(**params)

    def _build_native_team_runtime(self, **overrides):
        params = {
            "aparells": [SimpleNamespace(id=9, is_team_competition_unit=True)],
            "tipus": "equips",
            "team_mode": "native_team",
            "base_ex_cfg": {"mode": "millor_1"},
            "team_app_ex_rows_by_equip": {
                9: {
                    55: [
                        _row(app_id=9, equip_id=55, exercici=1, value=12.0, by_camp={"total": 12.0, "E": 5.0}),
                        _row(app_id=9, equip_id=55, exercici=2, value=13.5, by_camp={"total": 13.5, "E": 6.0}),
                    ]
                }
            },
        }
        params.update(overrides)
        return SelectionRuntime(**params)

    def test_resolve_score_fields_for_app_exercise_supports_per_exercise_override(self):
        runtime = SelectionRuntime(
            aparells=[SimpleNamespace(id=11, is_team_competition_unit=False)],
            legacy_camp="legacy_total",
            agg_camps="sum",
            camps_per_aparell={"11": ["total", "exec"]},
            camps_mode_per_aparell={"11": "per_exercici"},
            camps_per_exercici_per_aparell={"11": {"2": ["salt", "nota"], "3": [""]}},
            agregacio_camps_per_aparell={"11": "avg"},
            agregacio_camps_per_exercici_per_aparell={"11": {"2": "max", "3": "bad"}},
        )

        self.assertEqual(runtime._score_camps_for_app(11), ["total", "exec"])
        self.assertEqual(
            runtime._score_camps_for_app(11, include_per_exercise=True),
            ["total", "exec", "salt", "nota"],
        )
        self.assertEqual(runtime.resolve_score_fields_for_app_exercise(11, 2), (["salt", "nota"], "max"))
        self.assertEqual(runtime.resolve_score_fields_for_app_exercise(11, 3), (["total", "exec"], "avg"))

    def test_build_candidate_rows_from_source_rows_aggregates_fields_and_sources(self):
        runtime = SelectionRuntime(
            aparells=[SimpleNamespace(id=5, is_team_competition_unit=False)],
            tipus="individual",
            candidate_source_mode="participant_aggregate",
            candidate_source_cfg={"mode": "millor_n", "best_n": 2, "agregacio_exercicis": "avg"},
        )

        candidate_rows = runtime._build_candidate_rows_from_source_rows(
            [
                _row(app_id=5, inscripcio_id=7, exercici=1, value=8.0, by_camp={"total": 8.0, "E": 4.0}),
                _row(app_id=5, inscripcio_id=7, exercici=2, value=10.0, by_camp={"total": 10.0, "E": 6.0}),
                _row(app_id=5, inscripcio_id=7, exercici=3, value=6.0, by_camp={"total": 6.0, "E": 2.0}),
            ],
            5,
        )

        self.assertEqual(len(candidate_rows), 1)
        candidate = candidate_rows[0]
        self.assertEqual(candidate["candidate_source_mode"], "participant_aggregate")
        self.assertEqual(candidate["candidate_source_count"], 2)
        self.assertEqual(candidate["value"], 9.0)
        self.assertEqual(candidate["by_camp"], {"total": 9.0, "E": 5.0})
        self.assertEqual(
            [(row["inscripcio_id"], row["exercici"], row["value"]) for row in candidate["source_rows"]],
            [(7, 1, 8.0), (7, 2, 10.0)],
        )

    def test_group_contributors_respect_main_participant_selection_per_member(self):
        runtime = SelectionRuntime(
            aparells=[SimpleNamespace(id=1, is_team_competition_unit=False)],
            tipus="equips",
            team_mode="derived_from_individual",
            base_ex_cfg={"mode": "millor_1"},
            agg_exercicis="sum",
            agregacio_exercicis_per_aparell={"1": "sum"},
            participants_per_aparell={"1": {"mode": "millor_1"}},
            app_ex_rows_by_ins={
                1: {
                    101: [
                        _row(app_id=1, inscripcio_id=101, exercici=1, value=9.0, by_camp={"total": 9.0}),
                        _row(app_id=1, inscripcio_id=101, exercici=2, value=8.0, by_camp={"total": 8.0}),
                    ],
                    202: [
                        _row(app_id=1, inscripcio_id=202, exercici=1, value=10.0, by_camp={"total": 10.0}),
                        _row(app_id=1, inscripcio_id=202, exercici=2, value=7.0, by_camp={"total": 7.0}),
                    ],
                }
            },
        )

        contributors = runtime._get_main_selected_contributors_for_group("members:101,202", [101, 202])

        self.assertNotIn(101, contributors)
        self.assertEqual(list(contributors.keys()), [202])
        self.assertEqual(
            [(row["inscripcio_id"], row["exercici"], row["value"]) for row in contributors[202][1]],
            [(202, 1, 10.0)],
        )

    def test_team_pool_group_contributors_trace_candidate_sources_back_to_members(self):
        runtime = self._build_derived_team_runtime(
            app_ex_rows_by_ins={
                1: {
                    101: [
                        _row(app_id=1, inscripcio_id=101, exercici=1, value=8.0, by_camp={"total": 8.0}),
                        _row(app_id=1, inscripcio_id=101, exercici=2, value=9.0, by_camp={"total": 9.0}),
                    ],
                    202: [
                        _row(app_id=1, inscripcio_id=202, exercici=1, value=7.0, by_camp={"total": 7.0}),
                        _row(app_id=1, inscripcio_id=202, exercici=2, value=6.0, by_camp={"total": 6.0}),
                    ],
                }
            }
        )

        selected_rows = runtime._get_main_selected_rows_for_group([101, 202])
        contributors = runtime._get_main_selected_contributors_for_group([101, 202])

        self.assertEqual(len(selected_rows[1]), 1)
        self.assertEqual(selected_rows[1][0]["inscripcio_id"], 101)
        self.assertEqual(selected_rows[1][0]["candidate_source_count"], 2)
        self.assertEqual(
            [(row["inscripcio_id"], row["exercici"], row["value"]) for row in contributors[101][1]],
            [(101, 1, 8.0), (101, 2, 9.0)],
        )
        self.assertNotIn(202, contributors)

    def test_build_ctx_exports_exposes_bound_group_adapters(self):
        runtime = self._build_derived_team_runtime()

        exports = runtime.build_ctx_exports()

        self.assertIs(exports["copy_ex_row_with_value"].__self__, runtime)
        self.assertIs(exports["get_main_selected_rows_for_group"].__self__, runtime)
        self.assertIs(exports["get_main_selected_contributors_for_group"].__self__, runtime)
        self.assertEqual(
            [(row["inscripcio_id"], row["exercici"], row["value"]) for row in exports["get_main_selected_rows_for_group"]([101, 202])[1]],
            [(101, 2, 8.5)],
        )
        self.assertEqual(
            [(row["inscripcio_id"], row["exercici"], row["value"]) for row in exports["get_main_selected_contributors_for_group"]([101, 202])[101][1]],
            [(101, 1, 8.0), (101, 2, 9.0)],
        )

    def test_group_selection_public_methods_accept_explicit_or_adapted_signatures(self):
        runtime = self._build_derived_team_runtime()
        cache_key = "members:101,202"

        self.assertEqual(
            runtime.get_selected_rows_agg_for_derived_team([101, 202]),
            runtime.get_selected_rows_agg_for_derived_team(cache_key, [101, 202]),
        )
        self.assertEqual(
            runtime.get_main_selected_rows_for_group([101, 202]),
            runtime.get_main_selected_rows_for_group(cache_key, [101, 202]),
        )
        self.assertEqual(
            runtime.get_main_selected_contributors_for_group([101, 202]),
            runtime.get_main_selected_contributors_for_group(cache_key, [101, 202]),
        )
        self.assertEqual(
            runtime.get_main_selected_rows_for_group_field([101, 202], field_code="total"),
            runtime.get_main_selected_rows_for_group_field(cache_key, [101, 202], "total"),
        )

    def test_build_orchestrator_exports_exposes_group_and_team_selection_callables(self):
        derived_runtime = self._build_derived_team_runtime()
        derived_exports = derived_runtime.build_orchestrator_exports()

        self.assertEqual(
            [(row["inscripcio_id"], row["exercici"], row["value"]) for row in derived_exports["get_selected_rows_agg_for_derived_team"]("members:101,202", [101, 202])[1]],
            [(101, 2, 8.5)],
        )
        self.assertEqual(
            [(row["inscripcio_id"], row["exercici"], row["value"]) for row in derived_exports["get_main_selected_rows_for_group_field"]("members:101,202", [101, 202], "E")[1]],
            [(101, 2, 3.5)],
        )

        native_runtime = self._build_native_team_runtime()
        native_exports = native_runtime.build_orchestrator_exports()

        self.assertEqual(
            [(row["equip_id"], row["exercici"], row["value"]) for row in native_exports["get_main_selected_rows_agg_for_team"](55)[9]],
            [(55, 2, 13.5)],
        )
        self.assertEqual(
            [(row["equip_id"], row["exercici"], row["value"]) for row in native_exports["get_main_selected_team_rows_for_field"](55, "E")[9]],
            [(55, 2, 6.0)],
        )


if __name__ == "__main__":
    unittest.main()
