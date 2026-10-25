"""Load the panel, model, and planning tables once, then serve slices of them.

Live simulation and ranking call src.scenario and src.decide. A backtest run
calls src.model.evaluate_rate or src.simulate.forecast_errors and caches the
result by the full request. The startup tables are not relabelled as a new run.
"""

from __future__ import annotations

import io
import contextlib
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from fpdf import FPDF

from src.decide import (
    budget_table,
    compare_recommendations,
    court_day_assumption,
    decide,
    load_levers,
)
from src.model import (
    BLEND_WEIGHT,
    FEATURES,
    MODEL_VERSION,
    build_frame,
    evaluate_rate,
    fit_and_score,
    live_rows,
    shap_matrix,
)
from src.scenario import run_scenario
from src.simulate import (
    _accounting_error,
    _last4,
    _one_step_mae,
    backtest,
    forecast_errors,
    load_panel,
    simulate,
)

ROOT = Path(__file__).resolve().parents[1]
ACTIONS_PATH = ROOT / "data" / "actions.json"
TRIALS_PATH = ROOT / "data" / "trials.json"
EVIDENCE_PATH = ROOT / "config" / "evidence.yaml"

# Map bands from the UI brief. Not the trial-risk cut points.
MAP_GREEN_BELOW = 0.15
MAP_AMBER_AT_MOST = 0.30

# Trial-risk bands. Chosen, not fitted. Same cut points as app.py.
TRIAL_GREEN_BELOW = 0.20
TRIAL_AMBER_BELOW = 0.35

CAUSE_ACTIONS = [
    ("prosecution", "CPS readiness check 14 days pre-trial", "CPS"),
    ("overlisting", "Reduce listing ratio / standby case", "Listing officer"),
    ("defence_advocate", "Confirm counsel 48h prior", "Defence solicitor"),
    ("prisoner_not_produced", "Book video link / escort confirmation", "Prisoner escort"),
    ("judge", "Reallocate recorders", "Resident judge"),
]

FEATURE_LABELS = {
    "last_quarter_rate": "Last quarter rate",
    "rate_two_quarters_ago": "Rate two quarters ago",
    "rate_three_quarters_ago": "Rate three quarters ago",
    "rate_four_quarters_ago": "Rate four quarters ago",
    "four_quarter_average": "4-quarter average",
    "prosecution_share": "Prosecution / witness share",
    "overlisting_share": "Overlisting share",
    "defence_advocate_share": "Defence advocate share",
    "prisoner_not_produced_share": "Prisoner not produced share",
    "judge_share": "Judge availability share",
    "open_cases": "Open caseload",
    "receipts": "Receipts",
    "quarter": "Calendar quarter",
    "covid_2020_2022": "2020–2022 flag",
}

MODEL_KEYS = {
    "blend": "blend",
    "lightgbm": "lightgbm",
    "four_quarter": "four_quarter",
    "last_quarter": "last_quarter",
}

MODEL_NAMES = {
    "blend": "50/50 blend",
    "lightgbm": "LightGBM",
    "four_quarter": "4-quarter average",
    "last_quarter": "Last quarter",
}

_lock = threading.Lock()


def money(amount):
    if amount is None or (isinstance(amount, float) and np.isnan(amount)):
        return "not available"
    amount = float(amount)
    if abs(amount) >= 1_000_000:
        return f"£{amount / 1_000_000:.1f}m"
    return f"£{amount:,.0f}"


def _num(value):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, (np.floating, float)):
        return float(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _records(frame):
    if frame is None or frame.empty:
        return []
    copied = frame.copy()
    for column in copied.columns:
        if pd.api.types.is_numeric_dtype(copied[column]):
            copied[column] = copied[column].astype(object).where(copied[column].notna(), None)
    payload = json.loads(copied.to_json(orient="records"))
    return payload


def _paid_brief(row):
    return {
        "lever": row["lever"],
        "label": row["label"],
        "cases_cleared": float(row["cases_cleared"]),
        "spend": float(row["spend"]),
        "cases_per_1k": _num(row["cases_per_1k"]),
    }


def _rank_payload(frame):
    rows = []
    ordered = frame.copy()
    ordered["_section_order"] = ordered["section"].map({"per_pound": 0, "no_cost": 1}).fillna(2)
    ordered = ordered.sort_values(["_section_order", "rank"])
    for _, row in ordered.iterrows():
        rows.append(
            {
                "lever": row["lever"],
                "label": row["label"],
                "section": row["section"],
                "rank": int(row["rank"]),
                "cases_cleared": float(row["cases_cleared"]),
                "spend": float(row["spend"]),
                "cases_per_1k": _num(row["cases_per_1k"]),
                "is_recommendation": bool(row["is_recommendation"]),
                "free_win": bool(row["free_win"]),
                "note": row["note"],
            }
        )
    return rows


def load_evidence(path=EVIDENCE_PATH):
    with open(path) as handle:
        loaded = yaml.safe_load(handle)
    for claim in loaded.get("claims", []):
        alternative = claim.get("evidence_informed_alternative")
        if not alternative:
            continue
        disposal = float(alternative["disposal_change"])
        days = float(alternative["sitting_day_change"])
        alternative["sitting_productivity"] = disposal / days
    return loaded


def map_band(rate):
    if rate is None or (isinstance(rate, float) and np.isnan(rate)):
        return None
    if rate < MAP_GREEN_BELOW:
        return "green"
    if rate <= MAP_AMBER_AT_MOST:
        return "amber"
    return "red"


def _confidence(lever, free_win, assumed_cost):
    """High only when the unit cost is the published sitting-day figure."""
    if lever == "sitting_days" and not assumed_cost:
        return "High"
    if free_win:
        return "Low"
    return "Medium"


def _pdf_safe(text):
    return (
        str(text)
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2022", "-")
        .replace("\u00a3", "GBP ")
    )


class Store:
    def __init__(self):
        self.panel = load_panel()
        self.levers = load_levers()
        self.court_days, self.national_days, _ = court_day_assumption(self.panel, self.levers)
        self.ranked = decide(panel=self.panel, levers=self.levers)
        self.bills = budget_table(self.panel, self.levers, self.court_days)
        self.latest_period = str(self.panel["period"].max())
        self.latest = self.panel.loc[self.panel["period"] == self.latest_period].copy()

        scores, predictions, model, train, test = fit_and_score(self.panel)
        self.scores = scores
        self.predictions = predictions
        self.model = model
        self.train_rows = int(len(train))
        self.test_rows = int(len(test))

        frame = build_frame(self.panel)
        live = live_rows(frame)
        values = shap_matrix(model, live[FEATURES])
        self.drivers = {}
        self.inputs = {}
        for i, (_, row) in enumerate(live.iterrows()):
            court = row["court"]
            notes = []
            items = []
            for j, feature in enumerate(FEATURES):
                shap_value = float(values[i, j])
                note = None
                if feature == "covid_2020_2022" and int(row["covid_2020_2022"]) == 0:
                    note = (
                        "The 2020–2022 flag is off for this forecast. "
                        "A negative value means the tree is not in those years. "
                        "It is not a current cause."
                    )
                items.append(
                    {
                        "feature": feature,
                        "label": FEATURE_LABELS.get(feature, feature),
                        "shap": shap_value,
                        "note": note,
                    }
                )
                notes.append(note)
            items.sort(key=lambda item: abs(item["shap"]), reverse=True)
            self.drivers[court] = items
            self.inputs[court] = {feature: _num(row[feature]) for feature in FEATURES}

        model_rate = model.predict(test[FEATURES])
        average = test["four_quarter_average"].to_numpy()
        last = test["last_quarter_rate"].to_numpy()
        self.rate_test = pd.DataFrame(
            {
                "court": test["court"].to_numpy(),
                "period": test["target_period"].to_numpy(),
                "actual": test["target"].to_numpy(),
                "listed": test["target_listed"].to_numpy(),
                "lightgbm": model_rate,
                "four_quarter": average,
                "last_quarter": last,
                "blend": BLEND_WEIGHT * model_rate + (1.0 - BLEND_WEIGHT) * average,
            }
        )

        with contextlib.redirect_stdout(io.StringIO()):
            self.frozen = backtest(start="2023Q4", panel=self.panel)
        self.one_step = self._one_step_detail("2023Q4")
        account, previous = _accounting_error(self.panel, "2023Q4")
        self.accounting_mae = float(account)
        self.previous_flow_mae = float(previous)
        self.one_step_mae = float(_one_step_mae(self.panel, "2023Q4"))
        self.frozen_mae = float(self.frozen["abs_err"].mean())
        detail_one = float(self.one_step["abs_err"].mean())
        if abs(detail_one - self.one_step_mae) > 0.05:
            raise RuntimeError(
                f"One-step detail MAE {detail_one} does not match _one_step_mae {self.one_step_mae}"
            )

        self.national_open = float(self.latest["open"].sum())
        self.curve, self.per_million, self.allocation_order = self._allocation_frame()
        self.paths = self._do_nothing_paths()
        self._eval_cache = {}
        self._rank_cache = {}
        self._scenario_cache = {}

    def _one_step_detail(self, start):
        """Same loop as src.simulate._one_step_mae, kept so the series can be plotted."""
        rows = []
        for court, history in self.panel.groupby("court", sort=False):
            history = history.sort_values("period").reset_index(drop=True)
            for i in range(len(history)):
                if history.at[i, "period"] <= start:
                    continue
                past = history.iloc[:i]
                if past.empty:
                    continue
                receipts = float(past["receipts"].tail(4).mean())
                disposals = float(past["disposals"].tail(4).mean())
                predicted = float(past["open"].iloc[-1]) + receipts - disposals
                actual = float(history.at[i, "open"])
                rows.append(
                    {
                        "court": court,
                        "period": history.at[i, "period"],
                        "actual": actual,
                        "predicted": predicted,
                        "abs_err": abs(predicted - actual),
                    }
                )
        return pd.DataFrame(rows)

    def _allocation_frame(self):
        sitting = self.ranked.loc[self.ranked["lever"] == "sitting_days"].copy()
        merged = sitting.merge(self.bills, on="court", how="left")
        # spend is the 8-quarter bill from decide(). Do not divide by 2 again.
        merged["cases_per_pound"] = merged["cases_cleared"] / merged["spend"].where(
            merged["spend"] > 0
        )
        merged["cap_gbp"] = merged["back_to_2019_gbp"].fillna(0.0).clip(lower=0.0)
        merged["end_do_nothing"] = merged["open_now"] + 8.0 * (merged["receipts"] - merged["disposals"])
        merged = merged.sort_values(["cases_per_pound", "court"], ascending=[False, True])
        baseline = float(merged["end_do_nothing"].sum())
        points = []
        for budget in range(0, 150_000_001, 5_000_000):
            remaining = float(budget)
            cleared = 0.0
            for _, court in merged.iterrows():
                if remaining <= 0:
                    break
                take = min(remaining, float(court["cap_gbp"]))
                cleared += take * float(court["cases_per_pound"] or 0.0)
                remaining -= take
            points.append({"budget": budget, "open_cases": baseline - cleared})
        per_million = merged.loc[
            merged["cases_per_pound"].notna(), ["court", "cases_per_pound"]
        ].copy()
        per_million["cases_per_1m"] = per_million["cases_per_pound"] * 1_000_000
        per_million = per_million.sort_values("cases_per_1m", ascending=False)
        return pd.DataFrame(points), per_million, merged

    def _do_nothing_paths(self):
        paths = {}
        for court in sorted(self.panel["court"].unique()):
            projected = simulate(court, quarters=8, levers={}, panel=self.panel)
            paths[court] = [
                {
                    "period": str(row.period),
                    "open": float(row.open_baseline),
                }
                for row in projected.itertuples(index=False)
            ]
        return paths

    def _prediction_row(self, court):
        rows = self.predictions.loc[self.predictions["court"] == court]
        if rows.empty:
            raise KeyError(court)
        return rows.iloc[0]

    def _bill(self, court):
        rows = self.bills.loc[self.bills["court"] == court]
        if rows.empty:
            raise KeyError(court)
        return rows.iloc[0]

    def _latest_row(self, court):
        rows = self.latest.loc[self.latest["court"] == court]
        if rows.empty:
            raise KeyError(court)
        return rows.iloc[0]

    def _require(self, court):
        if court not in set(self.panel["court"]):
            raise KeyError(court)

    def courts(self):
        pred = self.predictions.set_index("court")
        out = []
        for _, row in self.latest.sort_values("court").iterrows():
            rate = float(pred.loc[row["court"], "predicted_rate"])
            out.append(
                {
                    "name": row["court"],
                    "lat": float(row["lat"]),
                    "lon": float(row["lon"]),
                    "open": float(row["open"]),
                    "predicted_rate": rate,
                    "risk_band": map_band(rate),
                    "period": self.latest_period,
                }
            )
        return out

    def _interventions(self, court):
        table = self.ranked.loc[self.ranked["court"] == court].copy()
        rows = []
        for _, row in table.iterrows():
            free = bool(row["free_win"])
            per_1k = _num(row["cases_per_1k"])
            if free:
                cost_label = "£0, policy change"
                cost_basis = "Assumed £0 admin cost. Not bought with the budget."
            elif row["lever"] == "sitting_days":
                cost_label = money(row["spend"])
                cost_basis = (
                    "Ranking budget of £100,000. That buys extra days at the published "
                    "£3,036 a day. The simulator holds the higher rate for 8 quarters. "
                    "This court's share of national days is assumed."
                )
            else:
                cost_label = money(row["spend"])
                cost_basis = (
                    "Placeholder price times the cut, over 8 quarters. "
                    "The price and the effect size are assumed."
                )
            rows.append(
                {
                    "lever": row["lever"],
                    "label": row["label"],
                    "cases_cleared": float(row["cases_cleared"]),
                    "cost": float(row["spend"]),
                    "cost_label": cost_label,
                    "cost_basis": cost_basis,
                    "cases_per_1k": per_1k,
                    "confidence": _confidence(row["lever"], free, bool(row["assumed_cost"])),
                    "assumed_cost": bool(row["assumed_cost"]),
                    "assumed_effect": True,
                    "assumed_day_split": row["lever"] == "sitting_days",
                    "free_win": free,
                    "rank": int(row["rank"]),
                    "section": row["section"],
                    "is_recommendation": bool(row["is_recommendation"]),
                    "note": row["note"],
                }
            )
        return rows

    def _actions(self, court):
        bill = self._bill(court)
        latest = self._latest_row(court)
        history = self.panel.loc[self.panel["court"] == court].sort_values("period")
        growth = float(bill["receipts"] - bill["disposals"])
        days = float(bill["stop_growth_days"]) if pd.notna(bill["stop_growth_days"]) else 0.0
        yearly = (
            float(bill["stop_growth_gbp_per_year"])
            if pd.notna(bill["stop_growth_gbp_per_year"])
            else 0.0
        )
        if growth > 1 and days > 0:
            impact = growth * 8.0
            detail = (
                f"Ask for {days:,.0f} extra sitting days a year so disposals meet receipts. "
                f"That is {money(yearly)} a year at the published £3,036 a day."
            )
            cost_label = f"{money(yearly)} a year"
            confidence = "High"
            confidence_note = (
                "Growth is calculated from receipts and disposals. "
                "£3,036 a day is published. The day split is assumed."
            )
        else:
            impact = 0.0
            yearly = 0.0
            detail = "No extra sitting days. On the last four quarters, disposals already meet receipts."
            cost_label = "£0"
            confidence = "High"
            confidence_note = "The last four quarters of receipts and disposals already balance."
        actions = [
            {
                "id": "capacity",
                "title": "Capacity ask",
                "detail": detail,
                "impact": impact,
                "impact_label": (
                    f"{impact:,.0f} cases not added over 8 quarters"
                    if impact
                    else "0 cases. This run-rate is not growing."
                ),
                "cost": yearly,
                "cost_label": cost_label,
                "owner": "Resident judge, to HMCTS",
                "confidence": confidence,
                "confidence_note": confidence_note,
                "assumed_day_split": True,
                "assumed_effect": True,
            }
        ]
        for name, title, owner in CAUSE_ACTIONS:
            available = _last4(history, f"{name}_n")
            if available <= 0:
                continue
            spec = self.levers[name]
            effect = float(spec["default_effect"])
            price = float(spec["cost_per_unit"])
            projected = simulate(court, quarters=8, levers={name: effect}, panel=self.panel)
            final = projected.iloc[-1]
            cases = float(final["open_baseline"] - final["open_scenario"])
            spend = 0.0 if price == 0 else available * effect * 8.0 * price
            share = latest.get(f"{name}_share", 0.0)
            share = 0.0 if pd.isna(share) else float(share)
            if price == 0:
                cost_label = "£0, policy change"
                cost_note = "The £0 price is assumed, and so is the size of the cut."
                confidence = "Low"
            else:
                cost_label = money(spend)
                cost_note = "The price per avoided trial is a placeholder, and the size of the cut is assumed."
                confidence = "Medium"
            actions.append(
                {
                    "id": name,
                    "title": title,
                    "detail": (
                        f"{share * 100:.0f}% of ineffective trials in {latest['period']} were this cause. "
                        f"The plan assumes {effect * 100:.0f}% of them are avoided. "
                        f"{cost_note} One avoided trial is counted as one extra disposal."
                    ),
                    "impact": cases,
                    "impact_label": f"{cases:,.0f} cases cleared over 8 quarters",
                    "cost": spend,
                    "cost_label": cost_label,
                    "owner": owner,
                    "confidence": confidence,
                    "confidence_note": "The cause count is from the MoJ table. The effect and the cost are assumed.",
                    "assumed_day_split": False,
                    "assumed_effect": True,
                }
            )
        capacity = actions[0]
        causes = sorted(actions[1:], key=lambda row: row["impact"], reverse=True)
        chosen = sorted([capacity] + causes, key=lambda row: row["impact"], reverse=True)[:5]
        if not any(row["id"] == "capacity" for row in chosen):
            chosen = sorted(chosen[:4] + [capacity], key=lambda row: row["impact"], reverse=True)
        done = self._read_json(ACTIONS_PATH, {}).get(court, {})
        for rank, row in enumerate(chosen, start=1):
            row["rank"] = rank
            row["done"] = bool(done.get(row["id"], False))
        return chosen

    def _narrative(self, court):
        bill = self._bill(court)
        ranked = self.ranked.loc[self.ranked["court"] == court]
        paid = ranked.loc[ranked["is_recommendation"]].iloc[0]
        free = ranked.loc[ranked["section"] == "no_cost"]
        growth = float(bill["receipts"] - bill["disposals"])
        if growth > 1:
            opening = (
                f"{court}'s open caseload is growing by about {growth:.0f} cases a quarter, "
                "using the average of the last four quarters."
            )
        elif growth < -1:
            opening = (
                f"{court}'s open caseload is falling by about {-growth:.0f} cases a quarter, "
                "using the average of the last four quarters."
            )
        else:
            opening = f"{court}'s open caseload is roughly flat on the last four quarters."
        stop = (
            f"Stopping the growth would take about {money(bill['stop_growth_gbp_per_year'])} a year "
            f"in extra sitting days ({float(bill['stop_growth_days']):,.0f} days). "
            "The £3,036 per day is published. Assigning those days to this court is assumed."
        )
        if bool(paid["assumed_cost"]):
            price = "That price is a placeholder."
        else:
            price = (
                "That uses the published sitting-day cost. "
                "The size of the effect still uses the assumed day split."
            )
        best = (
            f"The best £100,000 purchase is {paid['label']}, clearing about {paid['cases_cleared']:.0f} "
            f"open cases over 8 quarters and spending {money(paid['spend'])}. {price}"
        )
        if free.empty or float(free.iloc[0]["cases_cleared"]) == 0:
            extra = "Overlisting has no failures to cut in the last four quarters."
        else:
            row = free.iloc[0]
            extra = (
                f"A no-cost cut of overlisting clears about {row['cases_cleared']:.0f} cases. "
                "The £0 price and the size of that cut are both assumed, so it is kept out of the per-£ ranking."
            )
        return " ".join([opening, stop, best, extra])

    def _scenario_lines(self, court):
        """Five eight-quarter paths. Effects and bills come from decide() and run_scenario()."""
        cached = self._scenario_cache.get(court)
        if cached is not None:
            return cached
        bill = self._bill(court)
        days_here = float(self.court_days.get(court, 0.0) or 0.0)
        ranked = self.ranked.loc[self.ranked["court"] == court]
        paid = ranked.loc[ranked["is_recommendation"]].iloc[0]
        free = ranked.loc[ranked["lever"] == "overlisting"]
        free_effect = 0.0 if free.empty else float(free.iloc[0]["effect"])

        def sitting_share(days):
            if days_here <= 0 or pd.isna(days):
                return 0.0, False
            raw = max(0.0, float(days) / days_here)
            return min(raw, 1.0), raw > 1.0

        stop_share, stop_capped = sitting_share(bill["stop_growth_days"])
        back_share, back_capped = sitting_share(bill["back_to_2019_days_per_year"])
        specs = [
            ("do_nothing", "Do nothing", {}, False),
            ("free", "Free fixes only", {"overlisting": min(1.0, max(0.0, free_effect))}, False),
            (
                "best",
                str(paid["label"]),
                {str(paid["lever"]): min(1.0, max(0.0, float(paid["effect"])))},
                False,
            ),
            ("stop", "Stop growth", {"sitting_days": stop_share}, stop_capped),
            ("back", "Return to 2019", {"sitting_days": back_share}, back_capped),
        ]
        lines = []
        for key, label, levers, capped in specs:
            report = run_scenario(
                court,
                self.panel,
                levers=levers,
                lever_config=self.levers,
                court_days=self.court_days,
                quarters=8,
            )
            lines.append(
                {
                    "key": key,
                    "label": label,
                    "series": [
                        {"period": row["period"], "open": float(row["open_scenario"])}
                        for row in report["series"]
                    ],
                    "end": float(report["end_scenario"]),
                    "cases_cleared": float(report["cases_cleared"]),
                    "cost": float(report["spend_8q"]),
                    "capped": capped,
                }
            )
        self._scenario_cache[court] = lines
        return lines

    def court(self, name):
        self._require(name)
        latest = self._latest_row(name)
        pred = self._prediction_row(name)
        bill = self._bill(name)
        history = self.panel.loc[self.panel["court"] == name].sort_values("period")
        year_ago = history.loc[history["period"] == "2025Q3"]
        open_prev = float(year_ago["open"].iloc[0]) if not year_ago.empty else None
        rate_prev = float(year_ago["ineffective_rate"].iloc[0]) if not year_ago.empty else None
        open_now = float(latest["open"])
        forecast_end = self.paths[name][-1]["open"]
        paid = self.ranked.loc[
            (self.ranked["court"] == name) & (self.ranked["is_recommendation"])
        ].iloc[0]
        shares = []
        for key, title, _owner in CAUSE_ACTIONS:
            share = latest.get(f"{key}_share", 0.0)
            count = latest.get(f"{key}_n", 0.0)
            shares.append(
                {
                    "key": key,
                    "label": title,
                    "share": 0.0 if pd.isna(share) else float(share),
                    "n": 0.0 if pd.isna(count) else float(count),
                }
            )
        trend = [
            {
                "period": str(row.period),
                "open": float(row.open),
                "receipts": float(row.receipts),
                "disposals": float(row.disposals),
                "ineffective_rate": None if pd.isna(row.ineffective_rate) else float(row.ineffective_rate),
            }
            for row in history.itertuples(index=False)
        ]
        tail = history.tail(8)
        return {
            "name": name,
            "latest_period": self.latest_period,
            "target_period": str(pred["period"]),
            "summary": {
                "open": open_now,
                "open_year_ago": open_prev,
                "open_year_ago_period": "2025Q3" if open_prev is not None else None,
                "open_delta_pct": None
                if not open_prev
                else (open_now - open_prev) / open_prev,
                "receipts_last4": float(bill["receipts"]),
                "disposals_last4": float(bill["disposals"]),
                "growth_per_quarter": float(bill["receipts"] - bill["disposals"]),
                "ineffective_rate": None
                if pd.isna(latest["ineffective_rate"])
                else float(latest["ineffective_rate"]),
                "predicted_rate": float(pred["predicted_rate"]),
                "model_rate": float(pred["model_rate"]),
                "four_quarter_average": float(pred["four_quarter_average"]),
                "rate_year_ago": rate_prev,
                "rate_delta_pp": None
                if rate_prev is None
                else float(pred["predicted_rate"]) - rate_prev,
                "forecast_open_8q": forecast_end,
                "forecast_delta_pct": (forecast_end - open_now) / open_now if open_now else None,
                "stop_growth_days": _num(bill["stop_growth_days"]),
                "stop_growth_gbp_per_year": _num(bill["stop_growth_gbp_per_year"]),
                "back_to_2019_gbp": _num(bill["back_to_2019_gbp"]),
                "open_2019": _num(bill["open_2019"]),
                "best_lever": paid["label"],
                "best_lever_key": paid["lever"],
                "best_lever_cases": float(paid["cases_cleared"]),
                "best_lever_cases_per_1k": _num(paid["cases_per_1k"]),
                "narrative": self._narrative(name),
            },
            "trend": trend,
            "spark_rate": [
                None if pd.isna(value) else float(value) for value in tail["ineffective_rate"]
            ],
            "spark_open": [float(value) for value in tail["open"]],
            "spark_forecast": [point["open"] for point in self.paths[name]],
            "forecast_path": self.paths[name],
            "drivers": self.drivers[name],
            "inputs": self.inputs[name],
            "cause_shares": shares,
            "interventions": self._interventions(name),
            "actions": self._actions(name),
            "scenarios": self._scenario_lines(name),
        }

    def simulate_court(self, court, levers, **kwargs):
        self._require(court)
        report = run_scenario(
            court,
            self.panel,
            levers=levers,
            lever_config=self.levers,
            court_days=self.court_days,
            **kwargs,
        )
        paid = self.ranked.loc[
            (self.ranked["court"] == court) & (self.ranked["is_recommendation"])
        ].iloc[0]
        report["recommendation"] = paid["label"]
        # One year of the sitting-day run-rate, plus a year of the cause bill.
        years = report["quarters"] / 4.0
        cause = report["spend_8q"] - report["sitting_spend_8q"]
        report["annual_cost"] = report["annual_sitting_cost"] + (cause / years if years else 0.0)
        report["annual_cost_assumed"] = True
        report["annual_cost_note"] = " ".join(report["notes"])
        report["backlog_change"] = report["backlog_difference"]
        report["assumptions"] = report["notes"]
        return report

    def rank_view(
        self,
        court,
        budget=100_000,
        sitting_charge="horizon",
        sitting_productivity=1.0,
        disposal_conversion=1.0,
        assumed_cost_scale=1.0,
    ):
        self._require(court)
        budget = float(budget)
        if budget < 0 or budget > 1_000_000:
            raise ValueError("budget must be from £0 to £1,000,000")
        key = (
            court,
            round(budget, 2),
            sitting_charge,
            round(float(sitting_productivity), 4),
            round(float(disposal_conversion), 4),
            round(float(assumed_cost_scale), 4),
        )
        cached = self._rank_cache.get(key)
        if cached is not None:
            return {**cached, "source": "cache"}
        shared = {
            "budget": budget,
            "panel": self.panel,
            "levers": self.levers,
            "sitting_charge": sitting_charge,
            "sitting_productivity": sitting_productivity,
            "disposal_conversion": disposal_conversion,
            "assumed_cost_scale": assumed_cost_scale,
        }
        current = decide(court=court, **shared)
        central = decide(court=court, budget=budget, panel=self.panel, levers=self.levers)
        before = current.loc[current["section"] == "per_pound"].iloc[0]
        # central frame is also rank-ordered, so the first paid row is the top.
        central_paid = central.loc[central["section"] == "per_pound"].iloc[0]
        compared = compare_recommendations(self.panel, self.levers, **{
            "budget": budget,
            "sitting_charge": sitting_charge,
            "sitting_productivity": sitting_productivity,
            "disposal_conversion": disposal_conversion,
            "assumed_cost_scale": assumed_cost_scale,
        })
        presets = []
        for label, charge, productivity, conversion, scale in (
            ("Charge once (original)", "once", 1.0, 1.0, 1.0),
            ("Conservative", "horizon", 0.5, 0.5, 2.0),
            ("Cheaper placeholder prices", "horizon", 1.0, 1.0, 0.5),
        ):
            preset = compare_recommendations(
                self.panel,
                self.levers,
                budget=budget,
                sitting_charge=charge,
                sitting_productivity=productivity,
                disposal_conversion=conversion,
                assumed_cost_scale=scale,
            )
            moved = preset.loc[~preset["stable"], "scenario_label"].value_counts()
            presets.append(
                {
                    "label": label,
                    "unchanged": int(preset["stable"].sum()),
                    "flipped": int((~preset["stable"]).sum()),
                    "most_common_new_top": None if moved.empty else str(moved.index[0]),
                }
            )
        flips = compared.loc[~compared["stable"]]
        payload = {
            "court": court,
            "budget": budget,
            "sitting_charge": sitting_charge,
            "source": "fresh",
            "assumption": "Scenario assumption — causal effect not established.",
            "ranking": _rank_payload(current),
            "central_top": _paid_brief(central_paid),
            "scenario_top": _paid_brief(before),
            "flipped": str(central_paid["lever"]) != str(before["lever"]),
            "stability": {
                "courts": int(len(compared)),
                "unchanged": int(compared["stable"].sum()),
                "flipped": int((~compared["stable"]).sum()),
                "flips": [
                    {
                        "court": row.court,
                        "central": row.central_label,
                        "scenario": row.scenario_label,
                        "central_per_1k": _num(row.central_per_1k),
                        "scenario_per_1k": _num(row.scenario_per_1k),
                    }
                    for row in flips.itertuples(index=False)
                ],
            },
            "presets": presets,
        }
        self._rank_cache[key] = {k: v for k, v in payload.items() if k != "source"}
        return payload

    def evidence(self):
        return load_evidence()

    def backtest_options(self):
        periods = sorted(str(period) for period in self.panel["period"].unique())
        cutoffs = [period for period in periods if period >= "2018Q4" and period < periods[-1]]
        return {
            "cutoffs": cutoffs,
            "latest": self.latest_period,
            "models": [
                {"key": key, "label": MODEL_NAMES[key]} for key in MODEL_NAMES
            ],
            "kinds": [
                {"key": "rate", "label": "Ineffective-trial rate, one step ahead"},
                {"key": "backlog", "label": "Open caseload, frozen last-4 forecast"},
            ],
        }

    def run_backtest(self, *, kind, court, cutoff, horizon, model):
        if kind not in ("rate", "backlog"):
            raise ValueError("kind must be 'rate' or 'backlog'")
        horizon = int(horizon)
        if horizon < 1 or horizon > 12:
            raise ValueError("horizon must be from 1 to 12 quarters")
        if model not in MODEL_KEYS:
            raise ValueError(f"Unknown model: {model}")
        cutoff = str(cutoff)
        periods = set(self.panel["period"].astype(str))
        if cutoff not in periods:
            raise ValueError(f"Unknown cutoff: {cutoff}")
        if court:
            self._require(court)
        key = (kind, court or "", cutoff, horizon, model, self.latest_period, int(len(self.panel)))
        cached = self._eval_cache.get(key)
        if cached is not None:
            return {
                **cached,
                "execution": {
                    **cached["execution"],
                    "source": "cache",
                    "note": "Retrieved from the evaluation cache for these parameters. Not recomputed.",
                },
            }
        started = time.perf_counter()
        if kind == "rate":
            evaluated = evaluate_rate(self.panel, cutoff, horizon)
            payload = self._present_rate(evaluated, court, model, cutoff)
        else:
            detail, by_step = forecast_errors(self.panel, cutoff, horizon, court=None)
            payload = self._present_backlog(detail, by_step, court, cutoff, horizon)
        payload["execution"]["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        payload["execution"]["computed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload["execution"]["source"] = "fresh"
        self._eval_cache[key] = payload
        return payload

    def _present_rate(self, evaluated, court, model, cutoff):
        frame = evaluated["frame"]
        scoped = frame if not court else frame.loc[frame["court"] == court]
        if scoped.empty:
            raise ValueError(f"No scored rows for {court} after {cutoff}")
        value_col = model
        scale = 100.0
        residual = (scoped["actual"] - scoped[value_col]) * scale
        weight = scoped["listed"].to_numpy()
        selected = float(np.sum(weight * np.abs(scoped["actual"] - scoped[value_col])) / np.sum(weight) * 100)
        last_mae = float(
            np.sum(weight * np.abs(scoped["actual"] - scoped["last_quarter"])) / np.sum(weight) * 100
        )
        # Selected-scope MAE can differ from the all-court score. The comparison
        # table is the all-court score for this run, recomputed from its predictions.
        series = []
        for period, piece in scoped.groupby("period", sort=True):
            piece_weight = piece["listed"].to_numpy()
            series.append(
                {
                    "period": str(period),
                    "actual": float(np.sum(piece_weight * piece["actual"].to_numpy()) / np.sum(piece_weight) * scale),
                    "predicted": float(
                        np.sum(piece_weight * piece[value_col].to_numpy()) / np.sum(piece_weight) * scale
                    ),
                }
            )
        return self._backtest_shell(
            kind="rate",
            court=court,
            model=model,
            horizon=int(scoped["period"].nunique()),
            unit="pp",
            frame=frame,
            scoped=scoped,
            actual_col="actual",
            value_col=value_col,
            scale=scale,
            residual=residual,
            series=series,
            selected_mae=selected,
            scores=evaluated["scores"],
            last_mae=last_mae,
            execution={
                "source": "fresh",
                "kind": "rate",
                "cutoff": cutoff,
                "train_from": evaluated["train_from"],
                "train_through": evaluated["train_through"],
                "train_rows": evaluated["train_rows"],
                "test_from": evaluated["test_from"],
                "test_through": evaluated["test_through"],
                "test_rows": int(len(scoped)),
                "model_version": evaluated["model_version"],
                "blend_weight": evaluated["blend_weight"],
                "blend_weight_fit_on_test": False,
                "sitting_days_used": False,
                "sitting_days_note": (
                    "The rate model does not use sitting-day allocations. "
                    "The 2025-26 national total is not an input to this run."
                ),
                "leakage_check": (
                    f"Training targets stop at {evaluated['train_through']}. "
                    "Test targets start after the cutoff. Features on a test row "
                    "are the published values in that feature quarter."
                ),
            },
        )

    def _present_backlog(self, detail, by_step, court, cutoff, horizon):
        scoped = detail if not court else detail.loc[detail["court"] == court]
        if scoped.empty:
            raise ValueError(f"No backlog rows for {court} after {cutoff}")
        grouped = scoped.groupby("period", sort=True)[["open", "open_baseline"]].sum().reset_index()
        series = [
            {
                "period": str(row.period),
                "actual": float(row.open),
                "predicted": float(row.open_baseline),
            }
            for row in grouped.itertuples(index=False)
        ]
        residual = scoped["open"] - scoped["open_baseline"]
        mae = float(scoped["abs_err"].mean())
        step_mae = {int(row.step): float(row.mae) for row in by_step.itertuples(index=False)}
        # by_step is national. For a selected court, recompute from scoped.
        if court:
            step_mae = {
                int(step): float(piece["abs_err"].mean())
                for step, piece in scoped.groupby("step")
            }
        one = step_mae.get(1, mae)
        eight = step_mae.get(horizon, step_mae.get(max(step_mae), mae))
        scores = [
            {
                "key": "frozen",
                "model": "Frozen last-4 forecast",
                "mae_pp": mae,
                "weighted_mae_pp": mae,
            }
        ]
        shell = self._backtest_shell(
            kind="backlog",
            court=court,
            model="frozen",
            horizon=horizon,
            unit="cases",
            frame=detail,
            scoped=scoped,
            actual_col="open",
            value_col="open_baseline",
            scale=1.0,
            residual=residual,
            series=series,
            selected_mae=mae,
            scores=scores,
            last_mae=mae,
            execution={
                "source": "fresh",
                "kind": "backlog",
                "cutoff": cutoff,
                "train_from": cutoff,
                "train_through": cutoff,
                "train_rows": int(scoped["court"].nunique()),
                "test_from": str(scoped["period"].min()),
                "test_through": str(scoped["period"].max()),
                "test_rows": int(len(scoped)),
                "model_version": "Frozen last-4 receipts and disposals. Not the rate model.",
                "blend_weight": None,
                "blend_weight_fit_on_test": False,
                "sitting_days_used": False,
                "sitting_days_note": (
                    f"This forecast does not use sitting days. The 110,647 national "
                    f"days are the 2025-26 total. They are not an input to a forecast "
                    f"frozen at {cutoff}, and they were not rebuilt from later years."
                ),
                "leakage_check": (
                    f"Receipts and disposals are the last four quarters at or before {cutoff}. "
                    "Later quarters are used only as the actual open caseload."
                ),
                "error_by_step": [
                    {"step": step, "mae": value} for step, value in sorted(step_mae.items())
                ],
                "one_quarter_mae": one,
                "horizon_mae": eight,
            },
        )
        shell["kpis"]["one_quarter_backlog_mae"] = one
        shell["kpis"]["eight_quarter_backlog_mae"] = eight
        shell["model_label"] = "Frozen last-4 forecast"
        return shell

    def _backtest_shell(
        self,
        *,
        kind,
        court,
        model,
        horizon,
        unit,
        frame,
        scoped,
        actual_col,
        value_col,
        scale,
        residual,
        series,
        selected_mae,
        scores,
        last_mae,
        execution,
    ):
        hist_values = residual.to_numpy()
        if kind == "rate":
            bins = np.linspace(-20, 20, 21)
        else:
            span = float(np.nanpercentile(np.abs(hist_values), 95)) if len(hist_values) else 1.0
            bins = np.linspace(-max(span, 1.0), max(span, 1.0), 21)
        counts, edges = np.histogram(hist_values, bins=bins)
        histogram = [
            {
                "bin_left": float(edges[i]),
                "bin_right": float(edges[i + 1]),
                "mid": float((edges[i] + edges[i + 1]) / 2),
                "count": int(counts[i]),
            }
            for i in range(len(counts))
        ]
        per_source = frame.assign(
            abs_err=(frame[actual_col] - frame[value_col]).abs() * scale
        )
        per_court = per_source.groupby("court")["abs_err"].mean().sort_values()
        by_court = (
            scoped.assign(abs_err=(scoped[actual_col] - scoped[value_col]).abs() * scale)
            .groupby("court")["abs_err"]
            .mean()
            .sort_values(ascending=False)
        )
        band = [point["actual"] - point["predicted"] for point in series]
        band_sd = float(np.std(band, ddof=1)) if len(band) > 1 else 0.0
        best_score = min(row["weighted_mae_pp"] for row in scores)
        live_court = court or "Snaresbrook"
        pred = self._prediction_row(live_court)
        return {
            "horizon": horizon,
            "model": model,
            "model_label": MODEL_NAMES.get(model, model),
            "court": court,
            "unit": unit,
            "kpis": {
                "trial_weighted_mae": selected_mae,
                "selected_weighted_mae": selected_mae,
                "selected_delta_vs_last_quarter": selected_mae - last_mae,
                "one_quarter_backlog_mae": self.one_step_mae,
                "eight_quarter_backlog_mae": self.frozen_mae,
                "eight_quarter_window": execution.get("leakage_check", ""),
                "best_benchmark": {
                    "key": next(row["key"] for row in scores if row["weighted_mae_pp"] == best_score),
                    "model": next(row["model"] for row in scores if row["weighted_mae_pp"] == best_score),
                    "weighted_mae_pp": best_score,
                },
                "coverage_courts": int(frame["court"].nunique()),
                "spark_rate_mae": [],
                "spark_backlog_1": [],
                "spark_backlog_8": [],
            },
            "series": series,
            "band_sd": band_sd,
            "band_label": "Spread of errors on this run. Not a confidence interval.",
            "histogram": histogram,
            "largest_errors": [
                {"court": name, "mae": float(value)} for name, value in by_court.head(5).items()
            ],
            "best_court": {"court": per_court.index[0], "mae": float(per_court.iloc[0])},
            "worst_court": {"court": per_court.index[-1], "mae": float(per_court.iloc[-1])},
            "per_court": [
                {"court": name, "mae": float(value)}
                for name, value in per_court.sort_values(ascending=False).items()
            ],
            "model_comparison": [
                {**row, "best": row["weighted_mae_pp"] == best_score} for row in scores
            ],
            "note": (
                "The 50/50 blend weight is a fixed rule. It was not chosen by scoring "
                "this test window. This run trains only on targets at or before the cutoff."
                if kind == "rate"
                else "Do-nothing stock-flow. It does not score whether a lever would have worked."
            ),
            "live": {
                "court": live_court,
                "period": str(pred["period"]),
                "inputs": self.inputs[live_court],
                "model_rate": float(pred["model_rate"]),
                "four_quarter_average": float(pred["four_quarter_average"]),
                "predicted_rate": float(pred["predicted_rate"]),
                "drivers": self.drivers[live_court][:5],
            },
            "honesty": self.validation()["honesty"],
            "scenario_validation": {
                "accounting_mae": self.accounting_mae,
                "previous_flow_mae": self.previous_flow_mae,
                "one_step_mae": self.one_step_mae,
                "frozen_forecast_mae": float(scoped["abs_err"].mean()) if kind == "backlog" else self.frozen_mae,
                "national": [
                    {"period": point["period"], "actual": point["actual"], "predicted": point["predicted"]}
                    for point in series
                ],
                "statement": (
                    "Lever effect sizes are not scored against later outcomes. "
                    "What is scored is the do-nothing stock-flow."
                ),
            },
            "execution": execution,
        }

    def decisions(self, name):
        self._require(name)
        bill = self._bill(name)
        return {
            "court": name,
            "interventions": self._interventions(name),
            "stop_growth_days": _num(bill["stop_growth_days"]),
            "stop_growth_gbp_per_year": _num(bill["stop_growth_gbp_per_year"]),
            "back_to_2019_days_per_year": _num(bill["back_to_2019_days_per_year"]),
            "back_to_2019_gbp": _num(bill["back_to_2019_gbp"]),
            "assumed_day_split": True,
            "day_cost_published": True,
            "day_cost": float(self.levers["sitting_days"]["cost_per_unit"]),
        }

    def national(self, budget):
        budget = max(0.0, min(150_000_000.0, float(budget)))
        price = float(self.levers["sitting_days"]["cost_per_unit"])
        remaining = budget
        rows = []
        for _, court in self.allocation_order.iterrows():
            if remaining <= 0:
                break
            cap = float(court["cap_gbp"])
            rate = float(court["cases_per_pound"] or 0.0)
            if cap <= 0 or rate <= 0:
                continue
            take = min(remaining, cap)
            rows.append(
                {
                    "court": court["court"],
                    "gbp": take,
                    "days_per_year": take / (2.0 * price),
                    "cases_cleared": take * rate,
                    "funded_to_cap": take >= cap - 1,
                }
            )
            remaining -= take
        stop_year = float(self.bills["stop_growth_gbp_per_year"].sum())
        back = float(self.bills["back_to_2019_gbp"].sum())
        return {
            "budget": budget,
            "curve": _records(self.curve),
            "baseline_open_8q": float(self.allocation_order["end_do_nothing"].sum()),
            "stop_growth_per_year": stop_year,
            "stop_growth_2y": stop_year * 2.0,
            "return_2019": back,
            "top15": _records(self.per_million.head(15)[["court", "cases_per_1m"]]),
            "allocation": rows,
            "leftover": remaining,
            "day_cost": price,
            "day_split_assumed": True,
            "national_days": self.national_days,
        }

    def _score_row(self, key):
        name = MODEL_NAMES[key]
        row = self.scores.loc[self.scores["model"] == name].iloc[0]
        return {
            "key": key,
            "model": name,
            "mae_pp": float(row["mae_pp"]),
            "weighted_mae_pp": float(row["weighted_mae_pp"]),
        }

    def validation(self):
        comparison = [self._score_row(key) for key in MODEL_KEYS]
        blend = next(row for row in comparison if row["key"] == "blend")
        average = next(row for row in comparison if row["key"] == "four_quarter")
        trees = next(row for row in comparison if row["key"] == "lightgbm")
        last = next(row for row in comparison if row["key"] == "last_quarter")
        # A baseline is a comparator, not the blend being judged.
        best = min(
            (row for row in comparison if row["key"] != "blend"),
            key=lambda row: row["weighted_mae_pp"],
        )
        return {
            "accounting_mae": self.accounting_mae,
            "previous_flow_mae": self.previous_flow_mae,
            "one_step_mae": self.one_step_mae,
            "frozen_forecast_mae": self.frozen_mae,
            "frozen_from": "2023Q4",
            "frozen_through": self.latest_period,
            "frozen_quarters": int(self.frozen["period"].nunique()),
            "national_open": self.national_open,
            "national_period": self.latest_period,
            "courts": int(self.panel["court"].nunique()),
            "test_court_quarters": self.test_rows,
            "train_court_quarters": self.train_rows,
            "scores": comparison,
            "best_benchmark": best,
            "blend_vs_average_pp": blend["weighted_mae_pp"] - average["weighted_mae_pp"],
            "lightgbm_vs_average_pp": trees["weighted_mae_pp"] - average["weighted_mae_pp"],
            "blend_vs_last_quarter_pp": blend["weighted_mae_pp"] - last["weighted_mae_pp"],
            "honesty": self._honesty(blend, average, trees, last),
        }

    def _honesty(self, blend, average, trees, last):
        return [
            {
                "n": 1,
                "title": "Compare options. Do not promise a caseload.",
                "body": (
                    f"The trial-weighted error of the saved blend is {blend['weighted_mae_pp']:.2f} "
                    "percentage points on 2024Q1–2026Q2. Use it to compare courts and levers, "
                    "not as a guarantee of next quarter's ineffective rate."
                ),
            },
            {
                "n": 2,
                "title": "Recent history is the strongest predictor.",
                "body": (
                    f"LightGBM alone is {trees['weighted_mae_pp'] - average['weighted_mae_pp']:+.2f} "
                    "weighted points versus the 4-quarter average (positive means worse). "
                    f"The 50/50 blend is {blend['weighted_mae_pp'] - average['weighted_mae_pp']:+.2f} "
                    f"versus that average, and {blend['weighted_mae_pp'] - last['weighted_mae_pp']:+.2f} "
                    "versus last quarter. The edge over the recent average is small."
                ),
            },
            {
                "n": 3,
                "title": "Backlog error compounds when the run-rate is held flat.",
                "body": (
                    f"One quarter ahead, refreshing from the real stock, the error averages "
                    f"{self.one_step_mae:,.1f} open cases. Holding the last four quarters flat from "
                    f"2023Q4 through {self.latest_period} averages {self.frozen_mae:,.1f} open cases off. "
                    f"The same stock-flow rule with the actual receipts and disposals is "
                    f"{self.accounting_mae:,.1f}."
                ),
            },
            {
                "n": 4,
                "title": "The simulator ranks interventions. It does not certify them.",
                "body": (
                    "One avoided ineffective trial is counted as one extra disposal. "
                    "That unit change is an assumption. Per-court sitting days are an assumed "
                    f"share of {self.national_days:,.0f} national days in 2025-26. "
                    "£3,036 per day is published. Every other lever price is a placeholder."
                ),
            },
        ]

    def backtest_view(self, court=None, horizon=1, model="blend"):
        if model not in MODEL_KEYS:
            model = "blend"
        if horizon not in (1, 8):
            horizon = 1
        if court:
            self._require(court)
        validation = self.validation()
        if horizon == 1:
            frame = self.rate_test
            value_col = model
            actual_col = "actual"
            scale = 100.0
            unit = "pp"
        else:
            frame = self.frozen.rename(columns={"open": "actual", "open_baseline": "predicted"})
            value_col = "predicted"
            actual_col = "actual"
            scale = 1.0
            unit = "cases"
        scoped = frame if not court else frame.loc[frame["court"] == court]
        residual = (scoped[actual_col] - scoped[value_col]) * scale
        # Rate chart: ±1 SD of every test residual, in percentage points.
        # Backlog chart: ±1 SD of the gap on the aggregated series actually drawn,
        # so a national sum is not given a court-level band.
        full_residual = (frame[actual_col] - frame[value_col]) * scale
        band_sd = float(full_residual.std(ddof=1))
        band_label = (
            "empirical error band (±1 standard deviation of test residuals, full test set)"
        )
        if horizon == 1:
            grouped = (
                scoped.groupby("period", sort=True)[[actual_col, value_col]]
                .mean()
                .reset_index()
            )
            # Trial-weighted mean when the rate frame has listed counts.
            if "listed" in scoped.columns and not scoped.empty:
                def _wmean(piece, column):
                    weight = piece["listed"].to_numpy()
                    return float(np.sum(weight * piece[column].to_numpy()) / np.sum(weight))

                rows = []
                for period, piece in scoped.groupby("period", sort=True):
                    rows.append(
                        {
                            "period": period,
                            "actual": _wmean(piece, actual_col) * scale,
                            "predicted": _wmean(piece, value_col) * scale,
                        }
                    )
                series = rows
            else:
                series = [
                    {
                        "period": str(row.period),
                        "actual": float(getattr(row, actual_col)) * scale,
                        "predicted": float(getattr(row, value_col)) * scale,
                    }
                    for row in grouped.itertuples(index=False)
                ]
        else:
            grouped = scoped.groupby("period", sort=True)[[actual_col, value_col]].sum().reset_index()
            series = [
                {
                    "period": str(row.period),
                    "actual": float(getattr(row, actual_col)),
                    "predicted": float(getattr(row, value_col)),
                }
                for row in grouped.itertuples(index=False)
            ]

        per_court = (
            frame.assign(abs_err=(frame[actual_col] - frame[value_col]).abs() * scale)
            .groupby("court")["abs_err"]
            .mean()
            .sort_values()
        )
        largest_source = scoped.assign(
            abs_err=(scoped[actual_col] - scoped[value_col]).abs() * scale
        )
        by_court = largest_source.groupby("court")["abs_err"].mean().sort_values(ascending=False)
        hist_values = residual.to_numpy()
        if horizon == 1:
            bins = np.linspace(-20, 20, 21)
        else:
            span = float(np.nanpercentile(np.abs(hist_values), 95)) if len(hist_values) else 1.0
            span = max(span, 1.0)
            bins = np.linspace(-span, span, 21)
        counts, edges = np.histogram(hist_values, bins=bins)
        histogram = [
            {
                "bin_left": float(edges[i]),
                "bin_right": float(edges[i + 1]),
                "mid": float((edges[i] + edges[i + 1]) / 2),
                "count": int(counts[i]),
            }
            for i in range(len(counts))
        ]
        spark_rate = (
            self.rate_test.assign(
                abs_pp=(self.rate_test["actual"] - self.rate_test["blend"]).abs() * 100
            )
            .groupby("period")["abs_pp"]
            .mean()
            .tolist()
        )
        spark_1 = self.one_step.groupby("period")["abs_err"].mean().tolist()
        spark_8 = self.frozen.groupby("period")["abs_err"].mean().tolist()
        live_court = court or "Snaresbrook"
        pred = self._prediction_row(live_court)
        return {
            "horizon": horizon,
            "model": model,
            "model_label": MODEL_NAMES[model],
            "court": court,
            "unit": unit,
            "kpis": {
                "trial_weighted_mae": next(
                    row["weighted_mae_pp"] for row in validation["scores"] if row["key"] == model
                ),
                "selected_weighted_mae": next(
                    row["weighted_mae_pp"] for row in validation["scores"] if row["key"] == model
                ),
                "selected_delta_vs_last_quarter": next(
                    row["weighted_mae_pp"] for row in validation["scores"] if row["key"] == model
                )
                - next(row["weighted_mae_pp"] for row in validation["scores"] if row["key"] == "last_quarter"),
                "one_quarter_backlog_mae": self.one_step_mae,
                "eight_quarter_backlog_mae": self.frozen_mae,
                "eight_quarter_window": (
                    f"Frozen last-4 forecast from 2023Q4 through {self.latest_period} "
                    f"({int(self.frozen['period'].nunique())} quarters). "
                    "This is the figure labelled 8-quarter backlog MAE."
                ),
                "best_benchmark": validation["best_benchmark"],
                "coverage_courts": int(self.panel["court"].nunique()),
                "spark_rate_mae": spark_rate,
                "spark_backlog_1": spark_1,
                "spark_backlog_8": spark_8,
            },
            "series": series,
            "band_sd": (
                float(
                    np.std(
                        [point["actual"] - point["predicted"] for point in series],
                        ddof=1,
                    )
                )
                if horizon == 8 and len(series) > 1
                else band_sd
            ),
            "band_label": (
                "empirical error band (±1 standard deviation of the actual-minus-predicted gap on this series)"
                if horizon == 8
                else band_label
            ),
            "histogram": histogram,
            "largest_errors": [
                {"court": name, "mae": float(value)} for name, value in by_court.head(5).items()
            ],
            "best_court": {"court": per_court.index[0], "mae": float(per_court.iloc[0])},
            "worst_court": {"court": per_court.index[-1], "mae": float(per_court.iloc[-1])},
            "per_court": [
                {"court": name, "mae": float(value)}
                for name, value in per_court.sort_values(ascending=False).items()
            ],
            "model_comparison": [
                {
                    **row,
                    "best": row["weighted_mae_pp"]
                    == min(item["weighted_mae_pp"] for item in validation["scores"]),
                }
                for row in validation["scores"]
            ],
            "note": "Time-based split only. No shuffling to avoid leakage.",
            "execution": {
                "source": "startup_cache",
                "kind": "rate" if horizon == 1 else "backlog",
                "cutoff": "2023Q4",
                "model_version": MODEL_VERSION,
                "computed_at": None,
                "elapsed_ms": None,
                "blend_weight_fit_on_test": False,
                "sitting_days_used": False,
                "note": (
                    "Loaded from the evaluation computed when the API started. "
                    "This request did not retrain or recompute it."
                ),
            },
            "live": {
                "court": live_court,
                "period": str(pred["period"]),
                "inputs": self.inputs[live_court],
                "model_rate": float(pred["model_rate"]),
                "four_quarter_average": float(pred["four_quarter_average"]),
                "predicted_rate": float(pred["predicted_rate"]),
                "drivers": self.drivers[live_court][:5],
            },
            "honesty": validation["honesty"],
            "scenario_validation": {
                "accounting_mae": self.accounting_mae,
                "previous_flow_mae": self.previous_flow_mae,
                "one_step_mae": self.one_step_mae,
                "frozen_forecast_mae": self.frozen_mae,
                "national": [
                    {
                        "period": str(period),
                        "actual": float(piece["open"].sum()),
                        "predicted": float(piece["open_baseline"].sum()),
                    }
                    for period, piece in (
                        self.frozen.groupby("period")
                        if not court
                        else self.frozen.loc[self.frozen["court"] == court].groupby("period")
                    )
                ],
                "statement": (
                    "Lever effect sizes are not scored against later outcomes. "
                    "What is scored is the do-nothing stock-flow: actual receipts and disposals "
                    "replay the published open caseload closely; a frozen last-4 run-rate does not."
                ),
            },
        }

    def score_trial(self, payload):
        court = payload["court"]
        self._require(court)
        latest = self._latest_row(court)
        pred = self._prediction_row(court)
        shares = {}
        for key, _title, _owner in CAUSE_ACTIONS:
            value = latest.get(f"{key}_share", 0.0)
            shares[key] = 0.0 if pd.isna(value) else float(value)
        factors = []
        if not payload.get("cps_served", False):
            factors.append(("prosecution", shares["prosecution"]))
        if not payload.get("defence_confirmed", False):
            factors.append(("defence_advocate", shares["defence_advocate"]))
        if not payload.get("witnesses_confirmed", False):
            factors.append(("prosecution", shares["prosecution"]))
        if payload.get("floater", False):
            factors.append(("overlisting", shares["overlisting"]))
        if payload.get("custody", False):
            factors.append(("prisoner_not_produced", shares["prisoner_not_produced"]))
        weight = sum(value for _, value in factors)
        score = min(1.0, float(pred["predicted_rate"]) * (1.0 + weight))
        if score < TRIAL_GREEN_BELOW:
            band = "Green"
        elif score < TRIAL_AMBER_BELOW:
            band = "Amber"
        else:
            band = "Red"
        names = {key: title for key, title, _owner in CAUSE_ACTIONS}
        if factors:
            key = max(factors, key=lambda item: item[1])[0]
            suggestion = names[key]
        else:
            suggestion = "No extra check. The score is this court's predicted ineffective rate."
        row = {
            "court": court,
            "date": payload.get("date") or "",
            "custody": bool(payload.get("custody", False)),
            "defence_confirmed": bool(payload.get("defence_confirmed", False)),
            "cps_served": bool(payload.get("cps_served", False)),
            "witnesses_confirmed": bool(payload.get("witnesses_confirmed", False)),
            "floater": bool(payload.get("floater", False)),
            "score": round(score * 100, 1),
            "band": band,
            "suggested_action": suggestion,
            "predicted_rate": float(pred["predicted_rate"]),
            "heuristic": True,
        }
        with _lock:
            trials = self._read_json(TRIALS_PATH, [])
            trials.insert(0, row)
            self._write_json(TRIALS_PATH, trials)
        return row

    def trials(self):
        return self._read_json(TRIALS_PATH, [])

    def set_done(self, court, action_id, done):
        self._require(court)
        with _lock:
            data = self._read_json(ACTIONS_PATH, {})
            court_row = data.get(court, {})
            court_row[action_id] = bool(done)
            data[court] = court_row
            self._write_json(ACTIONS_PATH, data)
        return {"court": court, "action_id": action_id, "done": bool(done)}

    def brief_pdf(self, court):
        detail = self.court(court)
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=16)
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.multi_cell(0, 8, _pdf_safe(f"Courtfall brief: {court}"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(
            0,
            6,
            _pdf_safe(
                f"Actions for the resident judge. Figures as of {detail['latest_period']}. "
                f"Forecast quarter {detail['target_period']}."
            ),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.ln(2)
        pdf.multi_cell(0, 6, _pdf_safe(detail["summary"]["narrative"]), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        for action in detail["actions"]:
            pdf.set_font("Helvetica", "B", 12)
            pdf.multi_cell(
                0, 7, _pdf_safe(f"{action['rank']}. {action['title']}"), new_x="LMARGIN", new_y="NEXT"
            )
            pdf.set_font("Helvetica", "", 11)
            pdf.multi_cell(0, 6, _pdf_safe(action["detail"]), new_x="LMARGIN", new_y="NEXT")
            pdf.multi_cell(
                0,
                6,
                _pdf_safe(
                    f"Impact: {action['impact_label']}. Cost: {action['cost_label']}. "
                    f"Owner: {action['owner']}."
                ),
                new_x="LMARGIN",
                new_y="NEXT",
            )
            pdf.multi_cell(
                0,
                6,
                _pdf_safe(f"Confidence: {action['confidence']}. {action['confidence_note']}"),
                new_x="LMARGIN",
                new_y="NEXT",
            )
            pdf.ln(2)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(
            0,
            5,
            _pdf_safe(
                "Assumptions. One avoided ineffective trial is counted as one extra disposal. "
                "Per-court sitting days are an assumed share of 110,647 national days in 2025-26. "
                "GBP 3,036 per sitting day is published (HMCTS 2022-23, parliamentary question 4727, "
                "answered 5 December 2023). Every other price is a placeholder. "
                "The trial score, if used elsewhere, is a heuristic and is not in this brief."
            ),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        return bytes(pdf.output())

    def lever_catalog(self):
        rows = []
        for key, spec in self.levers.items():
            rows.append(
                {
                    "key": key,
                    "label": spec["label"],
                    "cost_per_unit": float(spec["cost_per_unit"]),
                    "unit": spec["unit"],
                    "default_effect": float(spec["default_effect"]),
                    "assumed": bool(spec["assumed"]),
                    "source": str(spec.get("source", "")).strip(),
                }
            )
        return {
            "levers": rows,
            "national_days_2025_26": self.national_days,
            "days_split_assumed": True,
        }

    @staticmethod
    def _read_json(path, fallback):
        if not path.exists():
            return fallback
        with path.open() as handle:
            return json.load(handle)

    @staticmethod
    def _write_json(path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as handle:
            json.dump(payload, handle, indent=2)


_STORE: Store | None = None


def get_store() -> Store:
    global _STORE
    if _STORE is None:
        _STORE = Store()
    return _STORE
