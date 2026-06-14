import math
import unittest

from calendaritzacions.domain.normalization import normalize_seed_value, parse_int
from calendaritzacions.domain.phases import (
    FIRST_PHASE,
    PRIMERA_FASE,
    PRIMERA_FASE_10,
    SECOND_PHASE,
    SEGONA_FASE,
    SEGONA_FASE_10,
    build_disposicions,
    phase_calendar,
    slot_count_for_numbers,
)
from calendaritzacions.domain.requests import (
    expected_seed,
    request_display_code,
    request_type,
)


class DomainPhaseRequestsTests(unittest.TestCase):
    def test_phase_lengths_match_legacy_calendar_shape(self):
        self.assertEqual(len(PRIMERA_FASE), 7)
        self.assertEqual(len(SEGONA_FASE), 14)
        self.assertEqual(FIRST_PHASE.rounds, 7)
        self.assertEqual(SECOND_PHASE.rounds, 14)
        self.assertTrue(all(len(jornada) == 4 for jornada in PRIMERA_FASE))
        self.assertTrue(all(len(jornada) == 4 for jornada in SEGONA_FASE))

    def test_phase_calendar_resolves_supported_slot_counts(self):
        self.assertIs(phase_calendar("primera_fase", 8), PRIMERA_FASE)
        self.assertIs(phase_calendar("primera_fase", 10), PRIMERA_FASE_10)
        self.assertIs(phase_calendar("segona_fase", 8), SEGONA_FASE)
        self.assertIs(phase_calendar("segona_fase", 10), SEGONA_FASE_10)
        self.assertEqual(slot_count_for_numbers((1, 2, 8)), 8)
        self.assertEqual(slot_count_for_numbers(tuple(range(1, 11))), 10)

    def test_build_disposicions_first_phase_home_away_patterns(self):
        disposicions = build_disposicions(PRIMERA_FASE)

        self.assertEqual(len(disposicions), 8)
        self.assertEqual(disposicions[0], ["casa", "fora", "casa", "fora", "casa", "fora", "casa"])
        self.assertEqual(disposicions[7], ["casa", "fora", "casa", "fora", "casa", "casa", "fora"])
        self.assertTrue(all(len(pattern) == 7 for pattern in disposicions))

    def test_build_disposicions_second_phase_extends_patterns(self):
        disposicions = build_disposicions(SEGONA_FASE)

        self.assertEqual(len(disposicions), 8)
        self.assertEqual(disposicions[0][:7], build_disposicions(PRIMERA_FASE)[0])
        self.assertEqual(disposicions[0][7:], ["fora", "casa", "fora", "casa", "fora", "casa", "fora"])
        self.assertTrue(all(len(pattern) == 14 for pattern in disposicions))

    def test_build_disposicions_supports_ten_slots(self):
        disposicions = build_disposicions(PRIMERA_FASE_10)

        self.assertEqual(len(disposicions), 10)
        self.assertTrue(all(len(pattern) == 9 for pattern in disposicions))
        self.assertEqual(disposicions[8][0], "casa")
        self.assertEqual(disposicions[9][0], "casa")

    def test_request_parsing_and_display_codes(self):
        cases = [
            (" casa ", "casa", "CASA"),
            ("FORA", "fora", "FORA"),
            ("3", "explicit", "3"),
            (3.0, "explicit", "3"),
            ("3.8", "explicit", "3"),
            (9, "none", ""),
            ("", "none", ""),
        ]
        for raw, expected_type, expected_code in cases:
            with self.subTest(raw=raw):
                self.assertEqual(request_type(raw), expected_type)
                self.assertEqual(request_display_code(raw), expected_code)

    def test_parse_int_and_seed_normalization_match_legacy_semantics(self):
        self.assertEqual(parse_int("3.0"), 3)
        self.assertTrue(math.isnan(parse_int("3.2")))
        self.assertTrue(math.isnan(parse_int(None)))
        self.assertEqual(normalize_seed_value(" CASA "), "casa")
        self.assertEqual(normalize_seed_value("fora"), "fora")
        self.assertEqual(normalize_seed_value("4.0"), 4)

    def test_expected_seed_resolves_explicit_and_casa_fora_mapping(self):
        mapping = {"eq-1": 8, "eq-2": "3"}

        self.assertEqual(expected_seed("2.9", "eq-1", mapping), 2)
        self.assertEqual(expected_seed("casa", "eq-1", mapping), 8)
        self.assertEqual(expected_seed("FORA", "eq-2", mapping), 3)
        self.assertTrue(math.isnan(expected_seed("casa", "missing", mapping)))
        self.assertTrue(math.isnan(expected_seed("x", "eq-1", mapping)))


if __name__ == "__main__":
    unittest.main()
