import { expect, test } from "@playwright/test"

test("wind page renders heading and stat tiles", async ({ page }) => {
  await page.goto("/")

  await expect(page.getByRole("heading", { name: "Wind" })).toBeVisible()
  await expect(page.getByTestId("stat-tile")).toHaveCount(8)
  await expect(page.getByTestId("collector-status")).toBeVisible()
  await expect(page.getByTestId("wind-chart")).toBeVisible()
})

test("wind page shows values from the API", async ({ page }) => {
  // Mock the API so this runs without a backend or collector.
  const now = new Date().toISOString()
  await page.route("**/api/v1/readings/latest*", (route) =>
    route.fulfill({
      json: {
        sensor: "anemometer",
        ts: now,
        age_s: 0.4,
        stale: false,
        metrics: {
          wind_speed_mph: 12.34,
          wind_gust_mph: 18.5,
          pulse_hz: 8.27,
          rpm: 496.2,
          pulse_count: 8,
          pulse_total: 12345,
          do_active: 1,
          secs_since_pulse: 0.1,
        },
      },
    }),
  )
  await page.route("**/api/v1/readings/history*", (route) =>
    route.fulfill({
      json: {
        sensor: "anemometer",
        metric: new URL(route.request().url()).searchParams.get("metric"),
        bucket_s: null,
        points: [{ ts: now, value: 12.34, max: null }],
      },
    }),
  )

  await page.goto("/")

  await expect(page.getByTestId("collector-status")).toHaveText(/Live/)
  await expect(
    page.getByTestId("stat-tile").filter({ hasText: "Wind speed" }),
  ).toContainText("12.3")
  await expect(
    page.getByTestId("stat-tile").filter({ hasText: "DO pin" }),
  ).toContainText("Active")
})
