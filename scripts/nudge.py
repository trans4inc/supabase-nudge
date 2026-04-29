#!/usr/bin/env python3
"""Ping each Supabase project in projects.json so it stays active.

Reads project list from projects.json and per-project credentials from
$ALL_SECRETS (a JSON blob populated by the GitHub Actions workflow from
${{ toJSON(secrets) }}). Pings every project, logs a line per result,
and exits non-zero if any failed.
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

    request_url = f"{url.rstrip('/')}/rest/v1/{table}?select=*&limit=1"
    req = urllib.request.Request(
        request_url,
        headers={
            "apikey": anon_key,
            "Authorization": f"Bearer {anon_key}",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            status = resp.status
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        preview = e.read().decode("utf-8", errors="replace")[:200].strip()
        return False, f"HTTP {e.code} from {request_url}: {preview}"
    except urllib.error.URLError as e:
        return False, f"network error contacting {request_url}: {e.reason}"
    except Exception as e:
        return False, f"unexpected error: {e!r}"

    if status != 200:
        return False, f"unexpected status {status}"

    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        return False, f"response was not valid JSON: {e}"

    if not isinstance(data, list):
        return False, f"expected JSON array, got {type(data).__name__}"
    if len(data) == 0:
        return False, (
            f"empty response from table {table!r} — "
            "table has no rows, or RLS denied the SELECT"
        )

    return True, f"ok ({len(data)} row from {table!r})"


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
