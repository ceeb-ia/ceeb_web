from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("competicions_trampoli", "0034_rename_competicion_status_26cc34_idx_competicion_status_1bf60d_idx_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="CompeticioMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("owner", "Owner"), ("editor", "Editor"), ("judge_admin", "Judge Admin"), ("scoring", "Scoring"), ("rotacions", "Rotacions"), ("classificacions", "Classificacions"), ("readonly", "Readonly")], default="readonly", max_length=30)),
                ("is_active", models.BooleanField(default=True)),
                ("notes", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("competicio", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="competicions_trampoli.competicio")),
                ("granted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="granted_competicio_memberships", to=settings.AUTH_USER_MODEL)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="competicio_memberships", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["competicio_id", "user_id"],
            },
        ),
        migrations.AddIndex(
            model_name="competiciomembership",
            index=models.Index(fields=["competicio", "role", "is_active"], name="competicion_competi_043c1d_idx"),
        ),
        migrations.AddIndex(
            model_name="competiciomembership",
            index=models.Index(fields=["user", "is_active"], name="competicion_user_id_bf218f_idx"),
        ),
        migrations.AddConstraint(
            model_name="competiciomembership",
            constraint=models.UniqueConstraint(fields=("user", "competicio"), name="uniq_competicio_membership_user_competicio"),
        ),
    ]
