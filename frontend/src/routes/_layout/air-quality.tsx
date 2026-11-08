import { createFileRoute } from "@tanstack/react-router"
import { AlertCircle, Info } from "lucide-react"
import { useState } from "react"
import { RANGES, type RangeKey } from "@/components/Charts/history"
import { MetricChart } from "@/components/Charts/MetricChart"
import { Co2Level } from "@/components/Sensors/Co2Level"
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
import { cToF, fmtDuration, fmtNumber } from "@/lib/format"

const SENSOR = "air_quality"

export const Route = createFileRoute("/_layout/air-quality")({
  component: AirQualityPage,
  head: () => ({
    meta: [{ title: "Air quality - Weather Station" }],
  }),
})

function toF(c: number | undefined) {
  return c === undefined ? undefined : cToF(c)
}

function AirQualityPage() {
  const [range, setRange] = useState<RangeKey>("1h")
  const { query, metrics: m, state, ageS, hasReading } = useSensorLatest(SENSOR)
  const dimmed = state !== "live"

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Air quality</h1>
          <p className="text-muted-foreground text-sm">
            Grove SCD41 · I2C 0x62
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
            The API is up but has no air quality samples. Check that the
            collector container is running and that the sensor shows up as{" "}
            <code>62</code> in <code>i2cdetect -y 1</code> on the Pi.
          </AlertDescription>
        </Alert>
      )}

      <section
        aria-label="Current readings"
        className="grid grid-cols-2 gap-3 md:grid-cols-4"
      >
        <StatTile
          label="CO₂"
          value={fmtNumber(m.co2_ppm, 0)}
          unit="ppm"
          hint={
            m.co2_ppm === undefined ? (
              "Measured every 5 s"
            ) : (
              <Co2Level ppm={m.co2_ppm} />
            )
          }
          dimmed={dimmed}
        />
        <StatTile
          label="Temperature"
          value={fmtNumber(toF(m.temperature_c))}
          unit="°F"
          hint="SCD41 sensor"
          dimmed={dimmed}
        />
        <StatTile
          label="Humidity"
          value={fmtNumber(m.humidity_pct, 0)}
          unit="%"
          hint="Relative humidity"
          dimmed={dimmed}
        />
        <StatTile
          label="Dew point"
          value={fmtNumber(toF(m.dew_point_c))}
          unit="°F"
          hint="Condensation temperature"
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

      <Card className="gap-4 shadow-none">
        <CardHeader>
          <CardTitle>CO₂</CardTitle>
          <CardDescription>
            ppm · good below 1000, elevated to 2000, high above
          </CardDescription>
        </CardHeader>
        <CardContent>
          <MetricChart
            sensor={SENSOR}
            metric="co2_ppm"
            range={range}
            label="CO₂"
            unit="ppm"
            digits={0}
            minSpan={100}
            color="var(--series-1)"
            testId="co2-chart"
          />
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="gap-4 shadow-none">
          <CardHeader>
            <CardTitle>Temperature</CardTitle>
            <CardDescription>°F</CardDescription>
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
              testId="aq-temperature-chart"
            />
          </CardContent>
        </Card>
        <Card className="gap-4 shadow-none">
          <CardHeader>
            <CardTitle>Humidity</CardTitle>
            <CardDescription>% relative humidity</CardDescription>
          </CardHeader>
          <CardContent>
            <MetricChart
              sensor={SENSOR}
              metric="humidity_pct"
              range={range}
              label="Humidity"
              unit="%"
              digits={0}
              minSpan={5}
              color="var(--series-1)"
              testId="humidity-chart"
            />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
