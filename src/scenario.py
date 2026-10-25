"""One costed eight-quarter scenario.

The chart, the API, and the Streamlit lab all call run_scenario().
decide() remains the ranking. A sitting-day fraction here is the same
fraction simulate() applies to disposals. The recorded bill depends on
sitting_charge:

    horizon  the cheque covers every quarter in the horizon
    once     legacy comparison: the same disposal path is kept, and the
             recorded bill is one year of those days

Neither charge mode is a causal estimate. sitting_productivity and
disposal_conversion are scenario assumptions.
"""

from __future__ import annotations

import math

import pandas as pd

from src.decide import _days_per_year, court_day_assumption, load_levers
from src.simulate import CAUSE_LEVERS, _last4, simulate

ALLOWED = ("sitting_days",) + tuple(CAUSE_LEVERS)
ASSUMPTION = "Scenario assumption — causal effect not established."


def _finite(name, value):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def sitting_fraction_for_budget(budget, court_days, day_cost, quarters, sitting_charge):
    """Turn an 8-quarter cheque into the disposal fraction simulate() uses.

    Returns the fraction, the annual days, and a note when the cheque buys
    more days than this court's assumed annual total.
    """
    budget = _finite("sitting_budget_gbp", budget)
    if budget < 0:
        raise ValueError("sitting_budget_gbp cannot be negative")
    day_cost = _finite("day_cost", day_cost)
    if day_cost <= 0:
        raise ValueError("day cost must be positive")
    days = _days_per_year(budget, day_cost, quarters, sitting_charge)
    if court_days is None or court_days <= 0:
        return 0.0, 0.0, (
            "This court has no assumed sitting days, so a sitting-day budget "
            "does not change disposals."
        )
    fraction = days / float(court_days)
    if fraction > 1:
        return 1.0, float(court_days), (
            "That budget buys more than 100% of this court's assumed annual days. "
            "The scenario stops at 100% extra days and prices those days, "
            "not the unused remainder."
        )
    return float(fraction), float(days), ""


def run_scenario(
    court,
    panel,
    levers=None,
    lever_config=None,
    court_days=None,
    quarters=8,
    sitting_productivity=1.0,
    disposal_conversion=1.0,
    assumed_cost_scale=1.0,
    sitting_charge="horizon",
    sitting_budget_gbp=None,
    as_of=None,
):
    """Baseline and scenario for one court, with the 8-quarter bill."""
    quarters = int(quarters)
    if quarters < 1 or quarters > 16:
        raise ValueError("quarters must be from 1 to 16")
    if sitting_charge not in ("horizon", "once"):
        raise ValueError("sitting_charge must be 'horizon' or 'once'")
    productivity = _finite("sitting_productivity", sitting_productivity)
    conversion = _finite("disposal_conversion", disposal_conversion)
    cost_scale = _finite("assumed_cost_scale", assumed_cost_scale)
    if productivity < 0 or conversion < 0:
        raise ValueError("productivity and conversion cannot be negative")
    if cost_scale <= 0:
        raise ValueError("assumed_cost_scale must be positive")

    if lever_config is None:
        lever_config = load_levers()
    if court_days is None:
        court_days, _, _ = court_day_assumption(panel, lever_config)
    if court not in set(panel["court"]):
        raise ValueError(f"Unknown court: {court}")

    clean = {}
    for key, value in (levers or {}).items():
        if key not in ALLOWED:
            raise ValueError(f"Unknown lever: {key}")
        number = _finite(key, value)
        if number < 0 or number > 1:
            raise ValueError(f"{key} must be between 0 and 1")
        clean[key] = number

    price = float(lever_config["sitting_days"]["cost_per_unit"])
    days_here = float(court_days.get(court, 0.0))
    budget_note = ""
    if sitting_budget_gbp is not None:
        fraction, _days, budget_note = sitting_fraction_for_budget(
            sitting_budget_gbp, days_here, price, quarters, sitting_charge
        )
        clean["sitting_days"] = fraction

    history = panel.loc[panel["court"] == court].sort_values("period")
    if as_of is not None:
        history = history.loc[history["period"] <= as_of]
    projected = simulate(
        court,
        quarters=quarters,
        levers=clean,
        as_of=as_of,
        panel=panel,
        sitting_productivity=productivity,
        disposal_conversion=conversion,
    )
    future = projected.loc[projected["step"] > 0]
    if (future["disposals_scenario"].astype(float) < -1e-9).any():
        raise ValueError("Scenario disposals went negative")
    if (future["disposals_baseline"].astype(float) < -1e-9).any():
        raise ValueError("Baseline disposals went negative")

    years = quarters / 4.0
    sitting_fraction = float(clean.get("sitting_days", 0.0))
    days_per_year = sitting_fraction * days_here
    days_over_horizon = days_per_year * years
    physical_spend = days_over_horizon * price
    if sitting_charge == "once":
        recorded_sitting = days_per_year * price
        charge_note = (
            "Legacy comparison. The disposal path still runs for every quarter "
            "in the horizon. The recorded sitting-day bill is one year of those days."
        )
    else:
        recorded_sitting = physical_spend
        charge_note = (
            "The sitting-day bill is £3,036 times the extra days over the full horizon."
        )

    lever_rows = []
    if sitting_fraction > 0 and days_here <= 0:
        sitting_status = "unpriced"
        sitting_reason = "No assumed sitting days, so this percentage is not priced."
    elif sitting_fraction == 0:
        sitting_status = "off"
        sitting_reason = ""
    elif productivity == 0:
        sitting_status = "no_productivity"
        sitting_reason = (
            "Extra days are priced, but the disposal gain is set to 0, so the backlog does not move."
        )
    else:
        sitting_status = "applied"
        sitting_reason = ""
    lever_rows.append(
        {
            "lever": "sitting_days",
            "label": lever_config["sitting_days"]["label"],
            "cut": sitting_fraction,
            "unit": "share of assumed annual sitting days",
            "days_per_year": days_per_year,
            "days_over_horizon": days_over_horizon,
            "quarterly_trials": None,
            "avoided_per_quarter": None,
            "disposals_per_quarter": None,
            "spend_8q": recorded_sitting,
            "status": sitting_status,
            "reason": " ".join(part for part in (budget_note, sitting_reason) if part),
        }
    )

    cause_spend = 0.0
    for name in CAUSE_LEVERS:
        cut = float(clean.get(name, 0.0))
        spec = lever_config[name]
        base_n = _last4(history, f"{name}_n")
        unit = float(spec["cost_per_unit"])
        if bool(spec["assumed"]) and unit > 0:
            unit *= cost_scale
        avoided = base_n * cut
        added = avoided * conversion
        spend = avoided * quarters * unit
        cause_spend += spend
        if cut == 0:
            status = "off"
            reason = ""
        elif base_n <= 0:
            status = "no_eligible_trials"
            reason = (
                f"No {spec['label'].lower()} trials in the last four quarters, "
                "so this cut clears nothing."
            )
        elif conversion == 0:
            status = "no_disposal_conversion"
            reason = (
                "The trials are still priced as avoided, but none are counted as disposals, "
                "so the backlog does not move."
            )
        else:
            status = "applied"
            reason = ""
        lever_rows.append(
            {
                "lever": name,
                "label": spec["label"],
                "cut": cut,
                "unit": "share of this cause's ineffective trials",
                "days_per_year": None,
                "days_over_horizon": None,
                "quarterly_trials": base_n,
                "avoided_per_quarter": avoided,
                "disposals_per_quarter": added,
                "spend_8q": spend,
                "status": status,
                "reason": reason,
            }
        )

    series = []
    for row in projected.itertuples(index=False):
        baseline = float(row.open_baseline)
        scenario = float(row.open_scenario)
        series.append(
            {
                "period": str(row.period),
                "step": int(row.step),
                "open_baseline": baseline,
                "open_scenario": scenario,
                "cases_cleared": baseline - scenario,
            }
        )
    end = series[-1]
    start = series[0]
    day_note = (
        "Court sitting days are an assumed share of the 2025-26 national total of "
        f"{float(lever_config['sitting_days']['national_days_2025_26']):,.0f}, "
        "split by disposals. £3,036 per day is published."
    )
    if as_of is not None and str(as_of) < "2025Q2":
        day_note += (
            " This day split uses 2025-26 information. It is retrospective future "
            f"information for a scenario frozen at {as_of}."
        )
    notes = [ASSUMPTION, charge_note, day_note]
    for row in lever_rows:
        if row["reason"]:
            notes.append(f"{row['label']}: {row['reason']}")
    return {
        "court": court,
        "quarters": quarters,
        "sitting_charge": sitting_charge,
        "sitting_productivity": productivity,
        "disposal_conversion": conversion,
        "assumed_cost_scale": cost_scale,
        "series": series,
        "open_now": start["open_baseline"],
        "end_baseline": end["open_baseline"],
        "end_scenario": end["open_scenario"],
        "cases_cleared": end["open_baseline"] - end["open_scenario"],
        "backlog_difference": end["open_scenario"] - end["open_baseline"],
        "spend_8q": recorded_sitting + cause_spend,
        "sitting_spend_8q": recorded_sitting,
        "sitting_spend_physical_8q": physical_spend,
        "annual_sitting_cost": days_per_year * price,
        "court_days": days_here,
        "day_cost": price,
        "sitting_fraction": sitting_fraction,
        "days_per_year": days_per_year,
        "days_over_horizon": days_over_horizon,
        "levers": lever_rows,
        "assumption": ASSUMPTION,
        "notes": notes,
        "causal_effect_established": False,
    }
