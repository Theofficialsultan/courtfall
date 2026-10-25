import { useState } from "react"
import { apiPost } from "../api"
import { Assumed, Card, Confidence, ErrorNote, InfoTip, PageSkeleton } from "../components/ui"
import { useCourtDetail } from "../courtDetail"
import { cases, money } from "../format"
import { useAppState } from "../state"
import type { ActionCard, CourtDetail } from "../types"

function splitSentences(text: string) {
  return text
    .split(/(?<=[.!?])\s+(?=[A-Z])/)
    .map((part) => part.trim())
    .filter(Boolean)
}

function sentences(text: string) {
  const parts = splitSentences(text)
  return {
    short: parts.slice(0, 2).join(" ").trim(),
    rest: parts.slice(2).join(" ").trim(),
  }
}

function firstSentence(text: string) {
  return splitSentences(text)[0] ?? text
}

function costText(action: ActionCard) {
  if (action.cost === 0) return action.cost_label
  return action.id === "capacity" ? `${money(action.cost)}/yr` : money(action.cost)
}

function headline(detail: CourtDetail) {
  const days = detail.summary.stop_growth_days ?? 0
  const yearly = detail.summary.stop_growth_gbp_per_year ?? 0
  const over = detail.interventions.find((row) => row.lever === "overlisting")
  const first =
    days > 0
      ? `Do this first: ask for ${cases(days)} extra sitting days (${money(yearly)}/yr).`
      : "Do this first: no extra sitting days. Disposals already meet receipts."
  const free =
    over && over.cases_cleared > 0 ? ` Free win: overlisting cut, ${cases(over.cases_cleared, 0)} cases.` : ""
  return first + free
}

export function Recommendations() {
  const { court, bump } = useAppState()
  const { detail, error } = useCourtDetail()
  const [showInactive, setShowInactive] = useState(false)

  async function toggle(actionId: string, done: boolean) {
    await apiPost(`/actions/${encodeURIComponent(court)}/${encodeURIComponent(actionId)}`, { done })
    bump()
  }

  if (error) return <ErrorNote message={error} />
  if (!detail) return <PageSkeleton />

  const shareOf = (id: string) => detail.cause_shares.find((cause) => cause.key === id)?.share
  const quiet = (id: string) => id !== "capacity" && shareOf(id) === 0
  const ordered = [...detail.actions].sort((a, b) => b.impact - a.impact)
  const active = ordered.filter((action) => !quiet(action.id))
  const inactive = ordered.filter((action) => quiet(action.id))
  const cards = showInactive ? [...active, ...inactive] : active
  const story = sentences(detail.summary.narrative)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-[-0.02em]">{detail.name}</h2>
          <p className="text-sm font-medium text-ink">{headline(detail)}</p>
        </div>
        <a
          className="inline-flex h-10 items-center rounded-lg bg-blue px-3.5 text-sm font-semibold text-white"
          href={`/api/court/${encodeURIComponent(court)}/brief`}
        >
          Download court brief (PDF)
        </a>
      </div>
      <p className="flex max-w-[72ch] items-start gap-2 text-sm leading-relaxed text-muted">
        <span>{story.short}</span>
        {story.rest ? <InfoTip label="Full recommendation note" text={story.rest} /> : null}
      </p>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {cards.map((action, index) => {
          const faded = quiet(action.id)
          const share = shareOf(action.id)
          const detailLead = firstSentence(action.detail)
          const detailRest = action.detail.slice(detailLead.length).trim()
          return (
            <Card key={action.id} className={faded ? "opacity-60" : ""}>
              <div className="flex items-start justify-between gap-3">
                <h3 className="text-[15px] font-semibold">
                  {index + 1}. {action.title}
                </h3>
                <Confidence level={action.confidence} />
              </div>
              {faded ? (
                <p className="mt-1 text-xs font-medium text-muted">
                  Latest quarter share is {pctShare(share)}. Greyed out because this cause did not appear.
                </p>
              ) : null}
              <p className="mt-2 flex items-start gap-2 text-sm leading-relaxed">
                <span>{detailLead}</span>
                {detailRest ? <InfoTip label={`${action.title} detail`} text={detailRest} /> : null}
              </p>
              <dl className="mt-3 grid gap-3 text-sm" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}>
                <div>
                  <dt className="text-xs text-muted">Impact</dt>
                  <dd className="text-base font-bold tabular-nums">{cases(action.impact)} cases</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted">Cost</dt>
                  <dd className="flex flex-wrap items-center gap-1 text-base font-bold tabular-nums">
                    {costText(action)}
                    {action.assumed_effect || action.assumed_day_split ? <Assumed text={action.confidence_note} /> : null}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted">Owner</dt>
                  <dd className="text-base font-bold">{action.owner}</dd>
                </div>
              </dl>
              <label className="mt-4 flex min-h-11 items-center gap-2 text-sm font-medium">
                <input
                  type="checkbox"
                  checked={action.done}
                  onChange={(event) => toggle(action.id, event.target.checked)}
                />
                Mark as done
              </label>
            </Card>
          )
        })}
      </div>
      {inactive.length ? (
        <button type="button" className="text-sm font-semibold text-blue" onClick={() => setShowInactive((value) => !value)}>
          {showInactive
            ? "Hide inactive actions"
            : `Show ${inactive.length} inactive action${inactive.length === 1 ? "" : "s"}`}
        </button>
      ) : null}
    </div>
  )
}

function pctShare(share: number | undefined) {
  if (share == null) return "0.0%"
  return `${(share * 100).toFixed(1)}%`
}
