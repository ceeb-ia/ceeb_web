from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("designacions", "0006_assignment_manual_override_warning_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "UPDATE designacions_assignment SET manual_override_warning = FALSE WHERE manual_override_warning IS NULL;",
                "UPDATE designacions_assignment SET manual_override_reason = '' WHERE manual_override_reason IS NULL;",
                "ALTER TABLE designacions_assignment ALTER COLUMN manual_override_warning SET DEFAULT FALSE;",
                "ALTER TABLE designacions_assignment ALTER COLUMN manual_override_reason SET DEFAULT '';",
            ],
            reverse_sql=[
                "ALTER TABLE designacions_assignment ALTER COLUMN manual_override_warning DROP DEFAULT;",
                "ALTER TABLE designacions_assignment ALTER COLUMN manual_override_reason DROP DEFAULT;",
            ],
        ),
    ]
