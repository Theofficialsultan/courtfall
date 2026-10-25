import { useEffect, useState } from "react"
import { Area, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Line, Tooltip, XAxis, YAxis } from "recharts"
import { apiGet, apiPost } from "../api"
import { ChartBox } from "../components/charts"
import { Card, ErrorNote, Kpi, Notice, PageSkeleton } from "../components/ui"
import { cases, paddedDomain, pct, periodLabel } from "../format"
import { useAppState } from "../state"
import type { Backtest } from "../types"

const TABS = ["Forecast accuracy", "Residuals", "Court comparison", "Scenario validation"] as const
const ORDER = ["last_quarter", "four_quarter", "lightgbm", "blend"]

export function Backtests() {
  const { court, model, setModel, horizon, setHorizon, backtestNonce, requestBacktest } = useAppState()
  const [scope, setScope] = useState<"all" | "court">("all")
  const [tab, setTab] = useState<(typeof TABS)[number]>("Forecast accuracy")
  const [data, setData] = useState<Backtest | null>(null)
  const [loadedKey, setLoadedKey] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [cutoff, setCutoff] = useState("2023Q4")
  const [cutoffs, setCutoffs] = useState<string[]>(["2023Q4"])
  const [quarters, setQuarters] = useState(horizon === 8 ? 8 : 1)
  const [running, setRunning] = useState(false)
  const kind = horizon === 8 ? "backlog" : "rate"
  const requestKey = `${kind}|${scope}|${court}|${model}|${cutoff}|${quarters}`

  useEffect(() => {
    apiGet<{ cutoffs: string[] }>("/backtest/options")
      .then((row) => setCutoffs(row.cutoffs))
      .catch(() => setCutoffs(["2023Q4"]))
  }, [])

  useEffect(() => {
    setQuarters(horizon === 8 ? 8 : 1)
  }, [horizon])

  useEffect(() => {
    let cancel = false
    const params = new URLSearchParams({ horizon: "1", model: "blend" })
    apiGet<Backtest>(`/backtest?${params.toString()}`)
      .then((row) => {
        if (cancel) return
        setData(row)
        setLoadedKey("startup")
        setError(null)
      })
      .catch((reason: Error) => {
        if (!cancel) setError(reason.message)
      })
    return () => {
      cancel = true
    }
  }, [])

  useEffect(() => {
    if (backtestNonce === 0) return
    let cancel = false
    setRunning(true)
    apiPost<Backtest>("/backtest/run", {
      kind,
      court: scope === "court" ? court : null,
      cutoff,
      horizon: quarters,
      model,
    })
      .then((row) => {
        if (cancel) return
        setData(row)
        setLoadedKey(requestKey)
        setError(null)
      })
      .catch((reason: Error) => {
        if (!cancel) setError(reason.message)
      })
      .finally(() => {
        if (!cancel) setRunning(false)
      })
    return () => {
      cancel = true
    }
  }, [backtestNonce, kind, scope, court, cutoff, quarters, model, requestKey])

  if (error) return <ErrorNote message={error} />
  if (!data) return <PageSkeleton />

  const execution = data.execution
  const stale = loadedKey !== requestKey && loadedKey !== "startup"
  const sourceLabel =
    execution?.source === "fresh"
      ? `Freshly computed${execution.elapsed_ms != null ? ` in ${execution.elapsed_ms} ms` : ""}`
      : execution?.source === "cache"
        ? "Retrieved from the evaluation cache for these parameters. Not recomputed."
        : "Startup cache. This chart was computed when the API started. It is not a new run."

  const kpis = data.kpis
  const unit = data.unit === "pp" ? " pp" : ""
  const chart = data.series.map((row) => ({
    period: periodLabel(row.period),
    actual: row.actual,
    predicted: row.predicted,
    band: [row.predicted - data.band_sd, row.predicted + data.band_sd] as [number, number],
  }))
  const yDomain = paddedDomain(
    chart.flatMap((row) => [row.actual, row.predicted, row.band[0], row.band[1]]),
    0.12,
  )
  const comparison = ORDER.map((key) => data.model_comparison.find((row) => row.key === key)).filter(
    (row): row is Backtest["model_comparison"][number] => Boolean(row),
  )
  const maxMae = Math.max(...comparison.map((row) => row.weighted_mae_pp), 0.01)

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm">
            <span className="mb-1 block text-xs font-medium text-muted">Cutoff</span>
            <select
              className="h-10 rounded-lg border border-line bg-white px-3"
              value={cutoff}
              onChange={(event) => setCutoff(event.target.value)}
            >
              {cutoffs.map((period) => (
                <option key={period} value={period}>
                  {periodLabel(period)}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block text-xs font-medium text-muted">Model</span>
            <select
              className="h-10 rounded-lg border border-line bg-white px-3"
              value={model}
              onChange={(event) => setModel(event.target.value as typeof model)}
            >
              <option value="blend">Blend model</option>
              <option value="lightgbm">LightGBM</option>
              <option value="four_quarter">4-quarter average</option>
              <option value="last_quarter">Last quarter</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block text-xs font-medium text-muted">Horizon</span>
            <select
              className="h-10 rounded-lg border border-line bg-white px-3"
              value={horizon}
              onChange={(event) => setHorizon(Number(event.target.value) === 8 ? 8 : 1)}
            >
              <option value={1}>1-quarter ahead</option>
              <option value={8}>8-quarter backlog</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block text-xs font-medium text-muted">Quarters after the cutoff</span>
            <input
              type="number"
              min={1}
              max={12}
              value={quarters}
              onChange={(event) => setQuarters(Math.max(1, Math.min(12, Number(event.target.value) || 1)))}
              className="h-10 w-24 rounded-lg border border-line px-3 tabular-nums"
            />
          </label>
          <button
            type="button"
            onClick={requestBacktest}
            disabled={running}
            className="h-10 rounded-lg bg-blue px-4 text-sm font-semibold text-white disabled:opacity-60"
          >
            {running ? "Running backtest" : "Run backtest"}
          </button>
        </div>
        <p className={`mt-3 text-sm font-medium ${execution?.source === "fresh" ? "text-emerald-800" : "text-amber-800"}`}>
          {running ? "Running. Training uses only data at or before the cutoff." : sourceLabel}
          {stale && !running ? " The chart is still the previous run." : ""}
        </p>
        {execution?.train_from ? (
          <p className="mt-1 text-xs leading-relaxed text-muted">
            Cutoff {execution.cutoff}. Train {execution.train_from}–{execution.train_through}. Test{" "}
            {execution.test_from}–{execution.test_through}. {execution.model_version} {execution.leakage_check}{" "}
            {execution.sitting_days_note}
          </p>
        ) : (
          <p className="mt-1 text-xs text-muted">
            {execution?.note || "Choose a cutoff, then run. The header chooses the model and whether this is the rate or the backlog."}
            {stale ? " The chart below is the previous run." : ""}
          </p>
        )}
        {execution?.error_by_step ? (
          <p className="mt-1 text-xs text-muted">
            Mean absolute error by quarter ahead:{" "}
            {execution.error_by_step.map((row) => `Q${row.step} ${row.mae.toFixed(1)}`).join(", ")}.
          </p>
        ) : null}
      </Card>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <Kpi
          label="Trial-weighted MAE"
          value={`${kpis.selected_weighted_mae.toFixed(2)} pp`}
          delta={`${kpis.selected_delta_vs_last_quarter > 0 ? "+" : ""}${kpis.selected_delta_vs_last_quarter.toFixed(2)} pp vs last quarter`}
          deltaTone={kpis.selected_delta_vs_last_quarter < 0 ? "good" : "bad"}
          spark={kpis.spark_rate_mae}
          sparkColor="#2563EB"
        />
        <Kpi
          label="1-quarter backlog MAE"
          value={`${kpis.one_quarter_backlog_mae.toFixed(1)} cases`}
          delta="Errors do not pile up"
          spark={kpis.spark_backlog_1}
          sparkColor="#10B981"
        />
        <Kpi
          label="8-quarter backlog MAE"
          value={`${kpis.eight_quarter_backlog_mae.toFixed(1)} cases`}
          delta="Frozen from 2023 Q4"
          deltaTone="bad"
          spark={kpis.spark_backlog_8}
          sparkColor="#EF4444"
          hint="2024 Q1–2026 Q2, 10 quarters"
        />
        <Kpi
          label="Best baseline benchmark"
          value={kpis.best_benchmark.model}
          valueClass="text-lg leading-snug"
          hint={`Lowest weighted MAE (${kpis.best_benchmark.weighted_mae_pp.toFixed(2)} pp)`}
        />
        <Kpi label="Coverage" value={String(kpis.coverage_courts)} hint="Crown Courts" />
      </div>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold">Backtest explorer</h2>
          <div className="inline-flex rounded-lg bg-page p-1 text-sm" role="group" aria-label="Court scope">
            <button
              type="button"
              onClick={() => setScope("all")}
              className={`min-h-9 rounded-md px-3 font-medium ${scope === "all" ? "bg-white text-ink shadow-sm" : "text-muted"}`}
            >
              All courts
            </button>
            <button
              type="button"
              onClick={() => setScope("court")}
              className={`min-h-9 rounded-md px-3 font-medium ${scope === "court" ? "bg-blue text-white" : "text-muted"}`}
            >
              Selected court
            </button>
          </div>
        </div>
        <div className="mt-4 flex gap-1 overflow-x-auto border-b border-line" role="tablist">
          {TABS.map((name) => (
            <button
              key={name}
              type="button"
              role="tab"
              aria-selected={tab === name}
              onClick={() => setTab(name)}
              className={`-mb-px min-h-11 shrink-0 border-b-2 px-3 text-sm font-medium ${
                tab === name ? "border-blue text-blue" : "border-transparent text-muted"
              }`}
            >
              {name}
            </button>
          ))}
        </div>

        {tab === "Forecast accuracy" ? (
          <div className="grid gap-4 pt-4 xl:grid-cols-[minmax(0,1fr)_280px]">
            <div>
              <h3 className="text-sm font-semibold">
                {horizon === 1 ? "Ineffective rate" : "Open caseload"} ({scope === "all" ? "all courts" : court})
              </h3>
              <div className="mt-1 flex flex-wrap gap-4 text-xs text-muted">
                <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-4 bg-bad" /> Actual</span>
                <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-4 bg-blue" /> Predicted ({data.model_label})</span>
                <span className="inline-flex items-center gap-1.5"><span className="h-2 w-4 rounded-sm bg-blue-200" /> {data.band_label}</span>
              </div>
              <ChartBox height={300}>
                <ComposedChart data={chart} margin={{ top: 12, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke="#E6EAF2" vertical={false} />
                  <XAxis dataKey="period" tick={{ fontSize: 11, fill: "#475569" }} />
                  <YAxis
                    tick={{ fontSize: 11, fill: "#475569" }}
                    width={56}
                    domain={yDomain}
                    allowDataOverflow
                    niceTicks="none"
                    tickFormatter={(value) => (horizon === 1 ? `${Number(value).toFixed(0)}%` : cases(Number(value)))}
                  />
                  <Tooltip
                    formatter={(value, name) =>
                      name === data.band_label
                        ? ["", ""]
                        : [horizon === 1 ? `${Number(value).toFixed(1)}%` : cases(Number(value)), name]
                    }
                  />
                  <Area
                    dataKey="band"
                    stroke="none"
                    fill="#BFDBFE"
                    fillOpacity={0.85}
                    name={data.band_label}
                    legendType="none"
                    isAnimationActive={false}
                  />
                  <Line dataKey="actual" name="Actual" stroke="#EF4444" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
                  <Line
                    dataKey="predicted"
                    name="Predicted"
                    stroke="#2563EB"
                    strokeWidth={2}
                    dot={{ r: 3, fill: "#2563EB" }}
                    isAnimationActive={false}
                  />
                </ComposedChart>
              </ChartBox>
            </div>
            <ModelComparison comparison={comparison} maxMae={maxMae} note={data.note} />
          </div>
        ) : null}

        {tab === "Residuals" ? (
          <div className="grid gap-4 pt-4 lg:grid-cols-2">
            <Histogram data={data} />
            <Largest data={data} unit={unit} />
          </div>
        ) : null}

        {tab === "Court comparison" ? (
          <div className="pt-4">
            <p className="mb-2 text-xs text-muted">
              Mean absolute error by court. {horizon === 1 ? "Percentage points of the ineffective rate." : "Open cases, frozen forecast from 2023 Q4."}
            </p>
            <ChartBox height={520}>
              <BarChart data={data.per_court.slice(0, 20)} layout="vertical" margin={{ left: 16, right: 12 }}>
                <CartesianGrid horizontal={false} stroke="#E6EAF2" />
                <XAxis type="number" tick={{ fontSize: 11, fill: "#475569" }} />
                <YAxis type="category" dataKey="court" width={150} tick={{ fontSize: 11, fill: "#334155" }} />
                <Tooltip />
                <Bar dataKey="mae" fill="#2563EB" radius={[0, 4, 4, 0]} name="MAE" isAnimationActive={false} />
              </BarChart>
            </ChartBox>
          </div>
        ) : null}

        {tab === "Scenario validation" ? (
          <div className="space-y-3 pt-4">
            <p className="max-w-[72ch] text-sm leading-relaxed">{data.scenario_validation.statement}</p>
            <div className="grid gap-2 sm:grid-cols-4">
              <Mini label="Accounting replay" value={`${data.scenario_validation.accounting_mae.toFixed(1)} cases`} />
              <Mini label="Previous-quarter flows" value={`${data.scenario_validation.previous_flow_mae.toFixed(1)} cases`} />
              <Mini label="One-step last-4" value={`${data.scenario_validation.one_step_mae.toFixed(1)} cases`} />
              <Mini label="Frozen forecast" value={`${data.scenario_validation.frozen_forecast_mae.toFixed(1)} cases`} />
            </div>
            <ChartBox height={280}>
              <ComposedChart
                data={data.scenario_validation.national.map((row) => ({
                  period: periodLabel(row.period),
                  actual: row.actual,
                  predicted: row.predicted,
                }))}
              >
                <CartesianGrid stroke="#E6EAF2" vertical={false} />
                <XAxis dataKey="period" tick={{ fontSize: 11, fill: "#475569" }} />
                <YAxis
                  tick={{ fontSize: 11, fill: "#475569" }}
                  width={64}
                  domain={paddedDomain(data.scenario_validation.national.flatMap((row) => [row.actual, row.predicted]))}
                  allowDataOverflow
                  niceTicks="none"
                  tickFormatter={(value) => cases(Number(value))}
                />
                <Tooltip formatter={(value) => cases(Number(value))} />
                <Line dataKey="actual" name="Actual open" stroke="#EF4444" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
                <Line
                  dataKey="predicted"
                  name="Frozen forecast"
                  stroke="#2563EB"
                  strokeWidth={2}
                  dot={{ r: 3, fill: "#2563EB" }}
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ChartBox>
          </div>
        ) : null}
      </Card>

      {tab === "Forecast accuracy" ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.9fr)_280px]">
          <Card>
            <h2 className="text-sm font-semibold">Residual distribution {horizon === 1 ? "(1-quarter ahead)" : "(frozen backlog)"}</h2>
            <div className="mt-2 grid gap-3 lg:grid-cols-[minmax(0,1fr)_180px]">
              <Histogram data={data} />
              <Largest data={data} unit={unit} />
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <div className="rounded-lg bg-emerald-50 px-3 py-2">
                <p className="text-[11px] font-medium text-emerald-800">Best (lowest MAE)</p>
                <p className="font-semibold">{data.best_court.court}</p>
                <p className="text-sm tabular-nums text-emerald-800">{data.best_court.mae.toFixed(1)}{unit}</p>
              </div>
              <div className="rounded-lg bg-red-50 px-3 py-2">
                <p className="text-[11px] font-medium text-red-800">Worst (highest MAE)</p>
                <p className="font-semibold">{data.worst_court.court}</p>
                <p className="text-sm tabular-nums text-red-800">{data.worst_court.mae.toFixed(1)}{unit}</p>
              </div>
            </div>
          </Card>
          <Card>
            <h2 className="text-sm font-semibold">Live forecast panel</h2>
            <p className="text-xs text-muted">{data.live.court} · {periodLabel(data.live.period)}</p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <div>
                <p className="text-xs font-medium text-muted">Current inputs</p>
                <InputList inputs={data.live.inputs} />
              </div>
              <div>
                <p className="text-xs font-medium text-muted">Forecast outputs</p>
                <ul className="mt-2 space-y-1 text-sm">
                  <li className="flex justify-between"><span>LightGBM</span><span className="font-semibold tabular-nums">{pct(data.live.model_rate)}</span></li>
                  <li className="flex justify-between"><span>4-quarter average</span><span className="font-semibold tabular-nums">{pct(data.live.four_quarter_average)}</span></li>
                  <li className="flex justify-between rounded-md bg-emerald-50 px-2 py-1"><span>Final blend</span><span className="font-semibold tabular-nums text-emerald-800">{pct(data.live.predicted_rate)}</span></li>
                </ul>
              </div>
            </div>
            <p className="mt-3 text-xs font-medium text-muted">Top drivers (tree half)</p>
            <ul className="mt-1 space-y-1">
              {data.live.drivers.slice(0, 3).map((driver) => (
                <li key={driver.feature} className="flex items-center justify-between text-sm">
                  <span>{driver.label}</span>
                  <span className={driver.shap >= 0 ? "font-semibold text-bad" : "font-semibold text-good"}>
                    {driver.shap >= 0 ? "+" : ""}
                    {(driver.shap * 100).toFixed(1)} pp
                  </span>
                </li>
              ))}
            </ul>
          </Card>
          <Card>
            <h2 className="text-sm font-semibold">Backtest honesty</h2>
            <ol className="mt-3 space-y-3">
              {data.honesty.map((item) => (
                <li key={item.n} className="text-sm">
                  <p className="font-semibold">{item.n}. {item.title}</p>
                  <p className="mt-1 text-xs leading-relaxed text-muted">{item.body}</p>
                </li>
              ))}
            </ol>
          </Card>
        </div>
      ) : null}
      <Notice>
        Time-based split only. Training targets stop at 2023 Q4. Nothing is shuffled.
      </Notice>
    </div>
  )
}

function ModelComparison({
  comparison,
  maxMae,
  note,
}: {
  comparison: Backtest["model_comparison"]
  maxMae: number
  note: string
}) {
  return (
    <div>
      <h3 className="text-sm font-semibold">Model comparison</h3>
      <p className="text-xs text-muted">Trial-weighted MAE, percentage points. Lower is better.</p>
      <ul className="mt-3 space-y-3">
        {comparison.map((row) => (
          <li key={row.key}>
            <div className="mb-1 flex items-center justify-between text-sm">
              <span className="font-medium">{row.model}</span>
              <span className="flex items-center gap-2 tabular-nums">
                {row.weighted_mae_pp.toFixed(2)}
                {row.best ? (
                  <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-800">Best</span>
                ) : null}
              </span>
            </div>
            <div className="h-2 rounded-full bg-page">
              <div
                className={`h-2 rounded-full ${row.best ? "bg-good" : "bg-red-300"}`}
                style={{ width: `${(row.weighted_mae_pp / maxMae) * 100}%` }}
              />
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-xs leading-relaxed text-muted">{note}</p>
    </div>
  )
}

function Histogram({ data }: { data: Backtest }) {
  return (
    <ChartBox height={280}>
      <BarChart data={data.histogram}>
        <CartesianGrid stroke="#E6EAF2" vertical={false} />
        <XAxis dataKey="mid" tick={{ fontSize: 10, fill: "#475569" }} tickFormatter={(value) => Number(value).toFixed(1)} />
        <YAxis tick={{ fontSize: 10, fill: "#475569" }} width={32} />
        <Tooltip />
        <Bar dataKey="count" name="Court-quarters" isAnimationActive={false}>
          {data.histogram.map((bin) => (
            <Cell key={bin.mid} fill={bin.mid >= 0 ? "#93C5FD" : "#FCA5A5"} />
          ))}
        </Bar>
      </BarChart>
    </ChartBox>
  )
}

function Largest({ data, unit }: { data: Backtest; unit: string }) {
  return (
    <div>
      <p className="text-xs font-medium text-muted">Largest absolute errors (by court)</p>
      <ol className="mt-2 space-y-1.5">
        {data.largest_errors.map((row, index) => (
          <li key={row.court} className="flex items-center justify-between text-sm">
            <span>{index + 1}. {row.court}</span>
            <span className="font-semibold text-bad tabular-nums">{row.mae.toFixed(1)}{unit}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}

function InputList({ inputs }: { inputs: Record<string, number | null> }) {
  const rows: [string, string][] = [
    ["last_quarter_rate", "Last-quarter rate"],
    ["four_quarter_average", "4-quarter average"],
    ["open_cases", "Open caseload"],
    ["receipts", "Receipts"],
    ["prosecution_share", "Prosecution / witness share"],
    ["overlisting_share", "Overlisting share"],
    ["defence_advocate_share", "Defence advocate share"],
    ["prisoner_not_produced_share", "Prisoner not produced share"],
    ["judge_share", "Judge availability share"],
    ["covid_2020_2022", "2020–2022 flag"],
  ]
  return (
    <ul className="mt-2 space-y-1 text-sm">
      {rows.map(([key, label]) => {
        const value = inputs[key]
        const shown =
          key.endsWith("rate") || key.endsWith("average") || key.endsWith("share")
            ? pct(value)
            : key === "covid_2020_2022"
              ? value
                ? "On"
                : "Off"
              : cases(value, 0)
        return (
          <li key={key} className="flex justify-between gap-3">
            <span className="text-muted">{label}</span>
            <span className="font-medium tabular-nums">{shown}</span>
          </li>
        )
      })}
    </ul>
  )
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-page px-3 py-2">
      <p className="text-[11px] font-medium text-muted">{label}</p>
      <p className="text-sm font-semibold tabular-nums">{value}</p>
    </div>
  )
}
