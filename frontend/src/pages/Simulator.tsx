import { useEffect, useState } from "react"
import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine, Tooltip, XAxis, YAxis } from "recharts"
import { apiGet, apiPost } from "../api"
import { ChartBox } from "../components/charts"
import { LivePath } from "../components/LivePath"
import { ScenarioChart } from "../components/ScenarioChart"
import { ScenarioControls } from "../components/ScenarioControls"
import { Card, ErrorNote, InfoTip, PageSkeleton } from "../components/ui"
import { useCourtDetail } from "../courtDetail"
import { cases, money, paddedDomain } from "../format"
import { useAppState } from "../state"
import type { National, RankResult, ScenarioLine } from "../types"
import { useSimulation } from "../useSimulation"

const ORDER = ["do_nothing", "free", "best", "stop", "back"] as const
const NAMES: Record<string, string> = {
  do_nothing: "Do nothing",
  free: "Free fixes",
  best: "£100k",
  stop: "Stop growth",
  back: "Return to 2019",
}

export function Simulator() {
  const { refresh } = useAppState()
  const { detail, error: detailError } = useCourtDetail()
  const [budget, setBudget] = useState(5_000_000)
  const [data, setData] = useState<National | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [advanced, setAdvanced] = useState(false)

  useEffect(() => {
    let cancel = false
    apiGet<National>(`/national?budget=${budget}`)
      .then((row) => {
        if (!cancel) {
          setData(row)
          setError(null)
        }
      })
      .catch((reason: Error) => {
        if (!cancel) setError(reason.message)
      })
    return () => {
      cancel = true
    }
  }, [budget, refresh])

  if (detailError || error) return <ErrorNote message={detailError || error || "The simulator could not be loaded."} />
  if (!detail || !data) return <PageSkeleton />

  const lines = ORDER.map((key) => detail.scenarios.find((line) => line.key === key)).filter(
    (line): line is ScenarioLine => Boolean(line),
  )
  const named = lines.map((line) =>
    line.key === "best" ? { ...line, label: `£100k · ${line.label}` } : { ...line, label: NAMES[line.key] ?? line.label },
  )
  const curve = data.curve.map((row) => ({
    million: row.budget / 1_000_000,
    open: row.open_cases,
  }))
  const openDomain = paddedDomain(curve.map((row) => row.open), 0.12)
  const barValues = data.top15.map((row) => row.cases_per_1m)
  const barDomain = paddedDomain(barValues, 0.08)
  const presets = [
    { label: money(5_000_000), value: 5_000_000 },
    { label: money(data.stop_growth_per_year), value: Math.round(data.stop_growth_per_year) },
    { label: money(data.stop_growth_2y), value: Math.round(data.stop_growth_2y) },
    { label: money(50_000_000), value: 50_000_000 },
    { label: money(data.return_2019), value: Math.round(data.return_2019) },
  ]

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-start justify-between gap-2">
          <h2 className="text-[15px] font-semibold">Scenarios for {detail.name}</h2>
          <InfoTip
            label="Where these paths come from"
            text="Do nothing holds the last four quarters flat. Free fixes is the overlisting cut only, priced at £0. £100k is the top paid lever from the cases-per-£1,000 ranking, at the effect that budget buys. Stop growth and return to 2019 are sitting-day paths from the court bill. The day split is assumed. £3,036 per day is published."
          />
        </div>
        <div className="mt-3">
          <ScenarioChart lines={named} height={320} />
        </div>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-muted">
              <tr className="border-b border-line">
                <th className="py-2 pr-3 font-medium">Scenario</th>
                <th className="py-2 pr-3 font-medium">End backlog</th>
                <th className="py-2 pr-3 font-medium">Cases cleared</th>
                <th className="py-2 font-medium">Cost</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((line) => (
                <tr key={line.key} className="border-b border-line last:border-0">
                  <td className="py-2 pr-3 font-medium">
                    {NAMES[line.key] ?? line.label}
                    {line.key === "best" ? <span className="font-normal text-muted"> · {line.label}</span> : null}
                    {line.capped ? <span className="font-normal text-muted"> · capped at this court’s assumed days</span> : null}
                  </td>
                  <td className="py-2 pr-3 tabular-nums">{cases(line.end, 0)}</td>
                  <td className="py-2 pr-3 tabular-nums">{cases(line.cases_cleared, 0)}</td>
                  <td className="py-2 tabular-nums" title="Eight-quarter bill.">
                    {money(line.cost)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">National budget</span>
        {presets.map((preset) => {
          const active = Math.abs(budget - preset.value) < 1_000
          return (
            <button
              key={preset.label}
              type="button"
              onClick={() => setBudget(preset.value)}
              className={`h-9 rounded-full border px-3 text-sm font-medium ${
                active ? "border-blue bg-blue text-white" : "border-line bg-white text-ink hover:bg-page"
              }`}
            >
              {preset.label}
            </button>
          )
        })}
        <InfoTip
          label="What the budget does"
          text={`The chips move the marker on the national curve. They do not redraw the curve. Extra sitting days go to courts in order of cases cleared per pound, capped at each court’s cost of returning to its 2019 average. Leftover after those caps: ${money(data.leftover)}. Stop growth for two years is twice the yearly bill. Per-court days are a share of the national 2025-26 total, split by disposals. £3,036 per day is published.`}
        />
      </div>

      <div className="grid grid-cols-12 gap-4">
        <Card className="col-span-12 flex h-full flex-col lg:col-span-6">
          <h2 className="text-[15px] font-semibold">National spend against backlog</h2>
          <div className="mt-3">
            <ChartBox height={300}>
              <LineChart data={curve} margin={{ top: 16, right: 12, left: 0, bottom: 8 }}>
                <CartesianGrid stroke="#E6EAF2" vertical={false} />
                <XAxis
                  type="number"
                  dataKey="million"
                  domain={[0, 150]}
                  tick={{ fontSize: 11, fill: "#475569" }}
                  tickFormatter={(value) => `£${value}m`}
                />
                <YAxis
                  domain={openDomain}
                  allowDataOverflow
                  niceTicks="none"
                  tick={{ fontSize: 11, fill: "#475569" }}
                  width={56}
                  tickFormatter={(value) => cases(Number(value))}
                />
                <Tooltip formatter={(value) => [cases(Number(value)), "Open cases after 8 quarters"]} />
                <ReferenceLine x={budget / 1_000_000} stroke="#0F172A" strokeWidth={2} />
                <Line
                  type="monotone"
                  dataKey="open"
                  name="Open cases"
                  stroke="#2563EB"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ChartBox>
          </div>
        </Card>
        <Card className="col-span-12 flex h-full flex-col lg:col-span-6">
          <h2 className="text-[15px] font-semibold">Top 15 courts by cases cleared per £1m</h2>
          <div className="mt-3">
            <ChartBox height={300}>
              <BarChart
                data={[...data.top15].reverse()}
                layout="vertical"
                margin={{ left: 8, right: 12, top: 4, bottom: 4 }}
              >
                <CartesianGrid horizontal={false} stroke="#E6EAF2" />
                <XAxis
                  type="number"
                  domain={[Math.min(barDomain[0], Math.min(...barValues) * 0.95), barDomain[1]]}
                  tick={{ fontSize: 11, fill: "#475569" }}
                  tickFormatter={(value) => Number(value).toFixed(1)}
                />
                <YAxis type="category" dataKey="court" width={188} tick={{ fontSize: 11, fill: "#334155" }} />
                <Tooltip formatter={(value) => [Number(value).toFixed(1), "Cases per £1m"]} />
                <Bar dataKey="cases_per_1m" name="Cases per £1m" fill="#2563EB" radius={[0, 4, 4, 0]} isAnimationActive={false} />
              </BarChart>
            </ChartBox>
          </div>
        </Card>
      </div>

      <details
        className="rounded-xl border border-line bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04),0_10px_24px_rgba(15,23,42,0.05)]"
        onToggle={(event) => setAdvanced(event.currentTarget.open)}
      >
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 text-[15px] font-semibold [&::-webkit-details-marker]:hidden">
          Advanced: adjust assumptions
          <span className="text-sm font-medium text-muted">{advanced ? "Hide" : "Show"}</span>
        </summary>
        {advanced ? <AdvancedAssumptions /> : null}
      </details>
    </div>
  )
}

function AdvancedAssumptions() {
  const simulation = useSimulation()
  return (
    <div className="border-t border-line px-5 py-4">
      {simulation.error ? <ErrorNote message={simulation.error} /> : null}
      <div className="grid items-start gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
        <ScenarioControls simulation={simulation.data} />
        <LivePath simulation={simulation.data} pending={simulation.pending} />
      </div>
      <RankingNote />
    </div>
  )
}

function RankingNote() {
  const { court, productivity, conversion, costScale, sittingCharge } = useAppState()
  const [data, setData] = useState<RankResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(true)

  useEffect(() => {
    let cancel = false
    const timer = window.setTimeout(() => {
      setPending(true)
      apiPost<RankResult>("/rank", {
        court,
        budget: 100_000,
        sitting_charge: sittingCharge,
        sitting_productivity: productivity,
        disposal_conversion: conversion,
        assumed_cost_scale: costScale,
      })
        .then((row) => {
          if (cancel) return
          setData(row)
          setError(null)
        })
        .catch((reason: Error) => {
          if (!cancel) setError(reason.message)
        })
        .finally(() => {
          if (!cancel) setPending(false)
        })
    }, 400)
    return () => {
      cancel = true
      window.clearTimeout(timer)
    }
  }, [court, sittingCharge, productivity, conversion, costScale])

  if (error) return <ErrorNote message={error} />
  return (
    <div className="mt-4 border-t border-line pt-4">
      <h3 className="text-[15px] font-semibold">Does the £100k ranking hold?</h3>
      <p className="mt-1 text-sm text-muted">
        {pending || !data
          ? "Checking all 68 courts under these assumptions."
          : data.flipped
            ? `The top purchase flips, from ${data.central_top.label} to ${data.scenario_top.label}. ${data.stability.unchanged} courts stay the same and ${data.stability.flipped} change.`
            : `The top purchase stays ${data.scenario_top.label}. ${data.stability.unchanged} courts stay the same and ${data.stability.flipped} change under these assumptions.`}
      </p>
      {data ? (
        <ul className="mt-2 space-y-1 text-sm">
          {data.presets.map((preset) => (
            <li key={preset.label}>
              {preset.label}: {preset.unchanged} unchanged, {preset.flipped} flip
              {preset.most_common_new_top ? `, mostly to ${preset.most_common_new_top}` : ""}.
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
