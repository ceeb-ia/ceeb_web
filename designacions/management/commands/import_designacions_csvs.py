import pandas as pd
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from designacions.models import ModalityMap, Address, AddressCluster

def _safe_str(v):
    if pd.isna(v):
        return ""
    return str(v).strip()

class Command(BaseCommand):
    help = "Importa map_modalitat_nom.csv + domicilis_geocodificats.csv + (opcional) domicilis_clusteritzats.csv a la BD."

    def add_arguments(self, parser):
        parser.add_argument(
            "--base-dir",
            type=str,
            default=None,
            help="Directori on hi ha els CSV (ex: /app/designacions)."
        )
        parser.add_argument(
            "--run-id",
            type=int,
            default=None,
            help="Si s’indica, importa també domicilis_clusteritzats.csv i el guarda a AddressCluster per aquest run."
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        # On són els CSV
        if opts["base_dir"]:
            base_dir = Path(opts["base_dir"]).resolve()
        else:
            # fallback: carpeta del paquet designacions
            base_dir = Path(__file__).resolve().parents[3]
        run_id = opts.get("run_id")

        self.stdout.write(self.style.NOTICE(f"Base dir CSV: {base_dir}"))
        if run_id:
            self.stdout.write(self.style.NOTICE(f"Import clusters per run_id={run_id}"))

        path_map = base_dir / "designacions" / "map_modalitat_nom.csv"
        path_geo = base_dir / "designacions" / "domicilis_geocodificats.csv"
        path_cluster = base_dir / "designacions" / "domicilis_clusteritzats.csv"

        # 1) map_modalitat_nom.csv (delimiter ';', BOM possible)
        if path_map.exists():
            df = pd.read_csv(path_map, sep=";", encoding="utf-8-sig")
            required = ["Id Categoria", "Modalitat", "Nom", "Descripció", "Nom Abreviat", "Ordre", "CodiExtern"]
            missing = [c for c in required if c not in df.columns]
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

                # clau estable (i curta) per mantenir unique de forma segura
                key = f"{modalitat}::{nom}"
                if len(key) > 255:
                    # últim recurs: retallem però mantenim diferenciació amb hash
                    import hashlib
                    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
                    key = (key[:240] + "::" + h)

                defaults = {
                    "name": nom,           # compat
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

        # 2) domicilis_geocodificats.csv (adreca,lat,lon)
        if path_geo.exists():
            df = pd.read_csv(path_geo, on_bad_lines="skip", encoding="utf-8-sig")
            required = ["adreca", "lat", "lon"]
            missing = [c for c in required if c not in df.columns]
            if missing:
                raise Exception(f"Falten columnes a {path_geo}: {missing}. Columnes actuals: {list(df.columns)}")

            upsert = 0
            for _, row in df.iterrows():
                adreca = _safe_str(row.get("adreca"))
                if not adreca:
                    continue

                lat = row.get("lat")
                lon = row.get("lon")
                lat = None if pd.isna(lat) else float(lat)
                lon = None if pd.isna(lon) else float(lon)

                status = "ok" if (lat is not None and lon is not None) else "pending"

                Address.objects.update_or_create(
                    text=adreca,
                    defaults={
                        "lat": lat,
                        "lon": lon,
                        "geocode_status": status,
                        "provider": "import_csv",
                        "last_error": None,
                    }
                )
                upsert += 1

            self.stdout.write(self.style.SUCCESS(f"Address (geocodificats) importat/actualitzat: {upsert} files"))
        else:
            self.stdout.write(self.style.WARNING(f"No trobo {path_geo} (saltat)."))

        # 3) domicilis_clusteritzats.csv (adreca,lat,lon,cluster) -> només si hi ha --run-id
        if path_cluster.exists():
            if not run_id:
                self.stdout.write(self.style.WARNING(
                    f"He detectat {path_cluster}, però la clusterització s’ha de guardar per RUN. "
                    "Executa amb --run-id <id> per importar-lo."
                ))
            else:
                df = pd.read_csv(path_cluster, on_bad_lines="skip", encoding="utf-8-sig")
                required = ["adreca", "cluster"]
                missing = [c for c in required if c not in df.columns]
                if missing:
                    raise Exception(f"Falten columnes a {path_cluster}: {missing}. Columnes actuals: {list(df.columns)}")

                upsert = 0
                for _, row in df.iterrows():
                    adreca = _safe_str(row.get("adreca"))
                    if not adreca:
                        continue

                    # assegurem Address existeix (i aprofitem lat/lon si ve al CSV)
                    lat = row.get("lat", None)
                    lon = row.get("lon", None)
                    lat = None if pd.isna(lat) else float(lat)
                    lon = None if pd.isna(lon) else float(lon)

                    addr, _ = Address.objects.get_or_create(text=adreca)
                    if addr.lat is None and lat is not None:
                        addr.lat = lat
                    if addr.lon is None and lon is not None:
                        addr.lon = lon
                    if addr.lat is not None and addr.lon is not None and addr.geocode_status in ("pending", "not_found"):
                        addr.geocode_status = "ok"
                    addr.provider = addr.provider or "import_csv"
                    addr.save()

                    c = row.get("cluster")
                    cluster_id = None if pd.isna(c) else int(c)

                    AddressCluster.objects.update_or_create(
                        run_id=run_id,
                        address=addr,
                        defaults={"cluster_id": cluster_id}
                    )
                    upsert += 1

                self.stdout.write(self.style.SUCCESS(f"AddressCluster importat/actualitzat per run {run_id}: {upsert} files"))
        else:
            self.stdout.write(self.style.WARNING(f"No trobo {path_cluster} (saltat)."))

        self.stdout.write(self.style.SUCCESS("Import finalitzat."))
