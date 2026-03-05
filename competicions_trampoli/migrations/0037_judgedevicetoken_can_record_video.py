from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0036_publiclivetoken_can_view_media"),
    ]

    operations = [
        migrations.AddField(
            model_name="judgedevicetoken",
            name="can_record_video",
            field=models.BooleanField(default=False),
        ),
    ]
