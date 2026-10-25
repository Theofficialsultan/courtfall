"""Regression tests for the sitting-day cost horizon.

The original engine bought `budget / £3,036` days and applied that as a
run-rate for every quarter, while recording spend as `budget`. On an
8-quarter path that charges one year for two years of capacity.

The default now spreads the same budget across the horizon. These tests
lock both results, and the national bills that must not move.
"""

import unittest

from src.decide import (
    budget_table,
    compare_recommendations,
    court_day_assumption,
    decide,
    load_levers,
)
from src.simulate import load_panel, simulate

# Computed from budget_table before the horizon fix, and again after it.
# They come from sitting_need(), which was not part of the undercharge.
STOP_GROWTH_PER_YEAR = 14_645_423.366172388
RETURN_TO_2019 = 148_979_178.24164864


class HorizonAccounting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = load_panel()
        cls.levers = load_levers()
        cls.days, cls.national_days, _ = court_day_assumption(cls.panel, cls.levers)
        cls.once = decide(
            court="Snaresbrook",
            panel=cls.panel,
            levers=cls.levers,
            sitting_charge="once",
        )
        cls.horizon = decide(
            court="Snaresbrook",
            panel=cls.panel,
            levers=cls.levers,
            sitting_charge="horizon",
        )

    def _sitting(self, ranked):
        return ranked.loc[ranked["lever"] == "sitting_days"].iloc[0]

    def test_original_charge_is_preserved(self):
        row = self._sitting(self.once)
        day_cost = float(self.levers["sitting_days"]["cost_per_unit"])
        court_days = float(self.days["Snaresbrook"])
        expected_effect = (100_000 / day_cost) / court_days
        self.assertAlmostEqual(float(row["effect"]), expected_effect, places=9)
        self.assertAlmostEqual(float(row["spend"]), 100_000.0, places=6)
        self.assertAlmostEqual(float(row["cases_cleared"]), 66.19019818073139, places=6)
        self.assertAlmostEqual(float(row["cases_per_1k"]), 0.6619019818073139, places=6)
        self.assertEqual(row["lever"], "sitting_days")
        self.assertTrue(bool(row["is_recommendation"]))

    def test_horizon_charges_two_years_for_two_years(self):
        original = self._sitting(self.once)
        corrected = self._sitting(self.horizon)
        self.assertAlmostEqual(float(corrected["effect"]) * 2, float(original["effect"]), places=9)
        self.assertAlmostEqual(float(corrected["cases_cleared"]) * 2, float(original["cases_cleared"]), places=6)
        self.assertAlmostEqual(float(corrected["spend"]), 100_000.0, places=6)
        self.assertAlmostEqual(float(corrected["cases_per_1k"]) * 2, float(original["cases_per_1k"]), places=6)
        # Same cases per pound as the old national curve, which divided by 2 * spend.
        old_rate = float(original["cases_cleared"]) / (2.0 * float(original["spend"]))
        new_rate = float(corrected["cases_cleared"]) / float(corrected["spend"])
        self.assertAlmostEqual(old_rate, new_rate, places=12)

    def test_horizon_changes_the_snaresbrook_recommendation(self):
        corrected = self._sitting(self.horizon)
        top = self.horizon.loc[self.horizon["is_recommendation"]].iloc[0]
        self.assertEqual(top["lever"], "prisoner_not_produced")
        self.assertAlmostEqual(float(top["cases_per_1k"]), 0.5, places=6)
        self.assertLess(float(corrected["cases_per_1k"]), 0.5)
        self.assertFalse(bool(corrected["is_recommendation"]))

    def test_cause_levers_were_already_on_the_horizon(self):
        for lever in ("prisoner_not_produced", "defence_advocate", "judge", "prosecution", "overlisting"):
            before = self.once.loc[self.once["lever"] == lever].iloc[0]
            after = self.horizon.loc[self.horizon["lever"] == lever].iloc[0]
            self.assertAlmostEqual(float(before["cases_cleared"]), float(after["cases_cleared"]), places=6)
            self.assertAlmostEqual(float(before["spend"]), float(after["spend"]), places=6)

    def test_headlines_are_unchanged(self):
        bills = budget_table(self.panel, self.levers, self.days)
        year = float(bills["stop_growth_gbp_per_year"].sum())
        back = float(bills["back_to_2019_gbp"].sum())
        self.assertAlmostEqual(year, STOP_GROWTH_PER_YEAR, places=4)
        self.assertAlmostEqual(back, RETURN_TO_2019, places=2)
        self.assertEqual(round(year / 1_000_000, 1), 14.6)
        self.assertEqual(round(year * 2 / 1_000_000, 1), 29.3)
        self.assertEqual(round(back / 1_000_000, 1), 149.0)
        self.assertEqual(int(self.panel["court"].nunique()), 68)
        self.assertAlmostEqual(float(self.days.sum()), self.national_days, places=6)

    def test_productivity_and_conversion_scale_cases_not_the_published_price(self):
        half = decide(
            court="Snaresbrook",
            panel=self.panel,
            levers=self.levers,
            sitting_charge="horizon",
            sitting_productivity=0.5,
            disposal_conversion=0.5,
        )
        sitting = self._sitting(half)
        full = self._sitting(self.horizon)
        self.assertAlmostEqual(float(sitting["cases_cleared"]) * 2, float(full["cases_cleared"]), places=6)
        self.assertAlmostEqual(float(sitting["spend"]), float(full["spend"]), places=6)
        prisoner = half.loc[half["lever"] == "prisoner_not_produced"].iloc[0]
        prisoner_full = self.horizon.loc[self.horizon["lever"] == "prisoner_not_produced"].iloc[0]
        self.assertAlmostEqual(float(prisoner["cases_cleared"]) * 2, float(prisoner_full["cases_cleared"]), places=6)
        self.assertAlmostEqual(float(prisoner["spend"]), float(prisoner_full["spend"]), places=6)

    def test_simulator_defaults_match_the_unscaled_path(self):
        plain = simulate("Snaresbrook", quarters=2, levers={"sitting_days": 0.1}, panel=self.panel)
        explicit = simulate(
            "Snaresbrook",
            quarters=2,
            levers={"sitting_days": 0.1},
            panel=self.panel,
            sitting_productivity=1.0,
            disposal_conversion=1.0,
        )
        self.assertTrue(plain["open_scenario"].equals(explicit["open_scenario"]))

    def test_charge_once_flips_some_courts_and_central_flips_none(self):
        same = compare_recommendations(self.panel, self.levers, sitting_charge="horizon")
        self.assertEqual(int((~same["stable"]).sum()), 0)
        self.assertEqual(len(same), 68)
        original = compare_recommendations(self.panel, self.levers, sitting_charge="once")
        self.assertGreater(int((~original["stable"]).sum()), 0)
        snaresbrook = original.loc[original["court"] == "Snaresbrook"].iloc[0]
        self.assertEqual(snaresbrook["central_lever"], "prisoner_not_produced")
        self.assertEqual(snaresbrook["scenario_lever"], "sitting_days")
        self.assertFalse(bool(snaresbrook["stable"]))


if __name__ == "__main__":
    unittest.main()
