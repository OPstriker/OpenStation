import { expect, type Page, test } from "@playwright/test"

const VANE = {
  direction_deg: 234,
  direction_avg_deg: 226.4,
  direction_sin: Math.sin((234 * Math.PI) / 180),
  direction_cos: Math.cos((234 * Math.PI) / 180),
  position: 13,
  calibrated: 1,
}

// Mock the API so this runs without a backend or collector.
async function mockApi(page: Page, vane: Record<string, number>) {
  const now = new Date().toISOString()
  await page.route("**/api/v1/readings/latest*", (route) => {
    const sensor = new URL(route.request().url()).searchParams.get("sensor")
    const metrics =
      sensor === "anemometer"
        ? { wind_speed_mph: 9.7, wind_gust_mph: 14 }
        : vane
    return route.fulfill({
      json: { sensor, ts: now, age_s: 0.3, stale: false, metrics },
    })
  })
  await page.route("**/api/v1/readings/history*", (route) => {
    const params = new URL(route.request().url()).searchParams
    const metric = params.get("metric") ?? ""
    return route.fulfill({
      json: {
        sensor: params.get("sensor"),
        metric,
        bucket_s: null,
        points: [{ ts: now, value: vane[metric] ?? 0, max: null }],
      },
    })
  })
}

const tile = (page: Page, name: string) =>
  page.getByLabel(new RegExp(`^${name}:`))

test("compass shows where the wind comes from", async ({ page }) => {
  await mockApi(page, VANE)
  await page.goto("/wind-direction")

  await expect(
    page.getByRole("heading", { name: "Wind direction" }),
  ).toBeVisible()
  await expect(page.getByTestId("compass")).toHaveAttribute(
    "aria-label",
    /Wind from SW, 234 degrees; average from SW, 226 degrees/,
  )
  await expect(page.getByTestId("compass-needle")).toBeVisible()
  await expect(page.getByTestId("compass")).toContainText("9.7")
  await expect(tile(page, "Direction")).toContainText("234°")
  await expect(tile(page, "Encoder position")).toContainText("13 / 20")
  await expect(page.getByTestId("direction-chart")).toBeVisible()
  await expect(page.getByTestId("vane-uncalibrated")).toHaveCount(0)
})

test("warns until north is set", async ({ page }) => {
  await mockApi(page, { ...VANE, calibrated: 0 })
  await page.goto("/wind-direction")
  await expect(page.getByTestId("vane-uncalibrated")).toBeVisible()
  await expect(tile(page, "North set")).toContainText("No")
})

test("sidebar links to the wind direction page", async ({ page }) => {
  await mockApi(page, VANE)
  await page.goto("/")
  await page.getByRole("link", { name: "Wind direction" }).click()
  await expect(page).toHaveURL(/\/wind-direction$/)
})
