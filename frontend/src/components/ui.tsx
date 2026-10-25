import type { ReactNode } from "react"
import { PageSkeleton } from "./skeleton"
import { Sparkline } from "./Sparkline"

export { PageSkeleton, Sparkline }

export function Card({
  children,
  className = "",
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <section
      className={`rounded-xl border border-line bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04),0_10px_24px_rgba(15,23,42,0.05)] ${className}`}
    >
      {children}
    </section>
  )
}

export function InfoTip({ label, text }: { label: string; text: string }) {
  return (
    <span className="group relative inline-flex align-middle">
      <button
        type="button"
        aria-label={label}
        className="grid h-5 w-5 place-items-center rounded-full border border-line text-[11px] font-semibold text-muted"
      >
        i
      </button>
      <span
        role="tooltip"
        className="pointer-events-none absolute top-full left-1/2 z-20 mt-1 hidden w-64 -translate-x-1/2 rounded-lg bg-navy px-3 py-2 text-left text-xs leading-snug font-normal text-white normal-case group-hover:block group-focus-within:block"
      >
        {text}
      </span>
    </span>
  )
}

export function Kpi({
  label,
  value,
  valueClass = "text-[28px]",
  delta,
  deltaTone,
  spark,
  sparkColor,
  hint,
  icon,
}: {
  label: string
  value: string
  valueClass?: string
  delta?: string
  deltaTone?: "good" | "bad" | "neutral"
  spark?: number[]
  sparkColor?: string
  hint?: string
  icon?: ReactNode
}) {
  const tone =
    deltaTone === "good" ? "text-good" : deltaTone === "bad" ? "text-bad" : "text-muted"
  return (
    <Card className="flex h-full items-start justify-between gap-3 p-4">
      <div className="min-w-0">
        <p className="text-[13px] font-medium text-muted">{label}</p>
        <p className={`mt-1 leading-tight font-bold tracking-[-0.03em] break-normal text-ink tabular-nums ${valueClass}`}>
          {value}
        </p>
        {delta ? <p className={`mt-2 text-xs font-medium ${tone}`}>{delta}</p> : null}
        {hint ? <p className="mt-1 text-xs text-muted">{hint}</p> : null}
      </div>
      <div className="flex shrink-0 flex-col items-end gap-2">
        {icon}
        {spark && sparkColor ? <Sparkline data={spark} color={sparkColor} /> : null}
      </div>
    </Card>
  )
}

export function Assumed({ text }: { text: string }) {
  return (
    <span
      title={text}
      className="inline-flex items-center rounded-md border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[11px] font-semibold tracking-wide text-amber-800 uppercase"
    >
      assumed
    </span>
  )
}

export function Confidence({ level }: { level: "High" | "Medium" | "Low" }) {
  const tone =
    level === "High"
      ? "bg-emerald-50 text-emerald-800"
      : level === "Medium"
        ? "bg-amber-50 text-amber-800"
        : "bg-slate-100 text-slate-700"
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ${tone}`}>
      {level}
    </span>
  )
}

export function Band({ band }: { band: string }) {
  const key = band.toLowerCase()
  const tone =
    key === "green"
      ? "bg-emerald-50 text-emerald-800"
      : key === "amber"
        ? "bg-amber-50 text-amber-800"
        : "bg-red-50 text-red-700"
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ${tone}`}>
      {band}
    </span>
  )
}

export function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="flex gap-2 rounded-lg bg-blue-50 px-3 py-2.5 text-[13px] leading-snug text-blue-950">
      <span aria-hidden className="mt-0.5 inline-block h-4 w-4 shrink-0 rounded-full bg-blue" />
      <p>{children}</p>
    </div>
  )
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800" role="alert">
      {message} Refresh the page once the API is up.
    </p>
  )
}
