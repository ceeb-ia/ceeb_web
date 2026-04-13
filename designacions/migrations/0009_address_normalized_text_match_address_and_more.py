from django.db import migrations, models
import django.db.models.deletion
import re
import unicodedata


_WHITESPACE_RE = re.compile(r"\s+")


def _clean_component(value):
    text = str(value or "").strip()
    if text.lower() in {"nan", "none"}:
        return ""
    text = _WHITESPACE_RE.sub(" ", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    return text.strip(" ,")


def _normalize_address(text):
    cleaned = _clean_component(text)
    normalized = unicodedata.normalize("NFKD", cleaned)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    ascii_text = re.sub(r"[^a-z0-9, ]+", " ", ascii_text)
    ascii_text = _WHITESPACE_RE.sub(" ", ascii_text)
    return ascii_text.strip(" ,")


def _compose_address(domicile, municipality):
    parts = [part for part in (_clean_component(domicile), _clean_component(municipality)) if part]
    return ", ".join(parts)


def backfill_addresses_and_matches(apps, schema_editor):
    Address = apps.get_model("designacions", "Address")
    Match = apps.get_model("designacions", "Match")
    AddressCluster = apps.get_model("designacions", "AddressCluster")

    seen_normalized = set()
    canonical_by_normalized = {}
    for address in Address.objects.order_by("id"):
        normalized = _normalize_address(address.text)
        if not normalized:
            normalized = f"address-{address.id}"
        if normalized in seen_normalized:
            normalized = f"{normalized}::{address.id}"
        seen_normalized.add(normalized)
        address.normalized_text = normalized
        address.save(update_fields=["normalized_text"])
        canonical_by_normalized.setdefault(_normalize_address(address.text), address.id)

    for match in Match.objects.order_by("id"):
        address_text = _compose_address(match.domicile, match.municipality)
        normalized = _normalize_address(address_text)
        address_id = canonical_by_normalized.get(normalized)
        if address_id:
            match.address_id = address_id
            match.save(update_fields=["address"])

    for cluster in AddressCluster.objects.select_related("address").order_by("id"):
        if cluster.cluster_id is not None:
            cluster.cluster_status = "clustered"
        elif getattr(cluster.address, "lat", None) is None or getattr(cluster.address, "lon", None) is None:
            cluster.cluster_status = "missing_geocode"
        else:
            cluster.cluster_status = "pending"
        cluster.save(update_fields=["cluster_status"])


class Migration(migrations.Migration):

    dependencies = [
        ("designacions", "0008_designationrun_map_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="address",
            name="normalized_text",
            field=models.CharField(blank=True, db_index=True, max_length=500, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="addresscluster",
            name="cluster_status",
            field=models.CharField(
                choices=[
                    ("pending", "pending"),
                    ("clustered", "clustered"),
                    ("outlier", "outlier"),
                    ("missing_geocode", "missing_geocode"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="match",
            name="address",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="matches",
                to="designacions.address",
            ),
        ),
        migrations.RunPython(backfill_addresses_and_matches, migrations.RunPython.noop),
    ]
