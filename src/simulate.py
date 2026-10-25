"""Backlog simulator. One court, quarter by quarter.

The MoJ table has open cases, receipts, and disposals on the SAME row.
That row is the end of the quarter. The rule that matches the table is:

    open[t] = open[t - 1] + receipts[t] - disposals[t]

In words: stock at the end of this quarter = stock at the end of last
quarter + cases received this quarter - cases finished this quarter.

Using last quarter's flows to predict this quarter's stock does not match
the published numbers. See backtest().

Forecast, from the last quarter we treat as known:
    receipts  = average of the last 4 quarters
    disposals = average of the last 4 quarters
Those two averages are held flat for the whole horizon. They are not
re-estimated as the forecast moves forward.

Scenario, on top of that baseline:
    extra sitting days: disposals * (1 + fraction * sitting_productivity)
    a cause lever: remove that fraction of this cause's ineffective trials,
    multiply by disposal_conversion, and add those trials to disposals,
    every quarter.

Both multipliers default to 1, which is the original simulator.
sitting_productivity is the assumed disposal gain per unit of extra days.
disposal_conversion is the assumed share of avoided ineffective trials
that become extra case disposals. Neither is estimated from an experiment.

Assumption, stated here because it is not in the data: at the default
conversion, 1 avoided ineffective trial = 1 extra disposal. Ineffective
trials are trials, disposals are cases. They are not the same unit.
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "clean" / "court_quarter.parquet"

# Cause levers. sitting_days is separate: it scales disposals, it does not
# remove a slice of ineffective trials.
CAUSE_LEVERS = [
    "prosecution",
    "overlisting",
    "defence_advocate",
    "prisoner_not_produced",
    "judge",
]


def load_panel(path=DATA):
    """Read the court x quarter table. period is a string like '2026Q2'."""
    df = pd.read_parquet(path)
    df["period"] = df["period"].astype(str)
    return df.sort_values(["court", "period"]).reset_index(drop=True)


def add_quarters(period, k):
    """'2026Q2' + 1 quarter = '2026Q3'. k can be negative."""
    year = int(period[:4])
    q = int(period[-1]) - 1 + k
    year += q // 4
    q = q % 4
    return f"{year}Q{q + 1}"


def _last4(history, column):
    """Mean of the last 4 rows. Uses fewer rows if the court is short."""
    return float(history[column].tail(4).mean())


def simulate(
    court,
    quarters=8,
    levers=None,
    as_of=None,
    panel=None,
    sitting_productivity=1.0,
    disposal_conversion=1.0,
):
    """Baseline vs scenario open cases for one court.

    Parameters
    ----------
    court : str
        Court name, as in the parquet file. Example: "Snaresbrook".
    quarters : int
        How many future quarters to project. Default 8.
    levers : dict
        Fractions, not percentages. Missing keys mean 0.
        sitting_days=0.05 means disposals are 5% higher when
        sitting_productivity is 1.
        overlisting=0.25 means 25% of overlisting ineffective trials
        are avoided. At disposal_conversion 1, all of those are added
        to disposals.
        An empty dict is the do-nothing path: scenario equals baseline.
    sitting_productivity : float
        Assumed disposal gain per unit of the sitting-day fraction.
        1 is the original proportional rule. 0.5 means an extra 1% of
        days raises disposals by 0.5%. Not estimated from outcomes.
    disposal_conversion : float
        Assumed share of avoided ineffective trials counted as extra
        disposals. 1 is the original assumption. Not a measured effect.
    as_of : str or None
        Last quarter treated as already known, e.g. "2023Q4".
        Default: the court's latest quarter. Rows after as_of are ignored,
        so a backtest cannot see the future.
    panel : DataFrame or None
        Pass the loaded table to avoid reading the file again.

    Returns
    -------
    DataFrame
        Row 0 is the known starting stock (actual open at as_of).
        Rows 1..quarters are the forecast.
        open_baseline uses unadjusted disposals.
        open_scenario uses lever-adjusted disposals.
    """
    if levers is None:
        levers = {}
    if panel is None:
        panel = load_panel()

    history = panel.loc[panel["court"] == court].sort_values("period")
    if history.empty:
        raise ValueError(f"Unknown court: {court}")
    if as_of is None:
        as_of = history["period"].iloc[-1]
    known = history.loc[history["period"] <= as_of]
    if known.empty:
        raise ValueError(f"No rows for {court} at or before {as_of}")

    receipts = _last4(known, "receipts")
    disposals = _last4(known, "disposals")
    productivity = float(sitting_productivity)
    conversion = float(disposal_conversion)
    if productivity < 0 or conversion < 0:
        raise ValueError("sitting_productivity and disposal_conversion must be zero or positive")

    # Sitting days scale the normal disposal rate. Cause levers add trials
    # on top. They are not scaled again, so the two effects are not double counted.
    sitting = float(levers.get("sitting_days", 0.0) or 0.0) * productivity
    freed = 0.0
    freed_by_lever = {}
    for name in CAUSE_LEVERS:
        cut = float(levers.get(name, 0.0) or 0.0)
        # Average ineffective trials of this cause per quarter, last 4 quarters.
        base_n = _last4(known, f"{name}_n")
        part = base_n * cut * conversion
        freed_by_lever[name] = part
        freed += part
    disposals_scenario = disposals * (1.0 + sitting) + freed

    open_baseline = float(known["open"].iloc[-1])
    open_scenario = open_baseline
    start = known["period"].iloc[-1]

    rows = [
        {
            "court": court,
            "step": 0,
            "period": start,
            "receipts": pd.NA,
            "disposals_baseline": pd.NA,
            "disposals_scenario": pd.NA,
            "trials_freed": pd.NA,
            "open_baseline": open_baseline,
            "open_scenario": open_scenario,
        }
    ]
    for step in range(1, quarters + 1):
        # Same rule as the table: this quarter's flows update this quarter's stock.
        open_baseline = open_baseline + receipts - disposals
        open_scenario = open_scenario + receipts - disposals_scenario
        rows.append(
            {
                "court": court,
                "step": step,
                "period": add_quarters(start, step),
                "receipts": receipts,
                "disposals_baseline": disposals,
                "disposals_scenario": disposals_scenario,
                "trials_freed": freed,
                "open_baseline": open_baseline,
                "open_scenario": open_scenario,
            }
        )

    out = pd.DataFrame(rows)
    for name, part in freed_by_lever.items():
        out[f"freed_{name}"] = part
        out.loc[out["step"] == 0, f"freed_{name}"] = pd.NA
    return out


def _accounting_error(panel, start):
    """How far published open is from the stock-flow rule, using real flows.

    pred[t] = open[t-1] + receipts[t] - disposals[t]
    Returns the mean absolute error on quarters after `start`.
    """
    df = panel.sort_values(["court", "period"]).copy()
    df["open_prev"] = df.groupby("court")["open"].shift(1)
    df["pred"] = df["open_prev"] + df["receipts"] - df["disposals"]
    # The other timing: flows from the previous quarter. This is the rule
    # people write as open[t+1] = open[t] + receipts[t] - disposals[t]
    # when t is the previous row. It does not fit this table.
    grouped = df.groupby("court")
    df["pred_prev_flows"] = (
        df["open_prev"] + grouped["receipts"].shift(1) - grouped["disposals"].shift(1)
    )
    future = df.loc[df["period"] > start]
    same = (future["open"] - future["pred"]).abs().mean()
    other = (future["open"] - future["pred_prev_flows"]).abs().mean()
    return float(same), float(other)


def _one_step_mae(panel, start):
    """One-quarter-ahead error. Uses the actual opening stock each quarter.

    This does not accumulate. It only asks: was last-4 receipts minus
    last-4 disposals close to the real change in open cases?
    """
    errors = []
    for _, history in panel.groupby("court", sort=False):
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
            errors.append(abs(predicted - float(history.at[i, "open"])))
    if not errors:
        return float("nan")
    return float(sum(errors) / len(errors))


def backtest(start="2023Q4", panel=None):
    """Project from `start` with no levers, and compare with later actual open.

    This tests simulate() as it is written: the last-4 averages are frozen
    at `start` and held flat. It does not update them each quarter.

    Prints three errors, in open cases:
      1. Frozen forecast. What simulate() itself does over 2024–2026.
      2. Accounting gap. Actual receipts and disposals, same rule.
      3. One-step forecast. Last-4 averages, but starting from the real
         stock each quarter so errors do not pile up.

    Returns the court-quarter detail behind (1).
    """
    if panel is None:
        panel = load_panel()

    periods_after = sorted(panel.loc[panel["period"] > start, "period"].unique())
    if not periods_after:
        raise ValueError(f"No quarters after {start}")

    pieces = []
    for court in sorted(panel["court"].unique()):
        history = panel.loc[panel["court"] == court]
        if start not in set(history["period"]):
            continue
        simulated = simulate(
            court,
            quarters=len(periods_after),
            levers={},
            as_of=start,
            panel=panel,
        )
        simulated = simulated.loc[simulated["step"] > 0]
        actual = history.loc[
            history["period"].isin(periods_after), ["period", "open"]
        ]
        merged = simulated.merge(actual, on="period", how="inner")
        merged["abs_err"] = (merged["open_baseline"] - merged["open"]).abs()
        pieces.append(merged)

    detail = pd.concat(pieces, ignore_index=True)
    per_court = detail.groupby("court")["abs_err"].mean().sort_values()
    by_period = detail.groupby("period")[["open_baseline", "open"]].sum()
    by_period["abs_err"] = (by_period["open_baseline"] - by_period["open"]).abs()

    account_mae, prev_flow_mae = _accounting_error(panel, start)
    one_step = _one_step_mae(panel, start)
    frozen = float(detail["abs_err"].mean())

    print(
        f"Backtest from {start}: {detail['court'].nunique()} courts, "
        f"{detail['period'].nunique()} quarters, {len(detail)} court-quarters"
    )
    print(f"Frozen last-4 forecast MAE:        {frozen:,.1f} open cases")
    print(
        f"  median court: {per_court.median():,.1f}    "
        f"best {per_court.index[0]} {per_court.iloc[0]:,.1f}    "
        f"worst {per_court.index[-1]} {per_court.iloc[-1]:,.1f}"
    )
    print("National open cases, simulated vs actual (sums of courts):")
    for period, row in by_period.iterrows():
        print(
            f"  {period}   sim {row['open_baseline']:,.0f}   "
            f"actual {row['open']:,.0f}   gap {row['abs_err']:,.0f}"
        )
    print(f"Accounting MAE, actual flows:       {account_mae:,.1f} open cases")
    print(f"Accounting MAE, previous-quarter flows: {prev_flow_mae:,.1f} open cases")
    print(f"One-step last-4 MAE (no pile-up):   {one_step:,.1f} open cases")
    return detail


def forecast_errors(panel, start, horizon, court=None):
    """Frozen last-4 forecast from `start`, compared with later actual open cases.

    Uses only rows at or before `start` for the forecast. Later rows are the
    outcome. Sitting-day allocations are not an input.
    """
    horizon = int(horizon)
    if horizon < 1:
        raise ValueError("horizon must be at least 1 quarter")
    periods_after = sorted(period for period in panel["period"].unique() if period > start)
    periods_after = periods_after[:horizon]
    if not periods_after:
        raise ValueError(f"No quarters after {start}")
    courts = [court] if court else sorted(panel["court"].unique())
    pieces = []
    for name in courts:
        history = panel.loc[panel["court"] == name]
        if history.empty:
            raise ValueError(f"Unknown court: {name}")
        if start not in set(history["period"]):
            continue
        simulated = simulate(
            name,
            quarters=len(periods_after),
            levers={},
            as_of=start,
            panel=panel,
        )
        simulated = simulated.loc[simulated["step"] > 0]
        actual = history.loc[history["period"].isin(periods_after), ["period", "open"]]
        merged = simulated.merge(actual, on="period", how="inner")
        merged["abs_err"] = (merged["open_baseline"] - merged["open"]).abs()
        pieces.append(merged)
    if not pieces:
        raise ValueError(f"No court has {start} in the panel")
    detail = pd.concat(pieces, ignore_index=True)
    by_step = (
        detail.groupby("step")["abs_err"].mean().rename("mae").reset_index()
    )
    return detail, by_step


def _check():
    """Small checks. These lock the formulas, they are not a model score."""
    panel = load_panel()
    base = simulate("Snaresbrook", quarters=8, levers={}, panel=panel)
    same = simulate("Snaresbrook", quarters=8, levers={"overlisting": 0}, panel=panel)
    if not base["open_baseline"].equals(same["open_scenario"]):
        raise AssertionError("A zero lever must match the do-nothing path")

    bumped = simulate("Snaresbrook", quarters=2, levers={"sitting_days": 0.10}, panel=panel)
    expected = float(bumped["disposals_baseline"].iloc[1]) * 1.10
    got = float(bumped["disposals_scenario"].iloc[1])
    if abs(got - expected) > 1e-6:
        raise AssertionError(f"Sitting days did not scale disposals: {got} vs {expected}")

    # First future stock = start + receipts - disposals.
    step1 = float(base["open_baseline"].iloc[0]) + float(base["receipts"].iloc[1]) - float(
        base["disposals_baseline"].iloc[1]
    )
    if abs(step1 - float(base["open_baseline"].iloc[1])) > 1e-6:
        raise AssertionError("Stock-flow step does not match the formula")

    # The new multipliers default to the original simulator.
    half_days = simulate(
        "Snaresbrook",
        quarters=2,
        levers={"sitting_days": 0.10},
        sitting_productivity=0.5,
        panel=panel,
    )
    expected_half = float(half_days["disposals_baseline"].iloc[1]) * 1.05
    if abs(float(half_days["disposals_scenario"].iloc[1]) - expected_half) > 1e-6:
        raise AssertionError("Sitting productivity did not scale the disposal gain")
    over = simulate("Snaresbrook", quarters=1, levers={"overlisting": 0.25}, panel=panel)
    over_half = simulate(
        "Snaresbrook",
        quarters=1,
        levers={"overlisting": 0.25},
        disposal_conversion=0.5,
        panel=panel,
    )
    if abs(float(over_half["trials_freed"].iloc[1]) * 2 - float(over["trials_freed"].iloc[1])) > 1e-6:
        raise AssertionError("Disposal conversion did not scale avoided trials")

    # as_of must ignore later rows. A forecast from 2023Q4 cannot use 2026 flows.
    early = simulate("Snaresbrook", quarters=1, as_of="2023Q4", panel=panel)
    known = panel.loc[
        (panel["court"] == "Snaresbrook") & (panel["period"] <= "2023Q4")
    ].sort_values("period")
    if abs(float(early["receipts"].iloc[1]) - _last4(known, "receipts")) > 1e-6:
        raise AssertionError("as_of leaked quarters after the cutoff")
    print("Checks passed.")
    return panel


if __name__ == "__main__":
    panel = _check()
    print()
    backtest(panel=panel)
    print()
    snaresbrook = simulate(
        "Snaresbrook",
        quarters=8,
        levers={"overlisting": 0.25},
        panel=panel,
    )
    columns = [
        "period",
        "receipts",
        "disposals_baseline",
        "disposals_scenario",
        "trials_freed",
        "open_baseline",
        "open_scenario",
    ]
    print("Snaresbrook, cut 25% of overlisting, next 8 quarters:")
    print(snaresbrook[columns].to_string(index=False))
