import { useEffect, useState } from "react"
import { apiGet } from "../api"
import { cases } from "../format"
import { useAppState } from "../state"
import type { EvidenceRegister, Levers, Simulation } from "../types"

const ROWS: { key: keyof Levers; label: string; max: number; unit: string }[] = [
  { key: "sitting_days", label: "Extra sitting days", max: 50, unit: "% of this court's assumed annual days" },
  { key: "overlisting", label: "Reduce overlisting", max: 100, unit: "% of those ineffective trials" },
  { key: "prosecution", label: "Reduce prosecution / witness issues", max: 100, unit: "% of those ineffective trials" },
  { key: "prisoner_not_produced", label: "Reduce prisoner not produced", max: 100, unit: "% of those ineffective trials" },
  { key: "defence_advocate", label: "Reduce defence advocate failures", max: 100, unit: "% of those ineffective trials" },
  { key: "judge", label: "Reduce judge availability failures", max: 100, unit: "% of those ineffective trials" },
]

export function ScenarioControls({ simulation }: { simulation: Simulation | null }) {
  const {
    levers,
    setLevers,
    productivity,
    setProductivity,
    conversion,
    setConversion,
    costScale,
    setCostScale,
    sittingCharge,
    setSittingCharge,
    resetScenario,
  } = useAppState()
  const [evidence, setEvidence] = useState<EvidenceRegister | null>(null)
  const ratio = evidence?.claims.find((claim) => claim.evidence_informed_alternative)?.evidence_informed_alternative

  useEffect(() => {
    apiGet<EvidenceRegister>("/evidence").then(setEvidence).catch(() => setEvidence(null))
  }, [])

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Scenario controls</h3>
        <button type="button" onClick={resetScenario} className="text-xs font-semibold text-blue">
          Reset
        </button>
      </div>
      <fieldset className="space-y-1">
        <legend className="text-xs font-medium text-muted">Sitting-day bill</legend>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="radio"
            checked={sittingCharge === "horizon"}
            onChange={() => setSittingCharge("horizon")}
          />
          Full eight quarters
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="radio" checked={sittingCharge === "once"} onChange={() => setSittingCharge("once")} />
          One-year charge, kept for comparison
        </label>
      </fieldset>
      {ROWS.map((row) => {
        const detail = simulation?.levers.find((item) => item.lever === row.key)
        const trials = detail?.quarterly_trials
        return (
          <label key={row.key} className="block text-xs font-medium text-muted">
            {row.label}
            <span className="mt-0.5 block font-normal">
              {row.unit}
              {trials != null ? ` · ${cases(trials, 1)} a quarter in the last four` : ""}
              {row.key === "sitting_days" && simulation
                ? ` · ${cases(simulation.days_per_year, 0)} days a year`
                : ""}
            </span>
            <span className="mt-1 flex items-center gap-2">
              <input
                type="range"
                min={0}
                max={row.max}
                step={1}
                value={levers[row.key]}
                onChange={(event) => setLevers({ ...levers, [row.key]: Number(event.target.value) })}
                className="min-h-11 w-full"
              />
              <input
                type="number"
                min={0}
                max={row.max}
                value={levers[row.key]}
                onChange={(event) =>
                  setLevers({
                    ...levers,
                    [row.key]: Math.max(0, Math.min(row.max, Number(event.target.value) || 0)),
                  })
                }
                className="h-9 w-16 rounded-lg border border-line px-2 text-sm text-ink tabular-nums"
              />
            </span>
          </label>
        )
      })}
      <Assumption
        label="Disposal gain from extra sitting days"
        value={productivity}
        onChange={setProductivity}
        help="1 means an extra 1% of days raises disposals by 1%. This is not estimated from an experiment."
      />
      <Assumption
        label="Avoided trials counted as disposals"
        value={conversion}
        onChange={setConversion}
        help="1 counts one avoided ineffective trial as one extra disposal. Trials and case disposals are different units."
      />
      <label className="block text-xs font-medium text-muted">
        Placeholder prices, relative to the file
        <input
          type="range"
          min={0.5}
          max={2}
          step={0.25}
          value={costScale}
          onChange={(event) => setCostScale(Number(event.target.value))}
          className="mt-1 min-h-11 w-full"
        />
        <span className="font-normal">{costScale.toFixed(2)}×. The published £3,036 is not scaled.</span>
      </label>
      {ratio ? (
        <button
          type="button"
          onClick={() => setProductivity(Number(ratio.sitting_productivity.toFixed(4)))}
          className="w-full rounded-lg border border-line px-3 py-2 text-left text-xs leading-relaxed"
        >
          <span className="font-semibold">{ratio.name}</span>
          <span className="mt-1 block text-muted">{ratio.meaning}</span>
        </button>
      ) : null}
      <button
        type="button"
        onClick={() =>
          setLevers({
            sitting_days: 0,
            overlisting: 0,
            prosecution: 0,
            prisoner_not_produced: 0,
            defence_advocate: 0,
            judge: 0,
          })
        }
        className="text-xs font-semibold text-blue"
      >
        Set every intervention to 0%
      </button>
    </div>
  )
}

function Assumption({
  label,
  value,
  onChange,
  help,
}: {
  label: string
  value: number
  onChange: (value: number) => void
  help: string
}) {
  return (
    <label className="block text-xs font-medium text-muted">
      {label}
      <input
        type="range"
        min={0}
        max={1}
        step={0.05}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="mt-1 min-h-11 w-full"
      />
      <span className="font-normal">{value.toFixed(2)}. {help}</span>
    </label>
  )
}
