import { expect, type Page, test } from "@playwright/test"

// Mock the API so this runs without a backend or collector.
async function mockApi(page: Page, metrics: Record<string, number>) {
  const now = new Date().toISOString()
  await page.route("**/api/v1/readings/latest*", (route) =>
    route.fulfill({
      json: { sensor: "barometer", ts: now, age_s: 0.3, stale: false, metrics },
    }),
  )
  await page.route("**/api/v1/readings/history*", (route) => {
    const metric = new URL(route.request().url()).searchParams.get("metric")
    return route.fulfill({
      json: {
        sensor: "barometer",
        metric,
        bucket_s: null,
        points: [{ ts: now, value: metrics[metric ?? ""] ?? 0, max: null }],
      },
    })
  })
}

test("barometer page renders tiles and both charts", async ({ page }) => {
  await mockApi(page, {
    pressure_hpa: 1008.42,
    temperature_c: 21.5,
    altitude_m: 40.1,
  })
  await page.goto("/barometer")

  await expect(page.getByRole("heading", { name: "Barometer" })).toBeVisible()
  await expect(page.getByTestId("stat-tile")).toHaveCount(4)
  await expect(page.getByTestId("collector-status")).toHaveText(/Live/)
  await expect(page.getByTestId("pressure-chart")).toBeVisible()
  await expect(page.getByTestId("temperature-chart")).toBeVisible()
})

test("barometer page shows hPa and converts to degF and ft", async ({
  page,
}) => {
  await mockApi(page, {
    pressure_hpa: 1008.42,
    temperature_c: 21.5,
    altitude_m: 40.1,
  })
  await page.goto("/barometer")

  // Tiles are labelled "<label>: <value> <unit>"; match on the label prefix
  // (hint text like BAROMETER_STATION_ALTITUDE_M would also match "Altitude").
  const tile = (name: string) => page.getByLabel(new RegExp(`^${name}:`))
  await expect(tile("Pressure")).toContainText("1,008.4")
  await expect(tile("Temperature")).toContainText("70.7")
  await expect(tile("Altitude")).toContainText("132")
  // No station altitude configured: the tile explains how to get one.
  await expect(tile("Sea-level pressure")).toContainText(
    "BAROMETER_STATION_ALTITUDE_M",
  )
})

test("sidebar links to the barometer page", async ({ page }) => {
  await mockApi(page, { pressure_hpa: 1013.25 })
  await page.goto("/")
  await page.getByRole("link", { name: "Barometer" }).click()
  await expect(page).toHaveURL(/\/barometer$/)
})
