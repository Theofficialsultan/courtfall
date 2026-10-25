import { useEffect, useRef } from "react"
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from "react-leaflet"
import type { CourtPoint } from "../types"
import { cases, pct } from "../format"

const BAND = {
  green: "#10B981",
  amber: "#F59E0B",
  red: "#EF4444",
}

function FitEngland({ courts }: { courts: CourtPoint[] }) {
  const map = useMap()
  const fitted = useRef(false)
  useEffect(() => {
    if (fitted.current || courts.length === 0) return
    let minLat = 90
    let maxLat = -90
    let minLon = 180
    let maxLon = -180
    for (const court of courts) {
      minLat = Math.min(minLat, court.lat)
      maxLat = Math.max(maxLat, court.lat)
      minLon = Math.min(minLon, court.lon)
      maxLon = Math.max(maxLon, court.lon)
    }
    map.fitBounds(
      [
        [minLat, minLon],
        [maxLat, maxLon],
      ],
      { padding: [28, 28], animate: false },
    )
    fitted.current = true
  }, [courts, map])
  return null
}

export function CourtMap({
  courts,
  selected,
  onSelect,
  className = "h-[520px]",
}: {
  courts: CourtPoint[]
  selected: string
  onSelect: (name: string) => void
  follow?: boolean
  className?: string
}) {
  const maxOpen = Math.max(...courts.map((court) => court.open), 1)
  const ordered = [...courts].sort((a, b) => Number(a.name === selected) - Number(b.name === selected))
  return (
    <div className={`${className} overflow-hidden rounded-lg border border-line`}>
      <MapContainer
        center={[52.8, -1.5]}
        zoom={6}
        scrollWheelZoom
        className="h-full w-full"
        aria-label="Crown Courts in England and Wales"
      >
        <TileLayer
          attribution='&copy; Esri &mdash; Esri, DeLorme, NAVTEQ'
          url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
        />
        <FitEngland courts={courts} />
        {ordered.map((court) => {
          const radius = 4 + 10 * Math.sqrt(court.open / maxOpen)
          const active = court.name === selected
          return (
            <CircleMarker
              key={court.name}
              center={[court.lat, court.lon]}
              radius={radius}
              pathOptions={{
                color: active ? "#2563EB" : "#ffffff",
                weight: active ? 2 : 1,
                fillColor: BAND[court.risk_band],
                fillOpacity: 0.75,
              }}
              eventHandlers={{ click: () => onSelect(court.name) }}
            >
              <Popup>
                <p className="text-sm font-semibold text-ink">{court.name}</p>
                <p className="text-xs text-muted">Predicted ineffective rate {pct(court.predicted_rate)}</p>
                <p className="text-xs text-muted">Open caseload {cases(court.open)}</p>
              </Popup>
            </CircleMarker>
          )
        })}
      </MapContainer>
    </div>
  )
}

export function MapLegend() {
  return (
    <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2 text-xs text-muted">
      <div>
        <p className="mb-1 font-medium text-ink">Predicted ineffective trial risk</p>
        <ul className="flex flex-col gap-1">
          <li className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full bg-good" /> Low (&lt; 15%)
          </li>
          <li className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full bg-amber-500" /> Medium (15–30%)
          </li>
          <li className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full bg-bad" /> High (&gt; 30%)
          </li>
        </ul>
      </div>
      <div>
        <p className="mb-1 font-medium text-ink">Open backlog size</p>
        <ul className="flex flex-col gap-1">
          <li>Smaller circle, fewer open cases</li>
          <li>Larger circle, more open cases</li>
        </ul>
      </div>
    </div>
  )
}
