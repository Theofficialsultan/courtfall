export type RiskBand = "green" | "amber" | "red"

export type CourtPoint = {
  name: string
  lat: number
  lon: number
  open: number
  predicted_rate: number
  risk_band: RiskBand
  period: string
}

export type Driver = {
  feature: string
  label: string
  shap: number
  note: string | null
}

export type Intervention = {
  lever: string
  label: string
  cases_cleared: number
  cost: number
  cost_label: string
  cost_basis: string
  cases_per_1k: number | null
  confidence: "High" | "Medium" | "Low"
  assumed_cost: boolean
  assumed_effect: boolean
  assumed_day_split: boolean
  free_win: boolean
  rank: number
  section: string
  is_recommendation: boolean
  note: string
}

export type ActionCard = {
  id: string
  title: string
  detail: string
  impact: number
  impact_label: string
  cost: number
  cost_label: string
  owner: string
  confidence: "High" | "Medium" | "Low"
  confidence_note: string
  assumed_day_split: boolean
  assumed_effect: boolean
  rank: number
  done: boolean
}

export type CourtDetail = {
  name: string
  latest_period: string
  target_period: string
  summary: {
    open: number
    open_year_ago: number | null
    open_year_ago_period: string | null
    open_delta_pct: number | null
    receipts_last4: number
    disposals_last4: number
    growth_per_quarter: number
    ineffective_rate: number | null
    predicted_rate: number
    model_rate: number
    four_quarter_average: number
    rate_year_ago: number | null
    rate_delta_pp: number | null
    forecast_open_8q: number
    forecast_delta_pct: number | null
    stop_growth_days: number | null
    stop_growth_gbp_per_year: number | null
    back_to_2019_gbp: number | null
    open_2019: number | null
    best_lever: string
    best_lever_key: string
    best_lever_cases: number
    best_lever_cases_per_1k: number | null
    narrative: string
  }
  trend: {
    period: string
    open: number
    receipts: number
    disposals: number
    ineffective_rate: number | null
  }[]
  spark_rate: (number | null)[]
  spark_open: number[]
  spark_forecast: number[]
  forecast_path: { period: string; open: number }[]
  drivers: Driver[]
  inputs: Record<string, number | null>
  cause_shares: { key: string; label: string; share: number; n: number }[]
  interventions: Intervention[]
  actions: ActionCard[]
  scenarios: ScenarioLine[]
}

export type ScenarioLine = {
  key: string
  label: string
  series: { period: string; open: number }[]
  end: number
  cases_cleared: number
  cost: number
  capped: boolean
}

export type Simulation = {
  series: {
    period: string
    step: number
    open_baseline: number
    open_scenario: number
    cases_cleared?: number
  }[]
  cases_cleared: number
  spend_8q: number
  annual_cost: number
  annual_cost_assumed: boolean
  annual_cost_note: string
  backlog_change: number
  backlog_difference: number
  open_now: number
  end_baseline: number
  end_scenario: number
  recommendation: string
  assumptions: string[]
  assumption: string
  sitting_charge: Charge
  sitting_fraction: number
  days_per_year: number
  days_over_horizon: number
  court_days: number
  levers: LeverResult[]
  notes: string[]
  causal_effect_established: boolean
}

export type RankRow = {
  lever: string
  label: string
  section: string
  rank: number
  cases_cleared: number
  spend: number
  cases_per_1k: number | null
  is_recommendation: boolean
  free_win: boolean
  note: string
}

export type RankResult = {
  court: string
  budget: number
  sitting_charge: Charge
  source: "fresh" | "cache"
  assumption: string
  ranking: RankRow[]
  central_top: { lever: string; label: string; cases_cleared: number; spend: number; cases_per_1k: number | null }
  scenario_top: { lever: string; label: string; cases_cleared: number; spend: number; cases_per_1k: number | null }
  flipped: boolean
  stability: {
    courts: number
    unchanged: number
    flipped: number
    flips: {
      court: string
      central: string
      scenario: string
      central_per_1k: number | null
      scenario_per_1k: number | null
    }[]
  }
  presets: { label: string; unchanged: number; flipped: number; most_common_new_top: string | null }[]
}

export type EvidenceRegister = {
  register_note: string
  claims: {
    id: string
    claim: string
    status: string
    label: string
    evidence_informed_alternative?: {
      name: string
      disposal_change: number
      sitting_day_change: number
      sitting_productivity: number
      meaning: string
    }
    sources: {
      title: string
      publisher: string
      date: string
      url: string
      intervention: string
      outcome: string
      design: string
      causal: boolean
      applies_to_england_wales_crown: boolean
      numeric_effect_used_in_simulator: boolean
      used_number?: string
      limitation: string
    }[]
  }[]
}

export type Validation = {
  accounting_mae: number
  previous_flow_mae: number
  one_step_mae: number
  frozen_forecast_mae: number
  frozen_from: string
  frozen_through: string
  frozen_quarters: number
  national_open: number
  national_period: string
  courts: number
  test_court_quarters: number
  train_court_quarters: number
  scores: { key: string; model: string; mae_pp: number; weighted_mae_pp: number }[]
  best_benchmark: { key: string; model: string; mae_pp: number; weighted_mae_pp: number }
  blend_vs_average_pp: number
  lightgbm_vs_average_pp: number
  blend_vs_last_quarter_pp: number
  honesty: { n: number; title: string; body: string }[]
}

export type Backtest = {
  horizon: number
  model: string
  model_label: string
  court: string | null
  unit: string
  kpis: {
    trial_weighted_mae: number
    selected_weighted_mae: number
    selected_delta_vs_last_quarter: number
    one_quarter_backlog_mae: number
    eight_quarter_backlog_mae: number
    eight_quarter_window: string
    best_benchmark: { key: string; model: string; weighted_mae_pp: number }
    coverage_courts: number
    spark_rate_mae: number[]
    spark_backlog_1: number[]
    spark_backlog_8: number[]
  }
  series: { period: string; actual: number; predicted: number }[]
  band_sd: number
  band_label: string
  histogram: { bin_left: number; bin_right: number; mid: number; count: number }[]
  largest_errors: { court: string; mae: number }[]
  best_court: { court: string; mae: number }
  worst_court: { court: string; mae: number }
  per_court: { court: string; mae: number }[]
  model_comparison: {
    key: string
    model: string
    mae_pp: number
    weighted_mae_pp: number
    best: boolean
  }[]
  note: string
  execution?: {
    source: "fresh" | "cache" | "startup_cache"
    kind?: string
    cutoff?: string
    computed_at?: string | null
    elapsed_ms?: number | null
    train_from?: string
    train_through?: string
    test_from?: string
    test_through?: string
    test_rows?: number
    model_version?: string
    blend_weight_fit_on_test?: boolean
    sitting_days_used?: boolean
    sitting_days_note?: string
    leakage_check?: string
    note?: string
    one_quarter_mae?: number
    horizon_mae?: number
    error_by_step?: { step: number; mae: number }[]
  }
  live: {
    court: string
    period: string
    inputs: Record<string, number | null>
    model_rate: number
    four_quarter_average: number
    predicted_rate: number
    drivers: Driver[]
  }
  honesty: { n: number; title: string; body: string }[]
  scenario_validation: {
    accounting_mae: number
    previous_flow_mae: number
    one_step_mae: number
    frozen_forecast_mae: number
    national: { period: string; actual: number; predicted: number }[]
    statement: string
  }
}

export type National = {
  budget: number
  curve: { budget: number; open_cases: number }[]
  baseline_open_8q: number
  stop_growth_per_year: number
  stop_growth_2y: number
  return_2019: number
  top15: { court: string; cases_per_1m: number }[]
  allocation: {
    court: string
    gbp: number
    days_per_year: number
    cases_cleared: number
    funded_to_cap: boolean
  }[]
  leftover: number
  day_cost: number
  day_split_assumed: boolean
  national_days: number
}

export type TrialRow = {
  court: string
  date: string
  custody: boolean
  defence_confirmed: boolean
  cps_served: boolean
  witnesses_confirmed: boolean
  floater?: boolean
  score: number
  band: string
  suggested_action: string
  predicted_rate?: number
  heuristic?: boolean
}

export type LeverSpec = {
  key: string
  label: string
  cost_per_unit: number
  unit: string
  default_effect: number
  assumed: boolean
  source: string
}

export type Levers = {
  sitting_days: number
  overlisting: number
  prosecution: number
  prisoner_not_produced: number
  defence_advocate: number
  judge: number
}

export const DEFAULT_LEVERS: Levers = {
  sitting_days: 5,
  overlisting: 25,
  prosecution: 25,
  prisoner_not_produced: 25,
  defence_advocate: 0,
  judge: 0,
}

export type Charge = "horizon" | "once"

export type LeverResult = {
  lever: string
  label: string
  cut: number
  unit: string
  days_per_year: number | null
  days_over_horizon: number | null
  quarterly_trials: number | null
  avoided_per_quarter: number | null
  disposals_per_quarter: number | null
  spend_8q: number
  status: string
  reason: string
}
