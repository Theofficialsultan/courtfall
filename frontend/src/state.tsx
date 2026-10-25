import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react"
import type { ReactNode } from "react"
import { useSearchParams } from "react-router-dom"
import { apiGet } from "./api"
import { DEFAULT_LEVERS } from "./types"
import type { Charge, CourtPoint, Levers } from "./types"

type ModelKey = "blend" | "lightgbm" | "four_quarter" | "last_quarter"

type AppState = {
  courts: CourtPoint[]
  courtsError: string | null
  court: string
  setCourt: (name: string) => void
  model: ModelKey
  setModel: (model: ModelKey) => void
  horizon: 1 | 8
  setHorizon: (horizon: 1 | 8) => void
  levers: Levers
  setLevers: (levers: Levers) => void
  productivity: number
  setProductivity: (value: number) => void
  conversion: number
  setConversion: (value: number) => void
  costScale: number
  setCostScale: (value: number) => void
  sittingCharge: Charge
  setSittingCharge: (value: Charge) => void
  resetScenario: () => void
  refresh: number
  bump: () => void
  backtestNonce: number
  requestBacktest: () => void
}

const AppContext = createContext<AppState | null>(null)

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [params, setParams] = useSearchParams()
  const court = params.get("court") || "Snaresbrook"
  const [courts, setCourts] = useState<CourtPoint[]>([])
  const [courtsError, setCourtsError] = useState<string | null>(null)
  const [model, setModel] = useState<ModelKey>("blend")
  const [horizon, setHorizon] = useState<1 | 8>(1)
  const [levers, setLevers] = useState<Levers>(DEFAULT_LEVERS)
  const [productivity, setProductivity] = useState(1)
  const [conversion, setConversion] = useState(1)
  const [costScale, setCostScale] = useState(1)
  const [sittingCharge, setSittingCharge] = useState<Charge>("horizon")
  const [refresh, setRefresh] = useState(0)
  const [backtestNonce, setBacktestNonce] = useState(0)
  const resetScenario = useCallback(() => {
    setLevers(DEFAULT_LEVERS)
    setProductivity(1)
    setConversion(1)
    setCostScale(1)
    setSittingCharge("horizon")
  }, [])

  const setCourt = useCallback(
    (name: string) => {
      setParams(
        (current) => {
          const next = new URLSearchParams(current)
          next.set("court", name)
          return next
        },
        { replace: true },
      )
    },
    [setParams],
  )

  useEffect(() => {
    if (params.get("court")) return
    setCourt("Snaresbrook")
  }, [params, setCourt])

  useEffect(() => {
    let cancel = false
    apiGet<CourtPoint[]>("/courts")
      .then((rows) => {
        if (cancel) return
        setCourts(rows)
        setCourtsError(null)
      })
      .catch((error: Error) => {
        if (!cancel) setCourtsError(error.message)
      })
    return () => {
      cancel = true
    }
  }, [refresh])

  const value = useMemo(
    () => ({
      courts,
      courtsError,
      court,
      setCourt,
      model,
      setModel,
      horizon,
      setHorizon,
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
      refresh,
      bump: () => setRefresh((n) => n + 1),
      backtestNonce,
      requestBacktest: () => setBacktestNonce((n) => n + 1),
    }),
    [
      courts,
      courtsError,
      court,
      setCourt,
      model,
      horizon,
      levers,
      productivity,
      conversion,
      costScale,
      sittingCharge,
      resetScenario,
      refresh,
      backtestNonce,
    ],
  )

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useAppState() {
  const value = useContext(AppContext)
  if (!value) throw new Error("App state is missing")
  return value
}
