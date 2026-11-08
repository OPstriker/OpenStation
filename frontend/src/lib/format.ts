export const EMPTY = "—"

/** Fixed-decimal number, or an em dash when missing / not finite. */
export function fmtNumber(value: number | undefined | null, digits = 1) {
  if (value === undefined || value === null || !Number.isFinite(value)) {
    return EMPTY
  }
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

/** Human duration: "4.2 s", "3m 20s", "2h 5m". */
export function fmtDuration(seconds: number | undefined | null) {
  if (seconds === undefined || seconds === null || !Number.isFinite(seconds)) {
    return EMPTY
  }
  if (seconds < 60) return `${seconds.toFixed(1)} s`
  const s = Math.floor(seconds)
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`
  if (s < 86400)
    return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`
}

export function fmtClock(ms: number, withSeconds: boolean) {
  return new Date(ms).toLocaleTimeString([], {
    hourCycle: "h23",
    hour: "2-digit",
    minute: "2-digit",
    second: withSeconds ? "2-digit" : undefined,
  })
}

/** Degrees Celsius to Fahrenheit. */
export function cToF(c: number) {
  return (c * 9) / 5 + 32
}

/** Metres to feet. */
export function mToFt(m: number) {
  return m / 0.3048
}

const COMPASS_POINTS = [
  "N",
  "NNE",
  "NE",
  "ENE",
  "E",
  "ESE",
  "SE",
  "SSE",
  "S",
  "SSW",
  "SW",
  "WSW",
  "W",
  "WNW",
  "NW",
  "NNW",
]

/** 16-point compass name for a bearing in degrees (0 = N, 90 = E). */
export function compassPoint(deg: number | undefined | null) {
  if (deg === undefined || deg === null || !Number.isFinite(deg)) return EMPTY
  const i = Math.round((((deg % 360) + 360) % 360) / 22.5) % 16
  return COMPASS_POINTS[i]
}
