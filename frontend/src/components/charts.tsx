import type { ReactElement } from "react"
import { ResponsiveContainer } from "recharts"

export function ChartBox({ height, children }: { height: number; children: ReactElement }) {
  return (
    <div className="w-full min-w-0" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 720, height }}>
        {children}
      </ResponsiveContainer>
    </div>
  )
}
