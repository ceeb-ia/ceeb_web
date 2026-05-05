import unittest

from calendaritzacions.domain.errors import (
    CalendarizationError,
    InfeasibleCalendarizationError,
    InvalidSeedMappingError,
)
from calendaritzacions.engine.legacy.costs import build_disposicions, cost_calc


class DomainErrorTests(unittest.TestCase):
    def test_domain_errors_share_calendarization_base(self):
        self.assertTrue(issubclass(InfeasibleCalendarizationError, CalendarizationError))
        self.assertTrue(issubclass(InvalidSeedMappingError, CalendarizationError))

    def test_cost_calc_raises_domain_error_for_missing_home_away_mapping(self):
        fase = [[(1, 2), (3, 4), (5, 6), (7, 8)]]
        disposicions = build_disposicions(fase)

        with self.assertRaises(InvalidSeedMappingError) as cm:
            cost_calc("Equip A", "casa", 0, 0, disposicions, {}, fase)

        self.assertEqual(str(cm.exception), "No hi ha mapping vàlid per a l'equip")

    def test_cost_calc_raises_domain_error_for_invalid_home_away_mapping(self):
        fase = [[(1, 2), (3, 4), (5, 6), (7, 8)]]
        disposicions = build_disposicions(fase)

        with self.assertRaises(InvalidSeedMappingError) as cm:
            cost_calc("Equip A", "fora", 0, 0, disposicions, {"Equip A": 1}, fase)

        self.assertEqual(str(cm.exception), "No hi ha número vàlid per a l'equip")


if __name__ == "__main__":
    unittest.main()
