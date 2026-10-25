"""The live simulator, the ranking, and a historical backtest share one contract."""

import unittest

import pandas as pd

from src.decide import court_day_assumption, decide, load_levers
from src.model import FEATURES, build_frame, evaluate_rate, supervised_rows
from src.scenario import run_scenario
from src.simulate import forecast_errors, load_panel, simulate


class ScenarioContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = load_panel()
        cls.levers = load_levers()
        cls.days, _, _ = court_day_assumption(cls.panel, cls.levers)

    def _run(self, levers, **kwargs):
        return run_scenario(
            "Snaresbrook",
            self.panel,
            levers=levers,
            lever_config=self.levers,
            court_days=self.days,
            **kwargs,
        )

    def test_zero_intervention_matches_baseline(self):
        report = self._run({})
        self.assertEqual(report["cases_cleared"], 0.0)
        self.assertEqual(report["end_baseline"], report["end_scenario"])
        self.assertEqual(report["spend_8q"], 0.0)
        for point in report["series"]:
            self.assertEqual(point["open_baseline"], point["open_scenario"])

    def test_overlisting_25_then_50_then_zero(self):
        zero = self._run({"overlisting": 0.0})
        quarter = self._run({"overlisting": 0.25})
        half = self._run({"overlisting": 0.50})
        self.assertGreater(quarter["cases_cleared"], zero["cases_cleared"])
        self.assertAlmostEqual(half["cases_cleared"], quarter["cases_cleared"] * 2, places=6)
        self.assertEqual(zero["end_baseline"], quarter["end_baseline"])
        self.assertEqual(quarter["end_baseline"], half["end_baseline"])
        self.assertLess(half["end_scenario"], quarter["end_scenario"])
        self.assertAlmostEqual(quarter["cases_cleared"], 26.5, places=6)
        self.assertAlmostEqual(half["cases_cleared"], 53.0, places=6)

    def test_zero_eligible_trials_clear_nothing(self):
        history = self.panel.loc[self.panel["court"] == "Snaresbrook"].sort_values("period")
        column = "judge_n"
        # Force the condition on a copy so the test does not depend on one court.
        panel = self.panel.copy()
        panel.loc[panel["court"] == "Snaresbrook", column] = 0.0
        report = run_scenario(
            "Snaresbrook",
            panel,
            levers={"judge": 0.5},
            lever_config=self.levers,
            court_days=self.days,
        )
        self.assertEqual(report["cases_cleared"], 0.0)
        judge = next(row for row in report["levers"] if row["lever"] == "judge")
        self.assertEqual(judge["status"], "no_eligible_trials")
        self.assertIn("clears nothing", judge["reason"])
        self.assertEqual(history["court"].iloc[0], "Snaresbrook")

    def test_horizon_bill_is_two_years_and_once_is_labelled_legacy(self):
        horizon = self._run({"sitting_days": 0.05}, sitting_charge="horizon")
        once = self._run({"sitting_days": 0.05}, sitting_charge="once")
        self.assertAlmostEqual(once["cases_cleared"], horizon["cases_cleared"], places=6)
        self.assertAlmostEqual(horizon["sitting_spend_8q"], once["sitting_spend_8q"] * 2, places=6)
        self.assertAlmostEqual(
            horizon["sitting_spend_8q"],
            horizon["days_per_year"] * 2 * horizon["day_cost"],
            places=6,
        )
        self.assertIn("Legacy comparison", " ".join(once["notes"]))
        direct = simulate(
            "Snaresbrook",
            quarters=8,
            levers={"sitting_days": 0.05},
            panel=self.panel,
        )
        self.assertAlmostEqual(
            horizon["cases_cleared"],
            float(direct["open_baseline"].iloc[-1] - direct["open_scenario"].iloc[-1]),
            places=6,
        )

    def test_budget_over_eight_quarters_matches_the_ranking_fraction(self):
        price = float(self.levers["sitting_days"]["cost_per_unit"])
        days = float(self.days["Snaresbrook"])
        budget = 100_000
        report = self._run({}, sitting_budget_gbp=budget, sitting_charge="horizon")
        expected_days = (budget / price) / 2.0
        self.assertAlmostEqual(report["days_per_year"], expected_days, places=6)
        self.assertAlmostEqual(report["spend_8q"], budget, places=4)
        ranked = decide(
            court="Snaresbrook",
            budget=budget,
            panel=self.panel,
            levers=self.levers,
            sitting_charge="horizon",
        )
        sitting = ranked.loc[ranked["lever"] == "sitting_days"].iloc[0]
        self.assertAlmostEqual(report["cases_cleared"], float(sitting["cases_cleared"]), places=6)
        self.assertAlmostEqual(report["sitting_fraction"], expected_days / days, places=8)

    def test_causes_do_not_double_count(self):
        both = self._run({"overlisting": 0.25, "prosecution": 0.25})
        over = self._run({"overlisting": 0.25})
        prosecution = self._run({"prosecution": 0.25})
        self.assertAlmostEqual(
            both["cases_cleared"],
            over["cases_cleared"] + prosecution["cases_cleared"],
            places=6,
        )

    def test_negative_lever_is_rejected(self):
        with self.assertRaises(ValueError):
            self._run({"overlisting": -0.2})

    def test_productivity_zero_does_not_invent_disposals(self):
        report = self._run({"sitting_days": 0.25}, sitting_productivity=0)
        self.assertEqual(report["cases_cleared"], 0.0)
        self.assertGreater(report["spend_8q"], 0)

    def test_assumptions_change_the_ranking_input(self):
        central = decide(
            court="Snaresbrook",
            panel=self.panel,
            levers=self.levers,
            sitting_charge="horizon",
        )
        original = decide(
            court="Snaresbrook",
            panel=self.panel,
            levers=self.levers,
            sitting_charge="once",
        )
        central_top = central.loc[central["is_recommendation"]].iloc[0]["lever"]
        original_top = original.loc[original["is_recommendation"]].iloc[0]["lever"]
        self.assertNotEqual(central_top, original_top)


class BacktestContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = load_panel()

    def test_future_rates_do_not_change_training_features(self):
        cutoff = "2023Q4"
        clean = supervised_rows(build_frame(self.panel))
        train = clean.loc[clean["target_period"] <= cutoff, ["court", "target_period", *FEATURES]]
        corrupted = self.panel.copy()
        corrupted.loc[corrupted["period"] > cutoff, "ineffective_rate"] = 0.99
        dirty = supervised_rows(build_frame(corrupted))
        train_dirty = dirty.loc[dirty["target_period"] <= cutoff, ["court", "target_period", *FEATURES]]
        pd.testing.assert_frame_equal(
            train.reset_index(drop=True),
            train_dirty.reset_index(drop=True),
        )

    def test_rate_mae_is_recomputed_from_the_predictions(self):
        evaluated = evaluate_rate(self.panel, "2023Q4", horizon_quarters=1)
        frame = evaluated["frame"]
        self.assertEqual(evaluated["train_through"], "2023Q4")
        self.assertGreater(frame["period"].min(), "2023Q4")
        weight = frame["listed"].to_numpy()
        gap = abs(frame["actual"] - frame["blend"])
        manual = 100 * float((weight * gap).sum() / weight.sum())
        blend = next(row for row in evaluated["scores"] if row["key"] == "blend")
        self.assertAlmostEqual(blend["weighted_mae_pp"], manual, places=6)
        self.assertFalse(evaluated["blend_weight_fit_on_test"])

    def test_backlog_forecast_ignores_later_flows_and_reports_step_errors(self):
        detail, by_step = forecast_errors(self.panel, "2023Q4", 8, court="Snaresbrook")
        self.assertEqual(set(detail["court"]), {"Snaresbrook"})
        self.assertEqual(int(by_step["step"].max()), 8)
        direct = simulate(
            "Snaresbrook",
            quarters=8,
            levers={},
            as_of="2023Q4",
            panel=self.panel,
        )
        merged = detail.merge(direct.loc[direct["step"] > 0, ["period", "open_baseline"]], on="period")
        self.assertTrue((merged["open_baseline_x"] - merged["open_baseline_y"]).abs().max() < 1e-6)
        self.assertIn(1, set(by_step["step"]))
        self.assertGreater(float(by_step.loc[by_step["step"] == 8, "mae"].iloc[0]), 0)


if __name__ == "__main__":
    unittest.main()
