export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...init.headers },
    ...init,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new ApiError(payload.detail || `Request failed (${response.status})`, response.status);
  }
  return response.status === 204 ? (undefined as T) : (response.json() as Promise<T>);
}

export type Session = {
  email: string | null;
  onboarded: boolean;
  role?: string;
  restaurant?: { id: string; name: string };
  location?: { id: string; label: string; city: string; pincode: string };
};

export type Product = { id: string; display_name: string; brand: string | null; category: string | null };
export type Offer = {
  id: string;
  product_variant_id: string | null;
  supplier_id: string;
  supplier: string;
  supplier_location: string;
  product_name: string;
  pack: string | null;
  pack_total_quantity: number | null;
  base_unit: "kg" | "l" | "piece" | null;
  price: number | null;
  mrp: number | null;
  availability: boolean | null;
  last_checked: string | null;
  stale: boolean;
  product_url: string | null;
  image_url: string | null;
  packs_required: number;
  quantity_purchased: number;
  excess_quantity: number;
  total_cost: number;
  normalized_unit_price: number;
};

export type Comparison = {
  base_unit: "kg" | "l" | "piece";
  offers: Offer[];
  best_total_cost_offer_id: string | null;
  best_unit_price_offer_id: string | null;
};

export type HistoryPoint = {
  id: string;
  offer_id: string;
  supplier: string;
  supplier_location: string;
  price: number | null;
  observed_at: string;
  trusted_for_statistics: boolean;
  data_quality: string;
};

export type History = {
  current_price: number | null;
  last_observed_at: string | null;
  latest_supplier: string | null;
  latest_supplier_location: string | null;
  observations: HistoryPoint[];
};

export type Purchase = { id: string; supplier: string; purchased_at: string; total_amount: number; notes: string | null };
export type InventoryItem = { id: string; canonical_product_id: string; product: string; quantity: number; unit: "kg" | "l" | "piece"; updated_at: string };
export type Analytics = {
  current_month_spend: number;
  by_supplier: { supplier: string; amount: number }[];
  by_category: { category: string; amount: number }[];
  over_time: { date: string; amount: number }[];
  recent_purchases: Purchase[];
};
export type ScrapeRun = { id: string; supplier: string; supplier_location: string; status: string; observed_count: number; finished_at: string | null; warning_count: number };

export const api = {
  session: () => request<Session>("/auth/session"),
  login: (email: string, password: string) => request("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  signup: (email: string, password: string) => request("/auth/signup", { method: "POST", body: JSON.stringify({ email, password }) }),
  confirm: (email: string, code: string) => request("/auth/confirm", { method: "POST", body: JSON.stringify({ email, code }) }),
  forgotPassword: (email: string) => request("/auth/forgot-password", { method: "POST", body: JSON.stringify({ email }) }),
  resetPassword: (email: string, code: string, password: string) => request("/auth/reset-password", { method: "POST", body: JSON.stringify({ email, code, password }) }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  onboard: (payload: { restaurant_name: string; location_label: string; city: string; pincode: string }) => request("/restaurants/bootstrap", { method: "POST", body: JSON.stringify(payload) }),
  search: (query: string) => request<{ items: Product[] }>(`/products/search?q=${encodeURIComponent(query)}`),
  compare: (product_id: string, required_quantity: number, unit: string) => request<Comparison>("/compare", { method: "POST", body: JSON.stringify({ product_id, required_quantity, unit }) }),
  history: (productId: string) => request<History>(`/products/${productId}/history`),
  purchases: () => request<{ items: Purchase[] }>("/purchases"),
  inventory: () => request<{ items: InventoryItem[] }>("/inventory"),
  analytics: () => request<Analytics>("/analytics/spending"),
  runs: () => request<{ items: ScrapeRun[] }>("/scrape-runs"),
  createPurchase: (payload: unknown) => request("/purchases", { method: "POST", body: JSON.stringify(payload) }),
  adjustInventory: (payload: unknown) => request("/inventory/adjustments", { method: "POST", body: JSON.stringify(payload) }),
};
