from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0035_competiciomembership"),
    ]

    operations = [
        migrations.AddField(
            model_name="publiclivetoken",
            name="can_view_media",
            field=models.BooleanField(default=False),
        ),
    ]
