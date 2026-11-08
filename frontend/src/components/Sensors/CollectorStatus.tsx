import { AlertTriangle, CircleDashed, WifiOff } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { fmtDuration } from "@/lib/format"

export type CollectorState = "loading" | "offline" | "empty" | "stale" | "live"

interface CollectorStatusProps {
  state: CollectorState
  ageS: number | null | undefined
}

/** Collector health badge. Status colors always come with an icon + label. */
export function CollectorStatus({ state, ageS }: CollectorStatusProps) {
  const age = ageS != null ? fmtDuration(Math.max(ageS, 0)) : null

  switch (state) {
    case "loading":
      return (
        <Badge variant="outline" data-testid="collector-status">
          <CircleDashed className="animate-spin text-muted-foreground" />
          Connecting
        </Badge>
      )
    case "offline":
      return (
        <Badge variant="outline" data-testid="collector-status">
          <WifiOff style={{ color: "var(--status-critical)" }} />
          API unreachable
        </Badge>
      )
    case "empty":
      return (
        <Badge variant="outline" data-testid="collector-status">
          <CircleDashed className="text-muted-foreground" />
          No data
        </Badge>
      )
    case "stale":
      return (
        <Badge
          variant="outline"
          data-testid="collector-status"
          title="Newest reading is older than the stale threshold; is the collector running?"
        >
          <AlertTriangle style={{ color: "var(--status-warning)" }} />
          Stale{age ? ` · ${age} old` : ""}
        </Badge>
      )
    case "live":
      return (
        <Badge variant="outline" data-testid="collector-status">
          <span className="relative flex size-2">
            <span
              className="absolute inline-flex size-full animate-ping rounded-full opacity-60"
              style={{ backgroundColor: "var(--status-good)" }}
            />
            <span
              className="relative inline-flex size-2 rounded-full"
              style={{ backgroundColor: "var(--status-good)" }}
            />
          </span>
          Live
        </Badge>
      )
  }
}
