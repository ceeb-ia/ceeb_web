import unittest

from ...services.classificacions.engine.team_pool_buckets import (
    DEFAULT_BUCKET_AGGREGATION,
    DEFAULT_BUCKET_PARTICIPANTS_CFG,
    TEAM_POOL_MODE_FLAT,
    TEAM_POOL_MODE_PER_EXERCISE,
    build_team_pool_bucket_rows,
    resolve_team_pool_bucket_config_for_exercise,
    resolve_team_pool_mode_for_app,
)


def _row(*, app_id, inscripcio_id, equip_id, exercici, value, by_camp=None, source_rows=None, row_id=None):
    item = {
        "idx": int(exercici),
        "value": float(value),
        "app_id": int(app_id),
        "app_order": int(app_id),
        "exercici": int(exercici),
        "inscripcio_id": int(inscripcio_id),
        "equip_id": int(equip_id),
        "by_camp": dict(by_camp or {}),
    }
    if row_id is not None:
        item["row_id"] = str(row_id)
    if source_rows is not None:
        item["source_rows"] = list(source_rows)
    return item


class EngineTeamPoolBucketsTests(unittest.TestCase):
    def test_build_team_pool_bucket_rows_groups_by_exercise_and_uses_per_bucket_cfg(self):
        rows = [
            _row(app_id=12, equip_id=77, inscripcio_id=303, exercici=2, value=6.0, by_camp={"total": 6.0, "E": 2.5}),
            _row(app_id=12, equip_id=77, inscripcio_id=101, exercici=1, value=9.0, by_camp={"total": 9.0, "E": 4.0}),
            _row(app_id=12, equip_id=77, inscripcio_id=202, exercici=2, value=8.0, by_camp={"total": 8.0, "E": 3.0}),
            _row(app_id=12, equip_id=77, inscripcio_id=303, exercici=1, value=7.0, by_camp={"total": 7.0, "E": 2.0}),
            _row(app_id=12, equip_id=77, inscripcio_id=202, exercici=1, value=8.0, by_camp={"total": 8.0, "E": 3.0}),
            _row(app_id=12, equip_id=77, inscripcio_id=101, exercici=2, value=5.0, by_camp={"total": 5.0, "E": 1.0}),
        ]

        bucket_rows = build_team_pool_bucket_rows(
            app_id=12,
            equip_id=77,
            rows=rows,
            team_pool_participants_per_exercici_per_aparell={
                "12": {
                    "1": {"mode": "millor_n", "n": 2},
                    "2": {"mode": "millor_n", "n": 2},
                }
            },
            team_pool_agregacio_participants_per_exercici_per_aparell={
                "12": {
                    "1": "sum",
                    "2": "max",
                }
            },
        )

        self.assertEqual([row["exercici"] for row in bucket_rows], [1, 2])

        first_bucket = bucket_rows[0]
        self.assertEqual(first_bucket["value"], 17.0)
        self.assertEqual(first_bucket["by_camp"], {"total": 17.0, "E": 7.0})
        self.assertEqual(first_bucket["team_pool_bucket_member_count"], 2)
        self.assertEqual(
            [(row["inscripcio_id"], row["exercici"], row["value"]) for row in first_bucket["source_rows"]],
            [(101, 1, 9.0), (202, 1, 8.0)],
        )

        second_bucket = bucket_rows[1]
        self.assertEqual(second_bucket["value"], 8.0)
        self.assertEqual(second_bucket["by_camp"], {"total": 8.0, "E": 3.0})
        self.assertEqual(second_bucket["team_pool_bucket_member_count"], 2)
        self.assertEqual(
            [(row["inscripcio_id"], row["exercici"], row["value"]) for row in second_bucket["source_rows"]],
            [(202, 2, 8.0), (303, 2, 6.0)],
        )

    def test_build_team_pool_bucket_rows_flattens_nested_source_rows(self):
        nested_source = [
            _row(app_id=12, equip_id=77, inscripcio_id=101, exercici=1, value=4.0, by_camp={"total": 4.0}, row_id="raw:101:1:a"),
            _row(app_id=12, equip_id=77, inscripcio_id=101, exercici=1, value=5.0, by_camp={"total": 5.0}, row_id="raw:101:1:b"),
        ]
        rows = [
            _row(
                app_id=12,
                equip_id=77,
                inscripcio_id=101,
                exercici=1,
                value=9.0,
                by_camp={"total": 9.0},
                source_rows=nested_source,
            ),
            _row(app_id=12, equip_id=77, inscripcio_id=202, exercici=1, value=8.0, by_camp={"total": 8.0}),
        ]

        bucket_rows = build_team_pool_bucket_rows(
            app_id=12,
            equip_id=77,
            rows=rows,
            team_pool_participants_per_exercici_per_aparell={"12": {"1": {"mode": "millor_1"}}},
            team_pool_agregacio_participants_per_exercici_per_aparell={"12": {"1": "sum"}},
        )

        self.assertEqual(len(bucket_rows), 1)
        self.assertEqual(
            [(row["inscripcio_id"], row["exercici"], row["value"]) for row in bucket_rows[0]["source_rows"]],
            [(101, 1, 4.0), (101, 1, 5.0)],
        )

    def test_build_team_pool_bucket_rows_returns_empty_for_empty_input(self):
        self.assertEqual(
            build_team_pool_bucket_rows(app_id=12, equip_id=77, rows=[]),
            [],
        )

    def test_build_team_pool_bucket_rows_uses_defaults_for_partial_config(self):
        rows = [
            _row(app_id=12, equip_id=77, inscripcio_id=101, exercici=1, value=4.0, by_camp={"total": 4.0}),
            _row(app_id=12, equip_id=77, inscripcio_id=202, exercici=1, value=9.0, by_camp={"total": 9.0}),
            _row(app_id=12, equip_id=77, inscripcio_id=101, exercici=2, value=8.0, by_camp={"total": 8.0}),
            _row(app_id=12, equip_id=77, inscripcio_id=202, exercici=2, value=3.0, by_camp={"total": 3.0}),
        ]

        bucket_rows = build_team_pool_bucket_rows(
            app_id=12,
            equip_id=77,
            rows=rows,
            team_pool_participants_per_exercici_per_aparell={"12": {"2": {"mode": "millor_1"}}},
            team_pool_agregacio_participants_per_exercici_per_aparell={"12": {"1": "max"}},
        )

        self.assertEqual([(row["exercici"], row["value"]) for row in bucket_rows], [(1, 9.0), (2, 8.0)])
        self.assertEqual(bucket_rows[0]["team_pool_bucket_aggregation"], "max")
        self.assertEqual(bucket_rows[1]["team_pool_bucket_aggregation"], DEFAULT_BUCKET_AGGREGATION)

    def test_resolve_team_pool_mode_and_bucket_config_for_app(self):
        self.assertEqual(resolve_team_pool_mode_for_app({"12": "per_exercici"}, 12), TEAM_POOL_MODE_PER_EXERCISE)
        self.assertEqual(resolve_team_pool_mode_for_app({}, 12), TEAM_POOL_MODE_FLAT)
        self.assertEqual(
            resolve_team_pool_bucket_config_for_exercise(app_id=12, exercici=3),
            (DEFAULT_BUCKET_PARTICIPANTS_CFG, DEFAULT_BUCKET_AGGREGATION),
        )


if __name__ == "__main__":
    unittest.main()
