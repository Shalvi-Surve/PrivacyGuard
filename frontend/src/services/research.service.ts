import { API_BASE, ApiError, apiRequest } from './api'

export type AttackScenario = 'difference' | 'repeated' | 'narrowing' | 'overlapping'
export type ResearchBaseline = 'M0' | 'M1' | 'M2' | 'M3' | 'M4' | 'M5' | 'B0' | 'B1' | 'B2' | 'B3' | 'B4'
export type ExperimentConfig = {
  scenario: AttackScenario
  dataset_size: number
  baselines: ResearchBaseline[]
  trials: number
  repetitions: number
  repeat_query_mode: 'identical' | 'equivalent_variants'
  seed: number
  epsilon: number
  budget_epsilon: number
  adaptive_epsilon_min?: number
  adaptive_risk_penalty?: number
  adaptive_cumulative_penalty?: number
  attack_relative_success_tolerance?: number
  narrowing_absolute_success_tolerance?: number
  trial_seed_strategy?: 'matched_sequential' | 'matched_hashed'
  history_depth?: 0 | 5 | 10 | 25 | 50
  ablation_mode?: 'full' | 'no_history_overlap' | 'no_repetition' | 'no_predicate_narrowing' | 'no_query_type'
  metric_definition_version?: string
  baseline_definition_version?: string
  experiment_engine_version?: string
  workload_definition_version?: string
  attack_definition_version?: string
  mechanism_version?: string
  trial_seed_schedule?: { strategy: string; seed: number; derivation: string; shared_across_baselines: boolean; trial_seeds?: number[] }
  protocol_version?: string
  protocol?: Record<string, any>
  quality_control?: QualityControl
}
export type QualityControl = { status: 'valid_completed' | 'completed_with_warnings' | 'partial' | 'invalid' | 'failed'; reasons: string[]; inferentially_eligible: boolean }
export type TrialMeasurement = {
  trial: number
  trial_seed?: number
  request_count: number
  independent_releases: number
  exact_cache_hits?: number
  nominal_epsilon_spent: number
  budget_utilization: number
  attack_absolute_error: number | null
  attack_relative_error: number | null
  attack_observation_count?: number
  attack_independent_observation_count?: number
  unique_attack_observation_count?: number
  unique_noise_sample_count?: number
  attack_estimator_version?: string
  attack_success_threshold?: number
  attack_success: boolean | null
  attack_evidence?: { evidence_scope: string; target_reference_id: string; target_value: number; inferred_value: number; absolute_error: number; relative_error_fraction: number | null; relative_error_denominator: number | null; success_threshold: number; success: boolean; estimator_version?: string; attack_observation_count?: number; attack_independent_observation_count?: number; unique_attack_observation_count?: number; unique_noise_sample_count?: number; observation_source_ids?: string[] } | null
  small_group_exposure: boolean | null
  aggregate_mae: number | null
  aggregate_rmse: number | null
  aggregate_median_absolute_error?: number | null
  query_latency_ms_mean: number
  query_latency_ms_median?: number | null
  query_latency_ms_p95?: number | null
  query_latency_ms_standard_deviation?: number | null
  history_lookup_ms_mean?: number
  risk_policy_ms_mean?: number
  release_execution_ms_mean?: number
  persistence_ms?: number | null
  latency_measurement_scope?: string
  engine_runtime_ms?: number
  campaign_engine_runtime_ms?: number
  middleware_overhead_ms_mean: number
  rejected_requests: number
  elapsed_ms: number
}
export type BaselineMetrics = {
  baseline: ResearchBaseline
  baseline_name: string
  protocol_version?: string
  attack_objective?: string
  scenario_definition?: Record<string, string | number>
  metric_definition_version?: string
  trial_count: number
  nominal_cumulative_epsilon: number
  mean_nominal_epsilon_per_trial: number
  independent_releases: number
  attack_estimator_version?: string
  attack_observation_count?: number
  attack_independent_observation_count?: number
  unique_attack_observation_count?: number
  unique_noise_sample_count?: number
  exact_cache_hits?: number
  exact_cache_hit_rate?: number
  exact_cache_reuse_consistent?: boolean
  query_answerability_rate?: number | null
  legitimate_query_rejection_rate?: number | null
  budget_rejection_rate?: number | null
  initial_nominal_budget_per_trial?: number
  remaining_nominal_budget_per_trial_mean?: number
  budget_utilization_percentage?: number | null
  attack_success_count?: number | null
  attack_attempt_count?: number
  attack_success_standard_deviation?: number | null
  attack_success_ci95?: [number | null, number | null]
  inference_rmse?: number | null
  inference_error_median?: number | null
  cold_start_attack_success_rate?: number | null
  attack_success_rate: number | null
  inference_absolute_error: number | null
  inference_error_standard_deviation: number | null
  inference_error_ci95: [number | null, number | null]
  relative_inference_error: number | null
  small_group_exposure_rate: number | null
  aggregate_mae: number | null
  aggregate_rmse: number | null
  aggregate_median_absolute_error?: number | null
  aggregate_error_standard_deviation?: number
  aggregate_error_ci95?: [number | null, number | null]
  aggregate_rmse_trial_mean?: number
  aggregate_rmse_trial_median?: number | null
  aggregate_rmse_standard_deviation?: number
  aggregate_rmse_ci95?: [number | null, number | null]
  aggregate_relative_error: number | null
  query_latency_ms_mean: number
  query_latency_ms_median?: number | null
  query_latency_ms_p95?: number | null
  query_latency_ms_standard_deviation?: number | null
  query_latency_ms_ci95?: [number | null, number | null]
  history_lookup_ms_mean?: number
  risk_policy_ms_mean?: number
  release_execution_ms_mean?: number
  persistence_ms?: number | null
  latency_measurement_scope?: string
  engine_runtime_ms?: number
  campaign_engine_runtime_ms?: number
  middleware_overhead_ms_mean: number
  throughput_requests_per_second: number
  estimated_dataset_memory_bytes: number
  mean_risk_score: number | null
  mean_selected_epsilon: number | null
  mean_history_overlap: number | null
  mean_repetition_signal: number | null
  mean_budget_utilization: number
  rejected_requests: number
  accounting_status: string
  privacy_guarantee_status: string
  measurements: TrialMeasurement[]
  metric_states?: Record<string, { state: 'MEASURED' | 'NOT_MEASURED' | 'INVALID' | 'PENDING' | 'NOT_APPLICABLE'; reason: string | null }>
  rejection_category_coverage?: Record<string, { state: string; reason: string | null }>
  request_measurements: { trial: number; request_index: number; query_key: string; request_status: string; observation_id?: string | null; attack_source_id?: string | null; release_id?: string | null; noise_sample_id?: string | null; selected_epsilon: number | null; epsilon_charged: number; cumulative_epsilon_spent?: number; aggregate_absolute_error: number | null; aggregate_relative_error: number | null; risk_score: number; history_overlap: number; repetition_signal: number; latency_ms: number }[]
  measurement_note: string
  statistical_note: string
  attack_metric_scope_note?: string
}
export type ResearchRun = {
  id: number
  name: string
  configuration: ExperimentConfig
  seed: number
  status: 'running' | 'completed' | 'failed' | string
  created_at: string
  results: { id: number; baseline: ResearchBaseline; baseline_name: string; metrics: BaselineMetrics; validation_report?: { status: 'PASS' | 'WARNING' | 'FAIL' | 'UNVERIFIABLE'; findings: { status: string; severity: string; field: string; description: string; expected: string; observed: string }[] } }[]
  validation_report?: { status: 'PASS' | 'WARNING' | 'FAIL' | 'UNVERIFIABLE'; findings: { status: string; severity: string; field: string; description: string; expected: string; observed: string }[]; summary: { errors: number; warnings: number; unverifiable: number } }
  quality_control?: QualityControl
  paired_comparisons?: {
    version: string
    status: 'AVAILABLE' | 'UNAVAILABLE' | 'INCOMPATIBLE'
    reference_baseline: string
    reason?: string
    protocol_version?: string
    minimum_trials_for_inferential_label?: number
    multiple_testing_correction?: string
    comparisons: {
      reference_baseline: string; baseline: string; metric: string; direction: string; n_pairs: number
      reference_mean: number | null; baseline_mean: number | null; mean_difference_baseline_minus_reference: number | null
      median_paired_difference: number | null; ci95_mean_difference: [number | null, number | null]
      effect_size_paired_dz: number | null; discordant_reference_only_successes: number | null
      discordant_baseline_only_successes: number | null; raw_p_value: number | null; holm_adjusted_p_value?: number | null
      statistically_significant_after_holm?: boolean | null; status: 'exploratory' | 'tested'; method: string; assumptions: string
    }[]
  }
}
export type ResearchRunList = { items: Omit<ResearchRun, 'results'>[]; total: number; page: number; page_size: number }
export type BenchmarkResultPage = { items: ResearchRun[]; total: number; page: number; page_size: number }
export type BenchmarkRunSummary = Pick<ResearchRun, 'id' | 'name' | 'configuration' | 'seed' | 'status' | 'created_at'>
export type BenchmarkRunSummaryPage = { items: BenchmarkRunSummary[]; total: number; page: number; page_size: number }

export function runExperiment(config: ExperimentConfig, token: string, attack = false) {
  const path = attack ? '/api/attacks/simulate' : '/api/experiments/runs'
  // Synthetic evaluations are synchronous and can exceed the ordinary 8 s API
  // timeout at the larger supported workload sizes.
  return apiRequest<ResearchRun>(path, { method: 'POST', body: JSON.stringify(config), signal: AbortSignal.timeout(120000) }, token)
}

export function listExperimentRuns(token: string, page = 1, pageSize = 20) {
  return apiRequest<ResearchRunList>(`/api/experiments/runs?page=${page}&page_size=${pageSize}`, {}, token)
}

export function getExperimentRun(runId: number, token: string) {
  // A single run detail response validates persisted trial evidence and
  // reconstructs its paired analysis; give this read endpoint room to finish.
  return apiRequest<ResearchRun>(`/api/experiments/runs/${runId}`, { signal: AbortSignal.timeout(30000) }, token)
}

export function getBenchmarkResults(token: string, filters: { page?: number; page_size?: number; scenario?: string; dataset_size?: number; baseline?: string; trials?: number; run_id?: number; date_from?: string; date_to?: string } = {}) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) if (value !== undefined && value !== '') query.set(key, String(value))
  return apiRequest<BenchmarkResultPage>(`/api/experiments/benchmark-results?${query}`, {}, token)
}

export function getBenchmarkRunSummaries(token: string, filters: { page?: number; page_size?: number; scenario?: string; dataset_size?: number; baseline?: string; trials?: number; run_id?: number; date_from?: string; date_to?: string } = {}) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) if (value !== undefined && value !== '') query.set(key, String(value))
  return apiRequest<BenchmarkRunSummaryPage>(`/api/experiments/benchmark-runs?${query}`, {}, token)
}

export async function downloadExperimentCsv(runId: number, token: string) {
  let response: Response
  try {
    response = await fetch(`${API_BASE}/api/experiments/runs/${runId}/export.csv`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(15000),
    })
  } catch {
    throw new ApiError('Could not reach the PrivacyGuard API. Check the backend connection.')
  }
  if (!response.ok) {
    if (response.status === 401 && typeof window !== 'undefined') window.dispatchEvent(new Event('privacyguard:unauthorized'))
    throw new ApiError(response.status === 403 ? 'Your role is not authorized to export this experiment.' : response.status === 404 ? 'The experiment run was not found.' : `CSV export failed (${response.status}).`, response.status)
  }
  return response.blob()
}
