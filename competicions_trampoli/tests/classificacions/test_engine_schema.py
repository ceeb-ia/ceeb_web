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
from ...services.classificacions.engine import DEFAULT_EQUIPS_CFG
from ...services.shared.birth_year_ranges import BIRTH_YEAR_RANGE_PARTITION_CODE


class EngineSchemaTests(SimpleTestCase):
    def test_default_schema_matches_current_compute_default(self):
        merged = merge_schema({})

        self.assertEqual(set(merged.keys()), set(DEFAULT_SCHEMA.keys()))
        self.assertEqual(merged["particions_config"], DEFAULT_SCHEMA["particions_config"])
        self.assertEqual(merged["puntuacio"], DEFAULT_SCHEMA["puntuacio"])
        self.assertEqual(merged["presentacio"], DEFAULT_SCHEMA["presentacio"])
        self.assertEqual(merged["filtres"], {})
        self.assertTrue(merged["equips"]["assignment_source"]["legacy_mode"])
        self.assertEqual(DEFAULT_SCHEMA["equips"], DEFAULT_EQUIPS_CFG)
        self.assertEqual(
            DEFAULT_SCHEMA["presentacio"],
            {
                "top_n": 0,
                "mostrar_empats": True,
                "columnes": [
                    {"type": "builtin", "key": "posicio", "label": "#", "align": "left"},
                    {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                    {"type": "builtin", "key": "punts", "label": "Punts", "align": "right", "decimals": 3},
                ],
                "detall": {
                    "enabled": False,
                    "default_open": False,
                    "sections": [],
                },
            },
        )
        self.assertIs(normalize_schema_for_compute, normalize_schema)

    def test_merge_schema_matches_current_partition_impl_for_shared_contract(self):
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

        merged = merge_schema(raw_schema)
        partition_merged = partitions_merge_schema(raw_schema)

        for key in (
            "particions",
            "particions_v2",
            "particions_custom",
            "particions_config",
            "filtres",
            "desempat",
            "presentacio",
            "equips",
        ):
            self.assertEqual(merged[key], partition_merged[key])
        for key, value in partition_merged["puntuacio"].items():
            self.assertEqual(merged["puntuacio"][key], value)
        self.assertEqual(merged["puntuacio"]["participants_per_aparell"], {})
        self.assertEqual(merged["puntuacio"]["agregacio_participants_per_aparell"], {})
        self.assertEqual(merged["presentacio"]["detall"]["columnes"], [{"type": "builtin", "key": "participant"}])
        self.assertEqual(merged["presentacio"]["detall"]["sections"], [])
        self.assertIsNot(merged["presentacio"]["detall"]["columnes"], raw_schema["presentacio"]["detall"]["columnes"])

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

    def test_merge_schema_keeps_team_pool_per_exercici_maps(self):
        raw_schema = {
            "puntuacio": {
                "team_pool_mode_per_aparell": {"12": "per_exercici"},
                "team_pool_participants_per_exercici_per_aparell": {
                    "12": {
                        "1": {"mode": "millor_n", "n": 2},
                        "2": {"mode": "millor_1"},
                    }
                },
                "team_pool_agregacio_participants_per_exercici_per_aparell": {
                    "12": {"1": "sum", "2": "avg"}
                },
            }
        }

        merged = merge_schema(raw_schema)

        self.assertEqual(merged["puntuacio"]["team_pool_mode_per_aparell"], {"12": "per_exercici"})
        self.assertEqual(
            merged["puntuacio"]["team_pool_participants_per_exercici_per_aparell"],
            {
                "12": {
                    "1": {"mode": "millor_n", "n": 2},
                    "2": {"mode": "millor_1"},
                }
            },
        )
        self.assertEqual(
            merged["puntuacio"]["team_pool_agregacio_participants_per_exercici_per_aparell"],
            {"12": {"1": "sum", "2": "avg"}},
        )

    def test_normalize_schema_matches_current_team_birth_partition_flow(self):
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

        actual_schema, actual_info = normalize_schema(
            competicio,
            raw_schema,
            tipus="equips",
            persist=True,
        )

        self.assertEqual(
            actual_info,
            {
                "legacy_inferred": True,
                "legacy_pending_review": False,
                "compatibility_errors": [],
            },
        )
        self.assertEqual(
            actual_schema["particions_v2"],
            [
                {"code": "categoria", "apply_mode": "all", "parent_values": []},
                {
                    "code": BIRTH_YEAR_RANGE_PARTITION_CODE,
                    "apply_mode": "all",
                    "parent_values": [],
                },
            ],
        )
        self.assertEqual(actual_schema["particions"], ["categoria", BIRTH_YEAR_RANGE_PARTITION_CODE])
        expected_equips = {
            **DEFAULT_EQUIPS_CFG,
            "assignment_source": {
                **DEFAULT_EQUIPS_CFG["assignment_source"],
                "legacy_mode": False,
            },
        }
        self.assertEqual(actual_schema["equips"], expected_equips)
        self.assertEqual(
            actual_schema["particions_config"],
            {
                BIRTH_YEAR_RANGE_PARTITION_CODE: {
                    "ranges": [
                        {
                            "label": "<=12",
                            "from_date": "2013-04-22",
                            "until_date": None,
                            "from_year": None,
                            "to_year": None,
                        },
                        {
                            "label": "13-14",
                            "from_date": "2011-04-22",
                            "until_date": "2013-04-21",
                            "from_year": None,
                            "to_year": None,
                        },
                        {
                            "label": ">14",
                            "from_date": None,
                            "until_date": "2011-04-21",
                            "from_year": None,
                            "to_year": None,
                        },
                    ],
                    "sense_data_label": "Sense edat",
                    "fora_rang_label": "Fora de forquilla",
                    "team_rules": {
                        "reference_mode": "oldest_member_birthdate",
                        "compliance_mode": "strict",
                        "max_members_outside_range": 0,
                        "missing_birthdate_policy": "outside_range",
                    },
                }
            },
        )
