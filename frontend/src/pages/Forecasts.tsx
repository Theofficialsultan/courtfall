import { CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts"
import { ChartBox } from "../components/charts"
import { Card, ErrorNote, InfoTip, PageSkeleton } from "../components/ui"
import { useCourtDetail } from "../courtDetail"
import { cases, paddedDomain, pct, periodLabel } from "../format"

export function Forecasts() {
  const { detail, error } = useCourtDetail()

  if (error) return <ErrorNote message={error} />
  if (!detail) return <PageSkeleton />

  const trend = detail.trend.map((row) => ({
    period: periodLabel(row.period),
    open: row.open,
    rate: row.ineffective_rate == null ? null : row.ineffective_rate * 100,
  }))
  const summary = detail.summary
  const openDomain = paddedDomain(trend.map((row) => row.open))
  const rateDomain = paddedDomain(trend.flatMap((row) => (row.rate == null ? [] : [row.rate])))

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_320px]">
      <Card>
        <h2 className="text-base font-semibold">
          {detail.name}, 2016–{detail.latest_period.slice(0, 4)}
        </h2>
        <p className="text-sm text-muted">
          Published open caseload and ineffective rate. The last point is {periodLabel(detail.latest_period)}.
        </p>
        <div className="mt-4">
          <ChartBox height={280}>
            <LineChart data={trend} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#E6EAF2" vertical={false} />
              <XAxis dataKey="period" tick={{ fontSize: 10, fill: "#475569" }} minTickGap={28} />
              <YAxis
                domain={openDomain}
                allowDataOverflow
                niceTicks="none"
                tick={{ fontSize: 11, fill: "#475569" }}
                width={56}
                tickFormatter={(value) => cases(Number(value))}
              />
              <Tooltip formatter={(value) => [cases(Number(value)), "Open cases"]} />
              <Line dataKey="open" name="Open cases" stroke="#2563EB" strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ChartBox>
        </div>
        <div className="mt-4">
          <ChartBox height={280}>
            <LineChart data={trend} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#E6EAF2" vertical={false} />
              <XAxis dataKey="period" tick={{ fontSize: 10, fill: "#475569" }} minTickGap={28} />
              <YAxis
                domain={rateDomain}
                allowDataOverflow
                niceTicks="none"
                tick={{ fontSize: 11, fill: "#475569" }}
                width={48}
                tickFormatter={(value) => `${Math.round(Number(value))}%`}
              />
              <Tooltip formatter={(value) => [`${Number(value).toFixed(1)}%`, "Ineffective rate"]} />
              <Line
                dataKey="rate"
                name="Ineffective rate"
                stroke="#EF4444"
                strokeWidth={2}
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
            </LineChart>
          </ChartBox>
        </div>
      </Card>
      <div className="space-y-4">
        <Card>
          <h2 className="text-sm font-semibold">Next quarter, {periodLabel(detail.target_period)}</h2>
          <ul className="mt-3 space-y-2 text-sm">
            <li className="flex justify-between">
              <span>LightGBM</span>
              <span className="font-semibold tabular-nums">{pct(summary.model_rate)}</span>
            </li>
            <li className="flex justify-between">
              <span>4-quarter average</span>
              <span className="font-semibold tabular-nums">{pct(summary.four_quarter_average)}</span>
            </li>
            <li className="flex justify-between rounded-md bg-emerald-50 px-2 py-1">
              <span>Final blend</span>
              <span className="font-semibold tabular-nums">{pct(summary.predicted_rate)}</span>
            </li>
          </ul>
          <p className="mt-3 text-xs leading-relaxed text-muted">
            Do-nothing open caseload after 8 quarters: {cases(summary.forecast_open_8q)}. That path holds the last four
            quarters of receipts and disposals flat.
          </p>
        </Card>
        <Card>
          <h2 className="flex items-center gap-1.5 text-sm font-semibold">
            What moved the tree
            <InfoTip
              label="About these drivers"
              text="SHAP on the LightGBM half of the blend, in percentage points of the ineffective rate. The other half is the 4-quarter average, which has no drivers. A negative covid flag means the forecast quarter is outside 2020–2022."
            />
          </h2>
          <ul className="mt-3 space-y-2">
            {detail.drivers.slice(0, 5).map((driver) => (
              <li key={driver.feature} className="text-sm">
                <span className="font-medium">{driver.label}</span>{" "}
                <span className={driver.shap >= 0 ? "font-semibold text-bad" : "font-semibold text-good"}>
                  {driver.shap >= 0 ? "+" : ""}
                  {(driver.shap * 100).toFixed(1)} pp
                </span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  )
}
