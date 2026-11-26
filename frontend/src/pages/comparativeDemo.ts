/**
 * Fully isolated, deterministic demonstration fixture for the Comparative
 * Results presentation. These generated values are illustrative only and are
 * never sent to an API, persisted, or made available through empirical export.
 */
export const demoScenarios = [
  { id: 'difference', label: 'Difference contribution inference', target: 'Synthetic individual contribution' },
  { id: 'repeated', label: 'Repeated aggregate reconstruction', target: 'Synthetic population aggregate' },
  { id: 'fixed_narrowing', label: 'Fixed-script cohort narrowing', target: 'Synthetic cohort count' },
  { id: 'adaptive_narrowing', label: 'Adaptive sequential narrowing', target: 'Synthetic cohort count' },
  { id: 'overlapping', label: 'Overlapping aggregate reconstruction', target: 'Synthetic cohort intersection' },
] as const

export const demoBaselineIds = ['M0', 'M1', 'M2', 'M3', 'M4', 'M5'] as const
export type DemoScenarioId = typeof demoScenarios[number]['id']

export type DemoObservation = {
  replicate: number
  trial: number
  baseline: typeof demoBaselineIds[number]
  attackSuccess: boolean
  attackError: number
  normalizedError: number
  aggregateMae: number
  aggregateRmse: number
  nominalEpsilon: number
  budgetUtilization: number | null
  independentReleases: number
  cacheHits: number
  cacheMisses: number
  requests: number
  rejections: number
  answerability: number
  latencyMs: number
  riskScore: number | null
  historyOverlap: number | null
  selectedEpsilon: number | null
}

const scenarioProfiles: Record<DemoScenarioId, { success: number[]; errorScale: number; targetScale: number; requests: number }> = {
  difference: { success: [.96, .48, .48, .40, .43, .36], errorScale: 1.1, targetScale: 120_000, requests: 2 },
  repeated: { success: [.92, .55, .59, .48, .45, .39], errorScale: 1.8, targetScale: 8_000_000, requests: 8 },
  fixed_narrowing: { success: [.88, .46, .45, .42, .43, .38], errorScale: 2.4, targetScale: 80, requests: 3 },
  adaptive_narrowing: { success: [.91, .51, .50, .44, .46, .35], errorScale: 2.2, targetScale: 80, requests: 5 },
  overlapping: { success: [.89, .49, .50, .43, .46, .40], errorScale: 2.0, targetScale: 1_200_000, requests: 3 },
}

const methodErrorScale = [0, 1, 1, .92, .98, 1.24]
const methodSpendScale = [0, 1, 1, .78, 1, .83]
const methodCacheHitBase = [0, 0, 0, 0, .74, .67]
const methodLatencyBase = [1.1, 2.1, 2.2, 2.5, 2.7, 3.4]

function stableUnit(seed: string): number {
  let value = 2166136261
  for (let index = 0; index < seed.length; index += 1) value = Math.imul(value ^ seed.charCodeAt(index), 16777619)
  value += value << 13; value ^= value >>> 7; value += value << 3; value ^= value >>> 17; value += value << 5
  return (value >>> 0) / 0x1_0000_0000
}

export function buildIllustrativeCampaign(): Record<DemoScenarioId, DemoObservation[]> {
  const campaign = {} as Record<DemoScenarioId, DemoObservation[]>
  for (const scenario of demoScenarios) {
    const profile = scenarioProfiles[scenario.id]
    const observations: DemoObservation[] = []
    for (let replicate = 1; replicate <= 4; replicate += 1) {
      for (let trial = 1; trial <= 12; trial += 1) {
        for (let method = 0; method < demoBaselineIds.length; method += 1) {
          const baseline = demoBaselineIds[method]
          const key = `${scenario.id}:${replicate}:${trial}:${baseline}`
          const populationShift = .83 + replicate * .075
          const noise = .72 + stableUnit(`${key}:error`) * .72
          const unprotected = method === 0
          const aggregateMae = unprotected ? 0 : profile.errorScale * methodErrorScale[method] * populationShift * noise
          const normalizedError = aggregateMae / profile.errorScale
          const success = stableUnit(`${key}:attack`) < profile.success[method] * (.92 + replicate * .035)
          const requests = profile.requests
          const cacheHits = scenario.id === 'repeated' ? Math.min(requests - 1, Math.round(methodCacheHitBase[method] * requests)) : 0
          const independentReleases = unprotected ? 0 : requests - cacheHits
          const budgetUtilization = unprotected ? null : Math.min(1, methodSpendScale[method] * (.68 + stableUnit(`${key}:budget`) * .28))
          const rejections = method === 2 && scenario.id === 'repeated' && stableUnit(`${key}:reject`) > .76 ? 1 : 0
          const answerability = Math.max(0, (requests - rejections) / requests)
          const riskScore = baseline === 'M5' ? .22 + stableUnit(`${key}:risk`) * .7 : null
          const historyOverlap = baseline === 'M5' ? stableUnit(`${key}:history`) : null
          const selectedEpsilon = baseline === 'M5' ? .18 + stableUnit(`${key}:epsilon`) * .3 : baseline === 'M0' ? null : .5 * (method === 3 ? .78 : 1)
          observations.push({
            replicate, trial, baseline, attackSuccess: success,
            attackError: profile.targetScale * normalizedError * (.28 + stableUnit(`${key}:attack-error`) * .22),
            normalizedError, aggregateMae, aggregateRmse: aggregateMae * (1.12 + stableUnit(`${key}:rmse`) * .22),
            nominalEpsilon: unprotected ? 0 : methodSpendScale[method] * (.38 + stableUnit(`${key}:spend`) * .16),
            budgetUtilization, independentReleases, cacheHits, cacheMisses: Math.max(0, requests - cacheHits - rejections), requests,
            rejections, answerability, latencyMs: methodLatencyBase[method] * (.82 + stableUnit(`${key}:latency`) * .48),
            riskScore, historyOverlap, selectedEpsilon,
          })
        }
      }
    }
    campaign[scenario.id] = observations
  }
  return campaign
}

