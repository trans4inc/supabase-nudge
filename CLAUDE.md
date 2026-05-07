# Orientation for Claude Code sessions

This repo is `supabase-nudge` — a scheduled GitHub Actions workflow that pings Supabase free-tier projects to prevent the 7-day inactivity auto-pause. The original spec and design rationale live in `docs/spec.md` and `docs/decisions.md` — read those before proposing changes.

**Status:** live since 2026-04-29. Switched from SELECT-based to INSERT-based pings on 2026-05-07 after two of three projects were flagged for inactivity pause despite green workflow runs (see `docs/decisions.md` 2026-05-07 entry). The failure-email path was verified end-to-end on 2026-04-29 (deliberately bad secret → red run → email); re-verify after the writes-based version has been live across the existing projects. Active projects in `projects.json`: DiamondBook, InfoPen, Synthesis. If you're touching this repo, assume real users (those three apps) depend on it staying green — don't break the cron schedule or the success criteria.

## Mental model in 30 seconds

- One workflow (`.github/workflows/nudge.yml`) runs Sun/Mon/Wed/Fri at 09:17 UTC and on manual trigger.
- It runs `scripts/nudge.py`, passing every GitHub Secret as a single JSON blob via `ALL_SECRETS: ${{ toJSON(secrets) }}`.
- The script reads `projects.json`, looks up `SUPABASE_<ID>_URL` and `SUPABASE_<ID>_ANON_KEY` for each entry, and POSTs `{}` to `/rest/v1/<table>` with the anon key plus `Prefer: return=representation`. The DB fills every column from defaults — the script never names a column.
- A "pass" is HTTP 201 + a non-empty JSON array containing the inserted row. Anything else fails the run; GitHub emails the repo owner.
- The single-blob secret pattern is **deliberate**: it means adding a project requires editing only `projects.json` (plus adding two secrets in the GitHub UI). Don't refactor it back to enumerated `env:` entries.

## Where to make common changes

- **Adding/removing a project** — edit `projects.json`. That's it.
- **Per-project ping target** — add `"table": "..."` to the project's entry; default is `keep_alive`. Whatever table you point at must have defaults on every column.
- **Schedule** — `cron:` line in `.github/workflows/nudge.yml`. The 4-day spread keeps gap ≤ 2 days; if you tighten or loosen, update `docs/spec.md` accordingly.
- **What counts as a successful ping** — `ping()` in `scripts/nudge.py`. Be careful: HTTP 201 is required, and a 201 with an empty body still fails (the body must contain the inserted row, which means the SELECT RLS policy has to be in place too).

## Constraints worth re-reading the docs for

- Anon keys only — never service role keys (`docs/decisions.md`, 2026-04-29 entry).
- Python stdlib only — no `pip install` step (keeps the workflow fast and dependency-free).
- **Pings must be writes, not reads.** SELECT-based pings were tried first and were demonstrably insufficient — Info Pen and Synthesis got flagged for pause within 7 days of go-live despite every workflow run completing green. See `docs/decisions.md` (2026-05-07 entry). Don't "simplify" the script back to a GET against `keep_alive` — it'll look cleaner and silently fail to keep projects alive.
- The script POSTs `{}` and lets the database fill every column from defaults. This is deliberate: it keeps the script decoupled from the table's exact column list, so schema tweaks don't require coordinated script changes. If you add a new required column without a default, the INSERT will start failing — add a default or revert.
- The repo is **private**. This matters: `permissions: {}` would strip the `contents:read` scope `actions/checkout` needs to clone, so the workflow uses `permissions: contents: read` (the strictest setting that still works) and intentionally drops every write scope.
- Out of scope for v1: Slack/Discord notifications, auto-unpause, custom dashboard, per-project frequencies. The Actions tab is the dashboard.

## If pause emails recur after the writes-based switch

Don't assume writes-based pings are wrong without first verifying:

1. Workflow runs are green and have been since the switch (`docs/decisions.md` 2026-05-07).
2. Each project's `keep_alive` table shows ~4 new rows per week (open Table Editor; sort by `pinged_at` desc).
3. Supabase API logs show our POST requests landing as `201`s at the cron timestamps.

If all three confirm but pause still happens, that's evidence Supabase has tightened the activity threshold further. Escalate via a support ticket and consider whether the affected project should move to Pro tier ($25/month). At that point the free-tier keep-alive pattern is exhausted.

## Security-related decisions (see SECURITY-REVIEW.md for full rationale)

- The `_NoRedirect` handler in `nudge.py` is **deliberate**: it raises on any 3xx so the `Authorization` header is never replayed to a different host (urllib follows redirects with auth attached by default, unlike `requests`). Don't simplify back to plain `urlopen` — local tests prove it blocks cross-origin redirects.
- `actions/checkout@v4` is **intentionally not SHA-pinned**. It's a first-party action and the maintenance cost of pinning + scheduled bumps was judged not worth it for this hobby tool. Don't proactively SHA-pin without re-evaluating the threat model.
- The `keep_alive` table is anon-readable by design. Don't add sensitive data to it; the README warns about this.
- `repr(e)` in the unexpected-error branch was reviewed and deliberately left as-is — GitHub log masking already provides a backstop, and a more verbose message is more useful for real debugging.

## Testing

Locally you can run:

```sh
ALL_SECRETS='{"SUPABASE_FOO_URL":"...","SUPABASE_FOO_ANON_KEY":"..."}' python3 scripts/nudge.py
```

with a matching entry in `projects.json`. A successful run logs `PASS: Foo — ok (1 row inserted into 'keep_alive')` **and** appends one row to that project's `keep_alive` table — verify both, since a green log without a row landing means the script's verification missed something.

To smoke-test failure paths:
- Wrong anon key → HTTP 401.
- `table` set to a nonexistent name → HTTP 404 / 400.
- Temporarily revoke the `"anon can insert keep_alive"` policy on one project → HTTP 401/403 on the INSERT.
- Temporarily revoke the `"anon can select keep_alive"` policy → INSERT succeeds with 201 but body is empty → "empty response from INSERT" failure.

For the workflow YAML, run `actionlint .github/workflows/nudge.yml`.

After any non-trivial change to `nudge.py` or the workflow, re-run the live failure smoke-test on GitHub (temporarily break one secret, run, confirm red + email, restore). The full run path is the only thing that catches issues like a response-shape change from Supabase.
