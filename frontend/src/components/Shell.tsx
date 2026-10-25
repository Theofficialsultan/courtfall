import { Suspense, useState } from "react"
import { NavLink, Outlet } from "react-router-dom"
import {
  Activity,
  BookOpen,
  LayoutDashboard,
  LineChart,
  ListChecks,
  Map,
  Menu,
  Settings,
  ShieldAlert,
  SlidersHorizontal,
  X,
} from "lucide-react"
import { useAppState } from "../state"
import { PageSkeleton } from "./skeleton"
const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/map", label: "Courts Map", icon: Map, end: false },
  { to: "/forecasts", label: "Forecasts", icon: LineChart, end: false },
  { to: "/simulator", label: "Simulator", icon: SlidersHorizontal, end: false },
  { to: "/backtests", label: "Backtests", icon: Activity, end: false },
  { to: "/recommendations", label: "Recommendations", icon: ListChecks, end: false },
  { to: "/trial-risk", label: "Trial risk", icon: ShieldAlert, end: false },
  { to: "/methodology", label: "Methodology", icon: BookOpen, end: false },
  { to: "/settings", label: "Settings", icon: Settings, end: false },
]

export function Shell() {
  const { courts, court, setCourt } = useAppState()
  const [open, setOpen] = useState(false)

  return (
    <div className="flex min-h-full bg-page text-ink">
      <aside
        className={`${open ? "translate-x-0" : "-translate-x-full"} fixed inset-y-0 left-0 z-30 flex w-[232px] flex-col bg-navy text-white transition-transform lg:static lg:translate-x-0`}
      >
        <div className="flex items-center gap-2.5 px-5 pt-5 pb-6">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-white/10">
            <LayoutDashboard size={16} aria-hidden />
          </span>
          <span className="text-[17px] font-semibold tracking-[-0.02em]">Courtfall</span>
        </div>
        <nav className="flex flex-1 flex-col gap-1 px-3" aria-label="Primary">
          {NAV.map((item) => {
            const Icon = item.icon
            return (
              <NavLink
                key={item.to}
                to={{ pathname: item.to, search: `?court=${encodeURIComponent(court)}` }}
                end={item.end}
                onClick={() => setOpen(false)}
                className={({ isActive }) =>
                  `flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm font-medium ${
                    isActive ? "bg-blue text-white" : "text-slate-200 hover:bg-white/8 hover:text-white"
                  }`
                }
              >
                <Icon size={18} aria-hidden />
                {item.label}
              </NavLink>
            )
          })}
        </nav>
      </aside>
      {open ? (
        <button
          type="button"
          className="fixed inset-0 z-20 bg-navy/40 lg:hidden"
          aria-label="Close menu"
          onClick={() => setOpen(false)}
        />
      ) : null}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex flex-wrap items-center gap-3 border-b border-line bg-white px-4 py-3 lg:px-5">
          <button
            type="button"
            className="grid h-11 w-11 place-items-center rounded-lg border border-line lg:hidden"
            aria-label={open ? "Close menu" : "Open menu"}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? <X size={18} /> : <Menu size={18} />}
          </button>
          <h1 className="mr-auto text-lg font-semibold tracking-[-0.02em]">Courtfall</h1>
          <label className="text-sm">
            <span className="sr-only">Court</span>
            <select
              className="h-10 max-w-[220px] rounded-lg border border-line bg-white px-3 text-sm font-medium"
              value={court}
              onChange={(event) => setCourt(event.target.value)}
            >
              {courts.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <span className="inline-flex h-8 items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 text-xs font-semibold text-emerald-800">
            <span className="h-1.5 w-1.5 rounded-full bg-good" aria-hidden />
            Live model
          </span>
        </header>
        <main className="mx-auto w-full min-w-0 max-w-[1440px] flex-1 p-4 lg:p-5">
          <Suspense fallback={<PageSkeleton />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  )
}
