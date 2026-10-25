import { useEffect, useState } from "react"
import { apiPost } from "../api"
import { Card, ErrorNote, PageSkeleton } from "../components/ui"
import { cases, money } from "../format"
import { useAppState } from "../state"
import type { RankResult } from "../types"

function rate(value: number | null) {
  if (value == null) return "no £ spent"
  return `${value.toFixed(3)} per £1,000`
}

export function DecisionLab() {
  const { court, productivity, conversion, costScale, sittingCharge } = useAppState()
  const [budget, setBudget] = useState(100_000)
  const [data, setData] = useState<RankResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(true)

  useEffect(() => {
    let cancel = false
    const timer = window.setTimeout(() => {
      setPending(true)
      apiPost<RankResult>("/rank", {
        court,
        budget,
        sitting_charge: sittingCharge,
        sitting_productivity: productivity,
        disposal_conversion: conversion,
        assumed_cost_scale: costScale,
      })
        .then((row) => {
          if (cancel) return
          setData(row)
          setError(null)
        })
        .catch((reason: Error) => {
          if (!cancel) setError(reason.message)
        })
        .finally(() => {
          if (!cancel) setPending(false)
        })
    }, 300)
    return () => {
      cancel = true
      window.clearTimeout(timer)
    }
  }, [court, budget, sittingCharge, productivity, conversion, costScale])

  if (error) return <ErrorNote message={error} />
  if (!data) return <PageSkeleton />

  const paid = data.ranking.filter((row) => row.section === "per_pound")
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold">Does the recommendation survive the assumption?</h2>
            <p className="max-w-[75ch] text-sm text-muted">
              The same budget is offered to every lever. Sitting days use the full eight-quarter bill unless the
              cost horizon is switched to the original one-year charge. {data.assumption}
            </p>
          </div>
          <label className="text-sm font-medium">
            Budget over 8 quarters
            <input
              type="number"
              min={0}
              max={1000000}
              step={10000}
              value={budget}
              onChange={(event) => setBudget(Math.max(0, Number(event.target.value) || 0))}
              className="mt-1 block h-10 w-36 rounded-lg border border-line px-3 tabular-nums"
            />
          </label>
        </div>
        <p className="mt-2 text-xs text-muted">
          Cost horizon now: {sittingCharge === "once" ? "one-year charge, original comparison" : "full eight quarters"}.
          Disposal gain {productivity.toFixed(2)}, avoided-trial conversion {conversion.toFixed(2)}, placeholder prices{" "}
          {costScale.toFixed(2)}×. {pending ? "Recalculating all 68 courts." : data.source === "cache" ? "Retrieved from the ranking cache." : "Calculated just now."}
        </p>
        {data.flipped ? (
          <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-950">
            The top purchase flips. Under the central assumptions it is {data.central_top.label} (
            {cases(data.central_top.cases_cleared, 1)} cases, {rate(data.central_top.cases_per_1k)}). With the current
            settings it is {data.scenario_top.label} ({cases(data.scenario_top.cases_cleared, 1)} cases,{" "}
            {rate(data.scenario_top.cases_per_1k)}).
          </p>
        ) : (
          <p className="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-950">
            The top purchase stays {data.scenario_top.label} ({cases(data.scenario_top.cases_cleared, 1)} cases,{" "}
            {rate(data.scenario_top.cases_per_1k)}). That is still an assumption-based ranking.
          </p>
        )}
      </Card>
      <Card>
        <h2 className="text-sm font-semibold">Paid levers at {court}, {money(budget)} over 8 quarters</h2>
        <table className="mt-3 w-full text-left text-sm">
          <thead className="text-xs text-muted">
            <tr className="border-b border-line">
              <th className="py-2 pr-2 font-medium">Rank</th>
              <th className="py-2 pr-2 font-medium">Intervention</th>
              <th className="py-2 pr-2 font-medium">Cases cleared</th>
              <th className="py-2 pr-2 font-medium">Spend</th>
              <th className="py-2 font-medium">Cases per £1,000</th>
            </tr>
          </thead>
          <tbody>
            {paid.map((row) => (
              <tr key={row.lever} className="border-b border-line last:border-0">
                <td className="py-2 pr-2 tabular-nums">{row.rank}</td>
                <td className="py-2 pr-2 font-medium">{row.label}</td>
                <td className="py-2 pr-2 tabular-nums">{cases(row.cases_cleared, 1)}</td>
                <td className="py-2 pr-2 tabular-nums">{money(row.spend)}</td>
                <td className="py-2 tabular-nums">{rate(row.cases_per_1k)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card>
        <h2 className="text-sm font-semibold">All 68 courts</h2>
        <p className="text-sm text-muted">
          {data.stability.unchanged} keep the same top purchase. {data.stability.flipped} flip.
        </p>
        {data.stability.flips.length ? (
          <div className="mt-3 max-h-80 overflow-auto">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-white text-xs text-muted">
                <tr className="border-b border-line">
                  <th className="py-2 pr-2 font-medium">Court</th>
                  <th className="py-2 pr-2 font-medium">Central</th>
                  <th className="py-2 font-medium">Under these settings</th>
                </tr>
              </thead>
              <tbody>
                {data.stability.flips.map((row) => (
                  <tr key={row.court} className="border-b border-line">
                    <td className="py-2 pr-2 font-medium">{row.court}</td>
                    <td className="py-2 pr-2">{row.central}</td>
                    <td className="py-2">{row.scenario}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-2 text-sm">No court changes its top paid lever under these settings.</p>
        )}
        <h3 className="mt-4 text-sm font-semibold">Named comparisons, not probabilities</h3>
        <ul className="mt-2 space-y-1 text-sm">
          {data.presets.map((row) => (
            <li key={row.label}>
              {row.label}: {row.unchanged} unchanged, {row.flipped} flip
              {row.most_common_new_top ? `, mostly to ${row.most_common_new_top}` : ""}.
            </li>
          ))}
        </ul>
      </Card>
    </div>
  )
}
