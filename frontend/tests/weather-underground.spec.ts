import { expect, type Page, test } from "@playwright/test"

const SECRET = "not-a-real-key-123"

function config(overrides: Record<string, unknown> = {}) {
  return {
    enabled: false,
    station_id: "",
    has_key: false,
    interval_s: 300,
    elevation_m: null,
    last_attempt_at: null,
    last_success_at: null,
    last_result: null,
    last_payload: null,
    next_upload_at: null,
    dry_run: false,
    fields: [
      {
        field: "tempf",
        label: "Temperature",
        value: 68.4,
        unit: "°F",
        source: "air_quality.temperature_c",
        skipped: null,
      },
      {
        field: "baromin",
        label: "Pressure (sea level)",
        value: null,
        unit: "inHg",
        source: "barometer.pressure_hpa",
        skipped: "set the station elevation",
      },
      {
        field: "winddir",
        label: "Wind direction (2 min avg)",
        value: null,
        unit: "°",
        source: "wind_vane.direction_avg_deg",
        skipped: "north not set (press the vane's knob)",
      },
    ],
    ...overrides,
  }
}

// Mock the API so this runs without a backend. Returns the PUT bodies sent.
async function mockApi(page: Page, initial = config()) {
  let current = initial
  const puts: Record<string, unknown>[] = []
  await page.route("**/api/v1/wunderground", (route) => {
    const req = route.request()
    if (req.method() === "PUT") {
      const body = req.postDataJSON() as Record<string, unknown>
      puts.push(body)
      const { station_key, ...rest } = body
      current = config({
        ...current,
        ...rest,
        has_key: current.has_key || Boolean(station_key),
      })
    }
    return route.fulfill({ json: current })
  })
  await page.route("**/api/v1/readings/**", (route) =>
    route.fulfill({
      json: { sensor: "x", ts: null, age_s: null, stale: true, metrics: {} },
    }),
  )
  return puts
}

test("saves settings with a 5 minute interval", async ({ page }) => {
  const puts = await mockApi(page)
  await page.goto("/weather-underground")

  await expect(
    page.getByRole("heading", { name: "Weather Underground" }),
  ).toBeVisible()
  await expect(page.getByTestId("wu-state")).toContainText("Upload off")
  await expect(page.getByLabel("Upload every (minutes)")).toHaveValue("5")

  await page.getByLabel("Upload enabled").check()
  await page.getByLabel("Station ID").fill("KTEST123")
  await page.getByLabel("Station key").fill(SECRET)
  await page.getByLabel("Station elevation (ft)").fill("33")
  await page.getByRole("button", { name: "Save" }).click()

  await expect(page.getByTestId("wu-state")).toContainText(
    "Uploading every 5 min",
  )
  expect(puts).toHaveLength(1)
  expect(puts[0]).toMatchObject({
    enabled: true,
    station_id: "KTEST123",
    station_key: SECRET,
    interval_s: 300,
  })
  expect(puts[0].elevation_m).toBeCloseTo(10.06, 1)
  // The key is cleared from the form after saving and never shown.
  await expect(page.getByLabel("Station key")).toHaveValue("")
  await expect(page.getByLabel("Station key")).toHaveAttribute(
    "placeholder",
    /Saved/,
  )
  await expect(page.locator("body")).not.toContainText(SECRET)
})

test("blank key is not sent, so the saved key is kept", async ({ page }) => {
  const puts = await mockApi(
    page,
    config({ enabled: true, station_id: "KTEST123", has_key: true }),
  )
  await page.goto("/weather-underground")
  await page.getByLabel("Upload every (minutes)").fill("10")
  await page.getByRole("button", { name: "Save" }).click()
  await expect(page.getByTestId("wu-state")).toContainText("every 10 min")
  expect(puts[0]).not.toHaveProperty("station_key")
  expect(puts[0].interval_s).toBe(600)
})

test("rejects enabling without credentials", async ({ page }) => {
  const puts = await mockApi(page)
  await page.goto("/weather-underground")
  await page.getByLabel("Upload enabled").check()
  await page.getByRole("button", { name: "Save" }).click()
  await expect(page.getByRole("alert")).toContainText("station ID and key")
  expect(puts).toHaveLength(0)
})

test("shows what is sent and why fields are skipped", async ({ page }) => {
  await mockApi(
    page,
    config({
      dry_run: true,
      last_result: "dry run: not sent (simulate mode)",
      last_attempt_at: new Date().toISOString(),
      last_payload: { tempf: 68.4 },
    }),
  )
  await page.goto("/weather-underground")
  await expect(page.getByTestId("wu-dry-run")).toBeVisible()
  await expect(page.getByTestId("wu-field-tempf")).toContainText("68.4 °F")
  await expect(page.getByTestId("wu-field-tempf")).toContainText("Included")
  await expect(page.getByTestId("wu-field-baromin")).toContainText(
    "Left out: set the station elevation",
  )
  await expect(page.getByTestId("wu-field-winddir")).toContainText(
    "north not set",
  )
  await expect(page.getByTestId("wu-last-result")).toContainText("dry run")
  await expect(page.getByText("tempf=68.4")).toBeVisible()
})

test("sidebar links to the Weather Underground page", async ({ page }) => {
  await mockApi(page)
  await page.goto("/barometer")
  await page.getByRole("link", { name: "Weather Underground" }).click()
  await expect(page).toHaveURL(/\/weather-underground$/)
})
