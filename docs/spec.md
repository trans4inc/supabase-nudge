# Spec: `supabase-nudge`

A pause-prevention pinger for Supabase free-tier projects.

## Purpose

Keep multiple Supabase free-tier projects active by pinging each one well before the 7-day inactivity window closes. Cost: $0/month. Maintenance: minimal — adding a new project should take a few minutes.

## How it works

A scheduled GitHub Actions workflow runs four times per week (Mon/Wed/Fri/Sun at 09:17 UTC). For each Supabase project in the configuration, it issues a real `SELECT` query against a known table and verifies the response actually returned data (not just an HTTP 200 status). On failure, GitHub Actions emails the repo owner.

The maximum gap between any two scheduled runs is two days. Even with one missed run, the project remains well inside Supabase's 7-day inactivity window.

## Project configuration

The pinger tracks a list of Supabase projects. For each project, it needs:

- A name (human-readable, for logs and notifications)
- The Supabase project URL
- The anon (public) key
- The name of the table to query (defaults to `keep_alive`)

The list of projects to be tracked will be provided before first deployment.

## Per-project Supabase setup

Each Supabase project must have a table the pinger can read. Two options:

- **Preferred:** a dedicated `keep_alive` table with one row, present in every project for consistency
- **Alternative:** an existing table the anon key can already SELECT from (per project)

In either case, the table requires:

- At least one row (so `SELECT` returns data, not an empty array)
- An RLS policy permitting the anon role to `SELECT` from it

The repo must include a SQL snippet (in the README or a `setup.sql` file) that creates the `keep_alive` table, inserts one row, and applies the RLS policy. The user runs this snippet once per Supabase project via the Supabase SQL editor.

## Architectural constraints

- Runs on GitHub Actions
- Uses **anon keys only** — never service role keys
- All credentials stored as GitHub Secrets, never committed to the repo
- The repo itself can be public or private; secrets remain private either way
- Adding a new project should require editing the project list in one place plus adding the new secrets — nothing else

## Failure handling

- If any ping fails (network error, auth error, empty response, RLS denial), the workflow fails
- GitHub's built-in workflow-failure email goes to the repo owner
- Run history and logs are visible in the GitHub Actions UI for diagnosing what went wrong
- The GitHub Actions tab serves as the status view — no separate dashboard

## Acceptance criteria

The build is done when:

- The workflow runs automatically on the Mon/Wed/Fri/Sun schedule
- The workflow can also be triggered manually from the GitHub Actions UI
- Each configured project gets pinged and the ping is verified to have returned data
- A deliberate failure (e.g., wrong key on one project) causes the workflow to fail and produces a failure email
- Adding a new project requires editing one config location and adding that project's secrets — no other changes
- The repo includes a per-project SQL snippet (creating the `keep_alive` table, inserting a row, and applying the RLS policy) plus README instructions for running it

## Out of scope (for v1)

- Notifications via Slack, Discord, or other channels
- Auto-recovery (unpausing already-paused projects)
- Per-project ping frequencies
- Custom dashboard (GitHub Actions UI is the dashboard)
