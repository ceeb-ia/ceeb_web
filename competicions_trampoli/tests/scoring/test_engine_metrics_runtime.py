from django.test import SimpleTestCase

from competicions_trampoli.services.classificacions.engine.metrics_runtime import (
    _pipeline_metric_map_for_crit,
    _pipeline_subject_key,
    _sanitize_desempat_for_tipus,
    build_metrics_runtime_adapters,
    build_pipeline_runtime_context,
    build_metrics_runtime,
    calc_metric_value_for_group,
    calc_metric_value_for_ins,
    calc_metric_value_for_native_team,
)
from competicions_trampoli.services.classificacions.engine.victories import build_victories_adapters


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

    def test_build_pipeline_runtime_context_caches_and_adapts_group_helpers(self):
        calls = {"cache_keys": [], "rows": [], "contributors": []}

        def derived_team_cache_key(_equip_id, member_ids):
            mids = tuple(member_ids)
            calls["cache_keys"].append(mids)
            return f"group:{','.join(str(item) for item in mids)}"

        def get_main_selected_rows_for_group(cache_key, member_ids):
            calls["rows"].append((cache_key, tuple(member_ids)))
            return {"cache_key": cache_key, "member_ids": tuple(member_ids)}

        def get_main_selected_contributors_for_group(cache_key, member_ids):
            calls["contributors"].append((cache_key, tuple(member_ids)))
            return [{"cache_key": cache_key, "member_ids": tuple(member_ids)}]

        runtime = build_metrics_runtime(
            tipus="equips",
            team_mode="derived_from_individual",
            derived_team_cache_key=derived_team_cache_key,
            get_main_selected_rows_for_group=get_main_selected_rows_for_group,
            get_main_selected_contributors_for_group=get_main_selected_contributors_for_group,
        )

        ctx = build_pipeline_runtime_context(runtime)
        self.assertIs(ctx, build_pipeline_runtime_context(runtime))

        self.assertEqual(
            ctx["get_main_selected_rows_for_group"]([11, 12]),
            {"cache_key": "group:11,12", "member_ids": (11, 12)},
        )
        self.assertEqual(
            ctx["get_main_selected_contributors_for_group"]([11, 12]),
            [{"cache_key": "group:11,12", "member_ids": (11, 12)}],
        )
        self.assertEqual(calls["cache_keys"], [(11, 12), (11, 12)])
        self.assertEqual(calls["rows"], [("group:11,12", (11, 12))])
        self.assertEqual(calls["contributors"], [("group:11,12", (11, 12))])

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

    def test_pipeline_metric_map_for_crit_supports_group_subjects_with_team_pool(self):
        selected_rows = {
            "group:501": {
                1: [
                    _row(app_id=1, idx=1, inscripcio_id=201, camp_values={"E": 8.0}),
                    _row(app_id=1, idx=2, inscripcio_id=202, camp_values={"E": 9.5}),
                ]
            },
            "group:502": {
                1: [_row(app_id=1, idx=1, inscripcio_id=203, camp_values={"E": 7.25})]
            },
        }

        runtime = build_metrics_runtime(
            tipus="equips",
            team_mode="derived_from_individual",
            selected_app_ids=[1],
            app_order={1: 1},
            group_subjects=[
                {"equip_id": 501, "member_ids": [201, 202]},
                {"equip_id": 502, "member_ids": [203]},
            ],
            derived_team_cache_key=lambda _equip_id, mids: "group:501" if tuple(mids) == (201, 202) else "group:502",
            get_main_selected_rows_for_group=lambda cache_key, _mids: selected_rows[cache_key],
        )

        tie = {
            "id": "pipe-team-pool",
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
                "exercise_selection_scope": "team_pool",
            },
        }

        self.assertEqual(
            _pipeline_metric_map_for_crit(runtime, tie),
            {
                ("equip", 501): 17.5,
                ("members", (201, 202)): 17.5,
                ("equip", 502): 7.25,
                ("members", (203,)): 7.25,
            },
        )

    def test_bound_metric_and_victories_adapters_apply_per_app_duels(self):
        runtime = build_metrics_runtime(
            tipus="individual",
            selected_app_ids=[1, 2],
            per_ins={1: {}, 2: {}},
            app_order={1: 1, 2: 2},
            app_ex_rows_by_ins={
                1: {
                    1: [_row(app_id=1, idx=1, inscripcio_id=1, camp_values={"E": 9.0})],
                    2: [_row(app_id=1, idx=1, inscripcio_id=2, camp_values={"E": 8.0})],
                },
                2: {
                    1: [_row(app_id=2, idx=1, inscripcio_id=1, camp_values={"E": 7.0})],
                    2: [_row(app_id=2, idx=1, inscripcio_id=2, camp_values={"E": 8.5})],
                },
            },
        )
        metric_adapters = build_metrics_runtime_adapters(runtime)
        victories_adapters = build_victories_adapters(metric_adapters["calc_metric_value_for_ins"])
        pipeline_tie = {
            "id": "pipe-individual-e",
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

        ranked_rows = victories_adapters["apply_victories_per_app_to_rows"](
            [
                {"inscripcio_id": 1, "participant": "A", "by_app_base": {1: 10.0, 2: 10.0}},
                {"inscripcio_id": 2, "participant": "B", "by_app_base": {1: 10.0, 2: 10.0}},
            ],
            [1, 2],
            "desc",
            "sum",
            {
                "punts_victoria": 1.0,
                "punts_empat": 0.5,
                "desempat_comparacio": [{"camp": "E", "ordre": "desc"}],
            },
        )
        by_name = {row["participant"]: row for row in ranked_rows}

        self.assertEqual(
            metric_adapters["pipeline_metric_map_for_crit"](pipeline_tie),
            {("ins", 1): 9.0, ("ins", 2): 8.0},
        )
        self.assertEqual(by_name["A"]["by_app"], {1: 1.0, 2: 0.0})
        self.assertEqual(by_name["B"]["by_app"], {1: 0.0, 2: 1.0})
        self.assertEqual(by_name["A"]["score"], 1.0)
        self.assertEqual(by_name["B"]["score"], 1.0)
