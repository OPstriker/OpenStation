import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  AlertCircle,
  CheckCircle2,
  CircleSlash,
  FlaskConical,
  Info,
  Upload,
  XCircle,
} from "lucide-react"
import { type FormEvent, useState } from "react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import {
  parseTs,
  type WundergroundConfig,
  type WundergroundField,
  type WundergroundUpdate,
  wundergroundApi,
} from "@/lib/api"
import { EMPTY, fmtDuration, mToFt } from "@/lib/format"

const QUERY_KEY = ["wunderground"]
const FT_PER_M = 1 / 0.3048
// Decimals per unit, matching the rounding of what is uploaded.
const DIGITS: Record<string, number> = {
  "°F": 1,
  "%": 0,
  inHg: 2,
  mph: 1,
  "°": 0,
}

export const Route = createFileRoute("/_layout/weather-underground")({
  component: WeatherUndergroundPage,
  head: () => ({
    meta: [{ title: "Weather Underground - Weather Station" }],
  }),
})

function WeatherUndergroundPage() {
  const query = useQuery({
    queryKey: QUERY_KEY,
    queryFn: ({ signal }) => wundergroundApi.get(signal),
    refetchInterval: 5_000,
  })
  const cfg = query.data

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Weather Underground</h1>
          <p className="text-muted-foreground text-sm">
            Upload readings to your personal weather station
          </p>
        </div>
        {cfg && <UploadBadge cfg={cfg} />}
      </div>

      {query.isError && !cfg && (
        <Alert variant="destructive">
          <AlertCircle />
          <AlertTitle>Can't reach the API</AlertTitle>
          <AlertDescription>{query.error.message}</AlertDescription>
        </Alert>
      )}
      {cfg?.dry_run && (
        <Alert data-testid="wu-dry-run">
          <FlaskConical />
          <AlertTitle>Simulate mode: nothing is sent</AlertTitle>
          <AlertDescription>
            The collector is running with simulated sensors, so uploads are
            built and shown here but never sent to Weather Underground.
          </AlertDescription>
        </Alert>
      )}

      {cfg && (
        <>
          <div className="grid gap-6 lg:grid-cols-2">
            <SettingsCard cfg={cfg} />
            <StatusCard cfg={cfg} />
          </div>
          <FieldsCard fields={cfg.fields} />
        </>
      )}
    </div>
  )
}

function UploadBadge({ cfg }: { cfg: WundergroundConfig }) {
  if (!cfg.enabled)
    return (
      <Badge variant="outline" data-testid="wu-state">
        <CircleSlash />
        Upload off
      </Badge>
    )
  return (
    <Badge variant="outline" data-testid="wu-state">
      <Upload style={{ color: "var(--status-good)" }} />
      {cfg.dry_run ? "Dry run" : "Uploading"} every{" "}
      {fmtInterval(cfg.interval_s)}
    </Badge>
  )
}

function fmtInterval(seconds: number) {
  const min = seconds / 60
  return Number.isInteger(min) ? `${min} min` : `${seconds} s`
}

// ---- Settings ----------------------------------------------------------------

interface FormState {
  enabled: boolean
  stationId: string
  stationKey: string
  minutes: string
  elevationFt: string
}

function toForm(cfg: WundergroundConfig): FormState {
  return {
    enabled: cfg.enabled,
    stationId: cfg.station_id,
    stationKey: "",
    minutes: String(Math.round(cfg.interval_s / 60)),
    elevationFt:
      cfg.elevation_m === null
        ? ""
        : String(Math.round(mToFt(cfg.elevation_m))),
  }
}

function validate(form: FormState, hasKey: boolean): string | null {
  const minutes = Number(form.minutes)
  if (!Number.isInteger(minutes) || minutes < 1 || minutes > 60)
    return "Upload interval must be a whole number of minutes, 1 to 60."
  if (
    form.elevationFt.trim() !== "" &&
    !Number.isFinite(Number(form.elevationFt))
  )
    return "Station elevation must be a number of feet."
  if (form.enabled && (!form.stationId.trim() || (!hasKey && !form.stationKey)))
    return "Enter the station ID and key before turning upload on."
  return null
}

function SettingsCard({ cfg }: { cfg: WundergroundConfig }) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  // Edited locally; the 5 s polling doesn't overwrite what is being typed.
  const [form, setForm] = useState(() => toForm(cfg))
  const [error, setError] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: (body: WundergroundUpdate) => wundergroundApi.update(body),
    onSuccess: (data) => {
      queryClient.setQueryData(QUERY_KEY, data)
      setForm(toForm(data))
      showSuccessToast(
        data.enabled
          ? `Uploading every ${fmtInterval(data.interval_s)}.`
          : "Settings saved. Upload is off.",
      )
    },
    onError: (err) => showErrorToast(err.message),
  })

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    const problem = validate(form, cfg.has_key)
    setError(problem)
    if (problem) return
    const elevation = form.elevationFt.trim()
    save.mutate({
      enabled: form.enabled,
      station_id: form.stationId.trim(),
      ...(form.stationKey ? { station_key: form.stationKey } : {}),
      interval_s: Number(form.minutes) * 60,
      elevation_m: elevation === "" ? null : Number(elevation) / FT_PER_M,
    })
  }

  return (
    <Card className="gap-4 shadow-none">
      <CardHeader>
        <CardTitle>Settings</CardTitle>
        <CardDescription>
          From wunderground.com → My Profile → My Devices
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          onSubmit={onSubmit}
          className="flex flex-col gap-4"
          aria-label="Weather Underground settings"
          noValidate
        >
          <Label className="gap-3">
            <input
              type="checkbox"
              className="size-4 accent-primary"
              checked={form.enabled}
              onChange={(e) => set("enabled", e.target.checked)}
            />
            Upload enabled
          </Label>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-2">
              <Label htmlFor="wu-station-id">Station ID</Label>
              <Input
                id="wu-station-id"
                placeholder="KNYNEWYO123"
                autoComplete="off"
                spellCheck={false}
                value={form.stationId}
                onChange={(e) => set("stationId", e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="wu-station-key">Station key</Label>
              <Input
                id="wu-station-key"
                type="password"
                autoComplete="new-password"
                placeholder={cfg.has_key ? "Saved; leave blank to keep" : ""}
                value={form.stationKey}
                onChange={(e) => set("stationKey", e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="wu-interval">Upload every (minutes)</Label>
              <Input
                id="wu-interval"
                type="number"
                inputMode="numeric"
                min={1}
                max={60}
                step={1}
                value={form.minutes}
                onChange={(e) => set("minutes", e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="wu-elevation">Station elevation (ft)</Label>
              <Input
                id="wu-elevation"
                type="number"
                inputMode="numeric"
                placeholder="Needed for pressure"
                value={form.elevationFt}
                onChange={(e) => set("elevationFt", e.target.value)}
              />
            </div>
          </div>
          <p className="text-muted-foreground text-xs">
            Elevation turns the barometer's station pressure into sea-level
            pressure, which is what Weather Underground shows. Use the same
            elevation as your station's profile.
          </p>

          {error && (
            <p role="alert" className="text-destructive text-sm">
              {error}
            </p>
          )}
          <div>
            <LoadingButton type="submit" loading={save.isPending}>
              Save
            </LoadingButton>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

// ---- Status ------------------------------------------------------------------

function ago(ts: string | null) {
  if (!ts) return EMPTY
  return `${fmtDuration(Math.max((Date.now() - parseTs(ts)) / 1000, 0))} ago`
}

function ResultLine({ result }: { result: string | null }) {
  if (!result) return <span className="text-muted-foreground">Never</span>
  const ok = result === "success"
  const failed = result.startsWith("error")
  const Icon = ok ? CheckCircle2 : failed ? XCircle : Info
  const color = ok
    ? "var(--status-good)"
    : failed
      ? "var(--status-critical)"
      : "var(--muted-foreground)"
  return (
    <span className="flex items-start gap-2" data-testid="wu-last-result">
      <Icon className="mt-0.5 size-4 shrink-0" style={{ color }} />
      <span className="break-words">{ok ? "Success" : result}</span>
    </span>
  )
}

function StatusCard({ cfg }: { cfg: WundergroundConfig }) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const uploadNow = useMutation({
    mutationFn: wundergroundApi.uploadNow,
    onSuccess: (data) => {
      queryClient.setQueryData(QUERY_KEY, data)
      if (data.last_result === "success")
        showSuccessToast("Uploaded to Weather Underground.")
      else if (data.last_result?.startsWith("error"))
        showErrorToast(data.last_result)
    },
    onError: (err) => showErrorToast(err.message),
  })

  const canUpload = cfg.has_key && cfg.station_id !== ""
  let next: string = "Off"
  if (cfg.enabled && !canUpload) next = "Needs station ID and key"
  else if (cfg.next_upload_at) {
    const inS = (parseTs(cfg.next_upload_at) - Date.now()) / 1000
    next = inS <= 15 ? "Within 15 s" : `In ${fmtDuration(inS)}`
  }
  const sent = Object.entries(cfg.last_payload ?? {})

  return (
    <Card className="gap-4 shadow-none">
      <CardHeader>
        <CardTitle>Status</CardTitle>
        <CardDescription>
          The collector checks the schedule every 15 s
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          <dt className="text-muted-foreground">Last upload</dt>
          <dd className="flex flex-col gap-0.5">
            <ResultLine result={cfg.last_result} />
            {cfg.last_attempt_at && (
              <span className="text-muted-foreground text-xs">
                {ago(cfg.last_attempt_at)}
              </span>
            )}
          </dd>
          <dt className="text-muted-foreground">Last success</dt>
          <dd>{ago(cfg.last_success_at)}</dd>
          <dt className="text-muted-foreground">Next upload</dt>
          <dd data-testid="wu-next">{next}</dd>
          <dt className="text-muted-foreground">Last sent</dt>
          <dd className="flex flex-wrap gap-1.5">
            {sent.length === 0
              ? EMPTY
              : sent.map(([k, v]) => (
                  <code
                    key={k}
                    className="bg-muted rounded px-1.5 py-0.5 text-xs"
                  >
                    {k}={v}
                  </code>
                ))}
          </dd>
        </dl>
        <div>
          <LoadingButton
            variant="outline"
            loading={uploadNow.isPending}
            disabled={!canUpload}
            onClick={() => uploadNow.mutate()}
          >
            <Upload />
            Upload now
          </LoadingButton>
        </div>
      </CardContent>
    </Card>
  )
}

// ---- Fields --------------------------------------------------------------------

function FieldsCard({ fields }: { fields: WundergroundField[] }) {
  return (
    <Card className="gap-4 shadow-none">
      <CardHeader>
        <CardTitle>What gets sent</CardTitle>
        <CardDescription>
          The values the next upload will carry. A field is left out while its
          sensor has no fresh reading; there is no rain gauge, so no
          precipitation is sent.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="divide-y" aria-label="Upload fields">
          {fields.map((f) => (
            <li
              key={f.field}
              className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 py-2.5"
              data-testid={`wu-field-${f.field}`}
            >
              <div className="flex min-w-0 flex-col">
                <span className="font-medium">{f.label}</span>
                <span className="text-muted-foreground break-words text-xs">
                  <code>{f.field}</code> · {f.source}
                </span>
              </div>
              <div className="flex flex-col items-end text-right">
                <span className="tabular-nums font-semibold">
                  {f.value === null
                    ? EMPTY
                    : `${f.value.toFixed(DIGITS[f.unit] ?? 1)} ${f.unit}`}
                </span>
                {f.skipped ? (
                  <span
                    className="flex items-center gap-1 text-xs"
                    style={{ color: "var(--status-warning)" }}
                  >
                    <AlertCircle className="size-3" />
                    Left out: {f.skipped}
                  </span>
                ) : (
                  <span
                    className="flex items-center gap-1 text-xs"
                    style={{ color: "var(--status-good)" }}
                  >
                    <CheckCircle2 className="size-3" />
                    Included
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
