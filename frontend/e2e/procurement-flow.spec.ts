import { expect, test } from "@playwright/test";

test("local mocked smoke: login through purchase, inventory, and analytics", async ({
  page,
}) => {
  let onboarded = false;
  let purchased = false;
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    const body = (payload: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(payload),
      });
    if (url.pathname === "/api/auth/login" && method === "POST")
      return body({});
    if (url.pathname === "/api/auth/session")
      return body(
        onboarded
          ? {
              email: "ops@example.com",
              onboarded: true,
              role: "owner",
              restaurant: { id: "restaurant-1", name: "Juniper Kitchen" },
              location: {
                id: "location-1",
                label: "Main kitchen",
                city: "Bengaluru",
                pincode: "560001",
              },
            }
          : { email: "ops@example.com", onboarded: false },
      );
    if (url.pathname === "/api/restaurants/bootstrap" && method === "POST") {
      onboarded = true;
      return body({ restaurant_id: "restaurant-1", location_id: "location-1" });
    }
    if (url.pathname === "/api/analytics/spending")
      return body({
        current_month_spend: purchased ? 750 : 0,
        by_supplier: [{ supplier: "Lots", amount: purchased ? 750 : 0 }],
        by_category: [{ category: "Staples", amount: purchased ? 750 : 0 }],
        over_time: purchased ? [{ date: "2026-09-05", amount: 750 }] : [],
        recent_purchases: purchased
          ? [
              {
                id: "purchase-1",
                supplier: "Lots",
                purchased_at: "2026-09-05T08:00:00Z",
                total_amount: 750,
                notes: "Smoke test",
              },
            ]
          : [],
      });
    if (url.pathname === "/api/purchases" && method === "GET")
      return body({
        items: purchased
          ? [
              {
                id: "purchase-1",
                supplier: "Lots",
                purchased_at: "2026-09-05T08:00:00Z",
                total_amount: 750,
                notes: "Smoke test",
              },
            ]
          : [],
      });
    if (url.pathname === "/api/purchases" && method === "POST") {
      purchased = true;
      return body({ id: "purchase-1", total_amount: 750 }, 201);
    }
    if (url.pathname === "/api/inventory")
      return body({
        items: purchased
          ? [
              {
                id: "inventory-1",
                canonical_product_id: "product-1",
                product: "Basmati Rice",
                quantity: 5,
                unit: "kg",
                updated_at: "2026-09-05T08:00:00Z",
              },
            ]
          : [],
      });
    if (url.pathname === "/api/scrape-runs")
      return body({
        items: [
          {
            id: "run-1",
            supplier: "Lots",
            supplier_location: "Lots fallback store 101 (unverified)",
            status: "complete",
            observed_count: 4000,
            finished_at: "2026-09-05T08:00:00Z",
            warning_count: 0,
          },
        ],
      });
    if (url.pathname === "/api/products/search")
      return body({
        items: [
          {
            id: "product-1",
            display_name: "Basmati Rice",
            brand: "Juniper",
            category: "Staples",
          },
        ],
      });
    if (url.pathname === "/api/compare")
      return body({
        base_unit: "kg",
        best_total_cost_offer_id: "offer-1",
        best_unit_price_offer_id: "offer-1",
        offers: [
          {
            id: "offer-1",
            product_variant_id: "variant-1",
            supplier_id: "supplier-1",
            supplier: "Lots",
            supplier_location: "Lots fallback store 101 (unverified)",
            product_name: "Basmati Rice",
            pack: "5 kg",
            pack_total_quantity: 5,
            base_unit: "kg",
            price: 750,
            mrp: 800,
            availability: true,
            last_checked: "2026-09-05T08:00:00Z",
            stale: false,
            product_url: "https://lots.example/rice",
            image_url: null,
            packs_required: 1,
            quantity_purchased: 5,
            excess_quantity: 4,
            total_cost: 750,
            normalized_unit_price: 150,
          },
        ],
      });
    if (url.pathname === "/api/products/product-1/history")
      return body({
        current_price: 750,
        last_observed_at: "2026-09-05T08:00:00Z",
        latest_supplier: "Lots",
        latest_supplier_location: "Lots fallback store 101 (unverified)",
        observations: [
          {
            id: "history-1",
            offer_id: "offer-1",
            supplier: "Lots",
            supplier_location: "Lots fallback store 101 (unverified)",
            price: 750,
            observed_at: "2026-09-05T08:00:00Z",
            trusted_for_statistics: true,
            data_quality: "complete_run",
          },
          {
            id: "history-2",
            offer_id: "offer-2",
            supplier: "Hyperpure",
            supplier_location: "Verified Bengaluru store",
            price: 790,
            observed_at: "2026-09-01T08:00:00Z",
            trusted_for_statistics: true,
            data_quality: "complete_run",
          },
        ],
      });
    return body({});
  });

  await page.goto("/login");
  await page.getByLabel("Email").fill("ops@example.com");
  await page.getByLabel("Password").fill("a-secure-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Let’s shape your workspace.")).toBeVisible();
  await page.getByLabel("Restaurant name").fill("Juniper Kitchen");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("City").fill("Bengaluru");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Pincode").fill("560001");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page.getByText("Keep purchasing")).toBeVisible();
  await page.getByRole("link", { name: "Procure", exact: true }).click();
  await page.getByLabel("Product").fill("rice");
  await page.getByRole("button", { name: /Basmati Rice/ }).click();
  await page.getByRole("button", { name: "Compare" }).click();
  await expect(
    page.getByText("Lots fallback store 101 (unverified)").first(),
  ).toBeVisible();
  await expect(page.getByLabel("Price history range")).toBeVisible();
  await expect(
    page.getByText("Hyperpure · Verified Bengaluru store"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Record purchase" }).click();
  await page.getByLabel("Actual paid total").fill("750");
  await page.getByRole("button", { name: "Save purchase" }).click();
  await expect(page.getByText("Purchase recorded")).toBeVisible();
  await page.getByRole("link", { name: "Inventory", exact: true }).click();
  await expect(page.getByText("Basmati Rice")).toBeVisible();
  await page.getByRole("button", { name: "New adjustment" }).click();
  await page.getByLabel("Product search").fill("rice");
  await page.getByRole("button", { name: /Basmati Rice/ }).click();
  await page.getByRole("button", { name: "Save adjustment" }).click();
  await expect(page.getByText("Inventory adjusted")).toBeVisible();
  await page.getByRole("link", { name: "Analytics", exact: true }).click();
  await expect(page.getByText("₹750")).toBeVisible();
});
