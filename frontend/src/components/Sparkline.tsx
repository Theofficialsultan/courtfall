import { Line, LineChart } from "recharts"

export function Sparkline({ data, color }: { data: number[]; color: string }) {
  const points = data.filter((value) => Number.isFinite(value)).slice(-8)
  if (points.length < 2) return <span className="block h-6 w-[60px] shrink-0" />
  return (
    <div className="h-6 w-[60px] shrink-0">
      <LineChart width={60} height={24} data={points.map((value, index) => ({ index, value }))}>
        <Line type="monotone" dataKey="value" stroke={color} strokeWidth={1.5} dot={false} isAnimationActive={false} />
      </LineChart>
    </div>
  )
}
