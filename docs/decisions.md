
## 2026-04-29 — Design decisions for `supabase-nudge`

**Decision** — Build the pause-prevention pinger as a GitHub Actions workflow named `supabase-nudge`. Pings four times per week (Mon/Wed/Fri/Sun at 09:17 UTC) using anon keys against a dedicated `keep_alive` table in each Supabase project. No v1 dashboard.

**Context** — Following the 2026-04-28 decision to stay on Supabase free tier and build a pinger, the design needed to be locked in before handoff to Claude Code: where it runs, what credentials it uses, what it pings, how often, and how visible status needs to be.

**Alternatives considered**

- **Hosting:** Vercel Cron (rejected — free tier limited to one cron job, friction for adding new projects); a personal VPS (rejected — adds ops burden contrary to the "minimal maintenance" priority).
- **Credentials:** service role key (rejected — far more powerful than needed; anon key is sufficient and lower-blast-radius if leaked).
- **Ping target:** `/auth/v1/health` endpoint (rejected — not a database query, undocumented whether it counts as activity); hitting an existing app table per project (rejected — inconsistent across projects, harder to maintain).
- **Frequency:** every 3 days (rejected in favor of 4x/week — tighter buffer, no real cost increase); weekly (rejected — no margin for missed runs).
- **Dashboard:** workflow summary using GitHub Actions job summaries (deferred — GitHub's built-in run history is sufficient for v1); static HTML status page on GitHub Pages (deferred — adds frontend maintenance); custom web app (rejected — would itself need pause prevention, recursive).

**Rationale** — GitHub Actions is the lowest-maintenance host: free, secrets management built in, no server to patch, run history visible in the UI. Anon keys are safer than service role keys and sufficient when paired with an RLS policy permitting SELECT on the keep-alive table. The dedicated `keep_alive` table pattern is consistent across projects (one snippet handles them all) rather than per-project guesswork. Mon/Wed/Fri/Sun keeps the maximum gap at 2 days, leaving comfortable buffer inside the 7-day pause window even if a run fails. Skipping a dashboard in v1 follows the "lightweight" scope decision — the GitHub Actions tab already shows green/red status per run, and a workflow summary can be added in 30 minutes later if needed.

**Open questions**

- Per-project Supabase setup (creating the `keep_alive` table and RLS policy) — Claude Code will produce a SQL snippet to run once per project; not yet drafted.
- Final list of projects to onboard — to be gathered before the handoff.

---

## 2026-04-28 — Stay on Supabase free tier; build a pause-prevention pinger

**Decision** — Keep all current apps on Supabase free tier and build a small "pause-prevention" app that pings each project on a schedule to prevent the 7-day inactivity auto-pause.

**Context** — Supabase free-tier projects are auto-paused after 7 days of inactivity. Multiple existing apps are affected. Needed a path that keeps projects alive without disrupting the current stack.

**Alternatives considered**
- Supabase Pro ($25/project/month) — fully managed, no pausing, but expensive across many projects.
- Self-hosting Supabase (Docker, Hetzner + Coolify) — cheap at scale, full data ownership, but real ops burden (backups, patches, upgrades) and cognitive overhead.
- Migrating to Pocketbase, Appwrite, or Nhost — all require code/data migration; Pocketbase and Appwrite aren't Postgres-compatible.
- Neon + bring-your-own-auth/storage — too many moving parts; conflicts with all-in-one preference.

**Rationale** — Most of the affected apps are hobby/playground projects without critical users. The cron-ping pattern preserves $0/month cost and ~zero maintenance, while self-hosting and Pro-tier upgrades would solve a problem that doesn't really exist for these projects. Migration to alternatives would be wasted effort.

**Open questions**
- Where the pinger runs (GitHub Actions, Vercel cron, existing VPS) — TBD.
- Ping mechanism (REST request vs. real `SELECT` query) — leaning toward real SELECT for reliability, not yet decided.
- Whether to include a status dashboard and/or failure notifications — TBD.
- Full list of apps and their Supabase configurations — to be provided in next session.

---

## 2026-04-28 — Defer self-hosting Supabase

**Decision** — Not self-hosting Supabase at this time.

**Context** — Self-hosting was the strongest match against stated priorities (data ownership, Postgres compatibility, all-in-one). Reality-checked the actual ops cost vs. the value of the projects.

**Alternatives considered** — Self-hosting on Hetzner via Coolify; Supabase Pro; staying on free tier with pause prevention.

**Rationale** — Self-hosting's economic advantage only materializes when projects justify the ops burden. For a portfolio of mostly hobby projects, the maintenance time and cognitive overhead outweigh the savings. Reconsider if (a) project mix shifts toward apps with real users, (b) project count grows substantially, or (c) compliance/sovereignty requirements emerge.

**Open questions** — None for now. Revisit if portfolio composition changes.

---

## 2026-04-28 — Defer migration away from Supabase

**Decision** — Not migrating off Supabase to alternatives (Pocketbase, Appwrite, Nhost, Neon, Firebase, Convex).

**Context** — Original framing was "explore alternatives to Supabase." After clarifying priorities and reality-checking, migration was determined to be the wrong solve.

**Alternatives considered** — All of the above.

**Rationale** — None of the alternatives offered a meaningful improvement over staying on Supabase + pause prevention. Postgres-incompatible options (Pocketbase, Appwrite, Firebase, Convex) require code rewrites. Postgres-compatible ones (Nhost, Neon) require either GraphQL adoption or assembling a multi-service stack.

**Open questions** — None.