from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0072_competicio_data_fi"),
    ]

    operations = [
        migrations.AddField(
            model_name="competicio",
            name="classificacions_view",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
