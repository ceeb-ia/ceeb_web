from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase

from ...services.classificacions._partitions_impl import _merge_schema as partitions_merge_schema
from ...services.classificacions.engine.schema import (
    DEFAULT_SCHEMA,
    merge_schema,
    normalize_schema,
    normalize_schema_for_compute,
)
from ...services.legacy.services_classificacions_2 import (
    DEFAULT_SCHEMA as legacy_default_schema,
    _merge_schema as legacy_merge_schema,
    normalize_schema_legacy_team_birth_partition as legacy_normalize_schema,
)


class EngineSchemaTests(SimpleTestCase):
    def test_default_schema_matches_current_compute_default(self):
        self.assertEqual(DEFAULT_SCHEMA, legacy_default_schema)
        self.assertIs(normalize_schema_for_compute, normalize_schema)

    def test_merge_schema_matches_legacy_merge_for_shared_contract(self):
        raw_schema = {
            "particions": ["categoria", "subcategoria"],
            "particions_v2": [
                {"code": "categoria", "apply_mode": "all"},
                {"code": "subcategoria", "apply_mode": "some_parents", "parent_values": ["Base"]},
            ],
            "particions_custom": {
                "categoria": {
                    "mode": "custom",
                    "grups": [{"label": "Base", "values": ["ALEVI", "PREBENJAMI"]}],
                }
            },
            "particions_config": {
                "any_naixement_forquilla": {
                    "ranges": [{"label": "2007-2009", "from_year": 2007, "to_year": 2009}],
                }
            },
            "filtres": {"entitats_in": [" Club A ", "club a", 7]},
            "puntuacio": {
                "aparells": {"mode": "seleccionar", "ids": [1, "2"]},
                "camps_per_aparell": {"1": ["total"]},
                "victories": {"punts_victoria": 3},
            },
            "desempat": [{"camp": "total", "ordre": "desc"}],
            "presentacio": {
                "top_n": 10,
                "detall": {
                    "enabled": True,
                    "columnes": [{"type": "builtin", "key": "participant"}],
                    "sections": "invalid",
                },
            },
            "equips": {"team_mode": "native_team"},
        }

        self.assertEqual(merge_schema(raw_schema), legacy_merge_schema(raw_schema))

    def test_merge_schema_keeps_current_candidate_source_merge_and_full_team_defaults(self):
        raw_schema = {
            "puntuacio": {
                "candidate_source_cfg": {"mode": "millor_n"},
                "candidate_source_per_aparell": "invalid",
                "participants_per_aparell": "invalid",
                "agregacio_participants_per_aparell": "invalid",
                "agregacio_exercicis_per_aparell": {"1": "max"},
            }
        }

        merged = merge_schema(raw_schema)
        partition_merged = partitions_merge_schema(raw_schema)

        self.assertEqual(
            merged["puntuacio"]["candidate_source_cfg"],
            partition_merged["puntuacio"]["candidate_source_cfg"],
        )
        self.assertEqual(
            merged["puntuacio"]["candidate_source_per_aparell"],
            partition_merged["puntuacio"]["candidate_source_per_aparell"],
        )
        self.assertEqual(merged["puntuacio"]["participants_per_aparell"], {})
        self.assertEqual(merged["puntuacio"]["agregacio_participants_per_aparell"], {})
        self.assertEqual(merged["puntuacio"]["agregacio_exercicis_per_aparell"], {"1": "max"})

    def test_normalize_schema_matches_legacy_team_birth_partition_flow(self):
        competicio = SimpleNamespace(data=date(2026, 4, 21))
        raw_schema = {
            "particions": ["categoria"],
            "equips": {
                "particio_edat": {
                    "activa": True,
                    "llindars": [12, 14],
                    "sense_data_label": "Sense edat",
                },
                "combinar_manual_i_edat": True,
            },
        }

        expected_schema, expected_info = legacy_normalize_schema(
            competicio,
            raw_schema,
            tipus="equips",
            persist=True,
        )
        actual_schema, actual_info = normalize_schema(
            competicio,
            raw_schema,
            tipus="equips",
            persist=True,
        )

        self.assertEqual(actual_schema, expected_schema)
        self.assertEqual(actual_info, expected_info)
