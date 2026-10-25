import { lazy, Suspense } from "react"
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom"
import { PageSkeleton } from "./components/skeleton"
import { Shell } from "./components/Shell"
import { AppStateProvider } from "./state"

const Overview = lazy(() => import("./pages/Overview").then((module) => ({ default: module.Overview })))
const MapPage = lazy(() => import("./pages/MapPage").then((module) => ({ default: module.MapPage })))
const Forecasts = lazy(() => import("./pages/Forecasts").then((module) => ({ default: module.Forecasts })))
const Simulator = lazy(() => import("./pages/Simulator").then((module) => ({ default: module.Simulator })))
const Backtests = lazy(() => import("./pages/Backtests").then((module) => ({ default: module.Backtests })))
const Recommendations = lazy(() =>
  import("./pages/Recommendations").then((module) => ({ default: module.Recommendations })),
)
const TrialRisk = lazy(() => import("./pages/TrialRisk").then((module) => ({ default: module.TrialRisk })))
const Methodology = lazy(() => import("./pages/Methodology").then((module) => ({ default: module.Methodology })))
const Settings = lazy(() => import("./pages/Settings").then((module) => ({ default: module.Settings })))

export default function App() {
  return (
    <BrowserRouter>
      <AppStateProvider>
        <Routes>
          <Route element={<Shell />}>
            <Route
              index
              element={
                <Suspense fallback={<PageSkeleton />}>
                  <Overview />
                </Suspense>
              }
            />
            <Route
              path="map"
              element={
                <Suspense fallback={<PageSkeleton />}>
                  <MapPage />
                </Suspense>
              }
            />
            <Route
              path="forecasts"
              element={
                <Suspense fallback={<PageSkeleton />}>
                  <Forecasts />
                </Suspense>
              }
            />
            <Route
              path="simulator"
              element={
                <Suspense fallback={<PageSkeleton />}>
                  <Simulator />
                </Suspense>
              }
            />
            <Route
              path="backtests"
              element={
                <Suspense fallback={<PageSkeleton />}>
                  <Backtests />
                </Suspense>
              }
            />
            <Route path="decisions" element={<Navigate to="/simulator" replace />} />
            <Route
              path="recommendations"
              element={
                <Suspense fallback={<PageSkeleton />}>
                  <Recommendations />
                </Suspense>
              }
            />
            <Route
              path="trial-risk"
              element={
                <Suspense fallback={<PageSkeleton />}>
                  <TrialRisk />
                </Suspense>
              }
            />
            <Route
              path="methodology"
              element={
                <Suspense fallback={<PageSkeleton />}>
                  <Methodology />
                </Suspense>
              }
            />
            <Route
              path="settings"
              element={
                <Suspense fallback={<PageSkeleton />}>
                  <Settings />
                </Suspense>
              }
            />
          </Route>
        </Routes>
      </AppStateProvider>
    </BrowserRouter>
  )
}
