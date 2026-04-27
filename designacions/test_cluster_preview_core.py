from io import BytesIO
import tempfile
from unittest.mock import patch

import pandas as pd
from django.test import TestCase
from openpyxl import Workbook

from .clusteritzacio import add_preview_override
from .clusteritzacio.engine import cluster_points_dataframe
from .clusteritzacio.overrides import apply_preview_overrides, load_preview_overrides
from .clusteritzacio.preview_service import build_cluster_preview
from .geolocate import GeocodingRateLimitedError
from .models import Address
from .services.geocoding_db import geocodifica_adreces


def _xlsx_bytes(headers, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


class ClusterPreviewEngineTests(TestCase):
    def test_cluster_points_marks_missing_geocode_and_outliers(self):
        df = pd.DataFrame(
            [
                {"address_id": 1, "adreca": "Carrer 1", "lat": 41.0, "lon": 2.0},
                {"address_id": 2, "adreca": "Carrer 2", "lat": 41.0005, "lon": 2.0005},
                {"address_id": 3, "adreca": "Carrer 3", "lat": None, "lon": None},
            ]
        )

        clustered = cluster_points_dataframe(df, eps_m=200, min_samples=2, max_points_per_subcluster=3)

        self.assertEqual(clustered.loc[0, "cluster_status"], "clustered")
        self.assertEqual(clustered.loc[1, "cluster_status"], "clustered")
        self.assertEqual(clustered.loc[2, "cluster_status"], "missing_geocode")


class ClusterPreviewServiceTests(TestCase):
    def test_apply_preview_overrides_can_merge_an_outlier_with_a_manual_target_cluster(self):
        points_df = pd.DataFrame(
            [
                {
                    "address_id": 1,
                    "adreca": "Carrer 1, Barcelona",
                    "lat": 41.0,
                    "lon": 2.0,
                    "cluster": -1,
                    "cluster_status": "outlier",
                },
                {
                    "address_id": 2,
                    "adreca": "Carrer 2, Barcelona",
                    "lat": 41.0005,
                    "lon": 2.0005,
                    "cluster": 7,
                    "cluster_status": "clustered",
                },
            ]
        )

        overridden_df, override_effects, override_summary = apply_preview_overrides(
            points_df,
            [
                {
                    "override_id": "ov-1",
                    "kind": "merge_with_address",
                    "source_address_id": 1,
                    "target_address_id": 2,
                }
            ],
        )

        by_address_id = {
            int(row["address_id"]): row
            for _, row in overridden_df.iterrows()
        }
        self.assertEqual(int(by_address_id[1]["cluster"]), 7)
        self.assertEqual(by_address_id[1]["cluster_status"], "clustered")
        self.assertTrue(bool(by_address_id[1]["is_manual"]))
        self.assertTrue(bool(by_address_id[2]["is_manual"]))
        self.assertEqual(by_address_id[1]["cluster_origin"], "manual")
        self.assertEqual(by_address_id[2]["cluster_origin"], "automatic")
        self.assertEqual(override_effects[0]["status"], "applied")
        self.assertEqual(override_summary["manual_point_count"], 2)

    def test_apply_preview_overrides_can_move_address_to_target_cluster_id(self):
        points_df = pd.DataFrame(
            [
                {
                    "address_id": 1,
                    "adreca": "Carrer 1, Barcelona",
                    "lat": 41.0,
                    "lon": 2.0,
                    "cluster": 2,
                    "cluster_status": "clustered",
                },
                {
                    "address_id": 2,
                    "adreca": "Carrer 2, Barcelona",
                    "lat": 41.0005,
                    "lon": 2.0005,
                    "cluster": 7,
                    "cluster_status": "clustered",
                },
            ]
        )

        overridden_df, override_effects, override_summary = apply_preview_overrides(
            points_df,
            [
                {
                    "override_id": "ov-1",
                    "kind": "merge_with_address",
                    "source_address_id": 1,
                    "target_cluster_id": 7,
                    "eps_m": 650,
                }
            ],
        )

        by_address_id = {
            int(row["address_id"]): row
            for _, row in overridden_df.iterrows()
        }
        self.assertEqual(int(by_address_id[1]["cluster"]), 7)
        self.assertEqual(int(by_address_id[2]["cluster"]), 7)
        self.assertTrue(bool(by_address_id[1]["is_manual"]))
        self.assertFalse(bool(by_address_id[2]["is_manual"]))
        self.assertEqual(override_effects[0]["status"], "applied")
        self.assertEqual(override_summary["manual_point_count"], 1)

    @patch("designacions.clusteritzacio.preview_service.geocodifica_adreces")
    def test_build_cluster_preview_returns_scenarios_and_counts(self, geocode_mock):
        address_1 = Address.objects.create(
            text="Carrer 1, Barcelona",
            normalized_text="carrer 1, barcelona",
            municipality="Barcelona",
            lat=41.0,
            lon=2.0,
            geocode_status="ok",
        )
        address_2 = Address.objects.create(
            text="Carrer 2, Barcelona",
            normalized_text="carrer 2, barcelona",
            municipality="Barcelona",
            lat=41.001,
            lon=2.001,
            geocode_status="ok",
        )
        geocode_mock.return_value = [address_1, address_2]

        df_partits = pd.read_excel(
            BytesIO(
                _xlsx_bytes(
                    [
                        "Codi",
                        "Club Local",
                        "Equip local",
                        "Equip visitant",
                        "Lliga",
                        "Grup",
                        "Modalitat",
                        "Categoria",
                        "Data",
                        "Hora",
                        "Domicili",
                        "Municipi",
                        "Pista joc",
                    ],
                    [
                        ["P1", "Club", "L1", "V1", "Lliga", "Grup", "FUTBOL 5", "ALEVI", "2026-04-25", "10:00", "Carrer 1", "Barcelona", "Pista A"],
                        ["P2", "Club", "L2", "V2", "Lliga", "Grup", "FUTBOL 5", "ALEVI", "2026-04-25", "12:00", "Carrer 2", "Barcelona", "Pista B"],
                    ],
                )
            ),
            engine="openpyxl",
        )
        df_dispos = pd.read_excel(
            BytesIO(
                _xlsx_bytes(
                    ["Codi Tutor de Joc", "Nom", "Categoria", "Modalitat", "Data", "Hora Inici", "Hora Fi"],
                    [["5001 F5", "Tutor", "TUTOR/TUTORA DE JOC", "FUTBOL 5", "2026-04-25", "09:00", "14:00"]],
                )
            ),
            engine="openpyxl",
        )

        preview = build_cluster_preview(
            df_dispos=df_dispos,
            df_partits=df_partits,
            params={
                "cluster_eps_m": 500,
                "cluster_min_samples": 2,
                "max_partits_subgrup": 3,
                "gap_same_pitch_min": 60,
                "gap_diff_pitch_min": 75,
                "modalitats": ["FUTBOL 5"],
                "preview_cluster_eps_options": [300, 500],
            },
        )

        self.assertEqual(preview.selected_eps_m, 500)
        self.assertEqual(len(preview.scenarios), 2)
        self.assertEqual(preview.preview_counts["total_matches"], 2)
        self.assertEqual(preview.preview_counts["total_unique_addresses"], 2)
        self.assertEqual(preview.availability_counts["total_unique_referees"], 1)
        self.assertEqual(preview.availability_counts["total_availability_rows"], 1)
        self.assertTrue(preview.scenarios[0].modality_breakdown)
        self.assertEqual(preview.scenarios[0].modality_breakdown[0]["unique_referees"], 1)
        self.assertTrue(any(scenario.metrics.cluster_count >= 1 for scenario in preview.scenarios))

    @patch("designacions.clusteritzacio.preview_service.geocodifica_adreces")
    def test_build_cluster_preview_includes_persisted_manual_overrides(self, geocode_mock):
        address_1 = Address.objects.create(
            text="Carrer 1, Barcelona",
            normalized_text="carrer 1, barcelona",
            municipality="Barcelona",
            lat=41.0,
            lon=2.0,
            geocode_status="ok",
        )
        address_2 = Address.objects.create(
            text="Carrer 2, Barcelona",
            normalized_text="carrer 2, barcelona",
            municipality="Barcelona",
            lat=41.0002,
            lon=2.0002,
            geocode_status="ok",
        )
        geocode_mock.return_value = [address_1, address_2]

        df_partits = pd.read_excel(
            BytesIO(
                _xlsx_bytes(
                    [
                        "Codi",
                        "Club Local",
                        "Equip local",
                        "Equip visitant",
                        "Lliga",
                        "Grup",
                        "Modalitat",
                        "Categoria",
                        "Data",
                        "Hora",
                        "Domicili",
                        "Municipi",
                        "Pista joc",
                    ],
                    [
                        ["P1", "Club", "L1", "V1", "Lliga", "Grup", "FUTBOL 5", "ALEVI", "2026-04-25", "10:00", "Carrer 1", "Barcelona", "Pista A"],
                        ["P2", "Club", "L2", "V2", "Lliga", "Grup", "FUTBOL 5", "ALEVI", "2026-04-25", "12:00", "Carrer 2", "Barcelona", "Pista B"],
                    ],
                )
            ),
            engine="openpyxl",
        )
        df_dispos = pd.read_excel(
            BytesIO(
                _xlsx_bytes(
                    ["Codi Tutor de Joc", "Nom", "Categoria", "Modalitat", "Data", "Hora Inici", "Hora Fi"],
                    [["5001 F5", "Tutor", "TUTOR/TUTORA DE JOC", "FUTBOL 5", "2026-04-25", "09:00", "14:00"]],
                )
            ),
            engine="openpyxl",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.settings(MEDIA_ROOT=tmp_dir):
                add_preview_override(
                    "preview-ovr-1",
                    {
                        "override_id": "ov-isolate-1",
                        "kind": "isolate_address",
                        "source_address_id": address_2.id,
                    },
                )
                stored_overrides = load_preview_overrides("preview-ovr-1")
                preview = build_cluster_preview(
                    preview_id="preview-ovr-1",
                    df_dispos=df_dispos,
                    df_partits=df_partits,
                    params={
                        "cluster_eps_m": 500,
                        "cluster_min_samples": 2,
                        "max_partits_subgrup": 3,
                        "gap_same_pitch_min": 60,
                        "gap_diff_pitch_min": 75,
                        "modalitats": ["FUTBOL 5"],
                        "preview_cluster_eps_options": [500],
                    },
                )

        self.assertEqual(len(stored_overrides), 1)
        self.assertEqual(len(preview.cluster_overrides), 1)
        self.assertEqual(preview.override_summary["active_override_count"], 1)
        self.assertEqual(preview.summary["active_override_count"], 1)
        scenario = preview.scenarios[0]
        self.assertEqual(scenario.manual_point_count, 1)
        self.assertEqual(scenario.override_summary["applied_override_count"], 1)
        self.assertEqual(scenario.active_overrides[0]["status"], "applied")
        by_address_id = {point.address_id: point for point in scenario.points}
        self.assertTrue(by_address_id[address_2.id].is_manual)
        self.assertEqual(by_address_id[address_2.id].manual_role, "isolated")
        self.assertEqual(by_address_id[address_2.id].cluster_origin, "manual")
        self.assertNotEqual(by_address_id[address_1.id].cluster, by_address_id[address_2.id].cluster)
        self.assertEqual(scenario.metrics.cluster_count, 2)

    @patch("designacions.clusteritzacio.preview_service.render_preview_map")
    @patch("designacions.clusteritzacio.preview_service.geocodifica_adreces")
    def test_build_cluster_preview_generates_map_path_per_scenario(self, geocode_mock, render_map_mock):
        address_1 = Address.objects.create(
            text="Carrer 1, Barcelona",
            normalized_text="carrer 1, barcelona",
            municipality="Barcelona",
            lat=41.0,
            lon=2.0,
            geocode_status="ok",
        )
        address_2 = Address.objects.create(
            text="Carrer 2, Barcelona",
            normalized_text="carrer 2, barcelona",
            municipality="Barcelona",
            lat=41.001,
            lon=2.001,
            geocode_status="ok",
        )
        geocode_mock.return_value = [address_1, address_2]
        render_map_mock.side_effect = lambda scenario, out_path: out_path

        df_partits = pd.read_excel(
            BytesIO(
                _xlsx_bytes(
                    [
                        "Codi",
                        "Club Local",
                        "Equip local",
                        "Equip visitant",
                        "Lliga",
                        "Grup",
                        "Modalitat",
                        "Categoria",
                        "Data",
                        "Hora",
                        "Domicili",
                        "Municipi",
                        "Pista joc",
                    ],
                    [
                        ["P1", "Club", "L1", "V1", "Lliga", "Grup", "FUTBOL 5", "ALEVI", "2026-04-25", "10:00", "Carrer 1", "Barcelona", "Pista A"],
                        ["P2", "Club", "L2", "V2", "Lliga", "Grup", "FUTBOL 5", "ALEVI", "2026-04-25", "12:00", "Carrer 2", "Barcelona", "Pista B"],
                    ],
                )
            ),
            engine="openpyxl",
        )
        df_dispos = pd.read_excel(
            BytesIO(
                _xlsx_bytes(
                    ["Codi Tutor de Joc", "Nom", "Categoria", "Modalitat", "Data", "Hora Inici", "Hora Fi"],
                    [["5001 F5", "Tutor", "TUTOR/TUTORA DE JOC", "FUTBOL 5", "2026-04-25", "09:00", "14:00"]],
                )
            ),
            engine="openpyxl",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_map_abs = f"{tmp_dir}/preview.html"
            preview = build_cluster_preview(
                df_dispos=df_dispos,
                df_partits=df_partits,
                params={
                    "cluster_eps_m": 500,
                    "cluster_min_samples": 2,
                    "max_partits_subgrup": 3,
                    "gap_same_pitch_min": 60,
                    "gap_diff_pitch_min": 75,
                    "modalitats": ["FUTBOL 5"],
                    "preview_cluster_eps_options": [300, 500],
                },
                out_map_abs=out_map_abs,
            )

        self.assertEqual(render_map_mock.call_count, 2)
        scenario_map_paths = {scenario.eps_m: scenario.map_path for scenario in preview.scenarios}
        self.assertTrue(scenario_map_paths[300].endswith("preview__eps_300.html"))
        self.assertTrue(scenario_map_paths[500].endswith("preview__eps_500.html"))
        self.assertEqual(preview.map_path, scenario_map_paths[500])

    @patch("designacions.services.geocoding_db.sleep", return_value=None)
    @patch("designacions.services.geocoding_db.geocode_address_amb_fallback")
    def test_geocodifica_adreces_stops_live_requests_after_rate_limit(self, geocode_mock, _sleep_mock):
        def fake_geocode(_geolocator, address_text):
            if "Carrer 1" in address_text:
                raise GeocodingRateLimitedError("HTTP 429 Too many requests")
            return (41.0, 2.0, address_text)

        geocode_mock.side_effect = fake_geocode

        resolved = geocodifica_adreces(
            ["Carrer 1, Barcelona", "Carrer 2, Barcelona"],
            sleep_seconds=0,
        )

        self.assertEqual(geocode_mock.call_count, 1)
        by_text = {address.text: address for address in resolved}
        self.assertEqual(by_text["Carrer 1, Barcelona"].geocode_status, "pending")
        self.assertIn("429", by_text["Carrer 1, Barcelona"].last_error)
        self.assertEqual(by_text["Carrer 2, Barcelona"].geocode_status, "pending")
        self.assertIn("ajornada temporalment", by_text["Carrer 2, Barcelona"].last_error)
