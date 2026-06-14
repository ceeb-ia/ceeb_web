from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0066_competicioaparell_participation_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="rotaciofranja",
            name="nota_interna",
            field=models.TextField(blank=True, default=""),
        ),
    ]
