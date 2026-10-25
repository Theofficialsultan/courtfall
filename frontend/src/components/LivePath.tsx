import { Area, CartesianGrid, ComposedChart, Line, Tooltip, XAxis, YAxis } from "recharts"
import { cases, money, paddedDomain, periodLabel, signedCases } from "../format"
import type { Simulation } from "../types"
import { ChartBox } from "./charts"

export function LivePath({ simulation, pending }: { simulation: Simulation | null; pending: boolean }) {
  if (!simulation) return <p className="text-sm text-muted">Calculating the eight-quarter path.</p>
  const chart = simulation.series.map((row) => ({
    period: periodLabel(row.period),
    baseline: row.open_baseline,
    scenario: row.open_scenario,
    cleared: row.open_baseline - row.open_scenario,
    gap: [Math.min(row.open_baseline, row.open_scenario), Math.max(row.open_baseline, row.open_scenario)] as [
      number,
      number,
    ],
  }))
  const last = chart.length - 1
  const domain = paddedDomain(chart.flatMap((row) => [row.baseline, row.scenario]), 0.18)
  const clearedDomain = paddedDomain(chart.map((row) => row.cleared).concat(0), 0.2)
  const quiet = simulation.levers.filter((row) => row.reason)
  return (
    <div className="min-w-0 space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">Backlog, baseline against this scenario</h3>
        <span className="text-xs text-muted">{pending ? "Recalculating" : "Calculated just now"}</span>
      </div>
      <p className="text-xs font-medium text-amber-800">{simulation.assumption}</p>
      <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}>
        <Stat label="Open now" value={cases(simulation.open_now)} />
        <Stat label="Baseline after 8 quarters" value={cases(simulation.end_baseline)} />
        <Stat label="Scenario after 8 quarters" value={cases(simulation.end_scenario)} />
        <Stat label="Cases cleared versus baseline" value={cases(simulation.cases_cleared, 1)} />
        <Stat label="Spend over 8 quarters" value={money(simulation.spend_8q)} />
        <Stat label="Backlog difference" value={signedCases(simulation.backlog_difference)} />
      </div>
      <div className="flex flex-wrap gap-4 text-xs text-muted">
        <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-4 bg-bad" /> Baseline</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-4 bg-good" /> Scenario</span>
      </div>
      <ChartBox height={280}>
        <ComposedChart
          key={`${simulation.end_scenario}-${simulation.cases_cleared}-${simulation.spend_8q}`}
          data={chart}
          margin={{ top: 16, right: 12, left: 0, bottom: 0 }}
        >
          <CartesianGrid stroke="#E6EAF2" vertical={false} />
          <XAxis dataKey="period" tick={{ fontSize: 11, fill: "#475569" }} interval={1} />
          <YAxis
            domain={domain}
            allowDataOverflow
            niceTicks="none"
            width={56}
            tick={{ fontSize: 11, fill: "#475569" }}
            tickFormatter={(value) => cases(Number(value))}
          />
          <Tooltip formatter={(value, name) => (name === "Gap" ? ["", ""] : [cases(Number(value)), name])} />
          <Area dataKey="gap" name="Gap" stroke="none" fill="#10B981" fillOpacity={0.18} isAnimationActive={false} />
          <Line dataKey="baseline" name="Baseline" stroke="#EF4444" strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line dataKey="scenario" name="Scenario" stroke="#10B981" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
        </ComposedChart>
      </ChartBox>
      <div>
        <h3 className="text-sm font-semibold">Cases cleared versus the baseline</h3>
        <p className="text-xs text-muted">Same calculation, drawn on the gap so a small cut is visible. Quarter {last} is the end of the horizon.</p>
        <ChartBox height={280}>
          <ComposedChart
            key={`gap-${simulation.cases_cleared}`}
            data={chart}
            margin={{ top: 8, right: 12, left: 0, bottom: 0 }}
          >
            <CartesianGrid stroke="#E6EAF2" vertical={false} />
            <XAxis dataKey="period" tick={{ fontSize: 11, fill: "#475569" }} interval={1} />
            <YAxis
              domain={clearedDomain}
              allowDataOverflow
              niceTicks="none"
              width={48}
              tick={{ fontSize: 11, fill: "#475569" }}
            />
            <Tooltip formatter={(value) => [cases(Number(value), 1), "Cases cleared"]} />
            <Line dataKey="cleared" name="Cases cleared" stroke="#2563EB" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
          </ComposedChart>
        </ChartBox>
      </div>
      {quiet.length ? (
        <ul className="space-y-1 text-xs text-muted">
          {quiet.map((row) => (
            <li key={row.lever}>
              <span className="font-medium text-ink">{row.label}.</span> {row.reason}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="text-xs leading-relaxed text-muted">
        {simulation.days_per_year > 0
          ? `${cases(simulation.days_per_year, 0)} extra sitting days a year, ${cases(simulation.days_over_horizon, 0)} over the horizon. `
          : ""}
        {simulation.sitting_charge === "once"
          ? "The recorded sitting-day bill is the original one-year charge. The backlog path still runs for eight quarters."
          : "The recorded bill covers the full eight quarters."}
      </p>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-[160px] rounded-lg bg-page px-3 py-2">
      <p className="text-[11px] font-medium text-muted">{label}</p>
      <p className="text-sm font-semibold break-normal tabular-nums">{value}</p>
    </div>
  )
}
