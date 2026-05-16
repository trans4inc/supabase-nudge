** NOTE: update May 16, 2026. This keep-alive is failing to accomplish the goal of preventing Supabase projects from being paused. I am currently researching if Supabase has changed their definition of "activity". I will update once research is done.**

# supabase-nudge

A pause-prevention pinger for Supabase free-tier projects.

**Status:** live since 2026-04-29. Switched from SELECT-based to INSERT-based pings on 2026-05-07 after two of three projects were flagged for inactivity pause despite green workflow runs (see `docs/decisions.md`). The failure-email path was smoke-tested end-to-end on 2026-04-29 (deliberately bad secret → red run → email to repo owner → secret restored → green again); re-verify after each existing project re-runs `setup.sql`.

A scheduled GitHub Actions workflow runs four times per week (Sun/Mon/Wed/Fri at 09:17 UTC) and issues a real `INSERT` against each Supabase project listed in [`projects.json`](./projects.json). If any project returns the wrong status, an auth error, an RLS denial, or a network error, the workflow fails and GitHub emails the repo owner. The maximum gap between runs is two days, well inside Supabase's 7-day inactivity window.

Cost: $0/month. Maintenance: edit one JSON file + add two GitHub Secrets to add a project.

> **Why writes, not reads?** SELECT-based pings turned out to be insufficient for Supabase's free-tier inactivity tracker — pings landed cleanly but two of three projects were still flagged for pause within 7 days. Writes are the empirically-supported pattern. See `docs/decisions.md` (2026-05-07 entry) for the full rationale.

## How it works

- [`projects.json`](./projects.json) — the list of projects to ping. Each entry has an `id`, a `name`, and an optional `table` (defaults to `keep_alive`).
- [`.github/workflows/nudge.yml`](./.github/workflows/nudge.yml) — the cron + manual trigger; passes `${{ toJSON(secrets) }}` to the script as one env var.
- [`scripts/nudge.py`](./scripts/nudge.py) — Python stdlib only; loops over projects, POSTs an empty JSON body to `/rest/v1/<table>` with the anon key and `Prefer: return=representation`, and verifies the response is `201 Created` plus a non-empty JSON array containing the inserted row.
- [`setup.sql`](./setup.sql) — the per-project SQL snippet you run once in each Supabase project's SQL editor (also serves as the migration for existing projects).

> **Note:** the `keep_alive` table is anon-readable **and** anon-writeable by design (the pinger uses the public anon key to INSERT). Don't add sensitive data to it; don't repurpose it for anything else. The RLS policies are intentionally narrow — `SELECT` and `INSERT` only, scoped to that one table — so the blast radius of the anon key is bounded to "anyone can append rows to `public.keep_alive`."

## Secret naming convention

For each project there are two GitHub Secrets, derived from the project's `id`:

| Secret name | Value |
| --- | --- |
| `SUPABASE_<ID>_URL` | `https://<ref>.supabase.co` |
| `SUPABASE_<ID>_ANON_KEY` | the project's anon (public) key |

`<ID>` is the project's `id` from `projects.json`, uppercased. So `id: "groceries"` means the workflow expects `SUPABASE_GROCERIES_URL` and `SUPABASE_GROCERIES_ANON_KEY`.

GitHub Secret names must contain only uppercase letters, digits, and underscores, and may not start with a digit or `GITHUB_`. Pick `id` values that satisfy that.

## Adding a new project

End-to-end, for a project you'll call `myapp`:

1. **Run the SQL snippet on the project.** In the Supabase Dashboard → SQL Editor → New query, paste the contents of [`setup.sql`](./setup.sql) and run it. This creates `keep_alive` with auto-generated `id` and `pinged_at` columns, enables RLS, and grants narrowly-scoped `SELECT` + `INSERT` to `anon`. Re-running it later is safe (it's also the migration path — see "Migrating an existing project" below).
2. **Add two GitHub Secrets.** Repo → Settings → Secrets and variables → Actions → New repository secret:
   - `SUPABASE_MYAPP_URL` — the project URL (e.g. `https://abcd1234.supabase.co`)
   - `SUPABASE_MYAPP_ANON_KEY` — the anon (public) key from Project Settings → API
3. **Add the entry to `projects.json`:**
   ```json
   { "id": "myapp", "name": "My App" }
   ```
   If you skipped step 1 and want to point at an existing table the anon role can already INSERT into (with all columns defaulted), add `"table": "your_table_name"`. Realistically, just run `setup.sql`.
4. **Verify.** Repo → Actions → `supabase-nudge` → Run workflow. Watch the run; you should see `PASS: My App — ok (1 row inserted into 'keep_alive')` and the job should be green. Then open the Supabase Table Editor for the project and confirm a new row with a recent `pinged_at` timestamp.

That's it. No workflow YAML changes, no Python changes.

## Migrating an existing project

If a project was set up under the older SELECT-based pinger and you're moving it to writes:

1. **Re-run [`setup.sql`](./setup.sql)** in the project's SQL Editor. The script is idempotent and migration-safe: it adds the `pinged_at` column if missing, converts the original `integer` `id` column to a generated identity (so `INSERT`s without a body work), and adds the new `INSERT` RLS policy. Existing data is preserved.
2. **Trigger the workflow manually.** Repo → Actions → `supabase-nudge` → Run workflow. Confirm green.
3. **Visually verify.** Open the Supabase Table Editor for the project; confirm one new row appeared in `keep_alive` with a recent `pinged_at` timestamp.

Repeat steps 1–3 once per project. No GitHub Secrets changes, no `projects.json` changes.

## Verifying the workflow is working

- **Day-to-day:** the Actions tab is the dashboard. Green runs are silent; red runs trigger a failure email to the repo owner.
- **Manual run:** Repo → Actions → `supabase-nudge` → Run workflow. Useful after editing `projects.json` or any time you want immediate confirmation rather than waiting for the next cron tick.
- **Re-smoke-test the failure path** (recommended after any non-trivial change to the script or workflow): temporarily change one project's `SUPABASE_<ID>_ANON_KEY` to a wrong value, run the workflow manually, confirm it fails with a clear `FAIL:` line and you get the email, then restore the secret.

## Running locally

For development or to debug a specific project:

```sh
ALL_SECRETS='{"SUPABASE_MYAPP_URL":"https://...supabase.co","SUPABASE_MYAPP_ANON_KEY":"eyJ..."}' \
  python3 scripts/nudge.py
```

`projects.json` should already contain the matching `id` entry. The script reads `projects.json` from the repo root regardless of where you invoke it from.

A successful local run logs `PASS: My App — ok (1 row inserted into 'keep_alive')` **and** appends one new row to that project's `keep_alive` table. Verify both: the log line *and* the row landing. If the log is green but no row appears, something's wrong with the INSERT path (likely RLS) and the script's verification missed it — file a bug.

## Failure modes the script catches

- **Missing secret** — the project's `SUPABASE_<ID>_URL` or `SUPABASE_<ID>_ANON_KEY` isn't in `ALL_SECRETS`.
- **Auth error** — wrong anon key (HTTP 401).
- **RLS denial on INSERT** — `INSERT` policy missing or wrong (HTTP 401 / 403).
- **Non-201 status** — anything other than `201 Created` (e.g. a `200` from a misrouted endpoint) is treated as a failure.
- **Empty response body** — PostgREST didn't echo back the inserted row, e.g. because `Prefer: return=representation` was stripped or the `SELECT` policy is missing on the new row.
- **Wrong table name / missing column default** — HTTP 404 / 400 (the table is gone, or has a non-defaulted column the script can't fill from `{}`).
- **Network error** — DNS failure, timeout, etc.
- **Project paused** — Supabase returns an error response; surfaces as HTTP error.
- **Unexpected redirect** — any 3xx response is treated as a failure rather than followed, so the anon key is never replayed to a different host (defense against `Authorization`-header leak via cross-origin redirect; see [`SECURITY-REVIEW.md`](./SECURITY-REVIEW.md) §2).

The script pings every project before exiting, so one bad project doesn't hide failures in others. Failures are summarised at the end.
