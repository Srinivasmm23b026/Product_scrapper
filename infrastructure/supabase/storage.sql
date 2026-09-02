-- Run in the Supabase SQL editor only when hosted raw snapshots are enabled.
-- The bucket is private. Only the scheduled backend worker uses its server-only service role.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('raw-scrapes', 'raw-scrapes', false, 5242880, array['application/json'])
on conflict (id) do update
set public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;
