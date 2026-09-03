-- Supabase-only defense in depth. The FastAPI backend remains the authorization authority.
-- The backend connects as the trusted database owner, which bypasses these Data API policies.
-- Browser roles receive no direct access to application tables.

begin;

alter table public.users enable row level security;
alter table public.restaurants enable row level security;
alter table public.restaurant_memberships enable row level security;
alter table public.restaurant_locations enable row level security;
alter table public.suppliers enable row level security;
alter table public.supplier_locations enable row level security;
alter table public.supplier_location_mappings enable row level security;
alter table public.canonical_products enable row level security;
alter table public.product_variants enable row level security;
alter table public.supplier_products enable row level security;
alter table public.product_matches enable row level security;
alter table public.supplier_offers enable row level security;
alter table public.scrape_runs enable row level security;
alter table public.price_observations enable row level security;
alter table public.purchases enable row level security;
alter table public.purchase_items enable row level security;
alter table public.inventory_items enable row level security;
alter table public.inventory_transactions enable row level security;
alter table public.expense_entries enable row level security;

revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;

commit;
