from importlib import import_module

from django.db import connection
from django.db import migrations
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


TARGET = (
    "competicions_trampoli",
    "0054_rename_competicion_serie_i_24c55a_idx_competicion_serie_i_c97877_idx_and_more",
)
PREVIOUS = ("competicions_trampoli", "0053_contextualize_equip")


class Migration0054RenameIndexTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)

    def tearDown(self):
        self.executor.loader.build_graph()
        self.executor.migrate(self.executor.loader.graph.leaf_nodes())
        super().tearDown()

    def _constraints_for_model(self, app_label, model_name):
        apps = self.executor.loader.project_state([TARGET]).apps
        model = apps.get_model(app_label, model_name)
        with connection.cursor() as cursor:
            return connection.introspection.get_constraints(cursor, model._meta.db_table)

    def _assert_target_indexes_present(self):
        serie_constraints = self._constraints_for_model("competicions_trampoli", "SerieEquip")
        item_constraints = self._constraints_for_model("competicions_trampoli", "SerieEquipItem")
        rotacio_constraints = self._constraints_for_model("competicions_trampoli", "RotacioAssignacioSerieEquip")

        self.assertIn("competicion_competi_531993_idx", serie_constraints)
        self.assertIn("competicion_serie_i_4b524d_idx", item_constraints)
        self.assertIn("competicion_team_su_18d79b_idx", item_constraints)
        self.assertIn("competicion_serie_i_c97877_idx", rotacio_constraints)

    def test_migrate_from_0053_to_0054_keeps_team_series_indexes_available(self):
        self.executor.migrate([PREVIOUS])
        self.executor.loader.build_graph()
        self.executor.migrate([TARGET])
        self._assert_target_indexes_present()

    def test_0054_uses_separate_database_and_state_operations(self):
        migration_0054 = import_module(
            "competicions_trampoli.migrations.0054_rename_competicion_serie_i_24c55a_idx_competicion_serie_i_c97877_idx_and_more"
        )

        self.assertEqual(len(migration_0054.Migration.operations), 4)
        for operation in migration_0054.Migration.operations:
            self.assertIsInstance(operation, migrations.SeparateDatabaseAndState)
            self.assertEqual(len(operation.database_operations), 1)
            self.assertEqual(len(operation.state_operations), 1)
