import { keepPreviousData, useQuery } from "@tanstack/react-query"

import { type ReadingHistory, readingsApi } from "@/lib/api"

/** Time ranges offered by the sensor charts. */
export const RANGES = {
  "5m": { label: "5 m", minutes: 5, refetchMs: 2_000, tickMs: 60_000 },
  "1h": { label: "1 h", minutes: 60, refetchMs: 5_000, tickMs: 10 * 60_000 },
  "24h": {
    label: "24 h",
    minutes: 1440,
    refetchMs: 5_000,
    tickMs: 4 * 3_600_000,
  },
} as const

export type RangeKey = keyof typeof RANGES

export function useHistory(sensor: string, metric: string, range: RangeKey) {
  const { minutes, refetchMs } = RANGES[range]
  return useQuery({
    queryKey: ["history", sensor, metric, minutes],
    queryFn: ({ signal }) =>
      readingsApi.history({ sensor, metric, minutes }, signal),
    refetchInterval: refetchMs,
    // Hold the previous render while a new range loads (no flash).
    placeholderData: keepPreviousData,
  })
}

/** Sample (1 s) or bucket step of a history response, in ms. */
export function stepMsOf(...histories: (ReadingHistory | undefined)[]) {
  const bucketS = histories.find((h) => h?.bucket_s)?.bucket_s ?? null
  return (bucketS ?? 1) * 1_000
}

/**
 * Sort rows by time and insert an empty row wherever samples are missing for
 * more than 2.5 steps, so a collector outage shows as a gap rather than a
 * straight line bridging it.
 */
export function withGaps<R extends { t: number }>(
  rows: Iterable<R>,
  stepMs: number,
  empty: (t: number) => R,
): R[] {
  const maxGapMs = stepMs * 2.5
  const sorted = [...rows].sort((a, b) => a.t - b.t)
  const out: R[] = []
  for (const r of sorted) {
    const prev = out[out.length - 1]
    if (prev && r.t - prev.t > maxGapMs) out.push(empty(prev.t + 1))
    out.push(r)
  }
  return out
}

export function makeTicks(start: number, end: number, step: number) {
  const ticks: number[] = []
  for (let t = Math.ceil(start / step) * step; t <= end; t += step) {
    ticks.push(t)
  }
  return ticks
}
