from django.test import SimpleTestCase

from ...services.classificacions.provenance import (
    build_derived_row,
    build_raw_row,
    build_selection_snapshot,
    collect_contributor_rows,
    collect_contributor_rows_by_app,
    collect_participant_ids,
    resolve_main_selected_contributors,
    row_identity,
    with_source_rows,
)


class ProvenanceQueryTests(SimpleTestCase):
    def test_collect_contributor_rows_returns_leaf_rows(self):
        ex1 = {"row_id": "r1", "app_id": 10, "exercici": 1, "inscripcio_id": 100, "value": 12.5}
        ex2 = {"row_id": "r2", "app_id": 10, "exercici": 2, "inscripcio_id": 100, "value": 13.0}
        candidate = with_source_rows(
            {"row_id": "candidate-1", "app_id": 10, "inscripcio_id": 100, "value": 25.5},
            [ex1, ex2],
        )

        contributors = collect_contributor_rows([candidate])

        self.assertEqual([row["row_id"] for row in contributors], ["r1", "r2"])

    def test_collect_contributor_rows_dedupes_nested_source_rows(self):
        leaf = {"row_id": "leaf-1", "app_id": 11, "exercici": 1, "inscripcio_id": 101, "value": 9.4}
        candidate = with_source_rows(
            {"row_id": "candidate-2", "app_id": 11, "inscripcio_id": 101, "value": 9.4},
            [leaf],
        )
        selected = with_source_rows(
            {"row_id": "selected-2", "app_id": 11, "inscripcio_id": 101, "value": 9.4},
            [candidate, leaf],
        )

        contributors = collect_contributor_rows([selected])

        self.assertEqual([row["row_id"] for row in contributors], ["leaf-1"])

    def test_collect_contributor_rows_by_app_groups_by_leaf_app(self):
        row_a = {"row_id": "a1", "app_id": 21, "exercici": 1, "inscripcio_id": 201, "value": 7.0}
        row_b = {"row_id": "b1", "app_id": 22, "exercici": 1, "inscripcio_id": 201, "value": 8.0}
        mixed = with_source_rows(
            {"row_id": "mix", "app_id": 99, "inscripcio_id": 201, "value": 15.0},
            [row_a, row_b],
        )

        grouped = collect_contributor_rows_by_app({99: [mixed]})

        self.assertEqual(sorted(grouped.keys()), [21, 22])
        self.assertEqual([row["row_id"] for row in grouped[21]], ["a1"])
        self.assertEqual([row["row_id"] for row in grouped[22]], ["b1"])

    def test_resolve_main_selected_contributors_can_filter_selected_members(self):
        member_1 = with_source_rows(
            {"row_id": "member-1-picked", "app_id": 31, "inscripcio_id": 301, "value": 12.0},
            [{"row_id": "m1-ex1", "app_id": 31, "exercici": 1, "inscripcio_id": 301, "value": 12.0}],
        )
        member_2 = with_source_rows(
            {"row_id": "member-2-picked", "app_id": 31, "inscripcio_id": 302, "value": 11.5},
            [{"row_id": "m2-ex1", "app_id": 31, "exercici": 1, "inscripcio_id": 302, "value": 11.5}],
        )

        grouped = resolve_main_selected_contributors(
            {31: [member_1, member_2]},
            selected_participant_ids=[302],
            participant_key="inscripcio_id",
        )

        self.assertEqual([row["row_id"] for row in grouped[31]], ["m2-ex1"])

    def test_collect_participant_ids_keeps_stable_unique_order(self):
        rows = [
            {"inscripcio_id": 401},
            {"inscripcio_id": 402},
            {"inscripcio_id": 401},
        ]

        self.assertEqual(collect_participant_ids(rows), (401, 402))

    def test_builders_create_stable_contract_values(self):
        row = {"app_id": 41, "exercici": 2, "inscripcio_id": 501, "value": 6.7, "by_camp": {"D": 6.7}}
        source = {"row_id": "src-1", "app_id": 41, "exercici": 2, "inscripcio_id": 501, "value": 6.7}

        raw_row = build_raw_row(row, participant_kind="inscripcio")
        derived_row = build_derived_row(row, stage="exercise_selection", source_rows=[source], participant_kind="inscripcio")
        snapshot = build_selection_snapshot(
            stage="exercise_selection",
            app_id=41,
            subject_kind="individual",
            subject_id=501,
            rows=[source],
        )

        self.assertEqual(raw_row.row_id, row_identity(row))
        self.assertEqual(derived_row.source_row_ids, ("src-1",))
        self.assertEqual(snapshot.selected_row_ids, ("src-1",))
