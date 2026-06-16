from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0073_competicio_classificacions_view"),
    ]

    operations = [
        migrations.AddField(
            model_name="judgeportalassignment",
            name="subject_scope",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
