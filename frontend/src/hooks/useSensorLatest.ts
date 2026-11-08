import { useQuery } from "@tanstack/react-query"

import type { CollectorState } from "@/components/Sensors/CollectorStatus"
import { readingsApi } from "@/lib/api"

/**
 * Poll the newest readings for one sensor every second and derive the
 * collector badge state from them. Shared by all sensor pages.
 */
export function useSensorLatest(sensor: string) {
  const query = useQuery({
    queryKey: ["latest", sensor],
    queryFn: ({ signal }) => readingsApi.latest(sensor, signal),
    refetchInterval: 1_000,
  })

  const data = query.data
  const metrics: Record<string, number> = data?.metrics ?? {}
  const hasReading = data?.ts != null

  let state: CollectorState
  if (query.isError) state = "offline"
  else if (query.isPending) state = "loading"
  else if (!hasReading) state = "empty"
  else if (data?.stale) state = "stale"
  else state = "live"

  // Server age at fetch time plus time since that fetch, so the age keeps
  // growing while the API is unreachable (failed polls still re-render).
  const ageS =
    data?.age_s != null
      ? Math.max(data.age_s + (Date.now() - query.dataUpdatedAt) / 1000, 0)
      : null

  return { query, metrics, state, ageS, hasReading }
}
