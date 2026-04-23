from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase

from ...services.classificacions.engine.partition_runtime import (
    _birth_year_range_partition_value,
    _birth_year_range_partition_value_for_team,
    _build_particions_custom_index,
    _bucket_edat,
    _inscripcio_value_for_partition,
    _partition_key_from_entries,
    _partition_key_from_entries_for_team,
    _resolve_partition_display,
    _resolve_particio_equip,
    _years_old,
)


class PartitionRuntimeTests(SimpleTestCase):
    def test_inscripcio_value_for_partition_reads_excel_alias_from_extra(self):
        ins = SimpleNamespace(extra={"nivell": "N1"})

        self.assertEqual(_inscripcio_value_for_partition(ins, "excel__nivell"), "N1")

    def test_partition_key_from_entries_resolves_custom_and_conditional_children(self):
        custom_idx = _build_particions_custom_index(
            {
                "categoria": {
                    "mode": "custom",
                    "grups": [
                        {"label": "Base", "values": ["ALEVI", "PREBENJAMI"]},
                        {"label": "Grans", "values": ["INFANTIL"]},
                    ],
                }
            }
        )
        entries = [
            {"code": "categoria", "apply_mode": "all"},
            {"code": "subcategoria", "apply_mode": "some_parents", "parent_values": ["Base"]},
        ]

        ins_base = SimpleNamespace(categoria="ALEVI", subcategoria="N1", extra={})
        ins_grans = SimpleNamespace(categoria="INFANTIL", subcategoria="N3", extra={})

        self.assertEqual(
            _partition_key_from_entries(ins_base, entries, particions_custom_index=custom_idx),
            "categoria:Base|subcategoria:N1",
        )
        self.assertEqual(
            _partition_key_from_entries(ins_grans, entries, particions_custom_index=custom_idx),
            "categoria:Grans",
        )

    def test_resolve_partition_display_uses_fallback_for_unmapped_custom_value(self):
        custom_idx = _build_particions_custom_index(
            {
                "categoria": {
                    "mode": "custom",
                    "fallback_label": "Altres",
                    "grups": [{"label": "Base", "values": ["ALEVI"]}],
                }
            }
        )

        self.assertEqual(
            _resolve_partition_display("categoria", "INFANTIL", custom_idx),
            "Altres",
        )

    def test_birth_year_range_partition_runtime_supports_individual_and_team(self):
        cfg = {
            "any_naixement_forquilla": {
                "ranges": [
                    {"label": "2007-2009", "from_year": 2007, "to_year": 2009},
                    {"label": "2010-2012", "from_year": 2010, "to_year": 2012},
                ],
                "sense_data_label": "Sense data",
                "fora_rang_label": "Fora de forquilla",
                "team_rules": {
                    "reference_mode": "oldest_member_birthdate",
                    "compliance_mode": "strict",
                    "max_members_outside_range": 0,
                    "missing_birthdate_policy": "outside_range",
                },
            }
        }

        ins = SimpleNamespace(data_naixement=date(2008, 5, 4))
        team_ok = [
            (SimpleNamespace(categoria="ALEVI", data_naixement=date(2008, 1, 1)), None),
            (SimpleNamespace(categoria="ALEVI", data_naixement=date(2009, 6, 1)), None),
        ]
        team_outside = [
            (SimpleNamespace(categoria="ALEVI", data_naixement=date(2008, 1, 1)), None),
            (SimpleNamespace(categoria="ALEVI", data_naixement=date(2011, 6, 1)), None),
        ]

        self.assertEqual(_birth_year_range_partition_value(ins, cfg), "2007-2009")
        self.assertEqual(_birth_year_range_partition_value_for_team(team_ok, cfg), "2007-2009")
        self.assertEqual(
            _birth_year_range_partition_value_for_team(team_outside, cfg),
            "Fora de forquilla",
        )

    def test_partition_key_from_entries_for_team_handles_birth_range_children(self):
        custom_idx = _build_particions_custom_index(
            {
                "categoria": {
                    "mode": "custom",
                    "grups": [
                        {"label": "Base", "values": ["ALEVI"]},
                        {"label": "Grans", "values": ["INFANTIL"]},
                    ],
                }
            }
        )
        entries = [
            {"code": "categoria", "apply_mode": "all"},
            {
                "code": "any_naixement_forquilla",
                "apply_mode": "some_parents",
                "parent_values": ["Base"],
            },
        ]
        cfg = {
            "any_naixement_forquilla": {
                "ranges": [{"label": "2007-2009", "from_year": 2007, "to_year": 2009}],
                "sense_data_label": "Sense data",
                "fora_rang_label": "Fora de forquilla",
                "team_rules": {
                    "reference_mode": "oldest_member_birthdate",
                    "compliance_mode": "strict",
                    "max_members_outside_range": 0,
                    "missing_birthdate_policy": "outside_range",
                },
            }
        }
        team_base = [
            (SimpleNamespace(categoria="ALEVI", data_naixement=date(2008, 1, 1)), None),
            (SimpleNamespace(categoria="ALEVI", data_naixement=date(2009, 1, 1)), None),
        ]
        team_grans = [
            (SimpleNamespace(categoria="INFANTIL", data_naixement=date(2008, 1, 1)), None),
        ]

        self.assertEqual(
            _partition_key_from_entries_for_team(
                team_base,
                entries,
                particions_custom_index=custom_idx,
                particions_config=cfg,
            ),
            "categoria:Base|any_naixement_forquilla:2007-2009",
        )
        self.assertEqual(
            _partition_key_from_entries_for_team(
                team_grans,
                entries,
                particions_custom_index=custom_idx,
                particions_config=cfg,
            ),
            "categoria:Grans",
        )

    def test_team_age_helpers_match_legacy_runtime(self):
        self.assertEqual(_years_old(date(2010, 4, 22), date(2026, 4, 21)), 15)
        self.assertEqual(_bucket_edat(11, [10, 12], "Sense edat"), "edat:<=12")
        self.assertEqual(_bucket_edat(None, [10, 12], "Sense edat"), "edat:Sense edat")
        self.assertEqual(
            _resolve_particio_equip("categoria:Base", "edat:<=12", True),
            "categoria:Base|edat:<=12",
        )
