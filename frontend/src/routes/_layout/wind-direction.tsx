import { createFileRoute } from "@tanstack/react-router"
import { AlertCircle, AlertTriangle, Info } from "lucide-react"
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
import { Compass } from "@/components/WindDirection/Compass"
import { DirectionChart } from "@/components/WindDirection/DirectionChart"
import { useSensorLatest } from "@/hooks/useSensorLatest"
import { compassPoint, EMPTY, fmtDuration, fmtNumber } from "@/lib/format"

const SENSOR = "wind_vane"
const STEPS_PER_REV = 20

export const Route = createFileRoute("/_layout/wind-direction")({
  component: WindDirectionPage,
  head: () => ({
    meta: [{ title: "Wind direction - Weather Station" }],
  }),
})

function fmtBearing(deg: number | undefined) {
  return deg === undefined ? EMPTY : `${Math.round(deg) % 360}°`
}

function WindDirectionPage() {
  const [range, setRange] = useState<RangeKey>("1h")
  const { query, metrics: m, state, ageS, hasReading } = useSensorLatest(SENSOR)
  // Wind speed for the compass hub comes from the anemometer.
  const wind = useSensorLatest("anemometer")
  const dimmed = state !== "live"
  const speed = wind.state === "live" ? wind.metrics.wind_speed_mph : undefined

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Wind direction</h1>
          <p className="text-muted-foreground text-sm">
            Wind vane · KY-040 rotary encoder
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
            {query.error?.message ?? "Request failed"}. Retrying every second
            {hasReading ? "; showing the last values received." : "."}
          </AlertDescription>
        </Alert>
      )}
      {state === "empty" && (
        <Alert>
          <Info />
          <AlertTitle>No readings yet</AlertTitle>
          <AlertDescription>
            The API is up but has no wind vane samples. Check that the collector
            container is running.
          </AlertDescription>
        </Alert>
      )}
      {hasReading && m.calibrated === 0 && (
        <Alert data-testid="vane-uncalibrated">
          <AlertTriangle style={{ color: "var(--status-warning)" }} />
          <AlertTitle>North not set since the collector started</AlertTitle>
          <AlertDescription>
            The encoder only counts relative turns, so 0° is wherever the vane
            pointed at startup. Point the vane north and press the encoder knob
            to set it.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="gap-4 shadow-none">
          <CardHeader>
            <CardTitle>Compass</CardTitle>
            <CardDescription>
              Needle points to where the wind comes from
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Compass
              direction={m.direction_deg}
              average={m.direction_avg_deg}
              speedMph={speed}
              dimmed={dimmed}
            />
          </CardContent>
        </Card>

        <section
          aria-label="Current readings"
          className="grid grid-cols-2 content-start gap-3"
        >
          <StatTile
            label="Direction"
            value={fmtBearing(m.direction_deg)}
            unit={
              m.direction_deg === undefined
                ? undefined
                : compassPoint(m.direction_deg)
            }
            hint="Wind from"
            dimmed={dimmed}
          />
          <StatTile
            label="2-min average"
            value={fmtBearing(m.direction_avg_deg)}
            unit={
              m.direction_avg_deg === undefined
                ? undefined
                : compassPoint(m.direction_avg_deg)
            }
            hint="Vector mean"
            dimmed={dimmed}
          />
          <StatTile
            label="Wind speed"
            value={fmtNumber(speed)}
            unit="mph"
            hint="From the anemometer"
            dimmed={wind.state !== "live"}
          />
          <StatTile
            label="Encoder position"
            value={
              m.position === undefined
                ? EMPTY
                : `${Math.round(m.position)} / ${STEPS_PER_REV}`
            }
            hint={`${360 / STEPS_PER_REV}° per step`}
            dimmed={dimmed}
          />
          <StatTile
            label="North set"
            value={
              m.calibrated === undefined ? EMPTY : m.calibrated ? "Yes" : "No"
            }
            hint={
              m.calibrated === 0 ? "Point north, press the knob" : undefined
            }
            dimmed={dimmed}
          />
        </section>
      </div>

      <Card className="gap-4 shadow-none">
        <CardHeader className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-col gap-1.5">
            <CardTitle>Direction history</CardTitle>
            <CardDescription>Bearing the wind comes from</CardDescription>
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
          <DirectionChart sensor={SENSOR} range={range} />
        </CardContent>
      </Card>
    </div>
  )
}
