# supabase-nudge

A pause-prevention pinger for Supabase free-tier projects.

**Status:** live since 2026-04-29 — workflow runs cleanly on manual trigger, the failure-email path has been smoke-tested end-to-end (deliberately bad secret → red run → email to repo owner → secret restored → green again).

A scheduled GitHub Actions workflow runs four times per week (Sun/Mon/Wed/Fri at 09:17 UTC) and issues a real `SELECT` query against each Supabase project listed in [`projects.json`](./projects.json). If any project returns no data, an auth error, or a network error, the workflow fails and GitHub emails the repo owner. The maximum gap between runs is two days, well inside Supabase's 7-day inactivity window.

Cost: $0/month. Maintenance: edit one JSON file + add two GitHub Secrets to add a project.

## How it works

- [`projects.json`](./projects.json) — the list of projects to ping. Each entry has an `id`, a `name`, and an optional `table` (defaults to `keep_alive`).
- [`.github/workflows/nudge.yml`](./.github/workflows/nudge.yml) — the cron + manual trigger; passes `${{ toJSON(secrets) }}` to the script as one env var.
- [`scripts/nudge.py`](./scripts/nudge.py) — Python stdlib only; loops over projects, hits `/rest/v1/<table>?select=*&limit=1` with the anon key, and verifies the response is a non-empty JSON array.
- [`setup.sql`](./setup.sql) — the per-project SQL snippet you run once in each Supabase project's SQL editor.

> **Note:** the `keep_alive` table is anon-readable by design (the pinger uses the public anon key). Don't add sensitive data to it — anything in that table can be read by anyone holding the project's anon key.

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

1. **Run the SQL snippet on the project.** In the Supabase Dashboard → SQL Editor → New query, paste the contents of [`setup.sql`](./setup.sql) and run it. This creates `keep_alive`, inserts one row, enables RLS, and grants `SELECT` to `anon`. Re-running it later is safe.
2. **Add two GitHub Secrets.** Repo → Settings → Secrets and variables → Actions → New repository secret:
   - `SUPABASE_MYAPP_URL` — the project URL (e.g. `https://abcd1234.supabase.co`)
   - `SUPABASE_MYAPP_ANON_KEY` — the anon (public) key from Project Settings → API
3. **Add the entry to `projects.json`:**
   ```json
   { "id": "myapp", "name": "My App" }
   ```
   If you skipped step 1 and want to point at an existing table the anon role can already read, add `"table": "your_table_name"`.
4. **Verify.** Repo → Actions → `supabase-nudge` → Run workflow. Watch the run; you should see `PASS: My App — ok (1 row from 'keep_alive')` and the job should be green.

That's it. No workflow YAML changes, no Python changes.

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

## Failure modes the script catches

- **Missing secret** — the project's `SUPABASE_<ID>_URL` or `SUPABASE_<ID>_ANON_KEY` isn't in `ALL_SECRETS`.
- **Auth error** — wrong anon key (HTTP 401).
- **RLS denial** — table exists but the anon role can't `SELECT` (often shows as an empty array).
- **Empty table** — the `keep_alive` row was deleted; ping looks like a 200 but with `[]`.
- **Wrong table name** — HTTP 404 / 400.
- **Network error** — DNS failure, timeout, etc.
- **Project paused** — Supabase returns an error response; surfaces as HTTP error.
- **Unexpected redirect** — any 3xx response is treated as a failure rather than followed, so the anon key is never replayed to a different host (defense against `Authorization`-header leak via cross-origin redirect; see [`SECURITY-REVIEW.md`](./SECURITY-REVIEW.md) §2).

The script pings every project before exiting, so one bad project doesn't hide failures in others. Failures are summarised at the end.
