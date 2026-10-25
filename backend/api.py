"""HTTP API over the cached Courtfall calculations.

Run: uvicorn backend.api:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.store import get_store


class SimulateBody(BaseModel):
    court: str
    levers: dict[str, float] = Field(default_factory=dict)
    quarters: int = Field(default=8, ge=1, le=16)
    sitting_productivity: float = Field(default=1.0, ge=0, le=2)
    disposal_conversion: float = Field(default=1.0, ge=0, le=2)
    assumed_cost_scale: float = Field(default=1.0, gt=0, le=4)
    sitting_charge: str = "horizon"
    sitting_budget_gbp: float | None = Field(default=None, ge=0, le=50_000_000)


class RankBody(BaseModel):
    court: str
    budget: float = Field(default=100_000, ge=0, le=1_000_000)
    sitting_charge: str = "horizon"
    sitting_productivity: float = Field(default=1.0, ge=0, le=2)
    disposal_conversion: float = Field(default=1.0, ge=0, le=2)
    assumed_cost_scale: float = Field(default=1.0, gt=0, le=4)


class BacktestBody(BaseModel):
    kind: str = "rate"
    court: str | None = None
    cutoff: str = "2023Q4"
    horizon: int = Field(default=8, ge=1, le=12)
    model: str = "blend"


class TrialBody(BaseModel):
    court: str
    date: str = ""
    custody: bool = False
    defence_confirmed: bool = False
    cps_served: bool = False
    witnesses_confirmed: bool = False
    floater: bool = False


class DoneBody(BaseModel):
    done: bool


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Fit, rank, and backtest once. Later requests only slice this cache.
    get_store()
    yield


app = FastAPI(title="Courtfall", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _court_or_404(name: str):
    try:
        return get_store().court(name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown court: {name}") from None


@app.get("/health")
def health():
    store = get_store()
    return {"ok": True, "courts": int(store.panel["court"].nunique()), "period": store.latest_period}


@app.get("/courts")
def courts():
    return get_store().courts()


@app.get("/court/{name}/brief")
def court_brief(name: str):
    try:
        payload = get_store().brief_pdf(name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown court: {name}") from None
    filename = f"courtfall-{name.replace(' ', '-').lower()}.pdf"
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/court/{name}")
def court(name: str):
    return _court_or_404(name)


@app.post("/simulate")
def simulate(body: SimulateBody):
    kwargs = {
        "quarters": body.quarters,
        "sitting_productivity": body.sitting_productivity,
        "disposal_conversion": body.disposal_conversion,
        "assumed_cost_scale": body.assumed_cost_scale,
        "sitting_charge": body.sitting_charge,
    }
    if body.sitting_budget_gbp is not None:
        kwargs["sitting_budget_gbp"] = body.sitting_budget_gbp
    try:
        return get_store().simulate_court(body.court, body.levers, **kwargs)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown court: {body.court}") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.post("/rank")
def rank(body: RankBody):
    try:
        return get_store().rank_view(
            body.court,
            budget=body.budget,
            sitting_charge=body.sitting_charge,
            sitting_productivity=body.sitting_productivity,
            disposal_conversion=body.disposal_conversion,
            assumed_cost_scale=body.assumed_cost_scale,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown court: {body.court}") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.get("/backtest/options")
def backtest_options():
    return get_store().backtest_options()


@app.post("/backtest/run")
def backtest_run(body: BacktestBody):
    try:
        return get_store().run_backtest(
            kind=body.kind,
            court=body.court or None,
            cutoff=body.cutoff,
            horizon=body.horizon,
            model=body.model,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown court: {body.court}") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.get("/evidence")
def evidence():
    return get_store().evidence()


@app.get("/decisions/{name}")
def decisions(name: str):
    try:
        return get_store().decisions(name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown court: {name}") from None


@app.get("/national")
def national(budget: float = Query(5_000_000, ge=0, le=150_000_000)):
    return get_store().national(budget)


@app.get("/backtest")
def backtest(
    court: str | None = None,
    horizon: int = Query(1, ge=1, le=8),
    model: str = "blend",
):
    # Only the two horizons the product talks about. Anything else snaps to 1.
    horizon = 8 if horizon == 8 else 1
    try:
        return get_store().backtest_view(court=court or None, horizon=horizon, model=model)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown court: {court}") from None


@app.get("/validation")
def validation():
    return get_store().validation()


@app.get("/trials")
def trials():
    return get_store().trials()


@app.post("/trials")
def add_trial(body: TrialBody):
    try:
        return get_store().score_trial(body.model_dump())
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown court: {body.court}") from None


@app.post("/actions/{name}/{action_id}")
def mark_action(name: str, action_id: str, body: DoneBody):
    try:
        return get_store().set_done(name, action_id, body.done)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown court: {name}") from None


@app.get("/settings")
def settings():
    return get_store().lever_catalog()
