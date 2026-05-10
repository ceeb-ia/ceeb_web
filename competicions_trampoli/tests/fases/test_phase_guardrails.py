from django.test import TestCase

from ...models.scoring import ScoreEntry, TeamScoreEntry


class PhaseRuntimeContractTests(TestCase):
    def test_score_entries_are_scoped_by_fase_without_english_alias(self):
        score_fields = {field.name for field in ScoreEntry._meta.get_fields()}
        team_score_fields = {field.name for field in TeamScoreEntry._meta.get_fields()}

        self.assertIn("fase", score_fields)
        self.assertNotIn("phase", score_fields)
        self.assertIn("fase", team_score_fields)
        self.assertNotIn("phase", team_score_fields)
