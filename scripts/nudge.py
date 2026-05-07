#!/usr/bin/env python3
"""Ping each Supabase project in projects.json so it stays active.

Reads project list from projects.json and per-project credentials from
$ALL_SECRETS (a JSON blob populated by the GitHub Actions workflow from
${{ toJSON(secrets) }}). Pings every project, logs a line per result,
and exits non-zero if any failed.

A "ping" is a POST that INSERTs one row into the project's keep_alive
table, using `Prefer: return=representation` so PostgREST echoes the
inserted row back. SELECT-based pings were tried first and turned out
to be insufficient for Supabase's free-tier activity tracker — see
docs/decisions.md (2026-05-07 entry) before changing this back.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECTS_PATH = REPO_ROOT / "projects.json"
DEFAULT_TABLE = "keep_alive"
TIMEOUT_SECONDS = 15


# Block redirect-following so the Authorization header is never replayed to a
# different host. urllib follows redirects by default and (unlike requests) does
# not strip Authorization on cross-origin hops; raising on any 3xx surfaces the
# unexpected response as a normal HTTPError that the failure path already handles.
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def http_error_301(self, req, fp, code, msg, headers):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)

    http_error_302 = http_error_301
    http_error_303 = http_error_301
    http_error_307 = http_error_301
    http_error_308 = http_error_301


_OPENER = urllib.request.build_opener(_NoRedirect())


def ping(project, secrets):
    project_id = project["id"]
    table = project.get("table", DEFAULT_TABLE)

    url_secret = f"SUPABASE_{project_id.upper()}_URL"
    key_secret = f"SUPABASE_{project_id.upper()}_ANON_KEY"

    url = secrets.get(url_secret)
    anon_key = secrets.get(key_secret)

    if not url:
        return False, f"missing secret {url_secret}"
    if not anon_key:
        return False, f"missing secret {key_secret}"

    request_url = f"{url.rstrip('/')}/rest/v1/{table}"
    # Empty JSON body — the table's columns must all have defaults so the
    # database fills every value. This keeps the script decoupled from the
    # exact column list of keep_alive (see setup.sql).
    req = urllib.request.Request(
        request_url,
        method="POST",
        data=b"{}",
        headers={
            "apikey": anon_key,
            "Authorization": f"Bearer {anon_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Prefer": "return=representation",
        },
    )

    try:
        with _OPENER.open(req, timeout=TIMEOUT_SECONDS) as resp:
            status = resp.status
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        preview = e.read().decode("utf-8", errors="replace")[:200].strip()
        return False, f"HTTP {e.code} from {request_url}: {preview}"
    except urllib.error.URLError as e:
        return False, f"network error contacting {request_url}: {e.reason}"
    except Exception as e:
        return False, f"unexpected error: {e!r}"

    if status != 201:
        return False, f"unexpected status {status} (expected 201 Created)"

    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        return False, f"response was not valid JSON: {e}"

    if not isinstance(data, list):
        return False, f"expected JSON array, got {type(data).__name__}"
    if len(data) == 0:
        return False, (
            f"empty response from INSERT into {table!r} — "
            "PostgREST didn't echo the inserted row, "
            "or RLS denied SELECT on the new row"
        )

    return True, f"ok ({len(data)} row inserted into {table!r})"


def main():
    raw = os.environ.get("ALL_SECRETS", "")
    if not raw:
        print("FATAL: ALL_SECRETS env var is empty or missing", file=sys.stderr)
        return 2
    try:
        secrets = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"FATAL: ALL_SECRETS is not valid JSON: {e}", file=sys.stderr)
        return 2

    if not PROJECTS_PATH.exists():
        print(f"FATAL: {PROJECTS_PATH} not found", file=sys.stderr)
        return 2

    try:
        projects = json.loads(PROJECTS_PATH.read_text())
    except json.JSONDecodeError as e:
        print(f"FATAL: {PROJECTS_PATH} is not valid JSON: {e}", file=sys.stderr)
        return 2

    if not isinstance(projects, list):
        print(f"FATAL: {PROJECTS_PATH} must contain a JSON array", file=sys.stderr)
        return 2
    if not projects:
        print(
            f"FATAL: {PROJECTS_PATH} is empty — add at least one project entry",
            file=sys.stderr,
        )
        return 2

    failures = []
    for project in projects:
        name = project.get("name", project.get("id", "<unnamed>"))
        ok, message = ping(project, secrets)
        prefix = "PASS" if ok else "FAIL"
        print(f"{prefix}: {name} — {message}", flush=True)
        if not ok:
            failures.append((name, message))

    print()
    if failures:
        print(f"{len(failures)} of {len(projects)} project(s) failed:")
        for name, message in failures:
            print(f"  - {name}: {message}")
        return 1

    print(f"All {len(projects)} project(s) pinged successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
