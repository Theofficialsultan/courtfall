import { useEffect, useMemo, useState } from "react"
import { apiPost } from "./api"
import { useAppState } from "./state"
import type { Levers, Simulation } from "./types"

function useDebounced<T>(value: T, ms: number) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), ms)
    return () => window.clearTimeout(timer)
  }, [value, ms])
  return debounced
}

export function leverFractions(levers: Levers) {
  return {
    sitting_days: levers.sitting_days / 100,
    overlisting: levers.overlisting / 100,
    prosecution: levers.prosecution / 100,
    prisoner_not_produced: levers.prisoner_not_produced / 100,
    defence_advocate: levers.defence_advocate / 100,
    judge: levers.judge / 100,
  }
}

export function useSimulation() {
  const { court, levers, productivity, conversion, costScale, sittingCharge, refresh } = useAppState()
  const request = useMemo(
    () => ({
      court,
      levers: leverFractions(levers),
      sitting_productivity: productivity,
      disposal_conversion: conversion,
      assumed_cost_scale: costScale,
      sitting_charge: sittingCharge,
      quarters: 8,
    }),
    [court, levers, productivity, conversion, costScale, sittingCharge],
  )
  const debounced = useDebounced(request, 200)
  const [data, setData] = useState<Simulation | null>(null)
  const [pending, setPending] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancel = false
    setPending(true)
    apiPost<Simulation>("/simulate", debounced)
      .then((row) => {
        if (cancel) return
        setData(row)
        setError(null)
        setPending(false)
      })
      .catch((reason: Error) => {
        if (cancel) return
        setError(reason.message)
        setPending(false)
      })
    return () => {
      cancel = true
    }
  }, [debounced, refresh])

  return { data, pending, error }
}
