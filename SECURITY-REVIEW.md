# Security review — `supabase-nudge`

**Review date:** 2026-04-29
**Scope:** the five risks listed below, plus one bonus finding spotted during review.
**Resolution date:** 2026-04-29 — actionable fixes shipped same day; deliberately-skipped items recorded below with reasoning.

| # | Risk | Verdict | Status |
| --- | --- | --- | --- |
| 1 | Secret leakage in logs | Fine, with optional tightening | Reviewed; tightening **deliberately skipped** |
| 2 | Malicious `projects.json` exfiltration | **Defense-in-depth gap** — urllib follows redirects with `Authorization` header attached | **Fixed** (commit `a84e62e`) |
| 3 | External action pinning | **Concern** — `actions/checkout@v4` is a mutable tag | **Deliberately skipped** for now |
| 4 | Trigger surface | Fine | No action needed |
| 5 | `setup.sql` scope | Re-evaluated 2026-05-07 — `INSERT TO anon` policy added | **Fixed** — README warning expanded (2026-05-07) |
| Bonus | `GITHUB_TOKEN` permissions | Broader than needed; recommend locking down | **Fixed** (commits `a84e62e` + `4f09017`) |

## 1. Could `nudge.py` log or expose secret values?

**Verdict: mostly fine.** Walked the print paths in `scripts/nudge.py`:

- The missing-secret branch echoes the secret **name** (`SUPABASE_<ID>_URL`) — never the value.
- `request_url` is printed in failure messages; it embeds the project URL but **not** the key (the key only ever lives in the request headers).
- The HTTP-error branch prints the first 200 chars of the response body. Supabase's 401 body is `{"message":"Invalid API key","hint":"..."}` — does not echo the submitted key. Verified live during the wrong-key smoke test. A different upstream that *did* echo back submitted credentials could leak via this path, but Supabase doesn't.
- The unexpected-error branch uses `f"unexpected error: {e!r}"`. `repr()` of standard `urllib.error.*` exceptions doesn't include request headers, but a non-`urllib` exception class could in theory carry more. Low risk.

**Backstop:** GitHub Actions auto-masks any string matching a secret value in workflow logs. Even if a value did slip through, it'd render as `***`. Side effect: URLs stored in secrets show as `***/rest/v1/...` in failed-run logs, which costs some debuggability but isn't a security issue.

**Optional tightening:** swap the unexpected-error path from `{e!r}` to `{type(e).__name__}: {e}` to narrow what gets printed. Not urgent.

**Status (2026-04-29): reviewed, deliberately not addressed.** The optional `repr(e)` tightening is too marginal a payoff to justify the code change — GitHub Actions log masking already provides a backstop, the `urllib.error.*` exceptions don't carry credential material, and the verbose message form is more useful than less for debugging real failures.

## 2. Could a malicious `projects.json` exfiltrate anon keys?

**Verdict: one real defense-in-depth gap.**

The host of the request is locked by the **secret**, not by `projects.json`. An attacker editing `projects.json` chooses only:

- The `id` — which decides which secret name to look up. Picking an id with no matching secrets fails early (`None`); picking a real id sends to the real (legit) host. No exfiltration.
- The `table` — which becomes part of the URL path. Hostile values like `"../../evil"` or `"x?evil=1"` are resolved by urllib **within** the locked host. No host escape.

**The gap:** `urllib.request.urlopen` follows HTTP redirects by default and **does not strip the `Authorization` header on cross-origin redirects**. (The popular `requests` library strips it; urllib doesn't.) If a Supabase host ever returned a 3xx pointing at a different domain, the anon key would be sent in the Bearer header to that domain.

- **Likelihood:** very low. Would require a Supabase-side compromise or a misconfigured project. HTTPS prevents on-path injection.
- **Impact:** bounded. Anon keys are designed to be public-facing and protected by RLS; the threat model already assumes they're somewhat exposed.
- **But:** still avoidable, and the fix is small.

**Suggested fix.** Disable redirect-following:

```python
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None

opener = urllib.request.build_opener(NoRedirect())
```

…then call `opener.open(req, timeout=TIMEOUT_SECONDS)` instead of `urllib.request.urlopen`. A 3xx then surfaces as a `urllib.error.HTTPError` with the redirect status, which the existing failure path already handles. Alternative: leave redirects on but assert `resp.url`'s netloc matches the request URL's netloc.

**Status (2026-04-29): fixed in commit `a84e62e`.** Added a custom `_NoRedirect(urllib.request.HTTPRedirectHandler)` whose `http_error_3{01,02,03,07,08}` methods all raise `urllib.error.HTTPError` immediately rather than constructing a follow-up request. Built a module-level `_OPENER = urllib.request.build_opener(_NoRedirect())` and switched the call site from `urllib.request.urlopen(req, ...)` to `_OPENER.open(req, ...)`. Verified locally with a temporary http.server: a cross-origin 302 surfaces as `HTTP 302 from <original_url>` and the redirect target is never contacted. Re-verified the green path on GitHub run `25128637607` (all three projects PASS).

## 3. Pinning of external GitHub Actions

**Verdict: concern.**

`.github/workflows/nudge.yml`:

```yaml
- uses: actions/checkout@v4
```

`@v4` is a **mutable major-version tag**. GitHub's own hardening guidance recommends pinning actions to a full commit SHA so a tag retargeting (intentional or compromised) can't swap in different code mid-flight.

`actions/checkout` is maintained by GitHub's first-party `actions` org, so the trust baseline is higher than a random third-party action — but the workflow does run with the repo's secrets in env, so a compromised checkout step could in principle exfiltrate them.

**Suggested fix:**

```yaml
- uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11 # v4.1.1
```

(Pick the current latest SHA at the time of fix and add the human-readable version as a trailing comment. Pair with Dependabot or a quarterly note to bump it.)

**Alternative:** the script doesn't actually need a checked-out repo with full git history — it only reads `projects.json` and `scripts/nudge.py`. You could replace `actions/checkout` with two `curl` calls in a `run:` step and remove the dependency entirely. More work to read; eliminates the pinning question. Judgment call.

**Status (2026-04-29): reviewed, deliberately not addressed.** For a hobby tool whose only third-party dependency is a first-party GitHub-maintained action (`actions/checkout`), the maintenance cost of SHA-pinning + scheduled bumps was judged to outweigh the marginal security gain. Revisit if the workflow grows to depend on third-party (non-`actions/*`) actions, or if the threat model changes.

(Forward-looking aside, not strictly a security item: GitHub Actions has begun warning that `actions/checkout@v4` runs on Node.js 20, which is being forced to Node.js 24 starting 2026-06-02. A future bump to `actions/checkout@v5` will resolve both the deprecation warning and — at the same time — present a natural moment to reconsider SHA-pinning if desired. The existing failure-email path will surface any breakage from the Node deprecation.)

## 4. Triggers beyond schedule and workflow_dispatch

**Verdict: clean.**

`.github/workflows/nudge.yml`:

```yaml
on:
  schedule:
    - cron: '17 9 * * 0,1,3,5'
  workflow_dispatch:
```

No `pull_request`, no `pull_request_target`, no `push`, no `repository_dispatch`. No path for an outsider PR to trigger the secret-bearing run.

**Status (2026-04-29): no action needed.** Trigger surface is correct as-is.

## 5. `setup.sql` scope — anon privileges on `keep_alive`

**Verdict (2026-05-07 update): clean. Anon now has `SELECT` *and* `INSERT` on `keep_alive`. Scope remains narrow and the blast radius is bounded.**

Every statement in `setup.sql` is still scoped to `public.keep_alive`:

- `CREATE TABLE IF NOT EXISTS public.keep_alive (...)` — one table.
- `ALTER TABLE public.keep_alive ADD COLUMN IF NOT EXISTS pinged_at ...` — additive column on the same table; idempotent migration for pre-existing tables.
- `ALTER TABLE public.keep_alive ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY ...` — wrapped in a `DO` block that no-ops if `id` is already an identity column. Same table only.
- `ALTER TABLE public.keep_alive ENABLE ROW LEVEL SECURITY` — that table only.
- `CREATE POLICY ... FOR SELECT TO anon USING (true)` — `SELECT` only, `anon` only, scoped to that table.
- `CREATE POLICY ... FOR INSERT TO anon WITH CHECK (true)` — `INSERT` only, `anon` only, scoped to that table. No `UPDATE`, no `DELETE`, no `ALL`. No `GRANT` statements that broaden table-level privileges.

**Why the new INSERT policy?** SELECT-based pings turned out to be insufficient for Supabase's free-tier inactivity tracker (see `docs/decisions.md` 2026-05-07 entry). The pinger now POSTs to `/rest/v1/keep_alive` to append a row each ping; that requires `INSERT TO anon`. The existing `SELECT TO anon` policy is also necessary, because PostgREST needs `SELECT` permission on the row it just inserted in order to echo it back when the request uses `Prefer: return=representation` (which the script relies on to verify the write actually landed).

**Bounded blast radius.** With both policies in place, the anon key's full capability surface on this project is:

- Read all rows from `public.keep_alive`.
- Append rows to `public.keep_alive` (every column has a default, so no column-name knowledge required).

It cannot UPDATE, DELETE, or modify schema; it cannot touch any other table; it cannot invoke RPCs that haven't been explicitly granted to anon. A leaked anon key gets the attacker the ability to spam-fill that one table and to read whatever's already in it. The table is designed to be anon-readable and will only ever hold ping audit rows — by policy, no sensitive data ever goes in it. Worst case from a leak: the attacker fills the table with junk, eating free-tier storage. Storage cost is bounded by free-tier limits; cleanup is `TRUNCATE public.keep_alive` followed by a key rotation.

**Forward-looking note (minor):** the table will accumulate ~4 rows/project/week × N projects ≈ a few hundred rows/year. By design, no cleanup logic in v1. The accumulating rows act as a free audit trail. Anyone editing `keep_alive` later still shouldn't put sensitive data in it — the SELECT policy doesn't filter rows.

**Status (2026-04-29 + 2026-05-07): SQL re-scoped on 2026-05-07 to add `INSERT TO anon`; README updated accordingly.** The original 2026-04-29 anon-readable warning has been expanded to mention the narrowly-scoped INSERT capability and the bounded blast radius.

## Bonus finding — `GITHUB_TOKEN` permissions

Not on your list, but worth flagging.

The workflow doesn't declare `permissions:`, so it inherits the **repo default** — typically read/write on `contents` and several other scopes. The script doesn't need *any* `GITHUB_TOKEN` permissions; it only makes outbound HTTP to Supabase. Locking the token down is defense-in-depth in case the script is ever compromised.

**Suggested fix:**

```yaml
jobs:
  ping:
    runs-on: ubuntu-latest
    permissions: {}     # or: contents: read
    steps:
      - uses: actions/checkout@<sha>
      ...
```

`permissions: {}` is the strictest — no token scopes at all. `contents: read` is the next-strictest and lets `actions/checkout` clone the repo (which it already does fine without explicit permission, but being explicit is better).

**Status (2026-04-29): fixed in commits `a84e62e` and `4f09017`.** Initial commit `a84e62e` set `permissions: {}` on the `ping` job per the strictest-possible recommendation. The first manual run (id `25128442220`) then failed at the checkout step with "repository not found" — `permissions: {}` had stripped the `contents:read` scope that `actions/checkout` needs to clone a **private** repository. (My review above incorrectly assumed the no-permissions form would work because I was implicitly treating the repo as public.) Follow-up commit `4f09017` relaxed the setting to `permissions: contents: read`, which is still strictly read-only — no write scopes anywhere — but enough for the clone to succeed. Re-verified with manual run `25128637607`: green, all three projects PASS, all secret values masked as `***` in the logs.

## Recommended fixes (if you want me to apply them)

Three actionable items, all small:

1. Disable HTTP redirects in `nudge.py` (~6 lines).
2. SHA-pin `actions/checkout` in `nudge.yml` (1-line change + comment).
3. Add `permissions: {}` to the `ping` job (1 line).

Optional fourth: tighten the `repr(e)` in the unexpected-error branch.

I'd ship all three in one commit and re-run the live failure smoke-test on GitHub afterward to confirm nothing regressed.

## Resolution summary (2026-04-29)

| # | Disposition | Commit(s) | Notes |
| --- | --- | --- | --- |
| 1 (optional `repr(e)`) | Skipped | — | Marginal payoff vs. code-change cost; backstop already exists in GitHub log masking |
| 2 (redirect blocking) | Fixed | `a84e62e` | `_NoRedirect` handler raises on 3xx; verified with local http.server test |
| 3 (SHA-pin `checkout`) | Skipped | — | First-party action only; maintenance cost > marginal gain for this hobby tool |
| 4 (trigger surface) | No action | — | Already correct |
| 5 (README warning) | Fixed (then expanded 2026-05-07) | `a84e62e`, then 2026-05-07 update | Original warning: `keep_alive` is anon-readable. Expanded 2026-05-07 to cover anon `INSERT` capability added when the pinger switched from SELECT-based to INSERT-based; blast radius re-evaluated and remains bounded |
| Bonus (`GITHUB_TOKEN`) | Fixed (with adjustment) | `a84e62e` then `4f09017` | Initial `permissions: {}` broke checkout on this private repo; relaxed to `contents: read` while keeping every write scope dropped |

**Failure-email path re-verified on 2026-04-29 after security fixes.** The user ran the smoke-test (deliberately broke one project's anon-key secret, triggered the workflow, confirmed a red run + a workflow-failure email, then restored the secret). End-to-end behavior is unchanged from the original 2026-04-29 verification: failures still produce a red run and the email still lands. Review closed.
