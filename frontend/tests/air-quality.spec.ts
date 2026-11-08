import { expect, type Page, test } from "@playwright/test"

// Mock the API so this runs without a backend or collector.
async function mockApi(page: Page, metrics: Record<string, number>) {
  const now = new Date().toISOString()
  await page.route("**/api/v1/readings/latest*", (route) =>
    route.fulfill({
      json: {
        sensor: "air_quality",
        ts: now,
        age_s: 0.3,
        stale: false,
        metrics,
      },
    }),
  )
  await page.route("**/api/v1/readings/history*", (route) => {
    const metric = new URL(route.request().url()).searchParams.get("metric")
    return route.fulfill({
      json: {
        sensor: "air_quality",
        metric,
        bucket_s: null,
        points: [{ ts: now, value: metrics[metric ?? ""] ?? 0, max: null }],
      },
    })
  })
}

const READING = {
  co2_ppm: 812,
  temperature_c: 22.0,
  humidity_pct: 41.4,
  dew_point_c: 8.3,
}

// Tiles are labelled "<label>: <value> <unit>"; match on the label prefix.
const tile = (page: Page, name: string) =>
  page.getByLabel(new RegExp(`^${name}:`))

test("air quality page renders tiles and charts", async ({ page }) => {
  await mockApi(page, READING)
  await page.goto("/air-quality")

  await expect(page.getByRole("heading", { name: "Air quality" })).toBeVisible()
  await expect(page.getByTestId("stat-tile")).toHaveCount(4)
  await expect(page.getByTestId("collector-status")).toHaveText(/Live/)
  await expect(page.getByTestId("co2-chart")).toBeVisible()
  await expect(page.getByTestId("aq-temperature-chart")).toBeVisible()
  await expect(page.getByTestId("humidity-chart")).toBeVisible()
})

test("air quality values, units and CO2 level", async ({ page }) => {
  await mockApi(page, READING)
  await page.goto("/air-quality")

  await expect(tile(page, "CO₂")).toContainText("812")
  await expect(page.getByTestId("co2-level")).toHaveText("Good")
  await expect(tile(page, "Temperature")).toContainText("71.6") // 22 °C
  await expect(tile(page, "Humidity")).toContainText("41")
  await expect(tile(page, "Dew point")).toContainText("46.9") // 8.3 °C
})

test("high CO2 is flagged", async ({ page }) => {
  await mockApi(page, { ...READING, co2_ppm: 2450 })
  await page.goto("/air-quality")
  await expect(page.getByTestId("co2-level")).toHaveText("High")
})

test("sidebar links to the air quality page", async ({ page }) => {
  await mockApi(page, READING)
  await page.goto("/")
  await page.getByRole("link", { name: "Air quality" }).click()
  await expect(page).toHaveURL(/\/air-quality$/)
})
