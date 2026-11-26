export type MetricState = 'MEASURED' | 'NOT_MEASURED' | 'INVALID' | 'PENDING' | 'NOT_APPLICABLE'
export type MetricStateInfo = { state: MetricState; reason?: string | null }

/** Format research values without conflating a measured zero with missing data. */
export function formatMetricValue(value: number | null | undefined, state?: MetricStateInfo, format: (value: number) => string = number => number.toLocaleString(undefined, { maximumFractionDigits: 3 })) {
  if (state?.state === 'INVALID') return 'Invalid measurement'
  if (state?.state === 'NOT_APPLICABLE') return 'N/A · not applicable'
  if (state?.state === 'PENDING') return 'Pending'
  if (state?.state === 'NOT_MEASURED') return 'N/A'
  if (value == null || !Number.isFinite(value)) return 'N/A'
  return format(value)
}
