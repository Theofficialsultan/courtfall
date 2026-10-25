import { useEffect, useState } from "react"
import { apiGet } from "./api"
import { useAppState } from "./state"
import type { CourtDetail } from "./types"

export function useCourtDetail() {
  const { court, refresh } = useAppState()
  const [detail, setDetail] = useState<CourtDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancel = false
    apiGet<CourtDetail>(`/court/${encodeURIComponent(court)}`)
      .then((row) => {
        if (cancel) return
        setDetail(row)
        setError(null)
      })
      .catch((reason: Error) => {
        if (!cancel) setError(reason.message)
      })
    return () => {
      cancel = true
    }
  }, [court, refresh])

  return { detail: detail?.name === court ? detail : null, error }
}
