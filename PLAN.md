# `supabase-nudge` — build plan

Pre-build proposal for review. Nothing is implemented yet; once you sign off on the choices below, I'll build.

## Secret naming convention

For each project, two GitHub Secrets:

```
SUPABASE_<ID>_URL
SUPABASE_<ID>_ANON_KEY
```

Where `<ID>` is an uppercase identifier — letters, digits, and underscores only, no leading digit. Example: project "groceries" → `SUPABASE_GROCERIES_URL` and `SUPABASE_GROCERIES_ANON_KEY`.

Why this prefix order: secrets group alphabetically in the GitHub UI, so all `SUPABASE_*` for a given project sit together.

## File / config structure

```
.github/workflows/nudge.yml    # cron schedule + workflow_dispatch, runs the script
scripts/nudge.py               # the ping logic — Python stdlib only, no pip install
projects.json                  # single source of truth for which projects to ping
setup.sql                      # per-project SQL snippet
README.md
CLAUDE.md
```

### `projects.json` shape

A flat list, one entry per project:

```json
[
  { "id": "groceries", "name": "Groceries app" },
  { "id": "journal",   "name": "Journal",        "table": "users" }
]
```

- `id` — derives the secret names (uppercased). The only thing tying config to secrets.
- `name` — human-readable; used in logs and the failure message.
- `table` — optional, defaults to `keep_alive`.

**Adding a new project = edit `projects.json` + add the two secrets in the GitHub UI.** Nothing else.

## Language: Python stdlib only

`urllib` + `json`, no third-party deps. Reasoning:

- Zero `pip install` step — workflow runs are faster and have one fewer failure mode.
- Pre-installed on `ubuntu-latest`.
- More readable than bash for the looping and error-handling we need.

## How secrets reach the script

The workflow passes **one** env var:

```yaml
env:
  ALL_SECRETS: ${{ toJSON(secrets) }}
```

The script parses that JSON and looks up `SUPABASE_<ID>_URL` / `SUPABASE_<ID>_ANON_KEY` per project at runtime.

This is the trick that lets a new project be added **without editing the workflow YAML**. The alternative — enumerating every secret in an `env:` block — would mean adding a project requires two file edits, violating the spec's "edit one place" requirement.

## Ping logic

For each project in `projects.json`:

1. Look up `SUPABASE_<ID>_URL` and `SUPABASE_<ID>_ANON_KEY` in `ALL_SECRETS`. Missing secret → failure for that project.
2. `GET <url>/rest/v1/<table>?select=*&limit=1` with headers `apikey: <key>` and `Authorization: Bearer <key>`.
3. Verify HTTP 200 **and** the parsed JSON body is a non-empty array. Anything else (network error, 4xx/5xx, empty array, malformed JSON) → failure.

The script pings **every** project before exiting — it does not short-circuit on the first failure. One run should surface every broken project at once. Failures are collected, logged with project name + reason, and the script exits non-zero at the end if any failed.

## Workflow YAML sketch

- `name: supabase-nudge`
- Triggers: `schedule: - cron: '17 9 * * 0,1,3,5'` (Sun / Mon / Wed / Fri at 09:17 UTC) and `workflow_dispatch`
- Single job `ping` on `ubuntu-latest`:
  - `actions/checkout@v4`
  - `actions/setup-python@v5` (pinned minor version)
  - `python scripts/nudge.py` with `ALL_SECRETS: ${{ toJSON(secrets) }}` in `env:`

## `setup.sql` (per-project snippet)

Run once per Supabase project in the SQL editor. Will:

1. `CREATE TABLE IF NOT EXISTS keep_alive (...)` — minimal schema, one column is enough.
2. `INSERT` one row if the table is empty (idempotent — safe to re-run).
3. `ALTER TABLE keep_alive ENABLE ROW LEVEL SECURITY`.
4. `CREATE POLICY` granting `SELECT` to the `anon` role.

Idempotent so the user can re-run it safely if something goes wrong.

## What I'll verify before declaring done

1. **Success path** — run `nudge.py` locally with one project's real creds; confirm it reports success.
2. **Auth failure** — re-run with a deliberately wrong anon key; confirm clear failure message.
3. **Empty response** — point at a table with no rows (or a wrong table name); confirm it's detected as a failure, not a false success.
4. **Workflow YAML** — `actionlint` on `nudge.yml`.
5. **SQL snippet** — syntax-check `setup.sql` as Postgres. (If you have a local Postgres I'll run it against a throwaway DB; otherwise I'll lean on `pg_query` / a parser.)

**Pending the first GitHub run** (cannot be verified locally): the cron actually firing, and GitHub's failure-email behavior reaching you.

## What I need from you to start building

1. **Sign-off** on the secret convention and `projects.json` shape above (or tweaks).
2. **One project's test credentials** — URL + anon key — for the local verification steps. I'll use them only for testing and will not write them to disk.
