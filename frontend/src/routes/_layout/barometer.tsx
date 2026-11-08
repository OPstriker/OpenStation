import { createFileRoute } from "@tanstack/react-router"
import { AlertCircle, Info } from "lucide-react"
import { useState } from "react"
import { RANGES, type RangeKey } from "@/components/Charts/history"
import { MetricChart } from "@/components/Charts/MetricChart"
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
import { useSensorLatest } from "@/hooks/useSensorLatest"
import { cToF, fmtDuration, fmtNumber, mToFt } from "@/lib/format"

const SENSOR = "barometer"

export const Route = createFileRoute("/_layout/barometer")({
  component: BarometerPage,
  head: () => ({
    meta: [{ title: "Barometer - Weather Station" }],
  }),
})

function BarometerPage() {
  const [range, setRange] = useState<RangeKey>("1h")
  const { query, metrics: m, state, ageS, hasReading } = useSensorLatest(SENSOR)
  const dimmed = state !== "live"

  const seaLevel = m.sea_level_pressure_hpa
  const altitudeM = m.altitude_m

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Barometer</h1>
          <p className="text-muted-foreground text-sm">
            Grove SPA06-003 · I2C 0x77
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
            The API is up but has no barometer samples. Check that the collector
            container is running and that the sensor shows up in{" "}
            <code>i2cdetect -y 1</code> on the Pi.
          </AlertDescription>
        </Alert>
      )}

      <section
        aria-label="Current readings"
        className="grid grid-cols-2 gap-3 md:grid-cols-4"
      >
        <StatTile
          label="Pressure"
          value={fmtNumber(m.pressure_hpa)}
          unit="hPa"
          hint="At the station"
          dimmed={dimmed}
        />
        <StatTile
          label="Sea-level pressure"
          value={fmtNumber(seaLevel)}
          unit="hPa"
          hint={
            seaLevel === undefined && hasReading
              ? "Set BAROMETER_STATION_ALTITUDE_M"
              : "Comparable to weather reports"
          }
          dimmed={dimmed}
        />
        <StatTile
          label="Temperature"
          value={fmtNumber(
            m.temperature_c === undefined ? undefined : cToF(m.temperature_c),
          )}
          unit="°F"
          hint="Sensor chip temperature"
          dimmed={dimmed}
        />
        <StatTile
          label="Altitude"
          value={fmtNumber(
            altitudeM === undefined ? undefined : mToFt(altitudeM),
            0,
          )}
          unit="ft"
          hint={
            altitudeM === undefined
              ? undefined
              : `${fmtNumber(altitudeM, 0)} m · from pressure`
          }
          dimmed={dimmed}
        />
      </section>

      <div className="flex justify-end">
        <Tabs value={range} onValueChange={(v) => setRange(v as RangeKey)}>
          <TabsList aria-label="Time range">
            {(Object.keys(RANGES) as RangeKey[]).map((key) => (
              <TabsTrigger key={key} value={key}>
                {RANGES[key].label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="gap-4 shadow-none">
          <CardHeader>
            <CardTitle>Pressure</CardTitle>
            <CardDescription>hPa, at the station</CardDescription>
          </CardHeader>
          <CardContent>
            <MetricChart
              sensor={SENSOR}
              metric="pressure_hpa"
              range={range}
              label="Pressure"
              unit="hPa"
              digits={2}
              minSpan={1}
              color="var(--series-1)"
              testId="pressure-chart"
            />
          </CardContent>
        </Card>
        <Card className="gap-4 shadow-none">
          <CardHeader>
            <CardTitle>Temperature</CardTitle>
            <CardDescription>°F, sensor chip</CardDescription>
          </CardHeader>
          <CardContent>
            <MetricChart
              sensor={SENSOR}
              metric="temperature_c"
              range={range}
              label="Temperature"
              unit="°F"
              transform={cToF}
              minSpan={2}
              color="var(--series-2)"
              testId="temperature-chart"
            />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
