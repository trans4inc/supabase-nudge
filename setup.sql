-- supabase-nudge: per-project keep-alive setup
--
-- Run once per Supabase project in the SQL editor (Dashboard → SQL Editor).
-- Idempotent: safe to re-run without breaking existing state.
--
-- Creates a keep_alive table with one row and grants the anon role
-- SELECT access via RLS, so the scheduled pinger can verify activity
-- using only the public anon key.

CREATE TABLE IF NOT EXISTS public.keep_alive (
    id integer PRIMARY KEY,
    note text NOT NULL DEFAULT 'pinged by supabase-nudge'
);

INSERT INTO public.keep_alive (id) VALUES (1)
ON CONFLICT (id) DO NOTHING;

ALTER TABLE public.keep_alive ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "anon can select keep_alive" ON public.keep_alive;
CREATE POLICY "anon can select keep_alive"
    ON public.keep_alive
    FOR SELECT
    TO anon
    USING (true);
