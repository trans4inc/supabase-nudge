# Orientation for Claude Code sessions

This repo is `supabase-nudge` — a scheduled GitHub Actions workflow that pings Supabase free-tier projects to prevent the 7-day inactivity auto-pause. The original spec and design rationale live in `docs/spec.md` and `docs/decisions.md` — read those before proposing changes.

**Status:** live since 2026-04-29. Manual runs are green, the failure-email path has been verified end-to-end (deliberately bad secret produced a red run + an email to the repo owner). Active projects in `projects.json`: DiamondBook, InfoPen, Synthesis. If you're touching this repo, assume real users (those three apps) depend on it staying green — don't break the cron schedule or the success criteria.

## Mental model in 30 seconds

- One workflow (`.github/workflows/nudge.yml`) runs Sun/Mon/Wed/Fri at 09:17 UTC and on manual trigger.
- It runs `scripts/nudge.py`, passing every GitHub Secret as a single JSON blob via `ALL_SECRETS: ${{ toJSON(secrets) }}`.
- The script reads `projects.json`, looks up `SUPABASE_<ID>_URL` and `SUPABASE_<ID>_ANON_KEY` for each entry, and hits `/rest/v1/<table>?select=*&limit=1` with the anon key.
- A "pass" is HTTP 200 + a non-empty JSON array. Anything else fails the run; GitHub emails the repo owner.
- The single-blob secret pattern is **deliberate**: it means adding a project requires editing only `projects.json` (plus adding two secrets in the GitHub UI). Don't refactor it back to enumerated `env:` entries.

## Where to make common changes

- **Adding/removing a project** — edit `projects.json`. That's it.
- **Per-project ping target** — add `"table": "..."` to the project's entry; default is `keep_alive`.
- **Schedule** — `cron:` line in `.github/workflows/nudge.yml`. The 4-day spread keeps gap ≤ 2 days; if you tighten or loosen, update `docs/spec.md` accordingly.
- **What counts as a successful ping** — `ping()` in `scripts/nudge.py`. Be careful: HTTP 200 alone is not enough (an empty array is also a 200), and the spec calls this out explicitly.

## Constraints worth re-reading the docs for

- Anon keys only — never service role keys (`docs/decisions.md`, 2026-04-29 entry).
- Python stdlib only — no `pip install` step (keeps the workflow fast and dependency-free).
- The repo is **private**. This matters: `permissions: {}` would strip the `contents:read` scope `actions/checkout` needs to clone, so the workflow uses `permissions: contents: read` (the strictest setting that still works) and intentionally drops every write scope.
- Out of scope for v1: Slack/Discord notifications, auto-unpause, custom dashboard, per-project frequencies. The Actions tab is the dashboard.

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

with a matching entry in `projects.json`. To smoke-test failure paths, swap in a wrong anon key (auth failure) or point `table` at a nonexistent name (HTTP 4xx) or an empty table (empty-array failure).

For the workflow YAML, run `actionlint .github/workflows/nudge.yml`.

After any non-trivial change to `nudge.py` or the workflow, re-run the live failure smoke-test on GitHub (temporarily break one secret, run, confirm red + email, restore). The full run path is the only thing that catches issues like an auth response shape change from Supabase.
