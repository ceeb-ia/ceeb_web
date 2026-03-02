from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from ceeb_web.auth_groups import GLOBAL_AUTH_GROUPS


class Command(BaseCommand):
    help = "Create or confirm the baseline global auth groups for the backoffice."

    @transaction.atomic
    def handle(self, *args, **options):
        created = 0
        existing = 0

        for name, description in GLOBAL_AUTH_GROUPS.items():
            group, was_created = Group.objects.get_or_create(name=name)
            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(f"Created group: {name}"))
            else:
                existing += 1
                self.stdout.write(f"Group already exists: {name}")

            self.stdout.write(f"  - {description}")

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Global auth groups ready. created={created} existing={existing}"
            )
        )
