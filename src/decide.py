"""Rank levers by open cases cleared per pound.

Each lever is offered the same budget (default £100,000) and run through
simulate() for 8 quarters. The budget is the total for the whole horizon,
not £100,000 every quarter.

Sitting days
    £3,036 is the published HMCTS cost per day.
    This project has no per-court sitting days. The stand-in is:
        court days = 110,647 * this court's share of national disposals
    110,647 is the HMCTS management-information total for 2025-26.
    The share uses disposals from April 2025 to March 2026 (2025Q2–2026Q1),
    the same financial year as that total.

    The budget is the total for the whole horizon, same as a cause lever.
    Default charge is "horizon":
        days over the horizon = budget / £3,036
        days per year = days over the horizon / (quarters / 4)
        fraction = days per year / court days
        spend = budget
    simulate() raises disposals by that fraction in every forecast quarter.
    Two years of that run-rate are paid for by the two-year budget.

    sitting_charge="once" keeps the original accounting for comparison:
        days per year = budget / £3,036
        fraction = days per year / court days
        spend = budget
    That applies the higher rate for every quarter of the horizon while
    charging the days only once. On an 8-quarter run it undercharges by half.

Cause levers
    Price comes from levers.yaml. Those prices are placeholders.
    trials you can afford per quarter = budget / (quarters * cost_per_unit)
    You cannot avoid more trials than the last-4-quarter average of that cause.
    fraction = affordable / available, capped at 1.
    A cost of £0 cannot be turned into a fraction. The yaml default_effect
    is used instead (25% unless edited), spend is £0, and the row is a free win.

Two separate lists
    per_pound: levers with a positive price, ranked by cases cleared per
    £1,000 actually spent. This is the recommendation.
    no_cost: levers priced at £0. Ranked by cases cleared, not by cases
    per pound. Overlisting lives here. It is a policy change, not a purchase.

Stop growth, and the path back to 2019
    Uses sitting days only. Court days are the assumed split above.
    To stop the stock rising, quarterly disposals must meet quarterly receipts.
        fraction = max(0, receipts / disposals - 1)
        extra days per year = fraction * court days
        £ per year = extra days * £3,036
    To be back at the 2019 level after 8 quarters, the same higher rate has
    to eat the gap as well as keep up with receipts. 2019 level means the
    average open-caseload figure across that court's four 2019 quarters.
    The £ for that path is two years of those extra days, because a sitting
    day costs £3,036 each year it is sat. The day split is assumed.
"""

import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.simulate import load_panel, simulate

LEVERS_PATH = ROOT / "config" / "levers.yaml"
OUT_PATH = ROOT / "data" / "clean" / "decisions.parquet"
BUDGET_PATH = ROOT / "data" / "clean" / "budgets.parquet"

# Financial year 2025/26. MoJ Q1 is January–March, so April 2025–March 2026
# is 2025Q2, 2025Q3, 2025Q4, 2026Q1.
FY_2025_26 = ["2025Q2", "2025Q3", "2025Q4", "2026Q1"]


def load_levers(path=LEVERS_PATH):
    """Read the editable lever file. Returns a dict keyed by lever name."""
    with open(path) as handle:
        loaded = yaml.safe_load(handle)
    if "sitting_days" not in loaded:
        raise ValueError(f"{path} has no sitting_days entry")
    return loaded


def _last4_mean(panel, court, column):
    history = panel.loc[panel["court"] == court].sort_values("period")
    return float(history[column].tail(4).mean())


def court_day_assumption(panel, levers):
    """Assumed sitting days per court, from the national total times disposal share.

    Returns a Series indexed by court, plus the national day total and the
    national disposal total used in the share.
    """
    spec = levers["sitting_days"]
    national_days = spec.get("national_days_2025_26")
    if not national_days:
        raise ValueError("sitting_days.national_days_2025_26 is missing from levers.yaml")
    if not spec.get("days_split_assumed", False):
        raise ValueError("The per-court day split must stay marked as assumed")

    year = panel.loc[panel["period"].isin(FY_2025_26)]
    disposals = year.groupby("court")["disposals"].sum()
    national_disposals = float(disposals.sum())
    if national_disposals <= 0:
        raise ValueError("No disposals in the 2025-26 financial year")
    court_days = disposals / national_disposals * float(national_days)
    return court_days, float(national_days), national_disposals


def _cases_cleared(
    court,
    lever_name,
    fraction,
    quarters,
    panel,
    sitting_productivity=1.0,
    disposal_conversion=1.0,
):
    """Open cases removed by the end of the horizon, versus do-nothing."""
    if fraction == 0:
        return 0.0
    projected = simulate(
        court,
        quarters=quarters,
        levers={lever_name: fraction},
        panel=panel,
        sitting_productivity=sitting_productivity,
        disposal_conversion=disposal_conversion,
    )
    final = projected.iloc[-1]
    return float(final["open_baseline"] - final["open_scenario"])


def _days_per_year(budget, day_cost, quarters, sitting_charge):
    """Annual extra days bought by `budget`.

    horizon: budget is the cheque for the whole horizon, so the annual
    run-rate is that many days divided by the number of years.
    once: the original rule. The same budget buys a full year's days,
    and the caller records only `budget` even though the rate runs on.
    """
    if sitting_charge not in ("horizon", "once"):
        raise ValueError("sitting_charge must be 'horizon' or 'once'")
    years = quarters / 4.0
    if years <= 0:
        raise ValueError("quarters must be positive")
    bought = budget / day_cost
    if sitting_charge == "once":
        return bought
    return bought / years


def rank_court(
    court,
    budget,
    quarters,
    panel,
    levers,
    court_days,
    sitting_charge="horizon",
    sitting_productivity=1.0,
    disposal_conversion=1.0,
    assumed_cost_scale=1.0,
):
    """One row per lever, in two sections that are ranked separately."""
    if float(sitting_productivity) < 0 or float(disposal_conversion) < 0:
        raise ValueError("Productivity and conversion must be zero or positive")
    if float(assumed_cost_scale) <= 0:
        raise ValueError("assumed_cost_scale must be positive")
    rows = []
    days_here = float(court_days.get(court, 0.0))
    years = quarters / 4.0

    for name, spec in levers.items():
        cost = float(spec["cost_per_unit"])
        assumed_cost = bool(spec["assumed"])
        label = spec["label"]
        effect = 0.0
        spend = 0.0
        days_bought = pd.NA
        free_win = False
        note = ""

        if name == "sitting_days":
            days_bought = _days_per_year(budget, cost, quarters, sitting_charge)
            spend = budget
            assumed_cost = False
            if days_here <= 0:
                effect = 0.0
                note = "No disposals in 2025-26, so the day split is zero."
            else:
                # Fraction of this court's assumed annual days. simulate()
                # applies it to disposals in every forecast quarter.
                effect = days_bought / days_here
                if sitting_charge == "once":
                    note = (
                        "Original accounting, kept for comparison. "
                        "£3,036 per day is published. The budget buys that many days "
                        "and the higher rate then runs for the whole horizon, while "
                        "spend stays equal to the budget. On an 8-quarter path that "
                        "charges one year for two years of capacity. "
                        "The per-court day split is assumed."
                    )
                else:
                    note = (
                        "£3,036 per day is published. The budget is the bill over "
                        f"{quarters} quarters ({years:g} years). "
                        "Days per year are that purchase divided by the years. "
                        "Court days are an assumed share of the 2025-26 national total."
                    )
        elif cost == 0:
            effect = float(spec["default_effect"])
            spend = 0.0
            free_win = True
            assumed_cost = True
            note = "Assumed £0. Default effect applied. Not bought with the budget."
        else:
            unit_cost = cost * float(assumed_cost_scale) if assumed_cost else cost
            available = _last4_mean(panel, court, f"{name}_n")
            if available <= 0:
                effect = 0.0
                spend = 0.0
                note = "No ineffective trials of this cause in the last 4 quarters."
            else:
                affordable = budget / (quarters * unit_cost)
                used = min(available, affordable)
                effect = used / available
                spend = used * quarters * unit_cost
                note = (
                    "Assumed cost, charged in every quarter of the horizon, "
                    "and the cut is assumed to work."
                )
                if float(assumed_cost_scale) != 1.0:
                    note += f" Placeholder prices are scaled by {float(assumed_cost_scale):g}."

        cases = _cases_cleared(
            court,
            name,
            effect,
            quarters,
            panel,
            sitting_productivity=sitting_productivity,
            disposal_conversion=disposal_conversion,
        )
        if spend > 0:
            cases_per_1k = cases / (spend / 1000.0)
        else:
            cases_per_1k = pd.NA
        cases_per_1k_of_budget = cases / (budget / 1000.0)

        # Effect sizes are not measured. The day split is not measured.
        # Every row depends on at least one assumption.
        assumed_effect = True

        rows.append(
            {
                "court": court,
                "lever": name,
                "label": label,
                "effect": effect,
                "sitting_charge": sitting_charge if name == "sitting_days" else pd.NA,
                "days_per_year": days_bought,
                "court_days_assumed": days_here if name == "sitting_days" else pd.NA,
                "cases_cleared": cases,
                "spend": spend,
                "cases_per_1k": cases_per_1k,
                "cases_per_1k_of_budget": cases_per_1k_of_budget,
                "budget": budget,
                "assumed_cost": assumed_cost,
                "assumed_effect": assumed_effect,
                "relies_on_assumption": assumed_cost or assumed_effect,
                "free_win": free_win,
                "note": note,
            }
        )

    table = pd.DataFrame(rows)
    table["section"] = "per_pound"
    table.loc[table["free_win"], "section"] = "no_cost"

    paid = table.loc[table["section"] == "per_pound"].sort_values(
        ["cases_per_1k", "cases_cleared"],
        ascending=[False, False],
    )
    free = table.loc[table["section"] == "no_cost"].sort_values(
        ["cases_cleared"],
        ascending=[False],
    )
    paid = paid.copy()
    free = free.copy()
    paid["rank"] = range(1, len(paid) + 1)
    free["rank"] = range(1, len(free) + 1)
    # The recommendation is the best purchase. A £0 lever is not in that list.
    paid["is_recommendation"] = paid["rank"] == 1
    free["is_recommendation"] = False
    return pd.concat([paid, free], ignore_index=True)


def decide(
    court=None,
    budget=100_000,
    quarters=8,
    panel=None,
    levers=None,
    sitting_charge="horizon",
    sitting_productivity=1.0,
    disposal_conversion=1.0,
    assumed_cost_scale=1.0,
):
    """Ranked table. Omit court to rank all courts.

    Rank 1 is the recommendation. relies_on_assumption is true when the
    cost is a placeholder or the effect size is not a measured result.

    sitting_charge "horizon" (the default) spreads a sitting-day budget
    across the whole horizon. "once" is the original undercharge.
    sitting_productivity and disposal_conversion default to 1, the
    original simulator. assumed_cost_scale multiplies placeholder prices
    only. The published £3,036 day cost is not scaled.
    """
    if panel is None:
        panel = load_panel()
    if levers is None:
        levers = load_levers()
    court_days, _, _ = court_day_assumption(panel, levers)

    if court is None:
        courts = sorted(panel["court"].unique())
    else:
        courts = [court]

    pieces = [
        rank_court(
            name,
            budget,
            quarters,
            panel,
            levers,
            court_days,
            sitting_charge=sitting_charge,
            sitting_productivity=sitting_productivity,
            disposal_conversion=disposal_conversion,
            assumed_cost_scale=assumed_cost_scale,
        )
        for name in courts
    ]
    return pd.concat(pieces, ignore_index=True)


def compare_recommendations(
    panel,
    levers,
    budget=100_000,
    quarters=8,
    sitting_charge="horizon",
    sitting_productivity=1.0,
    disposal_conversion=1.0,
    assumed_cost_scale=1.0,
):
    """Top paid lever under central horizon settings, and under a scenario.

    Central means the horizon charge, proportional sitting days, a 1:1
    avoided-trial conversion, and unscaled placeholder prices. The scenario
    is whatever the caller passes. This is a comparison of assumptions,
    not a confidence interval and not a causal test.
    """
    shared = {"panel": panel, "levers": levers, "budget": budget, "quarters": quarters}
    central = recommendations(decide(**shared))
    scenario = recommendations(
        decide(
            **shared,
            sitting_charge=sitting_charge,
            sitting_productivity=sitting_productivity,
            disposal_conversion=disposal_conversion,
            assumed_cost_scale=assumed_cost_scale,
        )
    )
    left = central.rename(
        columns={
            "lever": "central_lever",
            "label": "central_label",
            "cases_cleared": "central_cases",
            "cases_per_1k": "central_per_1k",
        }
    )[["court", "central_lever", "central_label", "central_cases", "central_per_1k"]]
    right = scenario.rename(
        columns={
            "lever": "scenario_lever",
            "label": "scenario_label",
            "cases_cleared": "scenario_cases",
            "cases_per_1k": "scenario_per_1k",
        }
    )[["court", "scenario_lever", "scenario_label", "scenario_cases", "scenario_per_1k"]]
    out = left.merge(right, on="court", how="inner")
    out["stable"] = out["central_lever"] == out["scenario_lever"]
    return out


def recommendations(ranked):
    """The top paid lever for each court. £0 levers are not in this list."""
    top = ranked.loc[ranked["is_recommendation"]].copy()
    return top.sort_values("court").reset_index(drop=True)


def _open_2019(panel, court):
    """Average open cases across 2019. None if that court has no 2019 rows."""
    rows = panel.loc[
        (panel["court"] == court) & (panel["period"].str.startswith("2019")),
        "open",
    ]
    if rows.empty:
        return None
    return float(rows.mean())


def _latest_open(panel, court):
    history = panel.loc[panel["court"] == court].sort_values("period")
    return float(history["open"].iloc[-1])


def sitting_need(court, panel, levers, court_days, quarters=8):
    """Extra sitting days, and the £, for two different goals.

    stop_growth: disposals at least match receipts, so the stock stops rising.
    The days and the £ are per year.

    back_to_2019: after `quarters`, open cases are back to the 2019 average.
    The days are still a per-year run-rate. The £ covers sitting those extra
    days for the whole horizon (quarters / 4 years).
    """
    receipts = _last4_mean(panel, court, "receipts")
    disposals = _last4_mean(panel, court, "disposals")
    open_now = _latest_open(panel, court)
    target = _open_2019(panel, court)
    days = float(court_days.get(court, 0.0))
    price = float(levers["sitting_days"]["cost_per_unit"])
    blank = {
        "court": court,
        "receipts": receipts,
        "disposals": disposals,
        "open_now": open_now,
        "open_2019": target,
        "stop_growth_days": pd.NA,
        "stop_growth_gbp_per_year": pd.NA,
        "back_to_2019_days_per_year": pd.NA,
        "back_to_2019_gbp": pd.NA,
        "assumed_day_split": True,
        "note": "",
    }
    if disposals <= 0 or days <= 0:
        blank["note"] = "No disposal rate or no assumed days, so the bill cannot be computed."
        return blank

    # fraction of extra annual days. 0 if the court is already keeping up.
    stop_fraction = max(0.0, receipts / disposals - 1.0)
    stop_days = stop_fraction * days
    blank["stop_growth_days"] = stop_days
    blank["stop_growth_gbp_per_year"] = stop_days * price

    if target is None:
        blank["note"] = "No 2019 open-caseload figure for this court."
        return blank

    # open_now + q*receipts - q*disposals*(1+s) = target
    back_fraction = (open_now - target) / (quarters * disposals) + receipts / disposals - 1.0
    back_fraction = max(0.0, back_fraction)
    back_days = back_fraction * days
    years = quarters / 4.0
    blank["back_to_2019_days_per_year"] = back_days
    blank["back_to_2019_gbp"] = back_days * years * price
    blank["note"] = "Day split is assumed. £3,036 per day is the published cost."
    return blank


def budget_table(panel, levers, court_days, quarters=8):
    """One row per court: days and £ to stop growth, and to regain the 2019 level."""
    rows = [
        sitting_need(court, panel, levers, court_days, quarters)
        for court in sorted(panel["court"].unique())
    ]
    return pd.DataFrame(rows)


def save_decisions(ranked, path=OUT_PATH):
    """Write the ranked table."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ranked.to_parquet(path, index=False)
    return path


def save_budgets(budgets, path=BUDGET_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    budgets.to_parquet(path, index=False)
    return path


def _check(panel, levers):
    """Lock the ranking split and the sitting-day arithmetic."""
    court_days, national_days, national_disposals = court_day_assumption(panel, levers)
    ranked = decide(court="Snaresbrook", panel=panel, levers=levers)
    once = decide(court="Snaresbrook", panel=panel, levers=levers, sitting_charge="once")
    budget = 100_000
    cost = float(levers["sitting_days"]["cost_per_unit"])
    # Original: the whole budget buys one year's days.
    once_effect = (budget / cost) / float(court_days["Snaresbrook"])
    got_once = float(once.loc[once["lever"] == "sitting_days", "effect"].iloc[0])
    if abs(got_once - once_effect) > 1e-9:
        raise AssertionError("Original sitting-day percent does not match budget / cost / court days")
    # Default: that purchase is spread over the 8-quarter horizon.
    expected_effect = once_effect / (8 / 4)
    got_effect = float(ranked.loc[ranked["lever"] == "sitting_days", "effect"].iloc[0])
    if abs(got_effect - expected_effect) > 1e-9:
        raise AssertionError("Horizon sitting-day percent is not the original divided by the years")
    once_cases = float(once.loc[once["lever"] == "sitting_days", "cases_cleared"].iloc[0])
    horizon_cases = float(ranked.loc[ranked["lever"] == "sitting_days", "cases_cleared"].iloc[0])
    if abs(horizon_cases * 2 - once_cases) > 1e-6:
        raise AssertionError("Horizon cases cleared should be half the original one-year charge")

    over = ranked.loc[ranked["lever"] == "overlisting"].iloc[0]
    if over["section"] != "no_cost" or over["is_recommendation"] or not over["free_win"]:
        raise AssertionError("Overlisting must stay in the no-cost section")
    if over["rank"] != 1:
        raise AssertionError("The only no-cost lever should be rank 1 in that section")

    paid = ranked.loc[ranked["section"] == "per_pound"]
    if paid["is_recommendation"].sum() != 1:
        raise AssertionError("Each court needs exactly one paid recommendation")
    if set(paid["rank"]) != set(range(1, len(paid) + 1)):
        raise AssertionError("Paid ranks should start at 1")

    need = sitting_need("Snaresbrook", panel, levers, court_days)
    receipts = need["receipts"]
    disposals = need["disposals"]
    # With the stop-growth fraction, next quarter's stock does not rise.
    fraction = max(0.0, receipts / disposals - 1.0)
    projected = simulate("Snaresbrook", quarters=1, levers={"sitting_days": fraction}, panel=panel)
    open0 = float(projected["open_baseline"].iloc[0])
    open1 = float(projected["open_scenario"].iloc[1])
    if abs(open1 - open0) > 0.05:
        raise AssertionError(f"Stop-growth path still moves the stock: {open0} -> {open1}")

    print("Checks passed.")
    print(
        f"2025-26 disposals {national_disposals:,.0f} across "
        f"{national_days:,.0f} national sitting days"
    )
    print(
        f"Snaresbrook assumed days {float(court_days['Snaresbrook']):,.1f} "
        f"({float(court_days['Snaresbrook']) / national_days:.1%} of the national total)"
    )
    return ranked


def _print_summary(full, budgets):
    """Paid ranking, the no-cost list, and the two national bills."""
    top = recommendations(full)
    print("Per-£ recommendation, count of courts:")
    print(top["label"].value_counts().to_string())
    print(
        f"Cases cleared if each court gets that paid lever: "
        f"{top['cases_cleared'].sum():,.1f}"
    )
    flagged = int(top["relies_on_assumption"].sum())
    priced = int(top["assumed_cost"].sum())
    print(f"Those recommendations rely on an assumption: {flagged} of {len(top)}")
    print(f"The price itself is a placeholder: {priced} of {len(top)}")

    free = full.loc[full["section"] == "no_cost"]
    print()
    print("No-cost policy change (ranked by cases cleared, not per £):")
    print(
        f"  {free['label'].iloc[0]} at the yaml default, "
        f"{free['cases_cleared'].sum():,.1f} cases across {free['court'].nunique()} courts"
    )
    print(f"  Courts where that clears nothing: {int((free['cases_cleared'] == 0).sum())}")

    print()
    already = int((budgets["stop_growth_days"] == 0).sum())
    print(
        f"Stop growth: {budgets['stop_growth_days'].sum():,.0f} extra sitting days a year, "
        f"£{budgets['stop_growth_gbp_per_year'].sum():,.0f} a year"
    )
    print(f"  Courts already disposing at least what they receive: {already}")
    on_track = int((budgets["back_to_2019_days_per_year"] == 0).sum())
    print(
        f"Back to 2019 open cases in 8 quarters: "
        f"{budgets['back_to_2019_days_per_year'].sum():,.0f} extra days a year, "
        f"£{budgets['back_to_2019_gbp'].sum():,.0f} over the 8 quarters"
    )
    print(f"  Courts already on that path with no extra days: {on_track}")
    print("  Both bills use the assumed per-court day split. £3,036 per day is published.")


def _print_court(ranked, budgets, court):
    show = ["section", "rank", "label", "cases_cleared", "spend", "cases_per_1k", "assumed_cost"]
    one = ranked.loc[ranked["court"] == court, show]
    print(f"{court}, £100,000 budget, 8 quarters")
    print("Per £:")
    print(one.loc[one["section"] == "per_pound"].to_string(index=False))
    print("No-cost policy change:")
    print(one.loc[one["section"] == "no_cost"].to_string(index=False))
    row = budgets.loc[budgets["court"] == court].iloc[0]
    print(
        f"2019 average open cases: {row['open_2019']:,.0f}. "
        f"Now: {row['open_now']:,.0f}. "
        f"Last-4 receipts {row['receipts']:,.1f}, disposals {row['disposals']:,.1f}."
    )
    print(
        f"Stop growth: {row['stop_growth_days']:,.0f} extra sitting days a year, "
        f"£{row['stop_growth_gbp_per_year']:,.0f} a year."
    )
    print(
        f"Back to 2019 in 8 quarters: {row['back_to_2019_days_per_year']:,.0f} extra days a year, "
        f"£{row['back_to_2019_gbp']:,.0f} over the 8 quarters."
    )


if __name__ == "__main__":
    panel = load_panel()
    levers = load_levers()
    _check(panel, levers)
    court_days, _, _ = court_day_assumption(panel, levers)
    full = decide(panel=panel, levers=levers)
    budgets = budget_table(panel, levers, court_days)
    decisions_path = save_decisions(full)
    budgets_path = save_budgets(budgets)
    print()
    _print_court(full, budgets, "Snaresbrook")
    print()
    _print_summary(full, budgets)
    print()
    print(f"Saved {decisions_path}")
    print(f"Saved {budgets_path}")
