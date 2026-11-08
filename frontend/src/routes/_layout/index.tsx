import { createFileRoute } from "@tanstack/react-router"
import { AlertCircle, Info } from "lucide-react"
import { useState } from "react"
import { RANGES, type RangeKey } from "@/components/Charts/history"
import { CollectorStatus } from "@/components/Sensors/CollectorStatus"
import { StatTile } from "@/components/Sensors/StatTile"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { WindChart } from "@/components/Wind/WindChart"
import { useSensorLatest } from "@/hooks/useSensorLatest"
import { EMPTY, fmtDuration, fmtNumber } from "@/lib/format"

const SENSOR = "anemometer"

export const Route = createFileRoute("/_layout/")({
  component: WindPage,
  head: () => ({
    meta: [{ title: "Wind - Weather Station" }],
  }),
})

function WindPage() {
  const [range, setRange] = useState<RangeKey>("5m")

  const {
    query: latest,
    metrics: m,
    state,
    ageS,
    hasReading,
  } = useSensorLatest(SENSOR)

  const dimmed = state !== "live"
  const doActive = m.do_active

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Wind</h1>
          <p className="text-muted-foreground text-sm">
            Cup anemometer · KY-025 reed switch
          </p>
        </div>
        <div className="flex flex-col items-start gap-1 sm:items-end">
          <CollectorStatus state={state} ageS={ageS} />
          {hasReading && ageS != null && (
            <span className="text-muted-foreground text-xs">
              Last sample {fmtDuration(ageS)} ago
            </span>
          )}
        </div>
      </div>

      {state === "offline" && (
        <Alert variant="destructive">
          <AlertCircle />
          <AlertTitle>Can't reach the API</AlertTitle>
          <AlertDescription>
            {latest.error?.message ?? "Request failed"}. Retrying every second
            {hasReading ? "; showing the last values received." : "."}
          </AlertDescription>
        </Alert>
      )}
      {state === "empty" && (
        <Alert>
          <Info />
          <AlertTitle>No readings yet</AlertTitle>
          <AlertDescription>
            The API is up but has no anemometer samples. Check that the
            collector container is running.
          </AlertDescription>
        </Alert>
      )}

      <section
        aria-label="Current readings"
        className="grid grid-cols-2 gap-3 md:grid-cols-4"
      >
        <StatTile
          label="Wind speed"
          value={fmtNumber(m.wind_speed_mph)}
          unit="mph"
          dimmed={dimmed}
        />
        <StatTile
          label="Gust"
          value={fmtNumber(m.wind_gust_mph)}
          unit="mph"
          hint="Peak 3 s avg, 10 min"
          dimmed={dimmed}
        />
        <StatTile
          label="Pulse rate"
          value={fmtNumber(m.pulse_hz, 2)}
          unit="Hz"
          dimmed={dimmed}
        />
        <StatTile
          label="Rotation"
          value={fmtNumber(m.rpm, 0)}
          unit="rpm"
          dimmed={dimmed}
        />
        <StatTile
          label="Pulses this sample"
          value={fmtNumber(m.pulse_count, 0)}
          dimmed={dimmed}
        />
        <StatTile
          label="Total pulses"
          value={fmtNumber(m.pulse_total, 0)}
          hint="Since collector start"
          dimmed={dimmed}
        />
        <StatTile
          label="Since last pulse"
          value={fmtDuration(m.secs_since_pulse)}
          dimmed={dimmed}
        />
        <StatTile
          label="DO pin"
          value={
            doActive === undefined ? EMPTY : doActive ? "Active" : "Inactive"
          }
          hint={doActive ? "Magnet at reed switch" : undefined}
          dimmed={dimmed}
        />
      </section>

      <Card className="gap-4 shadow-none">
        <CardHeader className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-col gap-1.5">
            <CardTitle>Wind speed and gust</CardTitle>
            <CardDescription>mph</CardDescription>
          </div>
          <Tabs value={range} onValueChange={(v) => setRange(v as RangeKey)}>
            <TabsList aria-label="Time range">
              {(Object.keys(RANGES) as RangeKey[]).map((key) => (
                <TabsTrigger key={key} value={key}>
                  {RANGES[key].label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </CardHeader>
        <CardContent>
          <WindChart sensor={SENSOR} range={range} />
        </CardContent>
      </Card>
    </div>
  )
}
