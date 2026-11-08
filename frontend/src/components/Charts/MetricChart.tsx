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

import { parseTs } from "@/lib/api"
import { EMPTY, fmtClock, fmtNumber } from "@/lib/format"
import { cn } from "@/lib/utils"
import {
  makeTicks,
  RANGES,
  type RangeKey,
  stepMsOf,
  useHistory,
  withGaps,
} from "./history"

type Row = { t: number; v: number | null }

interface MetricChartProps {
  sensor: string
  metric: string
  range: RangeKey
  /** Series name, used in the tooltip and data table. */
  label: string
  unit: string
  digits?: number
  /** Convert the stored value for display (e.g. degC -> degF). */
  transform?: (value: number) => number
  /** Smallest y-span shown, so sensor noise on a flat trace isn't magnified. */
  minSpan?: number
  color?: string
  testId?: string
}

/** A "nice" tick step (1, 2, 2.5 or 5 x 10^n) giving about `target` ticks. */
function niceStep(span: number, target = 4) {
  const raw = span / target
  const mag = 10 ** Math.floor(Math.log10(raw))
  const n = raw / mag
  const nice = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10
  return nice * mag
}

/**
 * Y scale following the data: the extent padded to at least minSpan, with
 * both ends on nice tick steps so labels are round numbers.
 */
function yScale(rows: Row[], minSpan: number) {
  let lo = Number.POSITIVE_INFINITY
  let hi = Number.NEGATIVE_INFINITY
  for (const r of rows) {
    if (r.v === null) continue
    lo = Math.min(lo, r.v)
    hi = Math.max(hi, r.v)
  }
  if (!Number.isFinite(lo)) return undefined
  const span = Math.max(hi - lo, minSpan)
  const mid = (lo + hi) / 2
  const pad = span * 0.1
  const step = niceStep(span + 2 * pad)
  const min = Math.floor((mid - span / 2 - pad) / step) * step
  const max = Math.ceil((mid + span / 2 + pad) / step) * step
  const ticks: number[] = []
  for (let t = min; t <= max + step / 2; t += step) {
    ticks.push(Number(t.toFixed(6)))
  }
  // Tick labels need as many decimals as the step has (2.5 -> 1, 0.25 -> 2).
  const decimals = Math.min((String(step).split(".")[1] ?? "").length, 3)
  return { domain: [min, max] as [number, number], ticks, decimals }
}

/**
 * Single-metric line chart over a time range. The y-axis follows the data
 * (pressure or temperature don't start at zero). Bucketed ranges plot each
 * bucket's average.
 */
export function MetricChart({
  sensor,
  metric,
  range,
  label,
  unit,
  digits = 1,
  transform,
  minSpan = 1,
  color = "var(--series-1)",
  testId,
}: MetricChartProps) {
  const q = useHistory(sensor, metric, range)
  const cfg = RANGES[range]
  const withSeconds = range === "5m"

  const rows = useMemo(() => {
    const stepMs = stepMsOf(q.data)
    const points: Row[] = (q.data?.points ?? []).map((p) => ({
      t: Math.round(parseTs(p.ts) / stepMs) * stepMs,
      v: transform ? transform(p.value) : p.value,
    }))
    return withGaps(points, stepMs, (t) => ({ t, v: null }))
  }, [q.data, transform])

  const y = useMemo(() => yScale(rows, minSpan), [rows, minSpan])

  // Slide the window with each refetch rather than on every render.
  const end = q.dataUpdatedAt || Date.now()
  const start = end - cfg.minutes * 60_000
  const ticks = useMemo(
    () => makeTicks(start, end, cfg.tickMs),
    [start, end, cfg.tickMs],
  )

  const hasData = rows.some((r) => r.v !== null)
  let overlay: string | null = null
  if (q.isError && !q.data) overlay = "History unavailable: API unreachable"
  else if (q.isPending) overlay = "Loading…"
  else if (!hasData) overlay = `No readings in the last ${cfg.label}`

  return (
    <div className="flex flex-col gap-3">
      {q.data?.bucket_s ? (
        <span className="text-muted-foreground text-xs">
          {Math.round(q.data.bucket_s)} s buckets (average)
        </span>
      ) : null}

      <div
        className={cn(
          "relative h-56 w-full transition-opacity sm:h-64",
          q.isPlaceholderData && "opacity-60",
        )}
        data-testid={testId}
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
              domain={y?.domain ?? ["auto", "auto"]}
              ticks={y?.ticks}
              allowDataOverflow
              tickFormatter={(v: number) => fmtNumber(v, y?.decimals ?? 0)}
              width={56}
              stroke="var(--chart-axis)"
              tick={{ fill: "var(--chart-tick)", fontSize: 12 }}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              cursor={{ stroke: "var(--chart-axis)", strokeWidth: 1 }}
              isAnimationActive={false}
              content={({ active, label: t, payload }) => {
                if (!active || !payload?.length || typeof t !== "number")
                  return null
                const v = payload[0]?.value
                return (
                  <div className="rounded-md border bg-popover px-3 py-2 text-xs shadow-md">
                    <div className="text-muted-foreground mb-1">
                      {fmtClock(t, withSeconds)}
                    </div>
                    <div className="flex items-center gap-2">
                      <span
                        className="inline-block h-0.5 w-3 rounded-full"
                        style={{ backgroundColor: color }}
                      />
                      <span className="font-semibold text-popover-foreground tabular-nums">
                        {typeof v === "number"
                          ? `${fmtNumber(v, digits)} ${unit}`
                          : EMPTY}
                      </span>
                      <span className="text-muted-foreground">{label}</span>
                    </div>
                  </div>
                )
              }}
            />
            <Line
              dataKey="v"
              name={label}
              type="monotone"
              stroke={color}
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

      {hasData && (
        <details className="text-sm">
          <summary className="text-muted-foreground cursor-pointer select-none">
            Show data table
          </summary>
          <div className="mt-2 max-h-64 overflow-auto rounded-md border">
            <table className="w-full text-left text-xs tabular-nums">
              <thead className="bg-muted sticky top-0">
                <tr>
                  <th className="px-3 py-1.5 font-medium">Time</th>
                  <th className="px-3 py-1.5 text-right font-medium">
                    {label} ({unit})
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows
                  .filter((r) => r.v !== null)
                  .slice(-60)
                  .reverse()
                  .map((r) => (
                    <tr key={r.t} className="border-t">
                      <td className="px-3 py-1">{fmtClock(r.t, true)}</td>
                      <td className="px-3 py-1 text-right">
                        {fmtNumber(r.v, digits)}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  )
}
