import { Area, CartesianGrid, ComposedChart, Line, Tooltip, XAxis, YAxis } from "recharts"
import { cases, paddedDomain, periodLabel } from "../format"
import type { ScenarioLine } from "../types"
import { ChartBox } from "./charts"

const STROKE: Record<string, { color: string; dash?: string }> = {
  do_nothing: { color: "#EF4444" },
  stop: { color: "#10B981" },
  free: { color: "#64748B", dash: "5 4" },
  best: { color: "#2563EB" },
  back: { color: "#0F172A" },
}

function endDot(color: string, last: number, dy: number) {
  return function Dot(props: { cx?: number; cy?: number; index?: number; value?: number }) {
    const { cx, cy, index, value } = props
    if (cx == null || cy == null || index !== last) return <g />
    return (
      <g>
        <circle cx={cx} cy={cy} r={3.5} fill={color} />
        <text x={cx - 8} y={cy + dy} textAnchor="end" fill={color} fontSize={11} fontWeight={600}>
          {cases(Number(value), 0)}
        </text>
      </g>
    )
  }
}

export function ScenarioChart({
  lines,
  height,
  names,
  shade,
}: {
  lines: ScenarioLine[]
  height: number
  names?: Record<string, string>
  shade?: [string, string]
}) {
  const present = lines.filter((line) => line.series.length > 0)
  if (!present.length) return <p className="text-sm text-muted">This court has no scenario path yet.</p>
  const count = present[0].series.length
  const chart = present[0].series.map((point, index) => {
    const row: Record<string, string | number | [number, number]> = { period: periodLabel(point.period) }
    for (const line of present) {
      row[line.key] = line.series[index]?.open ?? line.series[line.series.length - 1].open
    }
    if (shade && shade.every((key) => key in row)) {
      const low = Number(row[shade[0]])
      const high = Number(row[shade[1]])
      row.gap = [Math.min(low, high), Math.max(low, high)]
    }
    return row
  })
  const last = count - 1
  const domain = paddedDomain(
    chart.flatMap((row) => present.map((line) => Number(row[line.key]))),
    0.14,
  )
  return (
    <div className="min-w-0">
      <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        {present.map((line) => {
          const style = STROKE[line.key] ?? { color: "#334155" }
          return (
            <span key={line.key} className="inline-flex items-center gap-1.5">
              <span
                className="inline-block h-0.5 w-4"
                style={{
                  background: style.dash ? "transparent" : style.color,
                  borderTop: style.dash ? `2px dashed ${style.color}` : undefined,
                }}
              />
              {names?.[line.key] ?? line.label}
            </span>
          )
        })}
      </div>
      <ChartBox height={height}>
        <ComposedChart data={chart} margin={{ top: 18, right: 28, left: 0, bottom: 4 }}>
          <CartesianGrid stroke="#E6EAF2" vertical={false} />
          <XAxis dataKey="period" tick={{ fontSize: 11, fill: "#475569" }} interval={1} tickMargin={6} />
          <YAxis
            domain={domain}
            allowDataOverflow
            niceTicks="none"
            width={56}
            tick={{ fontSize: 11, fill: "#475569" }}
            tickFormatter={(value) => cases(Number(value), 0)}
          />
          <Tooltip
            formatter={(value, name) => (name === "Gap" ? ["", ""] : [cases(Number(value), 0), String(name)])}
          />
          {shade ? (
            <Area dataKey="gap" name="Gap" stroke="none" fill="#10B981" fillOpacity={0.16} isAnimationActive={false} />
          ) : null}
          {present.map((line, index) => {
            const style = STROKE[line.key] ?? { color: "#334155" }
            return (
              <Line
                key={line.key}
                dataKey={line.key}
                name={names?.[line.key] ?? line.label}
                stroke={style.color}
                strokeWidth={2}
                strokeDasharray={style.dash}
                dot={endDot(style.color, last, -16 + index * 14)}
                isAnimationActive={false}
              />
            )
          })}
        </ComposedChart>
      </ChartBox>
    </div>
  )
}
