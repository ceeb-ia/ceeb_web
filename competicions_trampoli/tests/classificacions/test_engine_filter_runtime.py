from types import SimpleNamespace

from django.test import SimpleTestCase

from ...services.classificacions.engine.filter_runtime import (
    _inscripcio_matches_classificacio_filters,
    _inscripcio_matches_filter_field,
    _native_team_members_match_classificacio_filters,
    _normalized_group_filter_value,
)


class FilterRuntimeTests(SimpleTestCase):
    def test_normalized_group_filter_value_prefers_display_num(self):
        inscripcio = SimpleNamespace(
            grup=9,
            grup_competicio=SimpleNamespace(display_num="4"),
        )

        self.assertEqual(_normalized_group_filter_value(inscripcio), "4")

    def test_inscripcio_matches_filter_field_supports_relational_ids_and_names(self):
        equip = SimpleNamespace(_meta=object(), nom="Team A")
        inscripcio = SimpleNamespace(equip_id=7, equip=equip)

        self.assertTrue(_inscripcio_matches_filter_field(inscripcio, "equip", [7]))
        self.assertTrue(_inscripcio_matches_filter_field(inscripcio, "equip", ["team a"]))
        self.assertFalse(_inscripcio_matches_filter_field(inscripcio, "equip", [8, "Team B"]))

    def test_inscripcio_matches_classificacio_filters_normalizes_text_and_groups(self):
        inscripcio = SimpleNamespace(
            entitat=" Club A ",
            categoria="Base",
            subcategoria="Senior",
            grup=9,
            grup_competicio=SimpleNamespace(display_num=4),
        )

        self.assertTrue(
            _inscripcio_matches_classificacio_filters(
                inscripcio,
                {
                    "entitats_in": ["club a"],
                    "categories_in": [" base "],
                    "subcategories_in": ["senior"],
                    "grups_in": [4.0],
                },
            )
        )
        self.assertFalse(
            _inscripcio_matches_classificacio_filters(
                inscripcio,
                {
                    "entitats_in": ["Club A"],
                    "grups_in": [5],
                },
            )
        )

    def test_native_team_members_match_filters_dedupes_repeated_member_rows(self):
        member_a = SimpleNamespace(
            id=11,
            entitat="Club A",
            categoria="Base",
            subcategoria="Senior",
            grup=1,
            grup_competicio=None,
        )
        member_b = SimpleNamespace(
            id=12,
            entitat="Club A",
            categoria="Base",
            subcategoria="Senior",
            grup=1,
            grup_competicio=None,
        )

        result = _native_team_members_match_classificacio_filters(
            [
                (member_a, {"slot": 1}),
                (member_a, {"slot": 1}),
                (member_b, {"slot": 2}),
            ],
            {"entitats_in": ["club a"], "categories_in": ["base"], "grups_in": ["1"]},
        )

        self.assertTrue(result)

    def test_native_team_members_match_filters_rejects_invalid_or_non_matching_rows(self):
        member = SimpleNamespace(
            id=21,
            entitat="Club B",
            categoria="Promo",
            subcategoria="Senior",
            grup=2,
            grup_competicio=None,
        )

        self.assertFalse(_native_team_members_match_classificacio_filters([], {"entitats_in": ["Club B"]}))
        self.assertFalse(_native_team_members_match_classificacio_filters(["bad-row"], {"entitats_in": ["Club B"]}))
        self.assertFalse(
            _native_team_members_match_classificacio_filters(
                [(member,)],
                {"entitats_in": ["Club A"]},
            )
        )
