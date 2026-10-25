"""Predict each court's ineffective-trial rate one quarter ahead.

The target on a row is next quarter's ineffective_rate. Every input on that
row is already known: lags of the rate, the average of the last four
quarters, the latest lever shares, open cases, receipts, the calendar
quarter being predicted, and a flag that is 1 for 2020, 2021, and 2022.

Split by time. Train on targets up to 2023Q4. Test on 2024Q1–2026Q2.
Nothing is shuffled. Rows whose target quarter had fewer than 10 trials
listed are left out of the fit and the score. Small quarters are noisy.

The published comparison is:
    last quarter's rate
    the average of the last four quarters
    LightGBM alone
    a 50/50 blend of LightGBM and that four-quarter average

The blend is the number that gets saved. SHAP drivers describe the
LightGBM half only. The other half of the blend is the four-quarter
average, which has no drivers.

Training rows are weighted by how many trials were listed in the target
quarter, so a large court counts for more than a one-trial court.
"""

import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import shap

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.simulate import add_quarters, load_panel

OUT_PATH = ROOT / "data" / "clean" / "predictions.parquet"
MIN_LISTED = 10

# Names are plain on purpose. They are what SHAP will print.
FEATURES = [
    "last_quarter_rate",
    "rate_two_quarters_ago",
    "rate_three_quarters_ago",
    "rate_four_quarters_ago",
    "four_quarter_average",
    "prosecution_share",
    "overlisting_share",
    "defence_advocate_share",
    "prisoner_not_produced_share",
    "judge_share",
    "open_cases",
    "receipts",
    "quarter",
    "covid_2020_2022",
]
SHARE_COLUMNS = [
    "prosecution_share",
    "overlisting_share",
    "defence_advocate_share",
    "prisoner_not_produced_share",
    "judge_share",
]


def build_frame(panel):
    """One row per court-quarter, with lags and the next quarter's rate.

    Lag 1 is this quarter's rate. The target is the following quarter.
    A feature never looks past the row it sits on.
    """
    frame = panel.sort_values(["court", "period"]).copy()
    grouped = frame.groupby("court", sort=False)
    rate = grouped["ineffective_rate"]
    frame["last_quarter_rate"] = frame["ineffective_rate"]
    frame["rate_two_quarters_ago"] = rate.shift(1)
    frame["rate_three_quarters_ago"] = rate.shift(2)
    frame["rate_four_quarters_ago"] = rate.shift(3)
    frame["four_quarter_average"] = rate.transform(
        lambda series: series.rolling(4, min_periods=4).mean()
    )
    frame["open_cases"] = frame["open"]
    frame["target"] = rate.shift(-1)
    frame["target_period"] = grouped["period"].shift(-1)
    frame["target_listed"] = grouped["listed"].shift(-1)
    for column in SHARE_COLUMNS:
        frame[column] = frame[column].fillna(0.0)
    # The first quarters of each court do not have four lags yet.
    ready = frame.dropna(
        subset=["rate_four_quarters_ago", "four_quarter_average"]
    ).copy()
    return ready


def _mark_target_calendar(frame):
    """Quarter number and the 2020–2022 flag, taken from the target period."""
    out = frame.copy()
    out["quarter"] = out["target_period"].str[-1].astype(int)
    year = out["target_period"].str[:4].astype(int)
    out["covid_2020_2022"] = year.between(2020, 2022).astype(int)
    return out


def supervised_rows(frame):
    """Rows that have a real next quarter to learn from."""
    known = frame.dropna(subset=["target", "target_listed", "target_period"]).copy()
    known = known.loc[known["target_listed"] >= MIN_LISTED]
    return _mark_target_calendar(known)


def live_rows(frame):
    """The latest quarter of each court, used to predict the quarter after it."""
    latest = frame.groupby("court", sort=False).tail(1).copy()
    latest["target_period"] = latest["period"].map(lambda period: add_quarters(period, 1))
    return _mark_target_calendar(latest)


def time_split(frame):
    """Train on targets through 2023Q4. Test on 2024Q1–2026Q2. No shuffle."""
    train = frame.loc[frame["target_period"] <= "2023Q4"].copy()
    test = frame.loc[
        (frame["target_period"] >= "2024Q1") & (frame["target_period"] <= "2026Q2")
    ].copy()
    if train.empty or test.empty:
        raise ValueError("Time split produced an empty train or test set")
    if train["target_period"].max() > "2023Q4":
        raise ValueError("Training rows leak past 2023")
    if test["target_period"].min() < "2024Q1":
        raise ValueError("Test rows start before 2024")
    return train, test


def make_model():
    """A small gradient-boosted tree. Defaults are left simple on purpose."""
    return lgb.LGBMRegressor(
        n_estimators=200,
        learning_rate=0.05,
        num_leaves=15,
        min_child_samples=30,
        random_state=7,
        verbose=-1,
    )


def absolute_error(actual, predicted, weight=None):
    """Mean absolute error. Pass trial counts to weight large courts more."""
    gap = np.abs(np.asarray(actual, dtype=float) - np.asarray(predicted, dtype=float))
    if weight is None:
        return float(gap.mean())
    weight = np.asarray(weight, dtype=float)
    return float(np.sum(weight * gap) / np.sum(weight))


def score_table(test, model_prediction):
    """Four forecasts, same test rows, unweighted and trial-weighted."""
    actual = test["target"].to_numpy()
    weight = test["target_listed"].to_numpy()
    forecasts = {
        "Last quarter": test["last_quarter_rate"].to_numpy(),
        "4-quarter average": test["four_quarter_average"].to_numpy(),
        "LightGBM": model_prediction,
        "50/50 blend": BLEND_WEIGHT * model_prediction
        + (1.0 - BLEND_WEIGHT) * test["four_quarter_average"].to_numpy(),
    }
    rows = []
    for name, predicted in forecasts.items():
        rows.append(
            {
                "model": name,
                "mae_pp": 100 * absolute_error(actual, predicted),
                "weighted_mae_pp": 100 * absolute_error(actual, predicted, weight),
            }
        )
    return pd.DataFrame(rows)


def top_drivers(shap_row, feature_names, n=3):
    """The n features with the largest absolute SHAP value on one row."""
    order = np.argsort(-np.abs(shap_row))[:n]
    names = [feature_names[i] for i in order]
    values = [float(shap_row[i]) for i in order]
    return names, values


def shap_matrix(model, features):
    """Tree SHAP values, one column per feature. The bias column is dropped."""
    explainer = shap.TreeExplainer(model)
    values = explainer.shap_values(features)
    if hasattr(values, "values"):
        values = values.values
    values = np.asarray(values)
    if values.ndim == 3:
        # Some versions return (classes, rows, features) for classifiers.
        values = values[0]
    return values


def predict_next(model, live):
    """Blend for the coming quarter, plus the top three SHAP drivers."""
    features = live[FEATURES]
    model_rate = model.predict(features)
    average = live["four_quarter_average"].to_numpy()
    blend = BLEND_WEIGHT * model_rate + (1.0 - BLEND_WEIGHT) * average
    values = shap_matrix(model, features)
    records = []
    for i, (_, row) in enumerate(live.iterrows()):
        names, shap_values = top_drivers(values[i], FEATURES)
        records.append(
            {
                "court": row["court"],
                "period": row["target_period"],
                "predicted_rate": float(blend[i]),
                "model_rate": float(model_rate[i]),
                "four_quarter_average": float(average[i]),
                "driver_1": names[0],
                "driver_2": names[1],
                "driver_3": names[2],
                "shap_1": shap_values[0],
                "shap_2": shap_values[1],
                "shap_3": shap_values[2],
            }
        )
    return pd.DataFrame(records)


# Fixed rule. Not estimated by scoring the 2024–2026 test window.
BLEND_WEIGHT = 0.5
MODEL_VERSION = (
    "LightGBM n_estimators=200 learning_rate=0.05 num_leaves=15 "
    "min_child_samples=30 random_state=7; "
    "blend weight 0.5 fixed, not estimated on the test window"
)


def evaluate_rate(panel, cutoff, horizon_quarters=8):
    """Train on targets at or before `cutoff`, then score later quarters.

    Each test row is one step ahead. Its features are the rates and counts
    published in that feature quarter, not a recursive forecast. Training
    never sees a target after the cutoff. The blend weight is BLEND_WEIGHT.
    """
    cutoff = str(cutoff)
    horizon_quarters = int(horizon_quarters)
    if horizon_quarters < 1:
        raise ValueError("horizon_quarters must be at least 1")
    frame = build_frame(panel)
    known = supervised_rows(frame)
    train = known.loc[known["target_period"] <= cutoff].copy()
    later = known.loc[known["target_period"] > cutoff].copy()
    periods = sorted(later["target_period"].unique())[:horizon_quarters]
    test = later.loc[later["target_period"].isin(periods)].copy()
    if train.empty:
        raise ValueError(f"No training rows with a target at or before {cutoff}")
    if test.empty:
        raise ValueError(f"No scored quarters after {cutoff}")
    if train["target_period"].max() > cutoff:
        raise ValueError("Training targets pass the cutoff")
    if test["target_period"].min() <= cutoff:
        raise ValueError("Test targets are not after the cutoff")
    overlap = set(train["court"] + train["target_period"]) & set(
        test["court"] + test["target_period"]
    )
    if overlap:
        raise ValueError("A court-quarter is in both train and test")
    model = make_model()
    model.fit(
        train[FEATURES],
        train["target"],
        sample_weight=train["target_listed"],
    )
    model_rate = model.predict(test[FEATURES])
    average = test["four_quarter_average"].to_numpy()
    last = test["last_quarter_rate"].to_numpy()
    scored = pd.DataFrame(
        {
            "court": test["court"].to_numpy(),
            "period": test["target_period"].to_numpy(),
            "feature_period": test["period"].to_numpy(),
            "actual": test["target"].to_numpy(),
            "listed": test["target_listed"].to_numpy(),
            "lightgbm": model_rate,
            "four_quarter": average,
            "last_quarter": last,
            "blend": BLEND_WEIGHT * model_rate + (1.0 - BLEND_WEIGHT) * average,
        }
    )
    # Recompute MAE from these predictions. Do not reuse a stored score.
    order = [
        ("last_quarter", "Last quarter", scored["last_quarter"].to_numpy()),
        ("four_quarter", "4-quarter average", scored["four_quarter"].to_numpy()),
        ("lightgbm", "LightGBM", scored["lightgbm"].to_numpy()),
        ("blend", "50/50 blend", scored["blend"].to_numpy()),
    ]
    actual = scored["actual"].to_numpy()
    weight = scored["listed"].to_numpy()
    scores = []
    for key, name, predicted in order:
        scores.append(
            {
                "key": key,
                "model": name,
                "mae_pp": 100 * absolute_error(actual, predicted),
                "weighted_mae_pp": 100 * absolute_error(actual, predicted, weight),
            }
        )
    return {
        "frame": scored,
        "scores": scores,
        "train_from": str(train["target_period"].min()),
        "train_through": str(train["target_period"].max()),
        "train_rows": int(len(train)),
        "test_from": str(test["target_period"].min()),
        "test_through": str(test["target_period"].max()),
        "test_rows": int(len(test)),
        "feature_period_max": str(test["period"].max()),
        "model_version": MODEL_VERSION,
        "blend_weight": BLEND_WEIGHT,
        "blend_weight_fit_on_test": False,
    }


def fit_and_score(panel=None):
    """Train, score the holdout, and build the next-quarter table.

    Returns the MAE table, the saved prediction frame, and the fitted model.
    """
    if panel is None:
        panel = load_panel()
    frame = build_frame(panel)
    known = supervised_rows(frame)
    train, test = time_split(known)
    model = make_model()
    model.fit(
        train[FEATURES],
        train["target"],
        sample_weight=train["target_listed"],
    )
    test_prediction = model.predict(test[FEATURES])
    scores = score_table(test, test_prediction)
    live = live_rows(frame)
    predictions = predict_next(model, live).sort_values("court").reset_index(drop=True)
    return scores, predictions, model, train, test


def _check(train, test, predictions):
    """The split and the save shape. Not a claim that the model is accurate."""
    if train["target_period"].max() > "2023Q4":
        raise AssertionError("Train goes past 2023")
    if test["target_period"].min() < "2024Q1" or test["target_period"].max() > "2026Q2":
        raise AssertionError("Test is not 2024Q1–2026Q2")
    overlap = set(train["court"] + train["target_period"]) & set(
        test["court"] + test["target_period"]
    )
    if overlap:
        raise AssertionError("A court-quarter is in both train and test")
    if predictions["court"].nunique() != predictions.shape[0]:
        raise AssertionError("Expected one prediction row per court")
    if not {"predicted_rate", "driver_1", "driver_2", "driver_3"} <= set(predictions.columns):
        raise AssertionError("Prediction table is missing required columns")
    print("Checks passed.")
    print(
        f"Train {train['target_period'].min()}–{train['target_period'].max()}: "
        f"{len(train)} court-quarters"
    )
    print(
        f"Test {test['target_period'].min()}–{test['target_period'].max()}: "
        f"{len(test)} court-quarters, {test['court'].nunique()} courts"
    )


if __name__ == "__main__":
    scores, predictions, _, train, test = fit_and_score()
    _check(train, test, predictions)
    print()
    print("Test error, in percentage points of the ineffective rate:")
    print(scores.to_string(index=False, float_format=lambda value: f"{value:.2f}"))
    blend = float(scores.loc[scores["model"] == "50/50 blend", "weighted_mae_pp"].iloc[0])
    average = float(scores.loc[scores["model"] == "4-quarter average", "weighted_mae_pp"].iloc[0])
    trees = float(scores.loc[scores["model"] == "LightGBM", "weighted_mae_pp"].iloc[0])
    last = float(scores.loc[scores["model"] == "Last quarter", "weighted_mae_pp"].iloc[0])
    print()
    print(
        f"LightGBM alone is {trees - average:+.2f} weighted percentage points "
        f"versus the 4-quarter average (positive means worse). "
        f"The 50/50 blend is {blend - average:+.2f} versus that average, "
        f"and {blend - last:+.2f} versus last quarter."
    )
    print(
        "Read the blend gap against the size of the error. "
        "A few hundredths of a point on a 4–5 point error is a small edge."
    )
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(OUT_PATH, index=False)
    print(f"Saved {OUT_PATH}")
    print()
    example = predictions.loc[predictions["court"] == "Snaresbrook"].iloc[0]
    print(
        f"Snaresbrook {example['period']}: blend {100 * example['predicted_rate']:.1f}%, "
        f"model {100 * example['model_rate']:.1f}%, "
        f"4-quarter average {100 * example['four_quarter_average']:.1f}%"
    )
    print(
        "Top drivers (LightGBM half only): "
        f"{example['driver_1']} ({example['shap_1']:+.3f}), "
        f"{example['driver_2']} ({example['shap_2']:+.3f}), "
        f"{example['driver_3']} ({example['shap_3']:+.3f})"
    )
