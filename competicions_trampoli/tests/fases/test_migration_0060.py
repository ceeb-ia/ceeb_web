from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


PREVIOUS = ("competicions_trampoli", "0059_competicioaparell_local_identity")
TARGET = ("competicions_trampoli", "0060_competicioaparellfase")


class Migration0060DefaultPhaseBackfillTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)

    def tearDown(self):
        self.executor.loader.build_graph()
        self.executor.migrate(self.executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_migration_backfills_default_phase_for_existing_competicio_aparell(self):
        self.executor.migrate([PREVIOUS])
        previous_apps = self.executor.loader.project_state([PREVIOUS]).apps
        User = previous_apps.get_model("auth", "User")
        Competicio = previous_apps.get_model("competicions_trampoli", "Competicio")
        Aparell = previous_apps.get_model("competicions_trampoli", "Aparell")
        CompeticioAparell = previous_apps.get_model("competicions_trampoli", "CompeticioAparell")

        user = User.objects.create_user(username="phase_migration_owner", password="testpass123")
        competicio = Competicio.objects.create(nom="Comp migracio fases", tipus="trampoli")
        aparell = Aparell.objects.create(codi="TRA", nom="Trampoli", created_by=user)
        comp_aparell = CompeticioAparell.objects.create(
            competicio=competicio,
            aparell=aparell,
            nom_local="Trampoli",
            codi_local="TRA",
            ordre=1,
        )

        self.executor.loader.build_graph()
        self.executor.migrate([TARGET])
        target_apps = self.executor.loader.project_state([TARGET]).apps
        CompeticioAparellFase = target_apps.get_model("competicions_trampoli", "CompeticioAparellFase")

        phase = CompeticioAparellFase.objects.get(comp_aparell_id=comp_aparell.id)
        self.assertEqual(phase.competicio_id, competicio.id)
        self.assertEqual(phase.nom, "Fase unica")
        self.assertEqual(phase.codi, "DEFAULT")
        self.assertEqual(phase.estat, "published")
        self.assertEqual(phase.config.get("source_mode"), "legacy_default")
