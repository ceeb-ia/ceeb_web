from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0063_score_entries_phase_scope"),
    ]

    operations = [
        migrations.AddField(
            model_name="classificacioconfig",
            name="publicada",
            field=models.BooleanField(default=True),
        ),
    ]
