import { useEffect, useState } from "react"
import type { FormEvent } from "react"
import { apiGet, apiPost } from "../api"
import { Band, Card, PageSkeleton } from "../components/ui"
import { useAppState } from "../state"
import type { TrialRow } from "../types"

export function TrialRisk() {
  const { courts, court } = useAppState()
  const [formCourt, setFormCourt] = useState(court)
  const [date, setDate] = useState("")
  const [custody, setCustody] = useState(false)
  const [defence, setDefence] = useState(false)
  const [cps, setCps] = useState(false)
  const [witnesses, setWitnesses] = useState(false)
  const [floater, setFloater] = useState(false)
  const [rows, setRows] = useState<TrialRow[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setFormCourt(court)
  }, [court])

  useEffect(() => {
    apiGet<TrialRow[]>("/trials")
      .then(setRows)
      .catch((reason: Error) => setError(reason.message))
  }, [])

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      const saved = await apiPost<TrialRow>("/trials", {
        court: formCourt,
        date,
        custody,
        defence_confirmed: defence,
        cps_served: cps,
        witnesses_confirmed: witnesses,
        floater,
      })
      setRows((current) => [saved, ...current])
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not score this trial")
    }
  }

  if (!courts.length && !error) return <PageSkeleton />

  return (
    <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
      <Card>
        <h2 className="text-base font-semibold">Trial risk check</h2>
        <p className="mt-1 text-sm text-muted">
          A heuristic for the listing officer. It is the court’s predicted ineffective rate, adjusted by the boxes below and that court’s cause shares. It is not a trained model.
        </p>
        <form className="mt-4 space-y-3" onSubmit={onSubmit}>
          <label className="block text-sm font-medium">
            Court for this trial
            <select
              className="mt-1 h-10 w-full rounded-lg border border-line px-3"
              value={formCourt}
              onChange={(event) => setFormCourt(event.target.value)}
            >
              {courts.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm font-medium">
            Date
            <input
              type="date"
              required
              value={date}
              onChange={(event) => setDate(event.target.value)}
              className="mt-1 h-10 w-full rounded-lg border border-line px-3"
            />
          </label>
          <Check label="Custody case" checked={custody} onChange={setCustody} />
          <Check label="Defence counsel confirmed" checked={defence} onChange={setDefence} />
          <Check label="CPS evidence served" checked={cps} onChange={setCps} />
          <Check label="Witnesses confirmed" checked={witnesses} onChange={setWitnesses} />
          <Check label="Listed as a floater/backer" checked={floater} onChange={setFloater} />
          <button type="submit" className="h-10 w-full rounded-lg bg-blue text-sm font-semibold text-white">
            Score this trial
          </button>
        </form>
        <p className="mt-3 text-xs leading-relaxed text-muted">
          Witnesses not confirmed and CPS evidence not served both use the prosecution/witness share (reason codes 1–6, 15, 16). If both are missing, that share is counted twice. A floater or backer uses the overlisting share. Custody uses the prisoner-not-produced share. Green is under 20%. Amber is under 35%. Those cut points were chosen, not fitted.
        </p>
        {error ? <p className="mt-2 text-sm text-bad">{error}</p> : null}
      </Card>
      <Card>
        <h2 className="text-sm font-semibold">Entered trials</h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="text-xs text-muted">
              <tr className="border-b border-line">
                <th className="py-2 pr-2 font-medium">Court</th>
                <th className="py-2 pr-2 font-medium">Date</th>
                <th className="py-2 pr-2 font-medium">Score</th>
                <th className="py-2 pr-2 font-medium">Band</th>
                <th className="py-2 font-medium">Suggested action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={`${row.court}-${row.date}-${index}`} className="border-b border-line last:border-0">
                  <td className="py-2.5 pr-2">{row.court}</td>
                  <td className="py-2.5 pr-2 tabular-nums">{row.date || "—"}</td>
                  <td className="py-2.5 pr-2 tabular-nums">{row.score.toFixed(1)}%</td>
                  <td className="py-2.5 pr-2"><Band band={row.band} /></td>
                  <td className="py-2.5">{row.suggested_action}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 ? <p className="py-6 text-sm text-muted">No trials scored yet.</p> : null}
        </div>
      </Card>
    </div>
  )
}

function Check({
  label,
  checked,
  onChange,
}: {
  label: string
  checked: boolean
  onChange: (value: boolean) => void
}) {
  return (
    <label className="flex min-h-11 items-center gap-2 text-sm">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      {label}
    </label>
  )
}
