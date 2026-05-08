# Claude Code handoff: switch `supabase-nudge` from SELECT pings to INSERT pings

## Context — why this change

Two of three nudged projects (Info Pen, Synthesis) were flagged for inactivity pause within 7 days of go-live, despite every scheduled workflow run completing green. Investigation confirmed:

- The pings are reaching the right projects (verified via Supabase API logs: `200 GET /rest/v1/keep_alive` requests at the cron timestamps).
- The current SELECT-based ping is not sufficient to count as "activity" for Supabase's free-tier inactivity tracker. Supabase's docs phrase this as "low activity in a 7-day period" — a threshold model, not a binary one.
- The most-starred community keep-alive tool (`travisvn/supabase-inactive-fix`) uses INSERT + DELETE rather than SELECT.
- Supabase community discussion #38442 documents a user whose once-weekly INSERT was insufficient and whose twice-weekly INSERT was sufficient. Confirmed Feb 2026.

The fix: switch from a GET against `keep_alive` to a POST that creates a new row each ping. The schedule, secrets pattern, and `projects.json` structure don't change.

There is **no authoritative Supabase statement** confirming this approach is correct. It is the best-supported bet given the available evidence. If pause emails recur after this change, see "Note for the next debugging session" at the bottom.

## What needs to change behaviorally

- Each ping does an INSERT into the project's `keep_alive` table instead of a SELECT.
- "Pass" = HTTP 201 Created + the inserted row returned in the response body (use `Prefer: return=representation` on the request).
- All current failure modes still fail the run: auth error, RLS denial, network error, unexpected redirect (the existing `_NoRedirect` handler stays), 4xx/5xx, missing or malformed response body.
- The script should not specify column values on insert — let the database fill defaults. This keeps the script decoupled from the table's exact column list.

## Schema changes (in `setup.sql`)

- Add a `pinged_at TIMESTAMPTZ DEFAULT now()` column (or equivalent — name it whatever reads well) to `keep_alive`. Use `ADD COLUMN IF NOT EXISTS` so existing tables migrate without data loss.
- Add an RLS policy: `INSERT TO anon WITH CHECK (true)` scoped to `keep_alive` only.
- Keep the existing `SELECT TO anon` policy. PostgREST needs SELECT permission on the table to return the inserted row when using `Prefer: return=representation`.
- `setup.sql` must remain idempotent so the user can re-run it on existing projects as a migration. The current file is already idempotent; preserve that property.

## Security implications

- The anon key gains narrowly-scoped INSERT capability on one dedicated table. No UPDATE, no DELETE, no schema modification.
- The `keep_alive` table will accumulate rows slowly (4 inserts/week × N projects = a few hundred rows/year). By design, no cleanup logic in v1. The accumulating rows act as a free audit trail.
- `SECURITY-REVIEW.md` needs updating: section 5 was previously "anon SELECT only on keep_alive"; it now needs to cover the INSERT addition and explain the bounded blast radius.

## Files to update

- `setup.sql` — schema migration + new INSERT policy. Idempotent.
- `scripts/nudge.py` — switch GET to POST with `Prefer: return=representation`; update pass criteria; preserve the `_NoRedirect` handler and all current failure-mode coverage.
- `README.md` — update "How it works", the per-project setup steps, the failure-modes list, and the security note. Add a sentence to the existing "anon-readable by design" warning explaining anon also has narrowly-scoped INSERT now.
- `docs/spec.md` — update to reflect INSERT-based ping. The acceptance criteria stay structurally the same; only the ping mechanism changes.
- `docs/decisions.md` — add a new dated entry documenting this switch. Capture the lesson: the original "REST SELECT counts as activity" assumption was based on third-party guides that turned out to be wrong (or out of date) for current Supabase behavior. Empirical evidence beat the consensus guidance.
- `CLAUDE.md` — update the orientation file. The "Mental model in 30 seconds" section needs to say writes, not reads. Add a one-line reminder under "Constraints worth re-reading the docs for" that SELECT-based pings were tried and demonstrably insufficient — don't let a future session "simplify" back to GET.
- `docs/SECURITY-REVIEW.md` — update section 5 (anon table privileges) and the resolution table to reflect the INSERT addition.

## User actions required after the code change

The user (not Claude Code) needs to:
1. Re-run the updated `setup.sql` in each of the three existing projects' SQL editors (DiamondBook, Info Pen, Synthesis).
2. Trigger the workflow manually and confirm green.
3. Visually confirm one new row appears in each project's `keep_alive` table (Table Editor).

The handoff should make this user-side responsibility explicit in the README's "Adding a new project" section and in a new "Migrating an existing project" subsection.

## Acceptance criteria

- Workflow runs on the same Mon/Wed/Fri/Sun 09:17 UTC schedule + manual trigger.
- Each scheduled run does an INSERT per project and verifies the response confirms the row was created.
- A failed INSERT (auth, RLS denial, network, redirect, non-201, empty body) fails the run with a clear `FAIL:` line naming the project.
- Existing projects can migrate by running the new `setup.sql` once. No data loss, no manual SQL beyond pasting and running the file.
- Adding a *new* project still requires only: run `setup.sql` in that project, add two GitHub Secrets, add an entry to `projects.json`.
- All five documentation files (README, spec, decisions, CLAUDE.md, SECURITY-REVIEW.md) are updated consistently.
- Local-run instructions in the README reflect the new behavior.

## Smoke tests Claude Code should run before declaring done

- `actionlint .github/workflows/nudge.yml` clean.
- Local script run against a real project (one of the three, with the user's permission) — verify green, verify a row appears in `keep_alive` with a recent `pinged_at`.
- Failure smoke-test: temporarily revoke the INSERT policy on one project, run, confirm red + failure message points at the right project, then restore the policy.
- Manual workflow run on GitHub: green, all three projects PASS, all secret values still masked as `***` in the logs.

## Out of scope for this change (deliberately)

- A separate verification workflow that reads recent `pinged_at` timestamps to confirm writes are landing. Worth doing as v1.1 — flag in the new `decisions.md` entry as a "next-step" item, but don't build it here.
- Any cleanup of accumulated `keep_alive` rows.
- Changing the schedule or per-project frequencies.
- Slack/Discord notifications, custom dashboard — already out-of-scope per the existing spec.

## Note for the next debugging session (preserve in `CLAUDE.md` or `decisions.md`)

If pause emails recur after this change, do not assume the writes-based design is wrong without first checking:
1. Workflow runs are green and have been since deployment.
2. `keep_alive` tables show the expected row growth (4 new rows per project per week).
3. Supabase API logs show our POST requests landing as 201s.

If all three confirm but pause still happens, that's evidence Supabase has tightened the activity threshold further. Escalate via a support ticket and consider whether the affected project should move to Pro tier ($25/month) — at that point we've exhausted what the free-tier keep-alive pattern can reliably do.
