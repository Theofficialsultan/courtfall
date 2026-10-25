# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Existing app: Python, Streamlit, pydeck, Plotly. Entry point `app.py`. Do not change `src/etl.py`.

## Users

Three roles, each with one job on the same court data:

- Resident judge: turn one court's numbers into a short list of actions.
- Listing officer: score an upcoming trial before it is listed.
- HMCTS: choose which courts receive extra sitting days for a given budget.

## Product Purpose

Courtfall shows which Crown Courts are likely to lose trials, why, and what to do about the backlog. Success is a person in one of those roles leaving with a concrete next step, with every assumed figure labelled.

## Positioning

The actions, the trial score, and the allocation all come from the same court-quarter table, the sitting-day bills, and the saved ineffective-rate forecast. The trial score is a labelled heuristic, not a second model.

## Operating Context

A working session in front of the published MoJ Crown Court table (through 2026Q2), the lever file, and the saved forecast. The map is how a court is chosen. Marked actions are written to `data/actions.json`. A court brief can be downloaded as a PDF.

## Capabilities and Constraints

- Keep the map as the way in, and the model-honesty notes at the bottom.
- Capacity action uses the stop-growth sitting days and the yearly £ bill.
- Cause actions use the fixed intervention map: prosecution → CPS readiness check 14 days pre-trial; overlisting → reduce listing ratio / standby case; defence advocate → confirm counsel 48h prior; prisoner not produced → book video link / escort confirmation; judge → reallocate recorders.
- Do not invent cited costs. £3,036 per sitting day is the published figure. The per-court day split and every other lever price are assumed.
- One avoided ineffective trial counted as one extra disposal is an assumption.
- Trial risk score: the court's predicted ineffective rate, adjusted by unchecked form items weighted by that court's cause shares. Label it a heuristic.

## Brand Commitments

The user asked for a dark, clean card layout in the manner of a software product, and for the page to behave as a tool rather than a report.

## Evidence on Hand

`data/clean/court_quarter.parquet`, `predictions.parquet`, `decisions` via `src/decide.py`, `config/levers.yaml`, `BUILD_PLAN.md`, `FEASIBILITY.md`. No invented courts, costs, or testimony.

## Product Principles

- Each screen answers one role's next action.
- Numbers are computed, then labelled if assumed.
- A free policy change is not ranked as a purchase.
- The forecast is shown with its error, not as a measured future.

## Accessibility & Inclusion

Body text and form labels stay high contrast on the dark ground. The court can be chosen from the map or from a named select. Controls name the action.
