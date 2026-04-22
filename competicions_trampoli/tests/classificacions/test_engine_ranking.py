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
