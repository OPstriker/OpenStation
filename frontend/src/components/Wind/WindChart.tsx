import { useMemo } from "react"
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
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
import { EMPTY, fmtClock, fmtNumber } from "@/lib/format"
import { cn } from "@/lib/utils"

const SERIES = [
  { key: "speed", label: "Wind speed", color: "var(--series-1)" },
  { key: "gust", label: "Gust", color: "var(--series-2)" },
] as const

type Row = { t: number; speed: number | null; gust: number | null }

/**
 * Merge speed + gust series by timestamp, with null rows where samples are
 * missing (see withGaps).
 */
function mergeSeries(
  speed: ReadingHistory | undefined,
  gust: ReadingHistory | undefined,
): Row[] {
  // Snap to the sample (1 s) or bucket step so the two metrics line up even
  // if their timestamps differ by a few ms.
  const stepMs = stepMsOf(speed, gust)

  const rows = new Map<number, Row>()
  const row = (ts: string) => {
    const t = Math.round(parseTs(ts) / stepMs) * stepMs
    let r = rows.get(t)
    if (!r) {
      r = { t, speed: null, gust: null }
      rows.set(t, r)
    }
    return r
  }
  for (const p of speed?.points ?? []) row(p.ts).speed = p.value
  // Bucketed gust: the bucket's max is the gust that matters.
  for (const p of gust?.points ?? []) row(p.ts).gust = p.max ?? p.value

  return withGaps(rows.values(), stepMs, (t) => ({
    t,
    speed: null,
    gust: null,
  }))
}

interface TooltipBodyProps {
  active?: boolean
  label?: unknown
  payload?: ReadonlyArray<{ dataKey?: unknown; value?: unknown }>
  withSeconds: boolean
}

function TooltipBody({
  active,
  label,
  payload,
  withSeconds,
}: TooltipBodyProps) {
  if (!active || !payload?.length || typeof label !== "number") return null
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs shadow-md">
      <div className="text-muted-foreground mb-1">
        {fmtClock(label, withSeconds)}
      </div>
      {SERIES.map((s) => {
        const v = payload.find((p) => p.dataKey === s.key)?.value
        return (
          <div key={s.key} className="flex items-center gap-2">
            <span
              className="inline-block h-0.5 w-3 rounded-full"
              style={{ backgroundColor: s.color }}
            />
            <span className="font-semibold text-popover-foreground tabular-nums">
              {typeof v === "number" ? `${fmtNumber(v)} mph` : EMPTY}
            </span>
            <span className="text-muted-foreground">{s.label}</span>
          </div>
        )
      })}
    </div>
  )
}

interface WindChartProps {
  sensor: string
  range: RangeKey
}

export function WindChart({ sensor, range }: WindChartProps) {
  const speedQ = useHistory(sensor, "wind_speed_mph", range)
  const gustQ = useHistory(sensor, "wind_gust_mph", range)
  const cfg = RANGES[range]
  const withSeconds = range === "5m"

  const rows = useMemo(
    () => mergeSeries(speedQ.data, gustQ.data),
    [speedQ.data, gustQ.data],
  )

  // Slide the window with each refetch rather than on every render.
  const end = speedQ.dataUpdatedAt || Date.now()
  const start = end - cfg.minutes * 60_000
  const ticks = useMemo(
    () => makeTicks(start, end, cfg.tickMs),
    [start, end, cfg.tickMs],
  )

  const hasData = rows.some((r) => r.speed !== null || r.gust !== null)
  const failed = speedQ.isError && !speedQ.data
  const loading = speedQ.isPending
  const refetchingRange = speedQ.isPlaceholderData || gustQ.isPlaceholderData

  let overlay: string | null = null
  if (failed) overlay = "History unavailable: API unreachable"
  else if (loading) overlay = "Loading…"
  else if (!hasData) overlay = `No readings in the last ${cfg.label}`

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-4 text-sm">
        {SERIES.map((s) => (
          <span key={s.key} className="flex items-center gap-2">
            <span
              className="inline-block h-0.5 w-4 rounded-full"
              style={{ backgroundColor: s.color }}
            />
            <span className="text-muted-foreground">{s.label}</span>
          </span>
        ))}
        {speedQ.data?.bucket_s ? (
          <span className="text-muted-foreground ml-auto text-xs">
            {Math.round(speedQ.data.bucket_s)} s buckets (avg speed, max gust)
          </span>
        ) : null}
      </div>

      <div
        className={cn(
          "relative h-64 w-full transition-opacity sm:h-72",
          refetchingRange && "opacity-60",
        )}
        data-testid="wind-chart"
      >
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
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
              domain={[0, (max: number) => Math.max(5, Math.ceil(max))]}
              allowDecimals={false}
              width={40}
              stroke="var(--chart-axis)"
              tick={{ fill: "var(--chart-tick)", fontSize: 12 }}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              cursor={{ stroke: "var(--chart-axis)", strokeWidth: 1 }}
              isAnimationActive={false}
              content={(props) => (
                <TooltipBody
                  active={props.active}
                  label={props.label}
                  payload={props.payload}
                  withSeconds={withSeconds}
                />
              )}
            />
            <Area
              dataKey="speed"
              name="Wind speed"
              type="monotone"
              stroke={SERIES[0].color}
              strokeWidth={2}
              fill={SERIES[0].color}
              fillOpacity={0.1}
              dot={false}
              activeDot={{ r: 4, stroke: "var(--card)", strokeWidth: 2 }}
              isAnimationActive={false}
            />
            <Line
              dataKey="gust"
              name="Gust"
              type="monotone"
              stroke={SERIES[1].color}
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              dot={false}
              activeDot={{ r: 4, stroke: "var(--card)", strokeWidth: 2 }}
              isAnimationActive={false}
            />
          </ComposedChart>
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
                    Speed (mph)
                  </th>
                  <th className="px-3 py-1.5 text-right font-medium">
                    Gust (mph)
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows
                  .filter((r) => r.speed !== null || r.gust !== null)
                  .slice(-60)
                  .reverse()
                  .map((r) => (
                    <tr key={r.t} className="border-t">
                      <td className="px-3 py-1">{fmtClock(r.t, true)}</td>
                      <td className="px-3 py-1 text-right">
                        {fmtNumber(r.speed)}
                      </td>
                      <td className="px-3 py-1 text-right">
                        {fmtNumber(r.gust)}
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
