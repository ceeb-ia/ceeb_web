from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand
from django.db import transaction

from designacions.models import Address, AddressCluster, ModalityMap
from designacions.services.addressing import build_address_payload, resolve_address


def _safe_str(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def _cluster_status_from_csv(cluster_id, lat, lon) -> str:
    if lat is None or lon is None:
        return "missing_geocode"
    if cluster_id is None or cluster_id == -1:
        return "outlier"
    return "clustered"


class Command(BaseCommand):
    help = "Importa map_modalitat_nom.csv + domicilis_geocodificats.csv + (opcional) domicilis_clusteritzats.csv a la BD."

    def add_arguments(self, parser):
        parser.add_argument(
            "--base-dir",
            type=str,
            default=None,
            help="Directori on hi ha els CSV (ex: /app/designacions).",
        )
        parser.add_argument(
            "--run-id",
            type=int,
            default=None,
            help="Si s'indica, importa també domicilis_clusteritzats.csv i el guarda a AddressCluster per aquest run.",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        base_dir = Path(opts["base_dir"]).resolve() if opts["base_dir"] else Path(__file__).resolve().parents[3]
        run_id = opts.get("run_id")

        self.stdout.write(self.style.NOTICE(f"Base dir CSV: {base_dir}"))
        if run_id:
            self.stdout.write(self.style.NOTICE(f"Import clusters per run_id={run_id}"))

        path_map = base_dir / "designacions" / "map_modalitat_nom.csv"
        path_geo = base_dir / "designacions" / "domicilis_geocodificats.csv"
        path_cluster = base_dir / "designacions" / "domicilis_clusteritzats.csv"

        if path_map.exists():
            df = pd.read_csv(path_map, sep=";", encoding="utf-8-sig")
            required = ["Id Categoria", "Modalitat", "Nom", "Descripció", "Nom Abreviat", "Ordre", "CodiExtern"]
            missing = [column for column in required if column not in df.columns]
            if missing:
                raise Exception(f"Falten columnes a {path_map}: {missing}. Columnes actuals: {list(df.columns)}")

            upsert = 0
            for _, row in df.iterrows():
                id_cat = row.get("Id Categoria")
                id_cat = None if pd.isna(id_cat) else int(id_cat)

                modalitat = _safe_str(row.get("Modalitat"))
                nom = _safe_str(row.get("Nom"))
                if not modalitat or not nom:
                    continue

                key = f"{modalitat}::{nom}"
                if len(key) > 255:
                    import hashlib

                    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
                    key = key[:240] + "::" + digest

                defaults = {
                    "name": nom,
                    "id_categoria": id_cat,
                    "modalitat": modalitat,
                    "nom": nom,
                    "descripcio": _safe_str(row.get("Descripció")) or None,
                    "nom_abreviat": _safe_str(row.get("Nom Abreviat")) or None,
                    "ordre": None if pd.isna(row.get("Ordre")) else int(row.get("Ordre")),
                    "codi_extern": _safe_str(row.get("CodiExtern")) or None,
                }
                ModalityMap.objects.update_or_create(key=key, defaults=defaults)
                upsert += 1

            self.stdout.write(self.style.SUCCESS(f"ModalityMap importat/actualitzat: {upsert} files"))
        else:
            self.stdout.write(self.style.WARNING(f"No trobo {path_map} (saltat)."))

        if path_geo.exists():
            df = pd.read_csv(path_geo, on_bad_lines="skip", encoding="utf-8-sig")
            required = ["adreca", "lat", "lon"]
            missing = [column for column in required if column not in df.columns]
            if missing:
                raise Exception(f"Falten columnes a {path_geo}: {missing}. Columnes actuals: {list(df.columns)}")

            upsert = 0
            for _, row in df.iterrows():
                payload = build_address_payload(text=row.get("adreca"))
                if not payload["text"]:
                    continue

                lat = row.get("lat")
                lon = row.get("lon")
                lat = None if pd.isna(lat) else float(lat)
                lon = None if pd.isna(lon) else float(lon)

                address = resolve_address(text=payload["text"], municipality=payload["municipality"])
                if address is None:
                    continue

                address.lat = lat
                address.lon = lon
                address.geocode_status = "ok" if lat is not None and lon is not None else "pending"
                address.provider = "import_csv"
                address.last_error = None
                address.save(
                    update_fields=["text", "normalized_text", "municipality", "lat", "lon", "geocode_status", "provider", "last_error", "updated_at"]
                )
                upsert += 1

            self.stdout.write(self.style.SUCCESS(f"Address (geocodificats) importat/actualitzat: {upsert} files"))
        else:
            self.stdout.write(self.style.WARNING(f"No trobo {path_geo} (saltat)."))

        if path_cluster.exists():
            if not run_id:
                self.stdout.write(
                    self.style.WARNING(
                        f"He detectat {path_cluster}, però la clusterització s'ha de guardar per RUN. Executa amb --run-id <id>."
                    )
                )
            else:
                df = pd.read_csv(path_cluster, on_bad_lines="skip", encoding="utf-8-sig")
                required = ["adreca", "cluster"]
                missing = [column for column in required if column not in df.columns]
                if missing:
                    raise Exception(f"Falten columnes a {path_cluster}: {missing}. Columnes actuals: {list(df.columns)}")

                upsert = 0
                for _, row in df.iterrows():
                    payload = build_address_payload(text=row.get("adreca"))
                    if not payload["text"]:
                        continue

                    lat = row.get("lat", None)
                    lon = row.get("lon", None)
                    lat = None if pd.isna(lat) else float(lat)
                    lon = None if pd.isna(lon) else float(lon)

                    address = resolve_address(text=payload["text"], municipality=payload["municipality"])
                    if address is None:
                        continue

                    if address.lat is None and lat is not None:
                        address.lat = lat
                    if address.lon is None and lon is not None:
                        address.lon = lon
                    if address.lat is not None and address.lon is not None and address.geocode_status in {"pending", "not_found"}:
                        address.geocode_status = "ok"
                    address.provider = address.provider or "import_csv"
                    address.save(update_fields=["lat", "lon", "geocode_status", "provider", "updated_at"])

                    raw_cluster = row.get("cluster")
                    cluster_id = None if pd.isna(raw_cluster) else int(raw_cluster)
                    if cluster_id == -1:
                        cluster_id = None
                    cluster_status = _cluster_status_from_csv(cluster_id, address.lat, address.lon)

                    AddressCluster.objects.update_or_create(
                        run_id=run_id,
                        address=address,
                        defaults={"cluster_id": cluster_id, "cluster_status": cluster_status},
                    )
                    upsert += 1

                self.stdout.write(self.style.SUCCESS(f"AddressCluster importat/actualitzat per run {run_id}: {upsert} files"))
        else:
            self.stdout.write(self.style.WARNING(f"No trobo {path_cluster} (saltat)."))

        self.stdout.write(self.style.SUCCESS("Import finalitzat."))
