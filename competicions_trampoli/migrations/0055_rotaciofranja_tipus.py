from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0054_rename_competicion_serie_i_24c55a_idx_competicion_serie_i_c97877_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="rotaciofranja",
            name="tipus",
            field=models.CharField(
                choices=[
                    ("competition", "Competicio"),
                    ("break", "Descans"),
                    ("awards", "Premis"),
                    ("separator", "Separador"),
                ],
                db_index=True,
                default="competition",
                max_length=20,
            ),
        ),
    ]
