import { useEffect, useState } from "react"
import { apiGet } from "../api"
import { Assumed, Card, ErrorNote, PageSkeleton } from "../components/ui"
import { money, pct } from "../format"
import type { LeverSpec } from "../types"

type Catalog = {
  levers: LeverSpec[]
  national_days_2025_26: number
  days_split_assumed: boolean
}

export function Settings() {
  const [data, setData] = useState<Catalog | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiGet<Catalog>("/settings")
      .then(setData)
      .catch((reason: Error) => setError(reason.message))
  }, [])

  if (error) return <ErrorNote message={error} />
  if (!data) return <PageSkeleton />

  return (
    <Card>
      <h2 className="text-base font-semibold">Lever file</h2>
      <p className="mt-1 max-w-[68ch] text-sm text-muted">
        These values are read from config/levers.yaml. Editing them is a change to that file, then a restart of the API. This screen does not write it.
      </p>
      <p className="mt-2 text-sm">
        National sitting days, 2025-26: {data.national_days_2025_26.toLocaleString("en-GB")}.{" "}
        {data.days_split_assumed ? <Assumed text="Courts receive a share of that total in proportion to disposals." /> : null}
      </p>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="text-xs text-muted">
            <tr className="border-b border-line">
              <th className="py-2 pr-3 font-medium">Lever</th>
              <th className="py-2 pr-3 font-medium">Price</th>
              <th className="py-2 pr-3 font-medium">Default cut</th>
              <th className="py-2 font-medium">Source</th>
            </tr>
          </thead>
          <tbody>
            {data.levers.map((lever) => (
              <tr key={lever.key} className="border-b border-line align-top last:border-0">
                <td className="py-3 pr-3 font-medium">{lever.label}</td>
                <td className="py-3 pr-3">
                  <span className="mr-2 tabular-nums">{money(lever.cost_per_unit)}</span>
                  {lever.assumed ? <Assumed text={lever.source} /> : null}
                  <span className="mt-1 block text-xs text-muted">per {lever.unit.replace(/_/g, " ")}</span>
                </td>
                <td className="py-3 pr-3 tabular-nums">{pct(lever.default_effect)}</td>
                <td className="py-3 text-xs leading-relaxed text-muted">{lever.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
