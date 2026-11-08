import type { ReactNode } from "react"

import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"

interface StatTileProps {
  label: string
  value: string
  unit?: string
  hint?: ReactNode
  /** Dim the value when the data behind it is old or unavailable. */
  dimmed?: boolean
}

export function StatTile({ label, value, unit, hint, dimmed }: StatTileProps) {
  return (
    <Card
      data-testid="stat-tile"
      className="gap-1 px-4 py-4 shadow-none"
      aria-label={`${label}: ${value}${unit ? ` ${unit}` : ""}`}
    >
      <span className="text-muted-foreground text-sm">{label}</span>
      <span
        className={cn(
          "flex items-baseline gap-1 transition-opacity",
          dimmed && "opacity-50",
        )}
      >
        <span className="text-2xl font-semibold sm:text-3xl">{value}</span>
        {unit && <span className="text-muted-foreground text-sm">{unit}</span>}
      </span>
      {hint && (
        <span className="text-muted-foreground truncate text-xs">{hint}</span>
      )}
    </Card>
  )
}
