"""Courtfall. Pick a court, then do one job.

The map is the way in. Four tabs follow it:

1. Court action plan. Resident judge. Ranked actions, with a PDF brief.
2. Trial risk check. Listing officer. A heuristic score for one trial.
3. National allocation. HMCTS. A budget, then sitting days in cases-per-£ order.
4. Decision Lab. Change the cost horizon and the unmeasured rates, and see
   whether the top purchase stays the same.
5. Live simulation. The same eight-quarter path the API plots.

Model honesty stays at the bottom. Assumed figures are labelled.
The £3,036 sitting-day cost is published. The split of national sitting
days across courts is not.
"""

import json
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st
from fpdf import FPDF

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.decide import (
    budget_table,
    court_day_assumption,
    decide,
    load_levers,
    recommendations,
)
from src.model import fit_and_score
from src.scenario import run_scenario
from src.simulate import _accounting_error, _last4, _one_step_mae, backtest, load_panel, simulate

PREDICTIONS = ROOT / "data" / "clean" / "predictions.parquet"
ACTIONS_PATH = ROOT / "data" / "actions.json"
TRIALS_PATH = ROOT / "data" / "trials.json"

# Cause key, the action a person can take, and who owns it.
# The phrases are the interventions for that cause, not measured programmes.
CAUSE_ACTIONS = [
    ("prosecution", "CPS readiness check 14 days pre-trial", "CPS"),
    ("overlisting", "Reduce listing ratio / standby case", "Listing officer"),
    ("defence_advocate", "Confirm counsel 48h prior", "Defence solicitor"),
    ("prisoner_not_produced", "Book video link / escort confirmation", "Prisoner escort"),
    ("judge", "Reallocate recorders", "Resident judge"),
]

# Chosen cut points for the trial-risk band. Not fitted to outcomes.
GREEN_BELOW = 0.20
AMBER_BELOW = 0.35

# Plain-language names for the SHAP columns written by src/model.py.
DRIVER_WORDS = {
    "last_quarter_rate": "the ineffective rate last quarter",
    "rate_two_quarters_ago": "the rate two quarters ago",
    "rate_three_quarters_ago": "the rate three quarters ago",
    "rate_four_quarters_ago": "the rate four quarters ago",
    "four_quarter_average": "the average rate over the last four quarters",
    "prosecution_share": "the share of failures caused by the prosecution not being ready",
    "overlisting_share": "the share of failures caused by overlisting",
    "defence_advocate_share": "the share of failures caused by defence advocates",
    "prisoner_not_produced_share": "the share of failures caused by the prisoner not being produced",
    "judge_share": "the share of failures caused by judge availability",
    "open_cases": "how many cases are already open",
    "receipts": "how many new cases arrived",
    "quarter": "which quarter of the year is being predicted",
    "covid_2020_2022": "the 2020–2022 flag",
}

CAUSES = [
    ("prosecution_share", "Prosecution not ready"),
    ("overlisting_share", "Overlisting"),
    ("defence_advocate_share", "Defence advocate"),
    ("prisoner_not_produced_share", "Prisoner not produced"),
    ("judge_share", "Judge availability"),
]


def money(amount):
    """£14.6m style. The number is computed by the caller."""
    if pd.isna(amount):
        return "not available"
    if abs(amount) >= 1_000_000:
        return f"£{amount / 1_000_000:.1f}m"
    return f"£{amount:,.0f}"


def chart_layout(title):
    return dict(
        title=dict(text=title, font=dict(size=16, color="#E7EDF6")),
        font=dict(family="ui-sans-serif, system-ui, sans-serif", size=14, color="#E7EDF6"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=48, b=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(color="#E7EDF6")),
        xaxis=dict(title="", gridcolor="#2A3548", color="#C5D0E0"),
        yaxis=dict(gridcolor="#2A3548", color="#C5D0E0"),
        height=340,
    )


def rate_colour(rate):
    """Blue at a low predicted rate, rose at a high one. The tooltip also states the number."""
    span = 0.42 - 0.08
    t = min(1.0, max(0.0, (float(rate) - 0.08) / span))
    low = (3, 105, 161)
    high = (159, 18, 57)
    return [int(low[i] + t * (high[i] - low[i])) for i in range(3)] + [210]


@st.cache_data
def panel():
    return load_panel()


@st.cache_data
def predictions():
    frame = pd.read_parquet(PREDICTIONS)
    frame["court"] = frame["court"].astype(str)
    return frame


@st.cache_data
def levers():
    return load_levers()


@st.cache_data
def planning_tables():
    """Ranked levers and the two sitting-day bills. Computed, then cached."""
    data = panel()
    config = levers()
    days, national_days, _ = court_day_assumption(data, config)
    ranked = decide(panel=data, levers=config)
    bills = budget_table(data, config, days)
    return ranked, bills, float(national_days), days


@st.cache_data
def project_court(court, sitting, overlisting, defence, prisoner, prosecution):
    """One court, 8 quarters. Slider values are fractions of 1, already converted."""
    return simulate(
        court,
        quarters=8,
        levers={
            "sitting_days": sitting,
            "overlisting": overlisting,
            "defence_advocate": defence,
            "prisoner_not_produced": prisoner,
            "prosecution": prosecution,
        },
        panel=panel(),
    )


@st.cache_data
def project_nation(sitting, overlisting, defence, prisoner, prosecution):
    """Same sliders at every court, then add the open-caseload figures up."""
    data = panel()
    parts = []
    for court in sorted(data["court"].unique()):
        parts.append(
            project_court(court, sitting, overlisting, defence, prisoner, prosecution)
        )
    stacked = pd.concat(parts, ignore_index=True)
    return (
        stacked.groupby("period", as_index=False)[["open_baseline", "open_scenario"]]
        .sum()
        .sort_values("period")
    )


def _sitting_fraction(days_per_year, court_days):
    """Turn extra days a year into the fraction simulate() applies to disposals."""
    if court_days is None or court_days <= 0 or pd.isna(days_per_year):
        return 0.0
    return max(0.0, float(days_per_year) / float(court_days))


@st.cache_data
def court_scenario_lines(court):
    """Four 8-quarter paths for one court. Costs are for the legend.

    Do nothing spends nothing.
    Best £100k uses the top paid lever from decide(), at the effect that
    budget can buy.
    Stop growth and return to 2019 use the sitting-day fractions from the
    bill. Those day counts are the assumed split.
    """
    ranked, bills, _, court_days = planning_tables()
    data = panel()
    paid = ranked.loc[
        (ranked["court"] == court) & (ranked["section"] == "per_pound") & (ranked["rank"] == 1)
    ].iloc[0]
    bill = bills.loc[bills["court"] == court].iloc[0]
    days_here = float(court_days.get(court, 0.0))
    stop_fraction = _sitting_fraction(bill["stop_growth_days"], days_here)
    back_fraction = _sitting_fraction(bill["back_to_2019_days_per_year"], days_here)

    do_nothing = simulate(court, quarters=8, levers={}, panel=data)
    best = simulate(court, quarters=8, levers={paid["lever"]: float(paid["effect"])}, panel=data)
    stop = simulate(court, quarters=8, levers={"sitting_days": stop_fraction}, panel=data)
    back = simulate(court, quarters=8, levers={"sitting_days": back_fraction}, panel=data)

    lines = do_nothing[["period"]].copy()
    lines["do_nothing"] = do_nothing["open_baseline"].to_numpy()
    lines["best"] = best["open_scenario"].to_numpy()
    lines["stop"] = stop["open_scenario"].to_numpy()
    lines["back"] = back["open_scenario"].to_numpy()

    best_price = "assumed price" if bool(paid["assumed_cost"]) else "published day cost, assumed split"
    labels = {
        "do_nothing": "Do nothing (£0)",
        "best": f"Best £100k: {paid['label']} ({money(paid['spend'])}, {best_price})",
        "stop": f"Stop growth ({money(bill['stop_growth_gbp_per_year'])}/year, assumed days)",
        "back": f"Return to 2019 ({money(bill['back_to_2019_gbp'])} over 8 quarters, assumed days)",
    }
    return lines, labels


@st.cache_data
def national_allocation():
    """Open cases after 8 quarters as a national sitting-day budget grows.

    Courts are funded in order of cases cleared per pound of sitting days.
    That rate comes from the £100,000 sitting-day row in decide(), where the
    £100,000 is the bill over 8 quarters. The effect is linear, so the same
    rate applies at other amounts.

    Each court is capped at the extra days that return it to its 2019 average.
    The pounds on the curve are the cost of sitting those days for 8 quarters
    (two years), which is the same basis as the £149m headline.
    """
    ranked, bills, _, _ = planning_tables()
    sitting = ranked.loc[ranked["lever"] == "sitting_days"].copy()
    merged = sitting.merge(bills, on="court", how="left")
    # decide() now records the 8-quarter bill. Cases cleared already match
    # that bill, so the rate is cases / spend. The old code divided by
    # 2 * spend because it charged the days only once.
    merged["cases_per_pound"] = merged["cases_cleared"] / merged["spend"].where(merged["spend"] > 0)
    merged["cap_gbp"] = merged["back_to_2019_gbp"].fillna(0.0).clip(lower=0.0)
    merged["cap_cases"] = merged["cases_per_pound"].fillna(0.0) * merged["cap_gbp"]
    merged["end_do_nothing"] = merged["open_now"] + 8.0 * (merged["receipts"] - merged["disposals"])
    merged = merged.sort_values(["cases_per_pound", "court"], ascending=[False, True])

    baseline = float(merged["end_do_nothing"].sum())
    step = 5_000_000
    points = []
    for budget in range(0, 150_000_001, step):
        remaining = float(budget)
        cleared = 0.0
        for _, court in merged.iterrows():
            if remaining <= 0:
                break
            take = min(remaining, float(court["cap_gbp"]))
            cleared += take * float(court["cases_per_pound"] or 0.0)
            remaining -= take
        points.append({"budget": budget, "open_cases": baseline - cleared})

    per_million = merged.loc[merged["cases_per_pound"].notna(), ["court", "cases_per_pound"]].copy()
    per_million["cases_per_1m"] = per_million["cases_per_pound"] * 1_000_000
    per_million = per_million.sort_values("cases_per_1m", ascending=False)
    return pd.DataFrame(points), per_million, baseline


@st.cache_data
def honesty_numbers():
    """Backtest of the stock-flow, and the forecast errors on 2024–2026."""
    data = panel()
    detail = backtest(start="2023Q4", panel=data)
    account, previous = _accounting_error(data, "2023Q4")
    one_step = _one_step_mae(data, "2023Q4")
    backlog = pd.DataFrame(
        [
            {"check": "Frozen last-4 forecast (what the 8-quarter chart does)", "mae_open_cases": detail["abs_err"].mean()},
            {"check": "Same rule with the actual receipts and disposals", "mae_open_cases": account},
            {"check": "Previous quarter's flows instead", "mae_open_cases": previous},
            {"check": "One-step last-4 forecast (errors do not pile up)", "mae_open_cases": one_step},
        ]
    )
    scores, _, _, _, _ = fit_and_score(data)
    return backlog, scores


def latest_rows():
    data = panel()
    latest = data["period"].max()
    rows = data.loc[data["period"] == latest].copy()
    return latest, rows


def map_frame():
    """One row per court for the map: position, open cases, predicted rate."""
    latest, rows = latest_rows()
    keep = rows.merge(predictions(), on="court", how="left", suffixes=("", "_pred"))
    keep = keep.dropna(subset=["lat", "lon", "predicted_rate"])
    keep["radius"] = 7000 + 32000 * (keep["open"] / keep["open"].max())
    colours = keep["predicted_rate"].map(rate_colour)
    keep["fill"] = colours
    keep["open_label"] = keep["open"].round(0).astype(int).map(lambda n: f"{n:,}")
    keep["rate_label"] = keep["predicted_rate"].map(lambda r: f"{100 * r:.1f}%")
    return latest, keep


def explain_driver(name, value, period):
    """One SHAP driver, in a sentence a judge can follow."""
    words = DRIVER_WORDS.get(name, name.replace("_", " "))
    points = 100 * abs(float(value))
    if name == "covid_2020_2022" and not str(period).startswith(("2020", "2021", "2022")):
        return (
            f"The 2020–2022 flag is off for {period}. "
            f"That pulls the tree's rate {'down' if value < 0 else 'up'} "
            f"by {points:.1f} percentage points. It does not mean those years are happening now."
        )
    direction = "adds" if value > 0 else "subtracts"
    return f"{words.capitalize()} {direction} {points:.1f} percentage points on the tree's rate."


def plain_summary(court, bill, paid, free):
    """One paragraph built only from this court's calculated numbers."""
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
        f"in extra sitting days ({bill['stop_growth_days']:,.0f} days). "
        "The £3,036 per day is published. Assigning those days to this court is assumed."
    )
    if bool(paid["assumed_cost"]):
        price = "That price is a placeholder."
    else:
        price = "That uses the published sitting-day cost. The size of the effect still uses the assumed day split."
    best = (
        f"The best purchase with £100,000 over 8 quarters is {paid['label']}, "
        f"clearing about {paid['cases_cleared']:.0f} open cases and spending {money(paid['spend'])}. "
        f"Sitting days in that comparison are a two-year run-rate, not a one-year bill. {price}"
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


def scenario_figure(lines, labels, title):
    """Four paths. The legend carries the £ cost of each one."""
    figure = go.Figure()
    colours = {
        "do_nothing": "#334155",
        "best": "#0369A1",
        "stop": "#0F766E",
        "back": "#9F1239",
    }
    for key in ("do_nothing", "best", "stop", "back"):
        figure.add_trace(
            go.Scatter(
                x=lines["period"],
                y=lines[key],
                name=labels[key],
                mode="lines+markers",
                line=dict(color=colours[key], width=3),
            )
        )
    layout = chart_layout(title)
    layout["height"] = 420
    layout["margin"] = dict(l=8, r=8, t=48, b=120)
    layout["legend"] = dict(orientation="h", yanchor="top", y=-0.2, x=0)
    figure.update_layout(**layout)
    figure.update_yaxes(title_text="Open cases")
    return figure


def spend_figure(curve, stop_gbp, back_gbp):
    """National open cases after 8 quarters, against the sitting-day budget."""
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=curve["budget"] / 1_000_000,
            y=curve["open_cases"],
            name="Open cases after 8 quarters",
            mode="lines+markers",
            line=dict(color="#8FB8FF", width=3),
        )
    )
    figure.add_vline(
        x=stop_gbp / 1_000_000,
        line_dash="dash",
        line_color="#7DCEA0",
        annotation_text=f"{money(stop_gbp)} Stop growth for 2 years",
        annotation_position="top left",
        annotation_font_color="#E7EDF6",
    )
    figure.add_vline(
        x=back_gbp / 1_000_000,
        line_dash="dot",
        line_color="#F0A3B0",
        annotation_text=f"{money(back_gbp)} Return to 2019",
        annotation_position="top right",
        annotation_font_color="#E7EDF6",
    )
    layout = chart_layout("Spend versus backlog, England and Wales")
    layout["height"] = 420
    figure.update_layout(**layout)
    figure.update_xaxes(title_text="£ million spent on extra sitting days over 8 quarters")
    figure.update_yaxes(title_text="Open cases after 8 quarters")
    return figure


def efficiency_figure(per_million):
    """Top 15 courts by cases cleared per £1 million of sitting days."""
    top = per_million.head(15).iloc[::-1]
    figure = go.Figure(
        go.Bar(
            x=top["cases_per_1m"],
            y=top["court"],
            orientation="h",
            marker_color="#8FB8FF",
            text=top["cases_per_1m"].map(lambda value: f"{value:.0f}"),
            textposition="outside",
        )
    )
    layout = chart_layout("Cases cleared per £1 million of sitting days")
    layout["height"] = 480
    layout["margin"] = dict(l=8, r=48, t=48, b=8)
    figure.update_layout(**layout)
    figure.update_xaxes(title_text="Open cases cleared over 8 quarters, per £1m")
    return figure


def backlog_figure(frame, title):
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=frame["period"],
            y=frame["open_baseline"],
            name="Do nothing",
            mode="lines+markers",
            line=dict(color="#334155", width=3),
        )
    )
    figure.add_trace(
        go.Scatter(
            x=frame["period"],
            y=frame["open_scenario"],
            name="With the sliders",
            mode="lines+markers",
            line=dict(color="#0369A1", width=3),
        )
    )
    figure.update_layout(**chart_layout(title))
    figure.update_yaxes(title_text="Open cases")
    return figure


def _read_json(path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return fallback


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def load_done():
    """Marked actions. Shape: {court: {action_id: true}}."""
    data = _read_json(ACTIONS_PATH, {})
    return data if isinstance(data, dict) else {}


def save_done(data):
    _write_json(ACTIONS_PATH, data)


def load_trials():
    rows = _read_json(TRIALS_PATH, [])
    return rows if isinstance(rows, list) else []


def save_trials(rows):
    _write_json(TRIALS_PATH, rows)


@st.cache_data
def lever_cases(court, lever_name, effect):
    """Open cases removed over 8 quarters if this lever is set to effect."""
    if effect <= 0:
        return 0.0
    projected = simulate(court, quarters=8, levers={lever_name: effect}, panel=panel())
    final = projected.iloc[-1]
    return float(final["open_baseline"] - final["open_scenario"])


def build_actions(court, bills, latest_row):
    """Three to five actions. Capacity is always included. Causes need a count."""
    config = levers()
    bill = bills.loc[bills["court"] == court].iloc[0]
    history = panel().loc[panel()["court"] == court].sort_values("period")
    growth = float(bill["receipts"] - bill["disposals"])
    days = float(bill["stop_growth_days"])
    yearly = float(bill["stop_growth_gbp_per_year"])
    if growth > 1 and days > 0:
        impact = growth * 8.0
        detail = (
            f"Ask for {days:,.0f} extra sitting days a year so disposals meet receipts. "
            f"That is {money(yearly)} a year at the published £3,036 a day."
        )
        cost_label = f"{money(yearly)} a year"
        confidence = "Growth is data-backed. The day split is assumed. £3,036 a day is published."
    else:
        impact = 0.0
        yearly = 0.0
        detail = "No extra sitting days. On the last four quarters, disposals already meet receipts."
        cost_label = "£0"
        confidence = "Data-backed. The last four quarters of receipts and disposals already balance."
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
            "cost_label": cost_label,
            "owner": "Resident judge, to HMCTS",
            "confidence": confidence,
        }
    ]
    for name, title, owner in CAUSE_ACTIONS:
        available = _last4(history, f"{name}_n")
        if available <= 0:
            continue
        spec = config[name]
        effect = float(spec["default_effect"])
        price = float(spec["cost_per_unit"])
        cases = lever_cases(court, name, effect)
        spend = 0.0 if price == 0 else available * effect * 8.0 * price
        share = latest_row.get(f"{name}_share", 0.0)
        share = 0.0 if pd.isna(share) else float(share)
        if price == 0:
            cost_label = "£0"
            cost_note = "The £0 price is assumed, and so is the size of the cut."
        else:
            cost_label = money(spend)
            cost_note = "The price per avoided trial is a placeholder, and the size of the cut is assumed."
        actions.append(
            {
                "id": name,
                "title": title,
                "detail": (
                    f"{share * 100:.0f}% of ineffective trials in {latest_row['period']} were this cause. "
                    f"The plan assumes {effect * 100:.0f}% of them are avoided, from config/levers.yaml. "
                    f"{cost_note} One avoided trial is counted as one extra disposal."
                ),
                "impact": cases,
                "impact_label": f"{cases:,.0f} cases cleared over 8 quarters",
                "cost_label": cost_label,
                "owner": owner,
                "confidence": "The cause count is data-backed. The effect and the cost are assumed.",
            }
        )
    capacity = actions[0]
    causes = sorted(actions[1:], key=lambda row: row["impact"], reverse=True)
    chosen = sorted([capacity] + causes, key=lambda row: row["impact"], reverse=True)[:5]
    if not any(row["id"] == "capacity" for row in chosen):
        chosen = sorted(chosen[:4] + [capacity], key=lambda row: row["impact"], reverse=True)
    for rank, row in enumerate(chosen, start=1):
        row["rank"] = rank
    return chosen


def trial_risk(
    predicted_rate,
    shares,
    custody,
    defence_confirmed,
    cps_served,
    witnesses_confirmed,
    floater,
):
    """Heuristic. The court's forecast, plus unchecked items weighted by cause shares.

    Not a trained model. Witnesses not confirmed use the prosecution/witness
    share (reason codes 1-6, 15, 16), the same share as CPS evidence not served.
    A floater or backer uses the overlisting share. A custody case uses the
    prisoner-not-produced share. Judge availability stays inside the predicted
    rate, because the form does not ask about the judge.
    """
    factors = []
    prosecution = float(shares.get("prosecution", 0.0) or 0.0)
    if not cps_served:
        factors.append(("prosecution", prosecution))
    if not defence_confirmed:
        factors.append(("defence_advocate", float(shares.get("defence_advocate", 0.0) or 0.0)))
    if not witnesses_confirmed:
        factors.append(("prosecution", prosecution))
    if floater:
        factors.append(("overlisting", float(shares.get("overlisting", 0.0) or 0.0)))
    if custody:
        factors.append(("prisoner_not_produced", float(shares.get("prisoner_not_produced", 0.0) or 0.0)))
    weight = sum(value for _, value in factors)
    score = min(1.0, float(predicted_rate) * (1.0 + weight))
    if score < GREEN_BELOW:
        band = "Green"
    elif score < AMBER_BELOW:
        band = "Amber"
    else:
        band = "Red"
    names = {key: title for key, title, _ in CAUSE_ACTIONS}
    if factors:
        key = max(factors, key=lambda item: item[1])[0]
        suggestion = names[key]
    else:
        suggestion = "No extra check. The score is this court's predicted ineffective rate."
    return score, band, suggestion


def court_shares(latest_row):
    shares = {}
    for name, _, _ in CAUSE_ACTIONS:
        value = latest_row.get(f"{name}_share", 0.0)
        shares[name] = 0.0 if pd.isna(value) else float(value)
    return shares


def pdf_safe(text):
    return (
        str(text)
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2022", "-")
    )


def court_brief_pdf(court, summary, actions, period):
    """One page-or-more brief of the action plan. Core fonts, Latin-1."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(0, 8, pdf_safe(f"Courtfall brief: {court}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(
        0, 6, pdf_safe(f"Actions for the resident judge. Figures as of {period}."),
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(2)
    pdf.multi_cell(0, 6, pdf_safe(summary), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    for action in actions:
        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(0, 7, pdf_safe(f"{action['rank']}. {action['title']}"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 6, pdf_safe(action["detail"]), new_x="LMARGIN", new_y="NEXT")
        pdf.multi_cell(
            0,
            6,
            pdf_safe(
                f"Impact: {action['impact_label']}. Cost: {action['cost_label']}. "
                f"Owner: {action['owner']}."
            ),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.multi_cell(0, 6, pdf_safe(f"Confidence: {action['confidence']}"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(
        0,
        5,
        pdf_safe(
            "Assumptions. One avoided ineffective trial is counted as one extra disposal. "
            "Per-court sitting days are an assumed share of 110,647 national days in 2025-26. "
            "£3,036 per sitting day is published (HMCTS 2022-23, parliamentary question 4727, "
            "answered 5 December 2023). Every other price is a placeholder."
        ),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    return bytes(pdf.output())


def allocate_budget(budget_gbp):
    """Courts funded, in cases-per-pound order, up to the 8-quarter budget."""
    curve, per_million, _ = national_allocation()
    ranked, bills, _, _ = planning_tables()
    sitting = ranked.loc[ranked["lever"] == "sitting_days"].copy()
    merged = sitting.merge(bills, on="court", how="left")
    merged["cases_per_pound"] = merged["cases_cleared"] / merged["spend"].where(merged["spend"] > 0)
    merged["cap_gbp"] = merged["back_to_2019_gbp"].fillna(0.0).clip(lower=0.0)
    price = float(levers()["sitting_days"]["cost_per_unit"])
    merged = merged.sort_values(["cases_per_pound", "court"], ascending=[False, True])
    remaining = max(0.0, float(budget_gbp))
    rows = []
    for _, court in merged.iterrows():
        if remaining <= 0:
            break
        cap = float(court["cap_gbp"])
        rate = float(court["cases_per_pound"] or 0.0)
        if cap <= 0 or rate <= 0:
            continue
        take = min(remaining, cap)
        rows.append(
            {
                "Court": court["court"],
                "£ over 8 quarters": money(take),
                "Extra days a year": f"{take / (2.0 * price):,.0f}",
                "Cases cleared": f"{take * rate:,.0f}",
                "Funded to 2019 cap": "Yes" if take >= cap - 1 else "Part",
            }
        )
        remaining -= take
    return pd.DataFrame(rows), remaining, curve, per_million


def clicked_court(event):
    if event is None:
        return None
    selection = event.selection
    objects = selection["objects"] if selection is not None else {}
    rows = objects.get("courts", [])
    if not rows:
        return None
    return rows[0].get("court")


def draw_map(points):
    layer = pdk.Layer(
        "ScatterplotLayer",
        data=points,
        id="courts",
        get_position=["lon", "lat"],
        get_fill_color="fill",
        get_radius="radius",
        pickable=True,
        auto_highlight=True,
        stroked=True,
        get_line_color=[231, 237, 246],
        line_width_min_pixels=1,
    )
    view = pdk.ViewState(latitude=52.6, longitude=-1.8, zoom=5.2)
    deck = pdk.Deck(
        layers=[layer],
        initial_view_state=view,
        map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
        tooltip={
            "text": "{court}\nOpen cases: {open_label}\nPredicted ineffective rate: {rate_label}"
        },
    )
    return st.pydeck_chart(
        deck,
        on_select="rerun",
        selection_mode="single-object",
        height=560,
        alt=(
            "Map of Crown Courts in England and Wales. "
            "Larger circles have more open cases. "
            "Colour runs from blue, a lower predicted ineffective rate, "
            "to rose, a higher one. The tooltip states both numbers."
        ),
    )


def apply_theme():
    st.markdown(
        """
        <style>
        :root { color-scheme: dark; }
        html, body, .stApp, [class*="css"] {
          font-family: ui-sans-serif, system-ui, sans-serif;
          font-variant-numeric: tabular-nums;
        }
        .stApp { background: #0E1420; color: #E7EDF6; }
        [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {
          color: #C5D0E0;
        }
        [data-testid="stSidebar"] { display: none; }
        h1, h2, h3 { letter-spacing: -0.02em; }
        [data-testid="stVerticalBlockBorderWrapper"] {
          background: #171F2E;
          border: 1px solid #2C3A52;
          border-radius: 12px;
          box-shadow: 0 10px 28px rgba(0, 0, 0, 0.35);
        }
        [data-testid="stTabs"] button[aria-selected="true"] {
          color: #8FB8FF;
          border-bottom-color: #8FB8FF;
        }
        ::selection { background: #8FB8FF; color: #0E1420; }
        *:focus-visible { outline: 2px solid #8FB8FF; outline-offset: 2px; }
        .band {
          display: inline-block;
          padding: 8px 14px;
          border-radius: 8px;
          font-weight: 700;
          font-size: 1.25rem;
          letter-spacing: -0.02em;
        }
        .band-Green { background: #A8D5B5; color: #102016; }
        .band-Amber { background: #F3D19C; color: #2A2112; }
        .band-Red { background: #F0A3A8; color: #2A1216; }
        button[kind="primary"], .stDownloadButton button, .stFormSubmitButton button {
          background: #8FB8FF;
          color: #0E1420;
          border: 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def draw_action_plan(court, bills, latest_row, forecast, ranked):
    paid = ranked.loc[
        (ranked["court"] == court) & (ranked["section"] == "per_pound") & (ranked["rank"] == 1)
    ].iloc[0]
    free = ranked.loc[(ranked["court"] == court) & (ranked["section"] == "no_cost")]
    bill = bills.loc[bills["court"] == court].iloc[0]
    summary = plain_summary(court, bill, paid, free)
    actions = build_actions(court, bills, latest_row)
    rate = float(forecast["predicted_rate"])
    st.caption(
        f"Predicted ineffective rate, {forecast['period']}: {100 * rate:.1f}%. "
        "Half tree, half four-quarter average. The tree alone does not beat the recent average."
    )
    st.write(summary)
    brief = court_brief_pdf(court, summary, actions, latest_row["period"])
    slug = court.lower().replace(" ", "-")
    st.download_button(
        "Download court brief (PDF)",
        data=brief,
        file_name=f"courtfall-{slug}.pdf",
        mime="application/pdf",
    )
    done = load_done()
    court_done = done.setdefault(court, {})
    for action in actions:
        with st.container(border=True):
            st.markdown(f"**{action['rank']}. {action['title']}**")
            st.write(action["detail"])
            impact, cost, owner = st.columns(3)
            impact.markdown(f"**Impact.** {action['impact_label']}")
            cost.markdown(f"**Cost.** {action['cost_label']}")
            owner.markdown(f"**Owner.** {action['owner']}")
            st.caption(action["confidence"])
            widget_key = f"done::{court}::{action['id']}"
            if widget_key not in st.session_state:
                st.session_state[widget_key] = bool(court_done.get(action["id"], False))
            checked = st.checkbox("Mark as done", key=widget_key)
            if bool(court_done.get(action["id"], False)) != checked:
                court_done[action["id"]] = checked
                save_done(done)


def draw_risk(court, latest_row, forecast, courts):
    st.write(
        "Score one upcoming trial. The number starts at this court's predicted "
        "ineffective rate, then rises when a check is missing, in proportion to "
        "that cause's share of ineffective trials. This is a heuristic, not a trained model."
    )
    rate = float(forecast["predicted_rate"])
    st.caption(
        f"Predicted ineffective rate for {forecast['period']}: {100 * rate:.1f}%. "
        "Half tree, half four-quarter average. "
        f"Green is under {100 * GREEN_BELOW:.0f}%. "
        f"Amber is under {100 * AMBER_BELOW:.0f}%. "
        "Red is the rest. Those cut points are a choice."
    )
    with st.form("trial_form", clear_on_submit=False):
        picked = st.selectbox(
            "Court for this trial",
            courts,
            index=courts.index(court) if court in courts else 0,
        )
        when = st.date_input("Trial date")
        custody = st.checkbox("Defendant in custody")
        defence = st.checkbox("Defence counsel confirmed")
        cps = st.checkbox("CPS evidence served")
        witnesses = st.checkbox("Witnesses confirmed")
        floater = st.checkbox("Listed as a floater/backer")
        submitted = st.form_submit_button("Score this trial")
    if submitted:
        row = latest_rows()[1].loc[latest_rows()[1]["court"] == picked]
        if row.empty:
            st.error(f"{picked} has no row in the latest quarter. Pick another court.")
        else:
            forecast_row = predictions().loc[predictions()["court"] == picked]
            if forecast_row.empty:
                st.error(f"{picked} has no predicted rate. Pick another court.")
            else:
                shares = court_shares(row.iloc[0])
                score, band, suggestion = trial_risk(
                    float(forecast_row.iloc[0]["predicted_rate"]),
                    shares,
                    custody,
                    defence,
                    cps,
                    witnesses,
                    floater,
                )
                record = {
                    "court": picked,
                    "date": when.isoformat(),
                    "custody": "Yes" if custody else "No",
                    "defence_confirmed": "Yes" if defence else "No",
                    "cps_served": "Yes" if cps else "No",
                    "witnesses_confirmed": "Yes" if witnesses else "No",
                    "floater": "Yes" if floater else "No",
                    "score": round(100 * score, 1),
                    "band": band,
                    "suggested_action": suggestion,
                }
                trials = load_trials()
                trials.insert(0, record)
                save_trials(trials)
    trials = load_trials()
    if not trials:
        st.info("No trials entered yet. Add one with the form. The table is saved in data/trials.json.")
        return
    latest = trials[0]
    st.markdown(
        f"<p class='band band-{latest['band']}'>{latest['band']} · {latest['score']:.1f}%</p>",
        unsafe_allow_html=True,
    )
    st.write(f"Suggested action: {latest['suggested_action']}")
    st.caption(
        "Witnesses not confirmed, and CPS evidence not served, each add the prosecution/witness share "
        "(reason codes 1-6, 15 and 16). If both are missing, that share is counted twice. "
        "Listed as a floater/backer adds the overlisting share. "
        "A custody case uses the prisoner-not-produced share. "
        "Judge availability stays inside the predicted rate, because the form does not ask about the judge."
    )
    table = pd.DataFrame(trials)
    table = table.rename(
        columns={
            "court": "Court",
            "date": "Date",
            "custody": "Custody",
            "defence_confirmed": "Counsel confirmed",
            "cps_served": "CPS served",
            "witnesses_confirmed": "Witnesses confirmed",
            "floater": "Floater/backer",
            "score": "Score %",
            "band": "Band",
            "suggested_action": "Suggested action",
        }
    )
    st.dataframe(table, hide_index=True, width="stretch")


def draw_allocation(bills):
    st.write(
        "Enter a sitting-day budget for the next 8 quarters. "
        "Courts are funded in order of cases cleared per pound, "
        "and each court stops once the days that return it to its 2019 average are funded."
    )
    budget = st.number_input(
        "Budget over 8 quarters (£)",
        min_value=0,
        max_value=150_000_000,
        value=5_000_000,
        step=1_000_000,
        help="Same time basis as the curve: the cost of sitting the extra days for two years.",
    )
    funded, leftover, curve, per_million = allocate_budget(budget)
    if funded.empty:
        st.info("Nothing is funded at £0. Raise the budget to give the first court its sitting days.")
    else:
        st.dataframe(funded, hide_index=True, width="stretch")
        if leftover > 1:
            st.caption(
                f"{money(leftover)} is unspent. Every funded court has reached the days "
                "that return it to its 2019 average, or the budget ran out on a court with no cap."
            )
    stop_year = float(bills["stop_growth_gbp_per_year"].sum())
    stop_gbp = stop_year * 2.0
    back_gbp = float(bills["back_to_2019_gbp"].sum())
    st.plotly_chart(spend_figure(curve, stop_gbp, back_gbp), width="stretch")
    st.caption(
        "Each step on the curve is £5 million, spent over 8 quarters. "
        f"Stop growth for 2 years is {money(stop_gbp)}, twice the yearly bill of {money(stop_year)}. "
        f"Return to 2019 is {money(back_gbp)} over those same 8 quarters. "
        "The day split is assumed. £3,036 per day is published."
    )
    st.plotly_chart(efficiency_figure(per_million), width="stretch")
    spread = float(per_million["cases_per_1m"].max() - per_million["cases_per_1m"].min())
    st.caption(
        "Cases cleared over 8 quarters for each £1 million of sitting days, on the two-year cost basis. "
        "Court days are an assumed share of the national total, so courts look similar. "
        f"The gap between the highest and lowest court is {spread:.0f} cases per £1 million."
    )


def draw_honesty():
    with st.expander("Model honesty"):
        st.markdown(
            "Both tables are calculated when the page loads. "
            "They are the same checks as `src/simulate.py` and `src/model.py`."
        )
        with st.spinner("Scoring the backlog backtest and the 2024–2026 forecast."):
            backlog, scores = honesty_numbers()
        st.markdown("**Backlog backtest, from 2023Q4, in open cases**")
        show = backlog.copy()
        show["mae_open_cases"] = show["mae_open_cases"].map(lambda v: f"{v:,.1f}")
        st.dataframe(show, hide_index=True, width="stretch")
        st.caption(
            "The stock-flow rule with the real receipts and disposals is close to the published stock. "
            "Holding the last four quarters flat and rolling that forward is not. "
            "Use the action impacts to compare levers, not as a precise caseload forecast."
        )
        st.markdown("**Ineffective-rate forecast, test 2024Q1–2026Q2, in percentage points**")
        rate_table = scores.copy()
        rate_table["mae_pp"] = rate_table["mae_pp"].map(lambda v: f"{v:.2f}")
        rate_table["weighted_mae_pp"] = rate_table["weighted_mae_pp"].map(lambda v: f"{v:.2f}")
        st.dataframe(rate_table, hide_index=True, width="stretch")
        trees = float(scores.loc[scores["model"] == "LightGBM", "weighted_mae_pp"].iloc[0])
        average = float(scores.loc[scores["model"] == "4-quarter average", "weighted_mae_pp"].iloc[0])
        blend = float(scores.loc[scores["model"] == "50/50 blend", "weighted_mae_pp"].iloc[0])
        st.write(
            f"LightGBM alone is {trees - average:+.2f} weighted points versus the four-quarter average "
            "(positive means worse). "
            f"The saved 50/50 blend is {blend - average:+.2f} versus that average. "
            "A few hundredths of a point, on an error of about 4.5 points, is a small edge."
        )
        st.markdown("**Assumptions, all of them labelled**")
        st.markdown(
            """
- One avoided ineffective trial is counted as one extra disposal. Trials and case disposals are different units.
- Per-court sitting days are not published. Each court is given a share of 110,647 national days in 2025-26, in proportion to its disposals. That split is assumed.
- £3,036 per sitting day is published. Every other price in `config/levers.yaml` is a placeholder, including the £0 on overlisting.
- Cause actions assume the default cut in that file (25% unless edited). The cause count itself is from the MoJ table.
- The £ to stop growth in the status line is a yearly bill. The chart marker is that bill for 2 years, on the same 8-quarter axis as Return to 2019.
- The trial score is a heuristic. It is not fitted to whether trials actually cracked.
- The 8-quarter backlog holds each court's last four quarters of receipts and disposals flat.
- The map colour is a blend of a tree model and a four-quarter average, not a measured future rate.
- Returning to the 2019 average is a chosen target. The average itself is calculated from the data.
            """
        )


def _lab_table(ranked):
    """Cases cleared and cases per £1,000, paid levers then the free one."""
    show = ranked.loc[:, ["rank", "label", "cases_cleared", "spend", "cases_per_1k", "section"]].copy()
    show["cases_cleared"] = show["cases_cleared"].map(lambda value: f"{value:,.1f}")
    show["spend"] = show["spend"].map(money)
    show["cases_per_1k"] = show["cases_per_1k"].map(lambda value: "—" if pd.isna(value) else f"{value:.3f}")
    show = show.rename(
        columns={
            "rank": "Rank",
            "label": "Intervention",
            "cases_cleared": "Cases cleared",
            "spend": "Spend over 8 quarters",
            "cases_per_1k": "Cases per £1,000",
            "section": "List",
        }
    )
    return show


def _top_paid(ranked):
    paid = ranked.loc[ranked["section"] == "per_pound"]
    return paid.loc[paid["rank"] == 1].iloc[0]


@st.cache_data
def lab_rank(court, budget, charge, productivity, conversion, cost_scale):
    """One court's ranking. Cached so a slider move does not recompute everyone."""
    return decide(
        court=court,
        budget=budget,
        panel=panel(),
        levers=levers(),
        sitting_charge=charge,
        sitting_productivity=productivity,
        disposal_conversion=conversion,
        assumed_cost_scale=cost_scale,
    )


@st.cache_data
def lab_recs(budget, charge, productivity, conversion, cost_scale):
    """Top paid lever at every court under one assumption set."""
    ranked = decide(
        budget=budget,
        panel=panel(),
        levers=levers(),
        sitting_charge=charge,
        sitting_productivity=productivity,
        disposal_conversion=conversion,
        assumed_cost_scale=cost_scale,
    )
    return recommendations(ranked)


def _stability(central, scenario):
    left = central.rename(
        columns={
            "lever": "central_lever",
            "label": "central_label",
            "cases_per_1k": "central_per_1k",
        }
    )[["court", "central_lever", "central_label", "central_per_1k"]]
    right = scenario.rename(
        columns={
            "lever": "scenario_lever",
            "label": "scenario_label",
            "cases_per_1k": "scenario_per_1k",
        }
    )[["court", "scenario_lever", "scenario_label", "scenario_per_1k"]]
    out = left.merge(right, on="court", how="inner")
    out["stable"] = out["central_lever"] == out["scenario_lever"]
    return out


@st.cache_data
def lab_presets(budget):
    """Named assumption sets. Not probabilities, and not causal estimates."""
    central = lab_recs(budget, "horizon", 1.0, 1.0, 1.0)
    sets = [
        ("Charge once (original)", "once", 1.0, 1.0, 1.0),
        ("Conservative", "horizon", 0.5, 0.5, 2.0),
        ("Cheaper placeholder prices", "horizon", 1.0, 1.0, 0.5),
    ]
    rows = []
    for label, charge, productivity, conversion, scale in sets:
        compared = _stability(central, lab_recs(budget, charge, productivity, conversion, scale))
        moved = compared.loc[~compared["stable"], "scenario_label"].value_counts()
        rows.append(
            {
                "Assumption set": label,
                "Courts unchanged": int(compared["stable"].sum()),
                "Courts that flip": int((~compared["stable"]).sum()),
                "Most common new top": "—" if moved.empty else f"{moved.index[0]} ({int(moved.iloc[0])})",
            }
        )
    return rows


def draw_decision_lab(court):
    """Change the unmeasured rates and see if the top purchase survives."""
    st.write(
        "The question on this tab: if an assumption changes, does Courtfall still "
        "recommend the same purchase? Nothing here is a confidence interval, and "
        "none of the lever effects have been checked against a real before-and-after."
    )
    st.markdown(
        """
**Observed.** Receipts, disposals, open cases, and ineffective-trial counts, from the MoJ court tables.

**Published.** £3,036 per sitting day (HMCTS 2022-23, parliamentary question 4727, 5 December 2023). 110,647 national sitting days in 2025-26.

**Assumed, and editable below.** How national days are split across courts. Placeholder prices other than £3,036. How much an extra sitting day raises disposals. How many avoided ineffective trials become case disposals.

**Backtest, not a causal test.** Model honesty checks whether the stock-flow and the rate model match later published numbers. It does not show that buying a lever caused those numbers.
        """
    )

    budget = st.number_input(
        "Budget over 8 quarters, offered to each lever",
        min_value=0,
        max_value=1_000_000,
        value=100_000,
        step=10_000,
        help="The same cheque for every lever. Cause levers already spent this over 8 quarters. Sitting days now do too, unless you switch back to the original one-year charge.",
    )
    charge_label = st.radio(
        "Sitting-day cost horizon",
        ["Charge both years", "Charge once (original)"],
        horizontal=True,
        help="Charge both years spreads the budget across the 8 quarters. Charge once is the original engine: it buys a year's days and then keeps that higher rate for two years while recording only the one-year cost.",
    )
    charge = "once" if charge_label.startswith("Charge once") else "horizon"
    productivity = st.slider(
        "Disposal gain from extra sitting days",
        min_value=0.0,
        max_value=1.0,
        value=1.0,
        step=0.05,
        help="1 means an extra 1% of sitting days raises disposals by 1%. 0.5 means half that gain. This is not estimated from a sitting-day experiment.",
    )
    conversion = st.slider(
        "Avoided trials counted as disposals",
        min_value=0.0,
        max_value=1.0,
        value=1.0,
        step=0.05,
        help="1 is the working assumption: one avoided ineffective trial, one extra disposal. 0.5 counts only half of them. Trials and case disposals are different units.",
    )
    cost_scale = st.slider(
        "Placeholder prices, relative to the file",
        min_value=0.5,
        max_value=2.0,
        value=1.0,
        step=0.25,
        help="Scales the assumed prices in config/levers.yaml. The published £3,036 is not scaled. Overlisting stays at £0.",
    )

    central = lab_rank(court, budget, "horizon", 1.0, 1.0, 1.0)
    current = lab_rank(court, budget, charge, productivity, conversion, cost_scale)
    before = _top_paid(central)
    after = _top_paid(current)
    def _rate(row):
        if pd.isna(row["cases_per_1k"]):
            return "no £ spent"
        return f"{float(row['cases_per_1k']):.3f} per £1,000"

    flipped = before["lever"] != after["lever"]
    if flipped:
        st.warning(
            f"The top purchase flips. Under the central assumptions it is {before['label']} "
            f"({before['cases_cleared']:.1f} cases, {_rate(before)}). "
            f"With the settings above it is {after['label']} "
            f"({after['cases_cleared']:.1f} cases, {_rate(after)})."
        )
    else:
        st.success(
            f"The top purchase stays {after['label']} "
            f"({after['cases_cleared']:.1f} cases, {_rate(after)}). "
            "That is still an assumption-based ranking, not a measured effect."
        )

    left, right = st.columns(2)
    left.markdown("**Central assumptions**")
    left.caption("Both years charged. Proportional sitting days. Every avoided trial counted. File prices.")
    left.dataframe(_lab_table(central), hide_index=True, width="stretch")
    right.markdown("**Settings on this tab**")
    right.caption("Same budget and court. Only the controls above have changed.")
    right.dataframe(_lab_table(current), hide_index=True, width="stretch")

    options = current["label"].tolist()
    lever_key = f"lab_lever_{court}"
    if lever_key not in st.session_state or st.session_state[lever_key] not in options:
        st.session_state[lever_key] = after["label"]
    picked = st.selectbox("Intervention to plot", options, key=lever_key)
    chosen = current.loc[current["label"] == picked].iloc[0]
    path = simulate(
        court,
        quarters=8,
        levers={chosen["lever"]: float(chosen["effect"])},
        panel=panel(),
        sitting_productivity=productivity,
        disposal_conversion=conversion,
    )
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=path["period"],
            y=path["open_baseline"],
            name="Baseline, do nothing",
            mode="lines+markers",
            line=dict(color="#9F1239", width=3),
        )
    )
    figure.add_trace(
        go.Scatter(
            x=path["period"],
            y=path["open_scenario"],
            name=f"{picked} ({money(chosen['spend'])} over 8 quarters)",
            mode="lines+markers",
            line=dict(color="#0369A1", width=3),
        )
    )
    layout = chart_layout(f"{court}: open cases, baseline versus the selected intervention")
    layout["height"] = 420
    figure.update_layout(**layout)
    figure.update_yaxes(title_text="Open cases")
    st.plotly_chart(figure, width="stretch")
    end_gap = float(path["open_baseline"].iloc[-1] - path["open_scenario"].iloc[-1])
    st.caption(
        f"End of the horizon: {path['open_scenario'].iloc[-1]:,.0f} open cases, "
        f"against {path['open_baseline'].iloc[-1]:,.0f} if nothing is done "
        f"({end_gap:,.1f} cases cleared). "
        "Receipts and disposals are the last four quarters, held flat. "
        "That is the same projection the backlog backtest scores. It is not evidence the lever works."
    )

    st.markdown("**All 68 Crown Courts**")
    st.caption(
        "Central is the corrected horizon charge at the slider defaults. "
        "Each other row changes one assumption set. A flip means the top paid lever changes. "
        "Counts are not probabilities."
    )
    compared = _stability(
        lab_recs(budget, "horizon", 1.0, 1.0, 1.0),
        lab_recs(budget, charge, productivity, conversion, cost_scale),
    )
    unchanged = int(compared["stable"].sum())
    st.write(
        f"With the settings above, {unchanged} of {len(compared)} courts keep the same top purchase. "
        f"{len(compared) - unchanged} change."
    )
    moved = compared.loc[~compared["stable"], ["court", "central_label", "scenario_label", "central_per_1k", "scenario_per_1k"]]
    if moved.empty:
        st.caption("No court changes its top paid lever under these settings.")
    else:
        show = moved.copy()
        show["central_per_1k"] = show["central_per_1k"].map(lambda value: f"{value:.3f}")
        show["scenario_per_1k"] = show["scenario_per_1k"].map(lambda value: f"{value:.3f}")
        show = show.rename(
            columns={
                "court": "Court",
                "central_label": "Central top",
                "scenario_label": "Top under these settings",
                "central_per_1k": "Central cases per £1,000",
                "scenario_per_1k": "Cases per £1,000 now",
            }
        )
        st.dataframe(show, hide_index=True, width="stretch")

    preset_rows = lab_presets(int(budget))
    st.markdown("**Preset stresses, same budget, every court**")
    st.caption(
        "Conservative: half the sitting-day gain, half the avoided trials counted as disposals, "
        "placeholder prices doubled. Cheaper prices: placeholder prices halved. "
        "The published day cost stays £3,036 in every row."
    )
    st.dataframe(pd.DataFrame(preset_rows), hide_index=True, width="stretch")


def draw_live(court):
    """Eight-quarter path. Every slider is an argument to run_scenario()."""
    st.write(
        "Baseline receipts and disposals stay on the last four quarters. "
        "Moving a control recalculates the scenario. "
        "Scenario assumption — causal effect not established."
    )
    sitting = st.slider("Extra sitting days, percent of assumed annual days", 0, 50, 0, 1)
    overlisting = st.slider("Reduce overlisting, percent of those trials", 0, 100, 0, 1)
    prosecution = st.slider("Reduce prosecution and witness issues, percent", 0, 100, 0, 1)
    prisoner = st.slider("Reduce prisoner not produced, percent", 0, 100, 0, 1)
    defence = st.slider("Reduce defence advocate failures, percent", 0, 100, 0, 1)
    judge = st.slider("Reduce judge availability failures, percent", 0, 100, 0, 1)
    productivity = st.slider("Disposal gain from extra sitting days", 0.0, 1.0, 1.0, 0.05)
    conversion = st.slider("Avoided trials counted as disposals", 0.0, 1.0, 1.0, 0.05)
    cost_scale = st.slider("Placeholder prices, relative to the file", 0.5, 2.0, 1.0, 0.25)
    charge_label = st.radio(
        "Sitting-day bill",
        ["Full eight quarters", "One-year charge, kept for comparison"],
        horizontal=True,
    )
    charge = "once" if charge_label.startswith("One-year") else "horizon"
    report = run_scenario(
        court,
        panel(),
        levers={
            "sitting_days": sitting / 100,
            "overlisting": overlisting / 100,
            "prosecution": prosecution / 100,
            "prisoner_not_produced": prisoner / 100,
            "defence_advocate": defence / 100,
            "judge": judge / 100,
        },
        sitting_productivity=productivity,
        disposal_conversion=conversion,
        assumed_cost_scale=cost_scale,
        sitting_charge=charge,
    )
    left, mid, right = st.columns(3)
    left.metric("Cases cleared versus baseline", f"{report['cases_cleared']:.1f}")
    mid.metric("Spend over 8 quarters", money(report["spend_8q"]))
    right.metric("Backlog difference", f"{report['backlog_difference']:.1f}")
    st.caption(
        f"Open now {report['open_now']:,.0f}. "
        f"Baseline after 8 quarters {report['end_baseline']:,.0f}. "
        f"Scenario after 8 quarters {report['end_scenario']:,.0f}. "
        f"Extra sitting days {report['days_per_year']:,.0f} a year."
    )
    frame = pd.DataFrame(report["series"])
    figure = go.Figure()
    figure.add_trace(go.Scatter(x=frame["period"], y=frame["open_baseline"], name="Baseline", line=dict(color="#EF4444")))
    figure.add_trace(go.Scatter(x=frame["period"], y=frame["open_scenario"], name="Scenario", line=dict(color="#10B981")))
    figure.update_layout(height=360, margin=dict(l=8, r=8, t=24, b=8), legend=dict(orientation="h"))
    st.plotly_chart(figure, width="stretch")
    for row in report["levers"]:
        if row["reason"]:
            st.caption(f"{row['label']}: {row['reason']}")


def main():
    st.set_page_config(page_title="Courtfall", layout="wide")
    apply_theme()
    st.title("Courtfall")
    st.write("Pick a court on the map. Then open the job for that role.")

    latest, rows = latest_rows()
    ranked, bills, _, _ = planning_tables()
    period, points = map_frame()
    if "court_box" not in st.session_state:
        st.session_state.court_box = "Snaresbrook"

    st.caption(
        f"Open cases in {period}. Colour is the predicted ineffective rate for the next quarter. "
        "Larger circles are more open cases. Both numbers are in the tooltip."
    )
    event = draw_map(points)
    clicked = clicked_court(event)
    if clicked and clicked != st.session_state.get("last_click"):
        st.session_state.last_click = clicked
        st.session_state.court_box = clicked
        st.rerun()
    courts = sorted(points["court"].unique())
    court = st.selectbox("Court", courts, key="court_box")

    national_open = float(rows["open"].sum())
    per_year = float(bills["stop_growth_gbp_per_year"].sum())
    back = float(bills["back_to_2019_gbp"].sum())
    st.caption(
        f"England and Wales: {national_open:,.0f} open cases. "
        f"{money(per_year)} a year to stop growth. "
        f"{money(back)} over 8 quarters to return to 2019. "
        "The day split behind the two money figures is assumed. "
        "£3,036 per sitting day is published: HMCTS 2022-23, parliamentary question 4727, "
        "answered 5 December 2023."
    )

    forecast = predictions().loc[predictions()["court"] == court].iloc[0]
    latest_row = rows.loc[rows["court"] == court].iloc[0]
    plan, risk, allocation, lab, live = st.tabs(
        ["Court action plan", "Trial risk check", "National allocation", "Decision Lab", "Live simulation"]
    )
    with plan:
        st.subheader(court)
        st.write("Actions for the resident judge.")
        draw_action_plan(court, bills, latest_row, forecast, ranked)
    with risk:
        st.subheader("Trial risk check")
        st.write("For the listing officer.")
        draw_risk(court, latest_row, forecast, courts)
    with allocation:
        st.subheader("National allocation")
        st.write("For HMCTS.")
        draw_allocation(bills)
    with lab:
        st.subheader("Decision Lab")
        st.write("For anyone asking whether the ranking is an artefact of the assumptions.")
        draw_decision_lab(court)
    with live:
        st.subheader("Live simulation")
        st.write("The same calculation as the API. Nothing on this tab is cached separately from its inputs.")
        draw_live(court)
    draw_honesty()


if __name__ == "__main__":
    main()
