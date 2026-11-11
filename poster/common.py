"""Shared helpers: settings, saved state, clock and GitHub issues."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state" / "state.json"
TOKEN_FILE = ROOT / "state" / "token.enc"
REPO = os.environ.get("GITHUB_REPOSITORY", "humiwell/linkedin-poster")


# ---- settings -------------------------------------------------------------
def load_config():
    cfg = yaml.safe_load((ROOT / "config.yml").read_text(encoding="utf-8")) or {}
    if os.environ.get("FORCE_DRY_RUN") == "true":
        cfg["dry_run"] = True
    cfg.setdefault("dry_run", True)
    cfg.setdefault("notion", {})
    cfg.setdefault("linkedin", {})
    cfg.setdefault("token", {})
    return cfg


# ---- clock ----------------------------------------------------------------
def now_utc():
    """The current time. Tests can pretend it is another time with NOW=2026-11-18T12:05+00:00."""
    fake = os.environ.get("NOW")
    if fake:
        return datetime.fromisoformat(fake).astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def local_tz(cfg):
    return ZoneInfo(cfg.get("timezone", "Europe/London"))


# ---- saved state ----------------------------------------------------------
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"posts": {}, "tries": {}, "token": {}}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ---- where the login pages live ---------------------------------------------
def pages_url():
    """The small web page LinkedIn sends you back to after you click Allow."""
    owner, name = REPO.split("/")
    return os.environ.get("LOGIN_PAGE_URL") or f"https://{owner}.github.io/{name}/"


# ---- GitHub issues --------------------------------------------------------
def _gh_headers():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return None
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def _api(path=""):
    return f"https://api.github.com/repos/{REPO}/issues{path}"


def open_issue(title, body, dry_run=False, labels=("robot",)):
    """Opens a GitHub issue unless one with the same title is already open."""
    headers = _gh_headers()
    if dry_run or not headers:
        print(f"[issue{' (dry run)' if dry_run else ''}] {title}\n{body}\n")
        return
    r = requests.get(_api(), headers=headers, params={"state": "open", "per_page": 100}, timeout=30)
    r.raise_for_status()
    if any(i["title"] == title for i in r.json()):
        print(f"[issue already open] {title}")
        return
    # Assigned to the repo owner so the GitHub phone app's "Assigned" push notification fires.
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER") or REPO.split("/")[0]
    r = requests.post(_api(), headers=headers, timeout=30,
                      json={"title": title, "body": body, "labels": list(labels), "assignees": [owner]})
    r.raise_for_status()
    print(f"[issue opened] {title}: {r.json().get('html_url')}")


def close_issues(title_starts, comment):
    """Closes every open issue whose title starts with one of the given texts."""
    headers = _gh_headers()
    if not headers:
        return
    r = requests.get(_api(), headers=headers, params={"state": "open", "per_page": 100}, timeout=30)
    r.raise_for_status()
    for i in r.json():
        if "pull_request" in i or not i["title"].startswith(tuple(title_starts)):
            continue
        requests.post(_api(f"/{i['number']}/comments"), headers=headers, json={"body": comment}, timeout=30)
        requests.patch(_api(f"/{i['number']}"), headers=headers, json={"state": "closed"}, timeout=30)
        print(f"[issue closed] {i['title']}")


def finish_issue(number, comment, new_body=None):
    """Comments on one issue, optionally replaces its text, and closes it."""
    headers = _gh_headers()
    if not headers or not number:
        print(f"[issue {number}] {comment}")
        return
    requests.post(_api(f"/{number}/comments"), headers=headers, json={"body": comment}, timeout=30)
    patch = {"state": "closed"}
    if new_body is not None:
        patch["body"] = new_body
    requests.patch(_api(f"/{number}"), headers=headers, json=patch, timeout=30)


def summary(text):
    """Adds a line to the run's summary page on GitHub (and prints it)."""
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n\n")
