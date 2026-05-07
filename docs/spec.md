# Spec: `supabase-nudge`

A pause-prevention pinger for Supabase free-tier projects.

## Purpose

Keep multiple Supabase free-tier projects active by pinging each one well before the 7-day inactivity window closes. Cost: $0/month. Maintenance: minimal — adding a new project should take a few minutes.

## How it works

A scheduled GitHub Actions workflow runs four times per week (Mon/Wed/Fri/Sun at 09:17 UTC). For each Supabase project in the configuration, it issues an `INSERT` against a known table and verifies the response is `201 Created` with the inserted row echoed back in the body. On failure, GitHub Actions emails the repo owner.

The maximum gap between any two scheduled runs is two days. Even with one missed run, the project remains well inside Supabase's 7-day inactivity window.

The original v1 design used a `SELECT` query. SELECTs turned out to be insufficient for Supabase's free-tier inactivity tracker — see `docs/decisions.md` (2026-05-07 entry) for the empirical evidence and the rationale for switching to writes.

## Project configuration

The pinger tracks a list of Supabase projects. For each project, it needs:

- A name (human-readable, for logs and notifications)
- The Supabase project URL
- The anon (public) key
- The name of the table to write to (defaults to `keep_alive`)

The list of projects to be tracked will be provided before first deployment.

## Per-project Supabase setup

Each Supabase project must have a table the pinger can write to. Two options:

- **Preferred:** a dedicated `keep_alive` table whose every column has a default, present in every project for consistency
- **Alternative:** an existing table the anon role can already INSERT into, where every column has a default (per project)

In either case, the table requires:

- Every column populated by a database default, so the script can POST `{}` and never has to know the column list
- An RLS policy permitting the anon role to `INSERT`
- An RLS policy permitting the anon role to `SELECT` (so PostgREST can return the inserted row when the script sends `Prefer: return=representation`)

The repo includes a `setup.sql` snippet that creates the `keep_alive` table, applies both RLS policies, and migrates pre-existing tables from the original SELECT-based schema. The user runs this snippet once per Supabase project via the Supabase SQL editor; re-running it on a project that's already been set up is the supported migration path.

## Architectural constraints

- Runs on GitHub Actions
- Uses **anon keys only** — never service role keys
- All credentials stored as GitHub Secrets, never committed to the repo
- The repo itself can be public or private; secrets remain private either way
- Adding a new project should require editing the project list in one place plus adding the new secrets — nothing else

## Failure handling

- If any ping fails (network error, auth error, non-201 status, empty response, RLS denial on INSERT or on the returning SELECT), the workflow fails
- GitHub's built-in workflow-failure email goes to the repo owner
- Run history and logs are visible in the GitHub Actions UI for diagnosing what went wrong
- The GitHub Actions tab serves as the status view — no separate dashboard

## Acceptance criteria

The build is done when:

- The workflow runs automatically on the Mon/Wed/Fri/Sun schedule
- The workflow can also be triggered manually from the GitHub Actions UI
- Each configured project gets pinged via `INSERT`, and the ping is verified by `201 Created` plus the inserted row echoed back in the response body
- A deliberate failure (e.g., wrong key on one project, or revoking the INSERT policy) causes the workflow to fail and produces a failure email
- Adding a new project requires editing one config location and adding that project's secrets — no other changes
- The repo includes a per-project SQL snippet (creating `keep_alive` with defaulted columns, applying the SELECT and INSERT RLS policies, and idempotently migrating pre-existing SELECT-era tables) plus README instructions for running it

## Out of scope (for v1)

- Notifications via Slack, Discord, or other channels
- Auto-recovery (unpausing already-paused projects)
- Per-project ping frequencies
- Custom dashboard (GitHub Actions UI is the dashboard)
- Cleanup of accumulated `keep_alive` rows (each ping appends; rows accumulate slowly — a few hundred per project per year — and are intentionally retained as a free audit trail)
- A separate verification workflow that reads recent `pinged_at` timestamps to confirm writes are landing — flagged as a v1.1 candidate in `docs/decisions.md`
