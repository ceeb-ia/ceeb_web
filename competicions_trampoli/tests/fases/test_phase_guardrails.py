from django.test import TestCase

from ...models.scoring import ScoreEntry, TeamScoreEntry


class Fase2RuntimeGuardrailTests(TestCase):
    def test_phase_model_does_not_change_score_entry_contract_yet(self):
        score_fields = {field.name for field in ScoreEntry._meta.get_fields()}
        team_score_fields = {field.name for field in TeamScoreEntry._meta.get_fields()}

        self.assertNotIn("fase", score_fields)
        self.assertNotIn("phase", score_fields)
        self.assertNotIn("fase", team_score_fields)
        self.assertNotIn("phase", team_score_fields)
