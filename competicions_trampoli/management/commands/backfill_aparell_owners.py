import copy

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Case, IntegerField, Value, When

from ...models import CompeticioMembership
from ...models_scoring import ScoringSchema
from ...models_trampoli import Aparell, CompeticioAparell


class Command(BaseCommand):
    help = (
        "Assigna created_by als Aparell existents. "
        "Si un Aparell esta compartit entre propietaris diferents, el duplica i reassigna CompeticioAparell."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fallback-user",
            dest="fallback_user",
            default="",
            help="Username de fallback per competicions sense owner/editor i aparells orfes.",
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

    def _build_owner_map(self, fallback_user_id: int):
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
        self.stdout.write(
            f"Owner map carregat: {len(owner_by_comp)} competicions amb owner/editor."
        )
        self._fallback_user_id = fallback_user_id
        return owner_by_comp

    def _owner_for_comp(self, comp_id: int, owner_by_comp: dict[int, int]) -> int:
        return owner_by_comp.get(comp_id) or self._fallback_user_id

    def _run(self, *, dry_run: bool, fallback_user_id: int):
        owner_by_comp = self._build_owner_map(fallback_user_id)

        total_aparells = 0
        updated_owner = 0
        created_clones = 0
        cloned_schemas = 0
        reassigned_links = 0
        orphan_assigned = 0
        skipped_conflicts = 0

        aparells = list(Aparell.objects.all().order_by("id"))
        total_aparells = len(aparells)

        for ap in aparells:
            links = list(
                CompeticioAparell.objects
                .filter(aparell_id=ap.id)
                .values("id", "competicio_id")
            )
            if not links:
                target_owner_id = ap.created_by_id or fallback_user_id
                if ap.created_by_id != target_owner_id:
                    orphan_assigned += 1
                    if not dry_run:
                        ap.created_by_id = target_owner_id
                        ap.save(update_fields=["created_by"])
                continue

            owner_ids = {
                self._owner_for_comp(link["competicio_id"], owner_by_comp)
                for link in links
            }
            if not owner_ids:
                owner_ids = {fallback_user_id}

            if len(owner_ids) == 1:
                target_owner_id = next(iter(owner_ids))
                if ap.created_by_id != target_owner_id:
                    updated_owner += 1
                    if not dry_run:
                        ap.created_by_id = target_owner_id
                        ap.save(update_fields=["created_by"])
                continue

            canonical_owner_id = ap.created_by_id if ap.created_by_id in owner_ids else min(owner_ids)
            if ap.created_by_id != canonical_owner_id:
                updated_owner += 1
                if not dry_run:
                    ap.created_by_id = canonical_owner_id
                    ap.save(update_fields=["created_by"])

            base_schema = (
                ScoringSchema.objects
                .filter(aparell_id=ap.id)
                .only("id", "schema")
                .first()
            )

            for owner_id in sorted(owner_ids):
                if owner_id == canonical_owner_id:
                    continue

                clone = Aparell.objects.filter(created_by_id=owner_id, codi=ap.codi).first()
                if clone is None:
                    created_clones += 1
                    if not dry_run:
                        clone = Aparell.objects.create(
                            codi=ap.codi,
                            nom=ap.nom,
                            actiu=ap.actiu,
                            created_by_id=owner_id,
                        )
                if clone is None:
                    continue

                if base_schema and not ScoringSchema.objects.filter(aparell_id=clone.id).exists():
                    cloned_schemas += 1
                    if not dry_run:
                        ScoringSchema.objects.create(
                            aparell=clone,
                            schema=copy.deepcopy(base_schema.schema or {}),
                        )

                target_comp_ids = {
                    link["competicio_id"]
                    for link in links
                    if self._owner_for_comp(link["competicio_id"], owner_by_comp) == owner_id
                }
                for link in links:
                    if link["competicio_id"] not in target_comp_ids:
                        continue
                    ca_id = link["id"]
                    if not dry_run:
                        ca = CompeticioAparell.objects.select_related("aparell").get(pk=ca_id)
                        if ca.aparell_id == clone.id:
                            continue
                        conflict = CompeticioAparell.objects.filter(
                            competicio_id=ca.competicio_id,
                            aparell_id=clone.id,
                        ).exclude(pk=ca.id).exists()
                        if conflict:
                            skipped_conflicts += 1
                            continue
                        ca.aparell = clone
                        ca.save(update_fields=["aparell"])
                    reassigned_links += 1

        return {
            "total_aparells": total_aparells,
            "updated_owner": updated_owner,
            "created_clones": created_clones,
            "cloned_schemas": cloned_schemas,
            "reassigned_links": reassigned_links,
            "orphan_assigned": orphan_assigned,
            "skipped_conflicts": skipped_conflicts,
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

        self.stdout.write(self.style.SUCCESS("Backfill d'aparells completat."))
        for k, v in summary.items():
            self.stdout.write(f"- {k}: {v}")
