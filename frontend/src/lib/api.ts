// Small hand-written client for the weather-station API.
// URLs are relative so the dashboard works wherever the backend serves it
// (e.g. http://raspberrypi.local:8000). Set VITE_API_URL only to point a dev
// build at another host; `bun run dev` proxies /api to the backend instead.
const API_BASE = import.meta.env.VITE_API_URL ?? ""

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

type QueryParams = Record<string, string | number | undefined>

async function getJson<T>(
  path: string,
  params: QueryParams = {},
  signal?: AbortSignal,
): Promise<T> {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value))
  }
  const qs = search.toString()
  const url = `${API_BASE}${path}${qs ? `?${qs}` : ""}`

  const res = await fetch(url, {
    headers: { Accept: "application/json" },
    signal,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body.detail === "string") detail = body.detail
    } catch {
      // Non-JSON error body (e.g. a proxy page); keep statusText.
    }
    throw new ApiError(res.status, `${res.status} ${detail}`.trim())
  }
  return (await res.json()) as T
}

/** Parse an API timestamp. Treats a zone-less ISO string as UTC. */
export function parseTs(ts: string): number {
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(ts)
  return Date.parse(hasZone ? ts : `${ts}Z`)
}

// ---- Types (mirror backend/app/models.py) --------------------------------

export type AnemometerMetric =
  | "wind_speed_mph"
  | "wind_gust_mph"
  | "pulse_hz"
  | "rpm"
  | "pulse_count"
  | "pulse_total"
  | "do_active"
  | "secs_since_pulse"

/** Barometer (Grove SPA06-003) metrics, stored in SI units. */
export type BarometerMetric =
  | "pressure_hpa"
  | "temperature_c"
  | "altitude_m"
  /** Only present when BAROMETER_STATION_ALTITUDE_M is set on the backend. */
  | "sea_level_pressure_hpa"

/** Air quality (Grove SCD41) metrics, stored in SI units. */
export type AirQualityMetric =
  | "co2_ppm"
  | "temperature_c"
  | "humidity_pct"
  | "dew_point_c"

/** Wind vane (KY-040 rotary encoder) metrics. Directions are bearings the
 * wind comes FROM, in degrees (0 = N). */
export type WindVaneMetric =
  | "direction_deg"
  | "direction_avg_deg"
  /** sin/cos of direction_deg: average these, then atan2, for a mean bearing. */
  | "direction_sin"
  | "direction_cos"
  | "position"
  | "calibrated"

export interface LatestReadings {
  sensor: string
  ts: string | null
  age_s: number | null
  stale: boolean
  metrics: Record<string, number>
}

export interface HistoryPoint {
  ts: string
  value: number
  /** Bucket maximum; null for raw (un-bucketed) points. */
  max: number | null
}

export interface ReadingHistory {
  sensor: string
  metric: string
  /** Bucket width in seconds, or null when points are raw samples. */
  bucket_s: number | null
  points: HistoryPoint[]
}

// ---- Endpoints -------------------------------------------------------------

export const readingsApi = {
  latest: (sensor: string, signal?: AbortSignal) =>
    getJson<LatestReadings>("/api/v1/readings/latest", { sensor }, signal),

  history: (
    params: { sensor: string; metric: string; minutes: number },
    signal?: AbortSignal,
  ) => getJson<ReadingHistory>("/api/v1/readings/history", params, signal),
}
