import { AlertOctagon, AlertTriangle, CheckCircle2 } from "lucide-react"

/**
 * Indoor-air CO2 bands (ppm). Fresh outdoor air is ~420 ppm; above ~1000 ppm
 * a room is noticeably stuffy, above ~2000 ppm ventilation is poor.
 */
export const CO2_LEVELS = [
  {
    below: 1000,
    label: "Good",
    Icon: CheckCircle2,
    color: "var(--status-good)",
  },
  {
    below: 2000,
    label: "Elevated",
    Icon: AlertTriangle,
    color: "var(--status-warning)",
  },
  {
    below: Number.POSITIVE_INFINITY,
    label: "High",
    Icon: AlertOctagon,
    color: "var(--status-critical)",
  },
] as const

export function co2Level(ppm: number) {
  return CO2_LEVELS.find((l) => ppm < l.below) ?? CO2_LEVELS[2]
}

/** Status icon + label (never color alone). Text stays in the ink color. */
export function Co2Level({ ppm }: { ppm: number | undefined }) {
  if (ppm === undefined || !Number.isFinite(ppm)) return null
  const { label, Icon, color } = co2Level(ppm)
  return (
    <span className="inline-flex items-center gap-1" data-testid="co2-level">
      <Icon className="size-3.5 shrink-0" style={{ color }} aria-hidden />
      {label}
    </span>
  )
}
