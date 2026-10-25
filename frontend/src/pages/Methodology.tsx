import { useEffect, useState } from "react"
import { apiGet } from "../api"
import { Card, ErrorNote, PageSkeleton } from "../components/ui"
import { cases, points } from "../format"
import type { EvidenceRegister, Validation } from "../types"

export function Methodology() {
  const [data, setData] = useState<Validation | null>(null)
  const [evidence, setEvidence] = useState<EvidenceRegister | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiGet<Validation>("/validation")
      .then(setData)
      .catch((reason: Error) => setError(reason.message))
    apiGet<EvidenceRegister>("/evidence")
      .then(setEvidence)
      .catch(() => setEvidence(null))
  }, [])

  if (error) return <ErrorNote message={error} />
  if (!data) return <PageSkeleton />

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card>
        <h2 className="text-base font-semibold">Where the numbers come from</h2>
        <ul className="mt-3 space-y-2 text-sm leading-relaxed">
          <li>Crown Court trials, receipts, disposals, and outstanding cases, published by the Ministry of Justice, one row per court per quarter from 2016 Q1 through {data.national_period.replace("Q", " Q")}.</li>
          <li>Ineffective-trial reason codes are grouped in the cleaner: prosecution and witnesses are codes 1–6, 15 and 16; overlisting is 24; defence advocate is 19–21; prisoner not produced is 14; judge availability is 23.</li>
          <li>Sitting-day cost is £3,036, HMCTS 2022-23, parliamentary question 4727, answered 5 December 2023. HMCTS costs only.</li>
          <li>National sitting days for 2025-26 are 110,647, from HMCTS management information. Sharing them across courts by each court’s disposal share is an assumption.</li>
        </ul>
      </Card>
      <Card>
        <h2 className="text-base font-semibold">Formulas</h2>
        <ul className="mt-3 space-y-2 text-sm leading-relaxed">
          <li>Stock flow, the rule that matches the published table: open this quarter = open last quarter + receipts this quarter − disposals this quarter.</li>
          <li>Forecast: receipts and disposals are the average of the last four quarters, held flat. Extra sitting days scale disposals. A cause lever adds that fraction of the cause’s recent ineffective trials to disposals.</li>
          <li>One avoided ineffective trial is counted as one extra disposal. Trials and case disposals are different units. That step is an assumption.</li>
          <li>The ineffective-rate model predicts the next quarter from lags, the four-quarter average, cause shares, open cases, receipts, the calendar quarter, and a 2020–2022 flag. Train through 2023 Q4. Test 2024 Q1–2026 Q2. No shuffle. The saved number is half the tree and half the four-quarter average.</li>
        </ul>
      </Card>
      <Card className="xl:col-span-2">
        <h2 className="text-base font-semibold">What the holdout actually says</h2>
        <div className="mt-3 grid gap-2 sm:grid-cols-4">
          <Mini label="Accounting replay" value={`${data.accounting_mae.toFixed(1)} cases`} />
          <Mini label="Previous-quarter flows" value={`${data.previous_flow_mae.toFixed(1)} cases`} />
          <Mini label="One-step backlog" value={`${data.one_step_mae.toFixed(1)} cases`} />
          <Mini label="Frozen forecast" value={`${data.frozen_forecast_mae.toFixed(1)} cases`} />
        </div>
        <p className="mt-3 text-sm leading-relaxed">
          National open cases in {data.national_period.replace("Q", " Q")}: {cases(data.national_open)}. The frozen forecast covers {data.frozen_quarters} quarters from {data.frozen_from} and is the figure shown as the 8-quarter backlog MAE. LightGBM alone is {points(data.lightgbm_vs_average_pp, 2)} weighted points versus the 4-quarter average (positive means worse). The blend is {points(data.blend_vs_average_pp, 2)} versus that average.
        </p>
        {evidence ? (
          <div className="mt-4 space-y-3 border-t border-line pt-4">
            <h3 className="text-sm font-semibold">Causal evidence register</h3>
            <p className="text-sm text-muted">{evidence.register_note}</p>
            {evidence.claims.map((claim) => (
              <div key={claim.id}>
                <p className="text-sm font-medium">{claim.claim}</p>
                <p className="text-xs font-semibold text-amber-800">{claim.label}</p>
                <ul className="mt-1 space-y-2">
                  {claim.sources.map((source) => (
                    <li key={source.url} className="text-xs leading-relaxed text-muted">
                      <a className="font-medium text-blue" href={source.url}>
                        {source.title}
                      </a>{" "}
                      ({source.publisher}, {source.date}). {source.design}.{" "}
                      {source.causal ? "Causal design." : "Not a causal estimate."} {source.limitation}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        ) : null}
        <ol className="mt-4 space-y-3">
          {data.honesty.map((item) => (
            <li key={item.n} className="text-sm">
              <p className="font-semibold">{item.n}. {item.title}</p>
              <p className="mt-1 text-muted">{item.body}</p>
            </li>
          ))}
        </ol>
      </Card>
    </div>
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
