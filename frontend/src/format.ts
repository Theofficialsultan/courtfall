export function pct(rate: number | null | undefined, digits = 1) {
  if (rate == null || Number.isNaN(rate)) return "—"
  return `${(rate * 100).toFixed(digits)}%`
}

export function pp(delta: number | null | undefined, digits = 1) {
  if (delta == null || Number.isNaN(delta)) return "—"
  const value = delta * 100
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(digits)} pp`
}

export function points(value: number | null | undefined, digits = 2) {
  if (value == null || Number.isNaN(value)) return "—"
  return value.toFixed(digits)
}

export function signedPct(delta: number | null | undefined, digits = 1) {
  if (delta == null || Number.isNaN(delta)) return "—"
  const value = delta * 100
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(digits)}%`
}

export function money(amount: number | null | undefined) {
  if (amount == null || Number.isNaN(amount)) return "—"
  const sign = amount < 0 ? "-" : ""
  const abs = Math.abs(amount)
  if (abs >= 1_000_000) {
    const millions = abs / 1_000_000
    const rounded = Math.round(millions * 10) / 10
    const text = Math.abs(millions - Math.round(millions)) < 0.05 ? String(Math.round(millions)) : rounded.toFixed(1)
    return `${sign}£${text}m`
  }
  if (abs >= 10_000) {
    const thousands = abs / 1_000
    const text = Math.abs(thousands - Math.round(thousands)) < 0.05 ? String(Math.round(thousands)) : thousands.toFixed(1)
    return `${sign}£${text}k`
  }
  return `${sign}£${Math.round(abs).toLocaleString("en-GB")}`
}

export function parseBudget(text: string) {
  const cleaned = text.replace(/£/g, "").replace(/,/g, "").trim().toLowerCase()
  if (!cleaned) return 0
  if (cleaned.endsWith("m")) return Math.round(Number.parseFloat(cleaned) * 1_000_000)
  if (cleaned.endsWith("k")) return Math.round(Number.parseFloat(cleaned) * 1_000)
  const value = Number(cleaned)
  return Number.isFinite(value) ? Math.round(value) : 0
}

export function paddedDomain(values: number[], padRatio = 0.08): [number, number] {
  const finite = values.filter((value) => Number.isFinite(value))
  if (!finite.length) return [0, 1]
  const min = Math.min(...finite)
  const max = Math.max(...finite)
  const span = max - min || Math.abs(max) * 0.08 || 1
  const pad = span * padRatio
  return [min - pad, max + pad]
}

export function cases(value: number | null | undefined, digits = 0) {
  if (value == null || Number.isNaN(value)) return "—"
  return value.toLocaleString("en-GB", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })
}

export function periodLabel(period: string) {
  if (!period || period.length < 6) return period
  return `${period.slice(0, 4)} ${period.slice(4)}`
}

export function signedCases(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return "—"
  const rounded = Math.round(value)
  const sign = rounded > 0 ? "+" : ""
  return `${sign}${rounded.toLocaleString("en-GB")}`
}
