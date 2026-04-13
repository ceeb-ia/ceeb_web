from __future__ import annotations

from collections import defaultdict

import pandas as pd
from django.core.management.base import BaseCommand
from django.db import transaction

from designacions.geolocate import clusteritza_i_plota
from designacions.models import Address, AddressCluster, Assignment, DesignationRun, Match
from designacions.services.addressing import build_address_payload, resolve_address
from designacions.services.geocoding_db import addresses_to_df
from designacions.services.manual_assignment import (
    build_manual_assignment_context,
    diagnose_assignment_for_referee,
    update_run_mobility_summary,
)


AUTO_REVIEW_PREFIX = "Revisio automatica: "


def _cluster_status_from_values(cluster_value, lat_value, lon_value) -> str:
    if lat_value is None or pd.isna(lat_value) or lon_value is None or pd.isna(lon_value):
        return "missing_geocode"
    if cluster_value is None or pd.isna(cluster_value):
        return "outlier"
    try:
        if int(cluster_value) == -1:
            return "outlier"
    except (TypeError, ValueError):
        pass
    return "clustered"


class Command(BaseCommand):
    help = "Repara coherencia de geolocalitzacio, clusters per run i avisos d'assignacions invalidades."

    def add_arguments(self, parser):
        parser.add_argument("--run-id", type=int, default=None, help="Limita la reparacio a un run concret.")
        parser.add_argument(
            "--audit-only",
            action="store_true",
            help="Mostra incoherencies sense escriure canvis.",
        )

    def handle(self, *args, **options):
        run_id = options.get("run_id")
        audit_only = options.get("audit_only", False)

        runs = DesignationRun.objects.all().order_by("id")
        if run_id:
            runs = runs.filter(id=run_id)

        address_stats = self._sync_addresses(audit_only=audit_only)
        match_stats = self._sync_matches(audit_only=audit_only, runs=runs)
        cluster_stats = self._rebuild_clusters(audit_only=audit_only, runs=runs)
        assignment_stats = self._revalidate_assignments(audit_only=audit_only, runs=runs)

        self.stdout.write(
            self.style.SUCCESS(
                "Repair completat. "
                f"Addresses actualitzades={address_stats['updated']}, "
                f"matches resolts={match_stats['updated']}, "
                f"clusters actualitzats={cluster_stats['updated']}, "
                f"assignacions marcades={assignment_stats['flagged']}."
            )
        )
        self.stdout.write(
            "Incoherencies: "
            f"matches_sense_address={match_stats['missing_address']}, "
            f"addresses_coords_estat_incorrecte={address_stats['coords_status_mismatch']}, "
            f"clusters_sense_status={cluster_stats['missing_status']}, "
            f"assignacions_amb_warning={assignment_stats['warnings_total']}."
        )

    def _sync_addresses(self, *, audit_only: bool) -> dict:
        stats = defaultdict(int)
        for address in Address.objects.all().order_by("id"):
            payload = build_address_payload(text=address.text, municipality=address.municipality)
            desired_status = address.geocode_status
            if address.lat is not None and address.lon is not None:
                if address.geocode_status not in {"ok", "manual"}:
                    stats["coords_status_mismatch"] += 1
                    desired_status = "ok"
            elif address.geocode_status in {"ok", "manual"}:
                stats["coords_status_mismatch"] += 1
                desired_status = "pending"

            update_fields = []
            if address.normalized_text != payload["normalized_text"]:
                address.normalized_text = payload["normalized_text"]
                update_fields.append("normalized_text")
            if payload["text"] and address.text != payload["text"]:
                address.text = payload["text"]
                update_fields.append("text")
            if payload["municipality"] and address.municipality != payload["municipality"]:
                address.municipality = payload["municipality"]
                update_fields.append("municipality")
            if address.geocode_status != desired_status:
                address.geocode_status = desired_status
                update_fields.append("geocode_status")
            if desired_status in {"ok", "manual"} and address.last_error:
                address.last_error = None
                update_fields.append("last_error")

            if update_fields:
                stats["updated"] += 1
                if not audit_only:
                    address.save(update_fields=update_fields + ["updated_at"])
        return stats

    def _sync_matches(self, *, audit_only: bool, runs) -> dict:
        stats = defaultdict(int)
        matches = Match.objects.filter(run__in=runs).select_related("address")
        for match in matches:
            resolved = resolve_address(domicile=match.domicile, municipality=match.municipality)
            if resolved is None:
                stats["missing_address"] += 1
                continue
            if match.address_id != resolved.id:
                stats["updated"] += 1
                if not audit_only:
                    match.address = resolved
                    match.save(update_fields=["address"])
        return stats

    @transaction.atomic
    def _rebuild_clusters(self, *, audit_only: bool, runs) -> dict:
        stats = defaultdict(int)
        for run in runs:
            matches = list(run.matches.select_related("address").exclude(address__isnull=True))
            address_ids = sorted({match.address_id for match in matches if match.address_id})
            if not address_ids:
                continue

            addresses = list(Address.objects.filter(id__in=address_ids).order_by("id"))
            df_addresses = addresses_to_df(addresses)
            if df_addresses.empty:
                continue

            params = run.params or {}
            clustered, _, _, _ = clusteritza_i_plota(
                df_addresses,
                lat_col="lat",
                lon_col="lon",
                eps_metres=float(params.get("cluster_eps_m", 500)),
                min_samples=int(params.get("cluster_min_samples", 2)),
                max_punts_per_subcluster=int(params.get("max_partits_subgrup", 3)),
            )

            rows_by_address_id = {}
            for _, row in clustered.iterrows():
                address_id = row.get("address_id")
                if pd.isna(address_id):
                    continue
                rows_by_address_id[int(address_id)] = row

            stale_qs = AddressCluster.objects.filter(run=run).exclude(address_id__in=address_ids)
            if stale_qs.exists():
                stats["updated"] += stale_qs.count()
                if not audit_only:
                    stale_qs.delete()

            for address in addresses:
                row = rows_by_address_id.get(address.id)
                if row is None:
                    cluster_status = "missing_geocode" if address.lat is None or address.lon is None else "pending"
                    cluster_id = None
                else:
                    cluster_status = _cluster_status_from_values(row.get("cluster"), row.get("lat"), row.get("lon"))
                    cluster_id = row.get("cluster")
                    if pd.isna(cluster_id) or int(cluster_id) == -1:
                        cluster_id = None
                    else:
                        cluster_id = int(cluster_id)

                existing = AddressCluster.objects.filter(run=run, address=address).first()
                if existing and not existing.cluster_status:
                    stats["missing_status"] += 1
                if existing and existing.cluster_id == cluster_id and existing.cluster_status == cluster_status:
                    continue

                stats["updated"] += 1
                if not audit_only:
                    AddressCluster.objects.update_or_create(
                        run=run,
                        address=address,
                        defaults={"cluster_id": cluster_id, "cluster_status": cluster_status},
                    )
        return stats

    def _revalidate_assignments(self, *, audit_only: bool, runs) -> dict:
        stats = defaultdict(int)
        for run in runs:
            context = build_manual_assignment_context(run)
            update_run_mobility_summary(run, context=context, save=not audit_only)
            assignments = run.assignments.select_related("match", "referee").filter(referee__isnull=False)
            for assignment in assignments:
                diagnosis = diagnose_assignment_for_referee(
                    run,
                    assignment,
                    assignment.referee,
                    availability_lookup=context["availability_lookup"],
                    assignments_by_referee=context["assignments_by_referee"],
                    cluster_by_match_id=context["cluster_by_match_id"],
                )
                if diagnosis["is_valid"]:
                    if assignment.manual_override_warning:
                        stats["warnings_total"] += 1
                    if assignment.manual_override_warning and assignment.manual_override_reason.startswith(AUTO_REVIEW_PREFIX):
                        stats["updated"] += 1
                        if not audit_only:
                            assignment.manual_override_warning = False
                            assignment.manual_override_reason = ""
                            assignment.save(update_fields=["manual_override_warning", "manual_override_reason", "updated_at"])
                    continue

                stats["flagged"] += 1
                stats["warnings_total"] += 1
                reason_text = diagnosis["warning_text"] or ", ".join(diagnosis["warning_reasons"])
                new_reason = AUTO_REVIEW_PREFIX + reason_text
                if assignment.manual_override_warning and assignment.manual_override_reason == new_reason:
                    continue

                stats["updated"] += 1
                if not audit_only:
                    assignment.manual_override_warning = True
                    assignment.manual_override_reason = new_reason
                    assignment.save(update_fields=["manual_override_warning", "manual_override_reason", "updated_at"])
        return stats
