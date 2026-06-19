from django.test import SimpleTestCase

from ...services.classificacions.engine.ranking import _pipeline_tie_signature, _rank_v2


class RankingEngineTests(SimpleTestCase):
    def test_rank_v2_keeps_tied_rows_when_top_n_and_mostrar_empats(self):
        rows = [
            {"participant": "A", "score": 10.0, "tie": {"E": 8.0}},
            {"participant": "B", "score": 10.0, "tie": {"E": 8.0}},
            {"participant": "C", "score": 9.0, "tie": {"E": 9.0}},
        ]

        ranked = _rank_v2(
            rows,
            [{"camp": "E", "ordre": "desc"}],
            {"top_n": 1, "mostrar_empats": True},
        )

        self.assertEqual([row["participant"] for row in ranked], ["A", "B"])
        self.assertEqual([row["posicio"] for row in ranked], [1, 1])
        self.assertEqual([row["punts"] for row in ranked], [10.0, 10.0])

    def test_rank_v2_supports_pipeline_tie_with_explicit_id(self):
        rows = [
            {"participant": "A", "score": 10.0, "tie": {"pipeline-1": 7.0}},
            {"participant": "B", "score": 10.0, "tie": {"pipeline-1": 8.0}},
        ]

        ranked = _rank_v2(
            rows,
            [{"id": "pipeline-1", "ordre": "desc", "pipeline": {"camps_per_aparell": {"1": ["total"]}}}],
            {},
        )

        self.assertEqual([row["participant"] for row in ranked], ["B", "A"])
        self.assertEqual([row["posicio"] for row in ranked], [1, 2])
        self.assertEqual(
            ranked[0]["tiebreak_reason"],
            {
                "criterion_number": 1,
                "criterion_id": "pipeline-1",
                "label": "",
                "order": "desc",
                "winner_value": 8.0,
                "loser_value": 7.0,
            },
        )
        self.assertNotIn("tiebreak_reason", ranked[1])

    def test_rank_v2_supports_pipeline_tie_without_id_via_signature(self):
        tie = {"ordre": "desc", "pipeline": {"camps_per_aparell": {"1": ["total"]}}}
        key = _pipeline_tie_signature(tie)
        rows = [
            {"participant": "A", "score": 10.0, "tie": {key: 1.0}},
            {"participant": "B", "score": 10.0, "tie": {key: 2.0}},
        ]

        ranked = _rank_v2(rows, [tie], {})

        self.assertEqual([row["participant"] for row in ranked], ["B", "A"])

    def test_rank_v2_honors_ascending_primary_order(self):
        rows = [
            {"participant": "A", "score": 8.0, "tie": {}},
            {"participant": "B", "score": 6.0, "tie": {}},
        ]

        ranked = _rank_v2(rows, [], {}, ordre_principal="asc")

        self.assertEqual([row["participant"] for row in ranked], ["B", "A"])

    def test_rank_v2_reports_second_determining_criterion_with_label(self):
        rows = [
            {"participant": "A", "score": 10.0, "tie": {"first": 4.0, "second": 1.0}},
            {"participant": "B", "score": 10.0, "tie": {"first": 4.0, "second": 3.0}},
        ]

        ranked = _rank_v2(
            rows,
            [
                {"id": "first", "nom": "Execucio", "ordre": "desc", "pipeline": {}},
                {"id": "second", "nom": "Suma penalitzacions", "ordre": "asc", "pipeline": {}},
            ],
            {},
        )

        self.assertEqual([row["participant"] for row in ranked], ["A", "B"])
        self.assertEqual(ranked[0]["tiebreak_reason"]["criterion_number"], 2)
        self.assertEqual(ranked[0]["tiebreak_reason"]["label"], "Suma penalitzacions")
        self.assertEqual(ranked[0]["tiebreak_reason"]["order"], "asc")
        self.assertEqual(ranked[0]["tiebreak_reason"]["winner_value"], 1.0)
        self.assertEqual(ranked[0]["tiebreak_reason"]["loser_value"], 3.0)

    def test_rank_v2_does_not_report_reason_for_real_tie_or_different_primary_score(self):
        real_tie = _rank_v2(
            [
                {"participant": "A", "score": 10.0, "tie": {"tie": 2.0}},
                {"participant": "B", "score": 10.0, "tie": {"tie": 2.0}},
            ],
            [{"id": "tie", "nom": "Execucio", "ordre": "desc", "pipeline": {}}],
            {},
        )
        different_score = _rank_v2(
            [
                {"participant": "A", "score": 10.0, "tie": {"tie": 1.0}},
                {"participant": "B", "score": 9.0, "tie": {"tie": 3.0}},
            ],
            [{"id": "tie", "nom": "Execucio", "ordre": "desc", "pipeline": {}}],
            {},
        )

        self.assertNotIn("tiebreak_reason", real_tie[0])
        self.assertTrue(real_tie[0]["definitive_tie"])
        self.assertTrue(real_tie[1]["definitive_tie"])
        self.assertNotIn("tiebreak_reason", different_score[0])
        self.assertNotIn("definitive_tie", different_score[0])
        self.assertNotIn("definitive_tie", different_score[1])

    def test_rank_v2_marks_every_row_in_a_definitive_tie_group(self):
        ranked = _rank_v2(
            [
                {"participant": "A", "score": 10.0, "tie": {"tie": 2.0}},
                {"participant": "B", "score": 10.0, "tie": {"tie": 2.0}},
                {"participant": "C", "score": 10.0, "tie": {"tie": 2.0}},
            ],
            [{"id": "tie", "nom": "Execucio", "ordre": "desc", "pipeline": {}}],
            {},
        )

        self.assertEqual([row["posicio"] for row in ranked], [1, 1, 1])
        self.assertTrue(all(row.get("definitive_tie") is True for row in ranked))
