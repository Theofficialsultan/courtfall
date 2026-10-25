import { useEffect, useState } from "react"
import { Award } from "lucide-react"
import { Bar, BarChart, CartesianGrid, Cell, Tooltip, XAxis, YAxis } from "recharts"
import { apiGet } from "../api"
import { ChartBox } from "../components/charts"
import { CourtMap, MapLegend } from "../components/CourtMap"
import { ScenarioChart } from "../components/ScenarioChart"
import { Card, Confidence, ErrorNote, InfoTip, Kpi, Notice, PageSkeleton } from "../components/ui"
import { useCourtDetail } from "../courtDetail"
import { cases, money, paddedDomain, pct, periodLabel, pp, signedPct } from "../format"
import { useAppState } from "../state"
import type { CourtDetail, ScenarioLine, Validation } from "../types"

export function Overview() {
  const { courts, courtsError, court, setCourt, refresh } = useAppState()
  const { detail, error: detailError } = useCourtDetail()
  const [validation, setValidation] = useState<Validation | null>(null)

  useEffect(() => {
    let cancel = false
    apiGet<Validation>("/validation")
      .then((row) => {
        if (!cancel) setValidation(row)
      })
      .catch(() => {
        if (!cancel) setValidation(null)
      })
    return () => {
      cancel = true
    }
  }, [refresh])

  if (courtsError) return <ErrorNote message={courtsError} />
  if (detailError) return <ErrorNote message={detailError} />
  if (!detail || !validation) return <PageSkeleton />

  const summary = detail.summary
  const blend = validation.scores.find((row) => row.key === "blend")
  const last = validation.scores.find((row) => row.key === "last_quarter")
  const maeDelta = blend && last ? blend.weighted_mae_pp - last.weighted_mae_pp : null
  const rateUp = (summary.rate_delta_pp ?? 0) > 0
  const openUp = (summary.open_delta_pct ?? 0) > 0
  const forecastUp = (summary.forecast_delta_pct ?? 0) > 0
  const scenarios = detail.scenarios ?? []
  const plan = scenarios.find((line) => line.key === "stop")
  const nothing = scenarios.find((line) => line.key === "do_nothing")
  const free = scenarios.find((line) => line.key === "free")
  const chartLines = [nothing, plan, free].filter((line): line is ScenarioLine => Boolean(line))
  const actions = topActions(detail)

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12 grid grid-cols-2 gap-4 xl:grid-cols-5">
        <Kpi
          label="Predicted ineffective rate"
          value={pct(summary.predicted_rate)}
          delta={`${pp(summary.rate_delta_pp)} vs ${summary.rate_year_ago ? periodLabel(detail.target_period.replace("2026", "2025")) : "a year earlier"} actual`}
          deltaTone={rateUp ? "bad" : "good"}
          spark={detail.spark_rate.filter((value): value is number => value != null)}
          sparkColor={rateUp ? "#EF4444" : "#10B981"}
        />
        <Kpi
          label="Current open caseload"
          value={cases(summary.open)}
          delta={`${signedPct(summary.open_delta_pct)} vs ${summary.open_year_ago_period ? periodLabel(summary.open_year_ago_period) : "a year earlier"}`}
          deltaTone={openUp ? "bad" : "good"}
          spark={detail.spark_open}
          sparkColor={openUp ? "#EF4444" : "#10B981"}
        />
        <Kpi
          label="8-quarter forecast backlog"
          value={cases(summary.forecast_open_8q, 0)}
          delta={`${signedPct(summary.forecast_delta_pct)} vs current`}
          deltaTone={forecastUp ? "bad" : "good"}
          spark={detail.spark_forecast}
          sparkColor={forecastUp ? "#EF4444" : "#10B981"}
        />
        <Kpi
          label="Model MAE"
          value={`${blend ? blend.weighted_mae_pp.toFixed(2) : "—"} pp`}
          delta={maeDelta == null ? undefined : `${maeDelta > 0 ? "+" : ""}${maeDelta.toFixed(2)} pp vs last quarter`}
          deltaTone={maeDelta != null && maeDelta < 0 ? "good" : "bad"}
          hint="Trial-weighted, 2024 Q1–2026 Q2"
        />
        <Kpi
          label="Best paid lever"
          value={summary.best_lever}
          valueClass="text-[15px] leading-snug"
          hint="Cases per £1,000. Free levers are separate."
          icon={
            <span className="grid h-9 w-9 place-items-center rounded-full bg-blue-50 text-blue">
              <Award size={18} aria-hidden />
            </span>
          }
        />
      </div>

      <Card className="col-span-12 flex h-full flex-col lg:col-span-4">
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 className="text-[15px] font-semibold">Courts risk map</h2>
          <span className="rounded-lg border border-line px-2 py-1 text-xs font-medium" title="England and Wales Crown Courts only.">
            England & Wales
          </span>
        </div>
        <CourtMap courts={courts} selected={court} onSelect={setCourt} className="min-h-[320px] flex-1" />
        <MapLegend />
      </Card>

      <Card className="col-span-12 flex h-full flex-col lg:col-span-8">
        <div className="flex items-start justify-between gap-2">
          <h2 className="text-[15px] font-semibold">Recommended plan for {court}</h2>
          <InfoTip
            label="How this plan is built"
            text="The green line is the extra sitting days that stop the caseload growing, run for eight quarters. The dashed line is the overlisting cut only. The shaded band is the gap between doing nothing and that sitting-day plan. Effects are assumptions, not measured causal results. The £3,036 day cost is published. The split of national days across courts is assumed."
          />
        </div>
        <p className="mt-2 text-sm font-medium leading-snug">{planHeadline(detail)}</p>
        <div className="mt-3">
          <ScenarioChart
            lines={chartLines}
            height={320}
            names={{ do_nothing: "Do nothing", stop: "Recommended plan", free: "Free fixes only" }}
            shade={["do_nothing", "stop"]}
          />
        </div>
        {plan ? (
          <div className="mt-3 grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}>
            <Chip label="Ends at" value={cases(plan.end, 0)} />
            <Chip label="Cases cleared" value={cases(plan.cases_cleared, 0)} />
            <Chip label="Cost" value={money(plan.cost)} title="Eight-quarter bill for the green line. The headline is one year of the same run-rate." />
            <Chip
              label="Backlog vs today"
              value={signedBacklog(plan.end - summary.open)}
              title="Open cases at the end of the green line, minus open cases today. Zero means the plan holds the backlog where it is."
            />
          </div>
        ) : null}
      </Card>

      <Card className="col-span-12 flex h-full flex-col lg:col-span-6">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-[15px] font-semibold">Top actions</h2>
          <InfoTip
            label="How actions are chosen"
            text="The three largest actions at this court, leaving out causes with a zero share in the latest quarter. The full list, including inactive causes, is on Recommendations."
          />
        </div>
        <div className="mt-3 grid flex-1 content-start gap-3">
          {actions.map((action) => (
            <article key={action.id} className="rounded-lg border border-line px-3 py-3">
              <div className="flex items-start justify-between gap-3">
                <h3 className="text-sm font-semibold">{action.title}</h3>
                <Confidence level={action.confidence} />
              </div>
              <p className="mt-1 text-sm tabular-nums">
                {cases(action.impact, 0)} cases · {action.cost === 0 ? action.cost_label : action.id === "capacity" ? `${money(action.cost)}/yr` : money(action.cost)}
              </p>
              <p className="text-xs text-muted">{action.owner}</p>
            </article>
          ))}
        </div>
      </Card>

      <Card className="col-span-12 flex h-full flex-col lg:col-span-3">
        <div className="mb-2 flex items-center justify-between gap-2">
          <h2 className="text-[15px] font-semibold">Forecast drivers</h2>
          <InfoTip
            label="About these drivers"
            text="SHAP on the LightGBM half of the blend, in percentage points of the ineffective rate. The other half is the four-quarter average, which has no drivers."
          />
        </div>
        <ChartBox height={280}>
          <BarChart
            data={detail.drivers.slice(0, 6).map((driver) => ({
              label: driver.label,
              shap: driver.shap * 100,
            }))}
            layout="vertical"
            margin={{ left: 4, right: 8, top: 4, bottom: 4 }}
          >
            <CartesianGrid horizontal={false} stroke="#E6EAF2" />
            <XAxis
              type="number"
              domain={paddedDomain(detail.drivers.slice(0, 6).map((driver) => driver.shap * 100), 0.12)}
              allowDataOverflow
              tick={{ fontSize: 11, fill: "#475569" }}
              tickFormatter={(value) => Number(value).toFixed(1)}
            />
            <YAxis type="category" dataKey="label" width={132} tick={{ fontSize: 10, fill: "#334155" }} />
            <Tooltip formatter={(value) => [`${Number(value).toFixed(1)} pp`, "SHAP"]} />
            <Bar dataKey="shap" radius={[0, 4, 4, 0]} isAnimationActive={false}>
              {detail.drivers.slice(0, 6).map((driver) => (
                <Cell key={driver.feature} fill={driver.shap >= 0 ? "#EF4444" : "#10B981"} />
              ))}
            </Bar>
          </BarChart>
        </ChartBox>
      </Card>

      <Card className="col-span-12 flex h-full flex-col lg:col-span-3">
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 className="text-[15px] font-semibold">Validation</h2>
          <InfoTip
            label="How to read validation"
            text="Use forecasts to compare options. They are not a promise of the exact backlog. Accounting replay checks that open cases equal the previous stock plus receipts minus disposals."
          />
        </div>
        <div className="grid flex-1 content-start gap-2">
          <Chip label="Accounting replay MAE" value={`${validation.accounting_mae.toFixed(1)} cases`} />
          <Chip label="1-quarter ahead MAE" value={`${validation.one_step_mae.toFixed(1)} cases`} />
          <Chip label="8-quarter backtest MAE" value={`${validation.frozen_forecast_mae.toFixed(1)} cases`} />
          <Chip label={`National ${periodLabel(validation.national_period)} open`} value={cases(validation.national_open)} />
        </div>
        <div className="mt-3">
          <Notice>Use forecasts to compare options, not to promise an exact backlog.</Notice>
        </div>
      </Card>
    </div>
  )
}

function planHeadline(detail: CourtDetail) {
  const days = detail.summary.stop_growth_days ?? 0
  const yearly = detail.summary.stop_growth_gbp_per_year ?? 0
  const over = detail.interventions.find((row) => row.lever === "overlisting")
  const first =
    days > 0
      ? `Do this first: ${cases(days, 0)} extra sitting days/yr, ${money(yearly)}.`
      : "Do this first: no extra sitting days. Disposals already meet receipts."
  const free =
    over && over.cases_cleared > 0 ? ` Free win: overlisting cut, ${cases(over.cases_cleared, 0)} cases.` : ""
  return first + free
}

function topActions(detail: CourtDetail) {
  const shareOf = (id: string) => detail.cause_shares.find((cause) => cause.key === id)?.share
  return [...detail.actions]
    .filter((action) => action.id === "capacity" || shareOf(action.id) !== 0)
    .sort((a, b) => b.impact - a.impact)
    .slice(0, 3)
}

function signedBacklog(value: number) {
  const rounded = Math.round(value)
  const sign = rounded > 0 ? "+" : ""
  return `${sign}${rounded.toLocaleString("en-GB")}`
}

function Chip({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div className="min-w-[160px] rounded-lg bg-page px-3 py-2" title={title}>
      <p className="text-[11px] font-medium text-muted">{label}</p>
      <p className="text-sm font-semibold break-normal tabular-nums">{value}</p>
    </div>
  )
}
