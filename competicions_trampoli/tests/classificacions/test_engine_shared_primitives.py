from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from ...models import Inscripcio
from ...services.classificacions._filters_impl import (
    DEFAULT_EQUIPS_CFG as FILTERS_DEFAULT_EQUIPS_CFG,
    competition_reference_date as filters_competition_reference_date,
    normalize_classificacio_equips_cfg as filters_normalize_classificacio_equips_cfg,
    normalize_classificacio_filters as filters_normalize_classificacio_filters,
    normalize_equip_assignment_source as filters_normalize_equip_assignment_source,
    normalize_exercise_selection_scope as filters_normalize_exercise_selection_scope,
    normalize_team_mode as filters_normalize_team_mode,
    resolve_classificacio_equips_context_code as filters_resolve_classificacio_equips_context_code,
)
from ...services.classificacions._partitions_impl import (
    _json_clone_value as partitions_json_clone_value,
    _normalize_partition_parent_values as partitions_normalize_partition_parent_values,
    _normalize_partition_token as partitions_normalize_partition_token,
)
from ...services.classificacions.engine import (
    DEFAULT_EQUIPS_CFG,
    competition_reference_date,
    display_value,
    filter_in,
    is_relational_field,
    json_clone,
    json_clone_value,
    normalize_classificacio_equips_cfg,
    normalize_classificacio_filter_values,
    normalize_classificacio_filters,
    normalize_equip_assignment_source,
    normalize_exercise_selection_scope,
    normalize_partition_parent_values,
    normalize_partition_token,
    normalize_positive_int,
    normalize_team_mode,
    normalized_text_token,
    resolve_classificacio_equips_context_code,
)
from ...services.legacy.services_classificacions_2 import (
    _display_value as legacy_display_value,
    _filter_in as legacy_filter_in,
    _is_relational_field as legacy_is_relational_field,
    _json_clone as legacy_json_clone,
    _json_clone_value as legacy_json_clone_value,
    _normalize_classificacio_filter_values as legacy_normalize_classificacio_filter_values,
    _normalize_classificacio_filters as legacy_normalize_classificacio_filters,
    _normalize_positive_int as legacy_normalize_positive_int,
    _normalized_text_token as legacy_normalized_text_token,
)


class _DummyQuerySet:
    def __init__(self):
        self.calls = []

    def filter(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs


class EngineSharedPrimitivesTests(SimpleTestCase):
    def test_common_normalizers_match_legacy_behavior(self):
        positive_int_values = [None, "", "0", "7", 9, 0, -4, 3.0, Decimal("11"), True]
        for raw_value in positive_int_values:
            self.assertEqual(
                normalize_positive_int(raw_value),
                legacy_normalize_positive_int(raw_value),
            )

        text_values = [None, "", "  Club  A  ", "MiXeD Case", "  12 "]
        for raw_value in text_values:
            self.assertEqual(
                normalized_text_token(raw_value),
                legacy_normalized_text_token(raw_value),
            )

        filter_value_cases = [
            ([1, "1", " 1 ", Decimal("1"), 2.0, 0, "", None, False, "Club"], False),
            ([1, "01", " 2 ", "Grup A", Decimal("3")], True),
            ("7", False),
            (None, False),
        ]
        for raw_values, groups in filter_value_cases:
            self.assertEqual(
                normalize_classificacio_filter_values(raw_values, groups=groups),
                legacy_normalize_classificacio_filter_values(raw_values, groups=groups),
            )

        filter_payload = {
            "entitats_in": [" Club A ", "club a", None, 4, "4"],
            "categories_in": "Base",
            "subcategories_in": [Decimal("3"), "Promo"],
            "grups_in": [1, " 1 ", "Final"],
            "ignored": ["x"],
        }
        self.assertEqual(
            normalize_classificacio_filters(filter_payload),
            legacy_normalize_classificacio_filters(filter_payload),
        )
        self.assertEqual(
            normalize_classificacio_filters(filter_payload),
            filters_normalize_classificacio_filters(filter_payload),
        )

    def test_engine_common_matches_current_filter_and_partition_helpers(self):
        assignment_source = {
            "mode": "native",
            "context_code": "custom_ctx",
            "fallback": "unknown",
        }
        self.assertEqual(DEFAULT_EQUIPS_CFG, FILTERS_DEFAULT_EQUIPS_CFG)
        self.assertEqual(
            normalize_equip_assignment_source(assignment_source),
            filters_normalize_equip_assignment_source(assignment_source),
        )
        self.assertEqual(
            resolve_classificacio_equips_context_code(
                "",
                assignment_source,
                normalize_equip_assignment_source(assignment_source),
            ),
            filters_resolve_classificacio_equips_context_code(
                "",
                assignment_source,
                filters_normalize_equip_assignment_source(assignment_source),
            ),
        )
        self.assertEqual(
            normalize_team_mode("NATIVE_TEAM"),
            filters_normalize_team_mode("NATIVE_TEAM"),
        )
        self.assertEqual(
            normalize_exercise_selection_scope("", allow_inherit=True),
            filters_normalize_exercise_selection_scope("", allow_inherit=True),
        )
        self.assertEqual(
            normalize_classificacio_equips_cfg(
                {
                    "team_mode": "native_team",
                    "assignment_source": assignment_source,
                    "mode_resolution": {"eligible_team_app_ids_at_save": [1, "1", 2, 0]},
                    "particio_edat": {"activa": True, "llindars": [12, 14]},
                }
            ),
            filters_normalize_classificacio_equips_cfg(
                {
                    "team_mode": "native_team",
                    "assignment_source": assignment_source,
                    "mode_resolution": {"eligible_team_app_ids_at_save": [1, "1", 2, 0]},
                    "particio_edat": {"activa": True, "llindars": [12, 14]},
                }
            ),
        )

        competicio = SimpleNamespace(data=date(2026, 4, 21))
        self.assertEqual(
            competition_reference_date(competicio),
            filters_competition_reference_date(competicio),
        )

        partition_raw = ["  Base  ", "base", "", "Promo", None, "PROMO"]
        self.assertEqual(
            normalize_partition_token("  Grup  Final "),
            partitions_normalize_partition_token("  Grup  Final "),
        )
        self.assertEqual(
            normalize_partition_parent_values(partition_raw),
            partitions_normalize_partition_parent_values(partition_raw),
        )

        payload = {
            "text": "Classe",
            "nested": {"list": [1, ("a", "b")]},
        }
        self.assertEqual(json_clone(payload), legacy_json_clone(payload))
        self.assertEqual(json_clone_value(payload), legacy_json_clone_value(payload))
        self.assertEqual(json_clone_value(payload), partitions_json_clone_value(payload))

    def test_model_utils_match_legacy_helpers(self):
        for field_name in ("equip", "grup_competicio", "categoria", "entitat", "missing_field"):
            self.assertEqual(
                is_relational_field(Inscripcio, field_name),
                legacy_is_relational_field(Inscripcio, field_name),
            )

        legacy_rel_qs = _DummyQuerySet()
        engine_rel_qs = _DummyQuerySet()
        self.assertEqual(
            filter_in(engine_rel_qs, Inscripcio, "equip", [3, 4]),
            legacy_filter_in(legacy_rel_qs, Inscripcio, "equip", [3, 4]),
        )
        self.assertEqual(engine_rel_qs.calls, legacy_rel_qs.calls)

        legacy_scalar_qs = _DummyQuerySet()
        engine_scalar_qs = _DummyQuerySet()
        self.assertEqual(
            filter_in(engine_scalar_qs, Inscripcio, "categoria", ["Base"]),
            legacy_filter_in(legacy_scalar_qs, Inscripcio, "categoria", ["Base"]),
        )
        self.assertEqual(engine_scalar_qs.calls, legacy_scalar_qs.calls)

        passthrough_qs = _DummyQuerySet()
        self.assertIs(filter_in(passthrough_qs, Inscripcio, "categoria", []), passthrough_qs)

        relation_value = SimpleNamespace(_meta=object(), nom="Club Nom")
        relation_row = SimpleNamespace(entitat=relation_value)
        scalar_row = SimpleNamespace(categoria="Base")
        empty_row = SimpleNamespace(entitat=None)

        self.assertEqual(display_value(relation_row, "entitat"), legacy_display_value(relation_row, "entitat"))
        self.assertEqual(display_value(scalar_row, "categoria"), legacy_display_value(scalar_row, "categoria"))
        self.assertEqual(display_value(empty_row, "entitat"), legacy_display_value(empty_row, "entitat"))
