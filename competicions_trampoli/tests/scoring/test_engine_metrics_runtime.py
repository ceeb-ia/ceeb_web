from django.test import SimpleTestCase

from competicions_trampoli.services.classificacions.engine.metrics_runtime import (
    _pipeline_metric_map_for_crit,
    _pipeline_subject_key,
    _sanitize_desempat_for_tipus,
    build_metrics_runtime,
    calc_metric_value_for_group,
    calc_metric_value_for_ins,
    calc_metric_value_for_native_team,
)


def _row(*, app_id, idx, camp_values, inscripcio_id=None, equip_id=None):
    return {
        "idx": idx,
        "app_id": app_id,
        "app_order": app_id,
        "exercici": idx,
        "inscripcio_id": inscripcio_id,
        "equip_id": equip_id,
        "value": sum(float(value) for value in camp_values.values()),
        "by_camp": dict(camp_values),
    }


class MetricsRuntimeTests(SimpleTestCase):
    def test_pipeline_subject_key_prefers_subject_specific_identifiers(self):
        self.assertEqual(_pipeline_subject_key({"inscripcio_id": "12", "nom": "Ignored"}), ("ins", 12))
        self.assertEqual(_pipeline_subject_key({"equip_id": 7}), ("equip", 7))
        self.assertEqual(_pipeline_subject_key({"_member_ids": [4, "3", 4]}), ("members", (3, 4)))
        self.assertEqual(_pipeline_subject_key({"entitat_nom": " Club A "}), ("entitat", "club a"))
        self.assertEqual(_pipeline_subject_key({"participant": " Anna  Smith "}), ("nom", "anna smith"))

    def test_sanitize_desempat_for_tipus_removes_participant_scope_outside_teams(self):
        desempat = [
            {
                "camp": "E",
                "scope": {
                    "participants": {"mode": "millor_1"},
                    "aparells": {"mode": "seleccionar", "ids": [1]},
                },
                "agregacio_participants": "sum",
            }
        ]

        self.assertEqual(
            _sanitize_desempat_for_tipus(desempat, "individual"),
            [{"camp": "E", "scope": {"aparells": {"mode": "seleccionar", "ids": [1]}}}],
        )
        self.assertEqual(_sanitize_desempat_for_tipus(desempat, "equips"), desempat)

    def test_calc_metric_value_for_ins_projects_legacy_tie_to_pipeline(self):
        runtime = build_metrics_runtime(
            tipus="individual",
            selected_app_ids=[1],
            per_ins={101: {}, 102: {}},
            app_order={1: 1},
            app_ex_rows_by_ins={
                1: {
                    101: [_row(app_id=1, idx=1, inscripcio_id=101, camp_values={"E": 9.2, "D": 8.1})],
                    102: [_row(app_id=1, idx=1, inscripcio_id=102, camp_values={"E": 8.4, "D": 8.8})],
                }
            },
        )

        tie = {"camp": "E", "ordre": "desc"}

        self.assertEqual(calc_metric_value_for_ins(runtime, 101, tie), 9.2)
        self.assertEqual(calc_metric_value_for_ins(runtime, 102, tie), 8.4)

    def test_calc_metric_value_for_group_honors_participant_selection(self):
        runtime = build_metrics_runtime(
            tipus="equips",
            team_mode="derived_from_individual",
            selected_app_ids=[1],
            app_order={1: 1},
            app_ex_rows_by_ins={
                1: {
                    201: [_row(app_id=1, idx=1, inscripcio_id=201, camp_values={"E": 8.2})],
                    202: [_row(app_id=1, idx=1, inscripcio_id=202, camp_values={"E": 9.5})],
                }
            },
        )

        tie = {
            "camp": "E",
            "scope": {"participants": {"mode": "millor_1"}},
            "agregacio_participants": "sum",
        }

        self.assertEqual(calc_metric_value_for_group(runtime, [201, 202], tie), 9.5)

    def test_calc_metric_value_for_native_team_uses_team_rows(self):
        runtime = build_metrics_runtime(
            tipus="equips",
            team_mode="native_team",
            selected_app_ids=[9],
            app_order={9: 1},
            team_app_ex_rows_by_equip={
                9: {
                    301: [
                        _row(app_id=9, idx=1, equip_id=301, camp_values={"TEAM": 12.0}),
                        _row(app_id=9, idx=2, equip_id=301, camp_values={"TEAM": 13.5}),
                    ]
                }
            },
        )

        tie = {
            "camp": "TEAM",
            "scope": {"exercicis": {"mode": "millor_1"}},
            "agregacio_exercicis": "sum",
            "aparell_id": 9,
        }

        self.assertEqual(calc_metric_value_for_native_team(runtime, 301, tie), 13.5)

    def test_pipeline_metric_map_for_crit_supports_entity_subjects(self):
        runtime = build_metrics_runtime(
            tipus="entitat",
            selected_app_ids=[1],
            app_order={1: 1},
            per_particio={
                "global": [
                    {"entitat_nom": "Club A", "inscripcio_id": 401},
                    {"entitat_nom": "Club A", "inscripcio_id": 402},
                    {"entitat_nom": "Club B", "inscripcio_id": 403},
                ]
            },
            app_ex_rows_by_ins={
                1: {
                    401: [_row(app_id=1, idx=1, inscripcio_id=401, camp_values={"E": 8.0})],
                    402: [_row(app_id=1, idx=1, inscripcio_id=402, camp_values={"E": 9.0})],
                    403: [_row(app_id=1, idx=1, inscripcio_id=403, camp_values={"E": 7.5})],
                }
            },
        )

        tie = {
            "id": "pipe-entitat",
            "ordre": "desc",
            "pipeline": {
                "aparells": {"mode": "seleccionar", "ids": [1]},
                "camps_mode_per_aparell": {"1": "comu"},
                "camps_per_aparell": {"1": ["E"]},
                "agregacio_camps": "sum",
                "exercicis": {"mode": "tots", "best_n": 1, "index": 1, "ids": [], "max_per_participant": 0},
                "mode_seleccio_exercicis": "per_aparell_global",
                "agregacio_exercicis": "sum",
                "agregacio_aparells": "sum",
                "exercise_selection_scope": "per_member",
            },
        }

        self.assertEqual(
            _pipeline_metric_map_for_crit(runtime, tie),
            {
                ("entitat", "club a"): 17.0,
                ("entitat", "club b"): 7.5,
            },
        )
