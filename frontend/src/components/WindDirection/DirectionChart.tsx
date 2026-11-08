import { useMemo } from "react"
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import {
  makeTicks,
  RANGES,
  type RangeKey,
  stepMsOf,
  useHistory,
  withGaps,
} from "@/components/Charts/history"
import { parseTs, type ReadingHistory } from "@/lib/api"
import { compassPoint, fmtClock } from "@/lib/format"
import { cn } from "@/lib/utils"

type Row = { t: number; deg: number | null }

const Y_TICKS = [0, 90, 180, 270, 360]

/**
 * Bearing per timestamp from the sin/cos components. Bucketed ranges average
 * the components server-side, and atan2 of those averages is the correct mean
 * direction (a plain average of degrees breaks across north: 350 and 10 would
 * give 180).
 */
function toRows(
  sin: ReadingHistory | undefined,
  cos: ReadingHistory | undefined,
): Row[] {
  const stepMs = stepMsOf(sin, cos)
  const snap = (ts: string) => Math.round(parseTs(ts) / stepMs) * stepMs
  const cosAt = new Map<number, number>()
  for (const p of cos?.points ?? []) cosAt.set(snap(p.ts), p.value)

  const points: Row[] = []
  for (const p of sin?.points ?? []) {
    const t = snap(p.ts)
    const c = cosAt.get(t)
    if (c === undefined || Math.hypot(p.value, c) < 1e-6) continue
    const deg = ((Math.atan2(p.value, c) * 180) / Math.PI + 360) % 360
    points.push({ t, deg })
  }
  const rows = withGaps(points, stepMs, (t) => ({ t, deg: null }))

  // Break the line where it crosses north, instead of drawing a vertical
  // stroke from 359 down to 1.
  const out: Row[] = []
  for (const r of rows) {
    const prev = out[out.length - 1]
    if (
      prev?.deg != null &&
      r.deg != null &&
      Math.abs(r.deg - prev.deg) > 180
    ) {
      out.push({ t: (prev.t + r.t) / 2, deg: null })
    }
    out.push(r)
  }
  return out
}

interface DirectionChartProps {
  sensor: string
  range: RangeKey
}

export function DirectionChart({ sensor, range }: DirectionChartProps) {
  const sinQ = useHistory(sensor, "direction_sin", range)
  const cosQ = useHistory(sensor, "direction_cos", range)
  const cfg = RANGES[range]
  const withSeconds = range === "5m"

  const rows = useMemo(
    () => toRows(sinQ.data, cosQ.data),
    [sinQ.data, cosQ.data],
  )

  const end = sinQ.dataUpdatedAt || Date.now()
  const start = end - cfg.minutes * 60_000
  const ticks = useMemo(
    () => makeTicks(start, end, cfg.tickMs),
    [start, end, cfg.tickMs],
  )

  const hasData = rows.some((r) => r.deg !== null)
  let overlay: string | null = null
  if (sinQ.isError && !sinQ.data)
    overlay = "History unavailable: API unreachable"
  else if (sinQ.isPending) overlay = "Loading…"
  else if (!hasData) overlay = `No readings in the last ${cfg.label}`

  return (
    <div className="flex flex-col gap-3">
      {sinQ.data?.bucket_s ? (
        <span className="text-muted-foreground text-xs">
          {Math.round(sinQ.data.bucket_s)} s buckets (vector average)
        </span>
      ) : null}
      <div
        className={cn(
          "relative h-56 w-full transition-opacity sm:h-64",
          (sinQ.isPlaceholderData || cosQ.isPlaceholderData) && "opacity-60",
        )}
        data-testid="direction-chart"
      >
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={rows}
            margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
          >
            <CartesianGrid
              vertical={false}
              stroke="var(--chart-grid)"
              strokeWidth={1}
            />
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={[start, end]}
              ticks={ticks}
              allowDataOverflow
              tickFormatter={(t: number) => fmtClock(t, withSeconds)}
              stroke="var(--chart-axis)"
              tick={{ fill: "var(--chart-tick)", fontSize: 12 }}
              tickLine={false}
              minTickGap={24}
            />
            <YAxis
              domain={[0, 360]}
              ticks={Y_TICKS}
              tickFormatter={(v: number) => compassPoint(v)}
              width={32}
              stroke="var(--chart-axis)"
              tick={{ fill: "var(--chart-tick)", fontSize: 12 }}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              cursor={{ stroke: "var(--chart-axis)", strokeWidth: 1 }}
              isAnimationActive={false}
              content={({ active, label, payload }) => {
                if (!active || !payload?.length || typeof label !== "number")
                  return null
                const v = payload[0]?.value
                if (typeof v !== "number") return null
                return (
                  <div className="rounded-md border bg-popover px-3 py-2 text-xs shadow-md">
                    <div className="text-muted-foreground mb-1">
                      {fmtClock(label, withSeconds)}
                    </div>
                    <div className="flex items-center gap-2">
                      <span
                        className="inline-block h-0.5 w-3 rounded-full"
                        style={{ backgroundColor: "var(--series-1)" }}
                      />
                      <span className="font-semibold text-popover-foreground tabular-nums">
                        {Math.round(v)}° {compassPoint(v)}
                      </span>
                      <span className="text-muted-foreground">Wind from</span>
                    </div>
                  </div>
                )
              }}
            />
            <Line
              dataKey="deg"
              name="Wind from"
              type="linear"
              stroke="var(--series-1)"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              dot={false}
              activeDot={{ r: 4, stroke: "var(--card)", strokeWidth: 2 }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
        {overlay && (
          <div className="text-muted-foreground pointer-events-none absolute inset-0 flex items-center justify-center text-sm">
            {overlay}
          </div>
        )}
      </div>
    </div>
  )
}
