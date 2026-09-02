# Supabase-specific controls

Application schema migrations remain in the root Alembic tree because they are standard PostgreSQL.
The SQL files here are intentionally provider-specific and applied only after Alembic:

- `rls.sql`: blocks `anon`/`authenticated` Data API access while retaining backend authorization.
- `storage.sql`: creates the optional private raw-snapshot bucket.

Neither file contains project IDs, passwords, publishable keys, secret keys, or legacy role keys.
