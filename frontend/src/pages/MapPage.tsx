import { useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { CourtMap, MapLegend } from "../components/CourtMap"
import { Band, Card, ErrorNote, PageSkeleton } from "../components/ui"
import { cases, pct } from "../format"
import { useAppState } from "../state"

export function MapPage() {
  const { courts, courtsError, court, setCourt } = useAppState()
  const navigate = useNavigate()
  const [sort, setSort] = useState<"open" | "rate">("open")
  const rows = useMemo(() => {
    const copy = [...courts]
    copy.sort((a, b) => (sort === "open" ? b.open - a.open : b.predicted_rate - a.predicted_rate))
    return copy
  }, [courts, sort])

  if (courtsError) return <ErrorNote message={courtsError} />
  if (!courts.length) return <PageSkeleton />

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(320px,0.7fr)]">
      <Card className="p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">England and Wales Crown Courts</h2>
          <span className="text-xs text-muted">{courts.length} courts · {courts[0]?.period}</span>
        </div>
        <CourtMap courts={courts} selected={court} onSelect={setCourt} follow className="h-[640px]" />
        <MapLegend />
      </Card>
      <Card className="p-4">
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">Courts</h2>
          <label className="text-xs text-muted">
            Sort
            <select
              className="ml-2 h-9 rounded-lg border border-line px-2 text-sm text-ink"
              value={sort}
              onChange={(event) => setSort(event.target.value === "rate" ? "rate" : "open")}
            >
              <option value="open">Open caseload</option>
              <option value="rate">Predicted rate</option>
            </select>
          </label>
        </div>
        <div className="max-h-[680px] overflow-auto">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-white text-xs text-muted">
              <tr className="border-b border-line">
                <th className="py-2 pr-2 font-medium">Court</th>
                <th className="py-2 pr-2 font-medium">Open</th>
                <th className="py-2 pr-2 font-medium">Predicted</th>
                <th className="py-2 font-medium">Band</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.name}
                  className={`cursor-pointer border-b border-line last:border-0 ${row.name === court ? "bg-blue-50" : ""}`}
                  onClick={() => setCourt(row.name)}
                  onDoubleClick={() => {
                    setCourt(row.name)
                    navigate({ pathname: "/", search: `?court=${encodeURIComponent(row.name)}` })
                  }}
                >
                  <td className="py-2.5 pr-2 font-medium">{row.name}</td>
                  <td className="py-2.5 pr-2 tabular-nums">{cases(row.open)}</td>
                  <td className="py-2.5 pr-2 tabular-nums">{pct(row.predicted_rate)}</td>
                  <td className="py-2.5"><Band band={row.risk_band} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-muted">Click a row or a circle to select the court. Double-click a row to open its overview.</p>
      </Card>
    </div>
  )
}
