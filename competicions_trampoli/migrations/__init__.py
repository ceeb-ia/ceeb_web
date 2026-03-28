from django.db import migrations


if not hasattr(migrations, "RenameIndex"):
    class RenameIndex(migrations.RunPython):
        def __init__(self, *args, **kwargs):
            super().__init__(migrations.RunPython.noop, migrations.RunPython.noop)


    migrations.RenameIndex = RenameIndex
