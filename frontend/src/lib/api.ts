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

async function apiError(res: Response): Promise<ApiError> {
  let detail = res.statusText
  try {
    const body = (await res.json()) as { detail?: unknown }
    if (typeof body.detail === "string") detail = body.detail
    // FastAPI validation errors: [{ msg, loc }, ...]
    else if (Array.isArray(body.detail) && body.detail[0]?.msg)
      detail = String(body.detail[0].msg)
  } catch {
    // Non-JSON error body (e.g. a proxy page); keep statusText.
  }
  return new ApiError(res.status, `${res.status} ${detail}`.trim())
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
  if (!res.ok) throw await apiError(res)
  return (await res.json()) as T
}

async function sendJson<T>(
  method: "PUT" | "POST",
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) throw await apiError(res)
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

// ---- Weather Underground upload --------------------------------------------

/** One upload field: the value that would be sent now, or why it is left out. */
export interface WundergroundField {
  /** WU parameter name, e.g. "tempf". */
  field: string
  label: string
  value: number | null
  unit: string
  source: string
  /** Reason the field is left out of the upload; null when it is sent. */
  skipped: string | null
}

/** Upload settings and status. The station key is never returned. */
export interface WundergroundConfig {
  enabled: boolean
  station_id: string
  has_key: boolean
  interval_s: number
  elevation_m: number | null
  last_attempt_at: string | null
  last_success_at: string | null
  /** "success", "error: ...", "skipped: ..." or "dry run: ..." */
  last_result: string | null
  last_payload: Record<string, number> | null
  next_upload_at: string | null
  /** True in simulate mode: uploads are built but never sent. */
  dry_run: boolean
  fields: WundergroundField[]
}

/** Partial update. A blank or missing station_key keeps the stored key. */
export interface WundergroundUpdate {
  enabled?: boolean
  station_id?: string
  station_key?: string
  /** 60..3600 */
  interval_s?: number
  elevation_m?: number | null
}

export const wundergroundApi = {
  get: (signal?: AbortSignal) =>
    getJson<WundergroundConfig>("/api/v1/wunderground", {}, signal),
  update: (body: WundergroundUpdate) =>
    sendJson<WundergroundConfig>("PUT", "/api/v1/wunderground", body),
  uploadNow: () =>
    sendJson<WundergroundConfig>("POST", "/api/v1/wunderground/upload"),
}
