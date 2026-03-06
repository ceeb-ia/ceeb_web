from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Case, IntegerField, Value, When

from ...models import CompeticioMembership
from ...models_classificacions import ClassificacioTemplateGlobal


class Command(BaseCommand):
    help = (
        "Assigna created_by a les plantilles de classificacio existents. "
        "Si no es pot deduir propietari des de source.competicio_id, usa fallback-user."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fallback-user",
            dest="fallback_user",
            default="",
            help="Username de fallback per plantilles sense owner deduible.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="No escriu canvis, nomes mostra resum.",
        )

    def _resolve_fallback_user(self, fallback_username: str):
        User = get_user_model()
        if fallback_username:
            user = User.objects.filter(username=fallback_username).first()
            if not user:
                raise CommandError(f"No existeix l'usuari fallback '{fallback_username}'.")
            return user

        user = User.objects.filter(is_superuser=True).order_by("id").first()
        if user:
            return user

        user = User.objects.order_by("id").first()
        if user:
            return user

        raise CommandError("No hi ha usuaris al sistema per assignar com a fallback.")

    def _build_owner_map(self):
        owner_rank = Case(
            When(role=CompeticioMembership.Role.OWNER, then=Value(0)),
            When(role=CompeticioMembership.Role.EDITOR, then=Value(1)),
            default=Value(99),
            output_field=IntegerField(),
        )
        rows = (
            CompeticioMembership.objects
            .filter(is_active=True)
            .annotate(owner_rank=owner_rank)
            .order_by("competicio_id", "owner_rank", "id")
            .values_list("competicio_id", "user_id", "owner_rank")
        )
        owner_by_comp = {}
        for competicio_id, user_id, rank in rows:
            if rank > 1:
                continue
            if competicio_id not in owner_by_comp:
                owner_by_comp[competicio_id] = user_id
        return owner_by_comp

    @staticmethod
    def _extract_source_competicio_id(template_obj):
        payload = getattr(template_obj, "payload", None) or {}
        if not isinstance(payload, dict):
            return None
        source = payload.get("source") or {}
        if not isinstance(source, dict):
            return None
        raw = source.get("competicio_id")
        try:
            return int(raw)
        except Exception:
            return None

    def _run(self, *, dry_run: bool, fallback_user_id: int):
        owner_by_comp = self._build_owner_map()

        total = 0
        already_owned = 0
        updated = 0
        resolved_from_source = 0
        fallback_assigned = 0

        templates = list(ClassificacioTemplateGlobal.objects.order_by("id"))
        total = len(templates)

        for tpl in templates:
            if tpl.created_by_id:
                already_owned += 1
                continue

            comp_id = self._extract_source_competicio_id(tpl)
            owner_id = owner_by_comp.get(comp_id) if comp_id else None
            if owner_id:
                resolved_from_source += 1
            else:
                owner_id = fallback_user_id
                fallback_assigned += 1

            updated += 1
            if not dry_run:
                tpl.created_by_id = owner_id
                tpl.save(update_fields=["created_by"])

        return {
            "total_templates": total,
            "already_owned": already_owned,
            "updated": updated,
            "resolved_from_source": resolved_from_source,
            "fallback_assigned": fallback_assigned,
            "dry_run": dry_run,
        }

    def handle(self, *args, **options):
        fallback_user = self._resolve_fallback_user(options.get("fallback_user") or "")
        dry_run = bool(options.get("dry_run"))

        self.stdout.write(
            f"Fallback user: {fallback_user.username} (id={fallback_user.id}) | dry_run={dry_run}"
        )

        if dry_run:
            summary = self._run(dry_run=True, fallback_user_id=fallback_user.id)
        else:
            with transaction.atomic():
                summary = self._run(dry_run=False, fallback_user_id=fallback_user.id)

        self.stdout.write(self.style.SUCCESS("Backfill de plantilles de classificacio completat."))
        for k, v in summary.items():
            self.stdout.write(f"- {k}: {v}")
