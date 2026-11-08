import { useRef } from "react"

import { compassPoint, EMPTY, fmtNumber } from "@/lib/format"
import { cn } from "@/lib/utils"

const RING_R = 96
const LABEL_R = 112
const CARDINALS = ["N", "E", "S", "W"]
const INTERCARDINALS = ["NE", "SE", "SW", "NW"]

/**
 * Accumulate a bearing without jumps, so the needle turns the short way
 * (350 -> 10 rotates +20, not -340) when CSS animates the rotation.
 */
function useUnwrapped(deg: number | undefined) {
  const ref = useRef<number | null>(null)
  if (deg === undefined || !Number.isFinite(deg)) return ref.current
  const prev = ref.current
  ref.current =
    prev === null ? deg : prev + ((((deg - prev) % 360) + 540) % 360) - 180
  return ref.current
}

function polar(r: number, deg: number) {
  const rad = (deg * Math.PI) / 180
  return { x: r * Math.sin(rad), y: -r * Math.cos(rad) }
}

interface CompassProps {
  /** Bearing the wind comes from, degrees (0 = N). */
  direction?: number
  /** Rolling average bearing. */
  average?: number
  speedMph?: number
  dimmed?: boolean
}

export function Compass({
  direction,
  average,
  speedMph,
  dimmed,
}: CompassProps) {
  const needle = useUnwrapped(direction)
  const avg = useUnwrapped(average)

  const label =
    direction === undefined
      ? "Wind direction: no reading"
      : `Wind from ${compassPoint(direction)}, ${Math.round(direction)} degrees` +
        (average === undefined
          ? ""
          : `; average from ${compassPoint(average)}, ${Math.round(average)} degrees`)

  return (
    <div className="flex flex-col items-center gap-3">
      <svg
        viewBox="-130 -130 260 260"
        className="w-full max-w-80"
        role="img"
        aria-label={label}
        data-testid="compass"
      >
        <circle
          r={RING_R}
          fill="var(--card)"
          stroke="var(--chart-axis)"
          strokeWidth={1.5}
        />
        <circle r={64} fill="none" stroke="var(--chart-grid)" strokeWidth={1} />

        {/* 16 ticks, longer on the cardinal points */}
        {Array.from({ length: 16 }, (_, i) => {
          const deg = i * 22.5
          const major = i % 4 === 0
          const a = polar(RING_R - (major ? 14 : 8), deg)
          const b = polar(RING_R, deg)
          return (
            <line
              key={deg}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke={major ? "var(--foreground)" : "var(--chart-axis)"}
              strokeWidth={major ? 2 : 1}
              strokeLinecap="round"
            />
          )
        })}

        {CARDINALS.map((name, i) => {
          const p = polar(LABEL_R, i * 90)
          return (
            <text
              key={name}
              x={p.x}
              y={p.y}
              textAnchor="middle"
              dominantBaseline="central"
              fontSize={15}
              fontWeight={600}
              fill="var(--foreground)"
            >
              {name}
            </text>
          )
        })}
        {INTERCARDINALS.map((name, i) => {
          const p = polar(LABEL_R, 45 + i * 90)
          return (
            <text
              key={name}
              x={p.x}
              y={p.y}
              textAnchor="middle"
              dominantBaseline="central"
              fontSize={11}
              fill="var(--muted-foreground)"
            >
              {name}
            </text>
          )
        })}

        {/* Average: a marker on the ring */}
        {avg !== null && (
          <g
            className="transition-transform duration-700 ease-out motion-reduce:transition-none"
            style={{ transform: `rotate(${avg}deg)` }}
            data-testid="compass-average"
          >
            <path
              d={`M 0 ${-RING_R + 10} L -7 ${-RING_R - 4} L 7 ${-RING_R - 4} Z`}
              fill="var(--series-2)"
              stroke="var(--card)"
              strokeWidth={2}
              strokeLinejoin="round"
            />
          </g>
        )}

        {/* Needle: points to where the wind comes from */}
        {needle !== null && (
          <g
            className={cn(
              "transition-[transform,opacity] duration-500 ease-out motion-reduce:transition-none",
              dimmed && "opacity-40",
            )}
            style={{ transform: `rotate(${needle}deg)` }}
            data-testid="compass-needle"
          >
            <path
              d="M 0 -84 L 9 -20 L 0 -28 L -9 -20 Z"
              fill="var(--series-1)"
              stroke="var(--card)"
              strokeWidth={2}
              strokeLinejoin="round"
            />
            <line
              x1={0}
              y1={-26}
              x2={0}
              y2={60}
              stroke="var(--series-1)"
              strokeWidth={2}
              strokeLinecap="round"
            />
          </g>
        )}

        {/* Hub: current wind speed */}
        <circle
          r={30}
          fill="var(--card)"
          stroke="var(--chart-grid)"
          strokeWidth={1}
        />
        <text
          y={-3}
          textAnchor="middle"
          dominantBaseline="central"
          fontSize={18}
          fontWeight={600}
          fill="var(--foreground)"
        >
          {speedMph === undefined ? EMPTY : fmtNumber(speedMph)}
        </text>
        <text
          y={14}
          textAnchor="middle"
          dominantBaseline="central"
          fontSize={10}
          fill="var(--muted-foreground)"
        >
          mph
        </text>
      </svg>

      <div className="flex flex-wrap items-center justify-center gap-4 text-sm">
        <span className="flex items-center gap-2">
          <span
            className="inline-block h-0.5 w-4 rounded-full"
            style={{ backgroundColor: "var(--series-1)" }}
          />
          <span className="text-muted-foreground">Now</span>
        </span>
        <span className="flex items-center gap-2">
          <span
            className="inline-block size-2.5 rotate-45 rounded-[1px]"
            style={{ backgroundColor: "var(--series-2)" }}
          />
          <span className="text-muted-foreground">2-min average</span>
        </span>
      </div>
    </div>
  )
}
