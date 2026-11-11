"""The LinkedIn login: keeps the token safe, reminds you before it runs out, handles re-login.

LinkedIn tokens last about 60 days and cannot be renewed by a robot. You log in again with one link.
The token is saved in state/token.enc, locked with the TOKEN_KEY secret, so the file is useless
to anyone who does not have that secret.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

import requests
from cryptography.fernet import Fernet, InvalidToken

from . import linkedin
from .common import TOKEN_FILE, close_issues, finish_issue, open_issue, pages_url

NEEDED = ("LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET", "NOTION_TOKEN", "TOKEN_KEY")
ROBOT_LOGIN_TITLES = ("Log in to LinkedIn", "LinkedIn login runs out", "LinkedIn login has run out",
                      "LinkedIn login is not valid", "Setup is not finished")


# ---- the locked token file ----------------------------------------------------
def save_token(data):
    key = os.environ["TOKEN_KEY"].encode()
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_bytes(Fernet(key).encrypt(json.dumps(data).encode()) + b"\n")


def load_token():
    """The saved login as a dict (access_token, person_id, name, expires_at), or None."""
    key = os.environ.get("TOKEN_KEY")
    if not key or not TOKEN_FILE.exists():
        return None
    try:
        return json.loads(Fernet(key.encode()).decrypt(TOKEN_FILE.read_bytes().strip()))
    except (InvalidToken, ValueError):
        return None


# ---- the login link -----------------------------------------------------------
def login_link():
    return linkedin.login_url(os.environ.get("LINKEDIN_CLIENT_ID", ""), pages_url())


def _how_to_login():
    return (f"**[Click here to log in to LinkedIn]({login_link()})**\n\n"
            "1. Click the link above and press **Allow** on LinkedIn.\n"
            "2. You land on a page that sends you back to GitHub with a new issue already filled in.\n"
            "3. Press the green **Create** button. Do not change the text.\n\n"
            "About a minute later the robot answers on that new issue, and closes this one.\n"
            "You can do this on your phone. You must be signed in to GitHub as the owner of this repo.")


# ---- daily check ---------------------------------------------------------------
def check(cfg, state, now, http=requests, log=print):
    """Returns the saved login if it can be used right now, else None. Opens reminder issues."""
    missing = [n for n in NEEDED if not os.environ.get(n)]
    if missing:
        log(f"Setup is not finished. Missing secrets: {', '.join(missing)}")
        open_issue("Setup is not finished",
                   "The robot cannot work yet. These secrets are missing:\n\n"
                   + "\n".join(f"- `{n}`" for n in missing)
                   + "\n\nAdd them in *Settings*, *Secrets and variables*, *Actions*. See SETUP.md.")
        return None
    tok = load_token()
    if tok is None:
        log("No LinkedIn login saved yet.")
        open_issue("Log in to LinkedIn", "The robot has no LinkedIn login yet.\n\n" + _how_to_login())
        return None

    expires = datetime.fromtimestamp(tok["expires_at"], timezone.utc)
    days_left = (expires - now).total_seconds() / 86400
    t = state.setdefault("token", {})
    t["expires_on"] = expires.date().isoformat()
    if days_left <= 0:
        log("The LinkedIn login has run out.")
        open_issue("LinkedIn login has run out",
                   "Nothing can be posted until you log in again.\n\n" + _how_to_login())
        return None

    # Once a day, ask LinkedIn if the login still works (it can be cancelled early, for example
    # after a password change).
    last = t.get("checked_at")
    if not last or now - datetime.fromisoformat(last) >= timedelta(hours=20):
        try:
            info = linkedin.introspect(tok["access_token"], os.environ["LINKEDIN_CLIENT_ID"],
                                       os.environ["LINKEDIN_CLIENT_SECRET"], http)
        except linkedin.LinkedInError as e:
            log(f"Login check failed, will try again next run: {e}")
            info = None
        if info is not None:
            t["checked_at"] = now.isoformat()
            if not info.get("active", False):
                log("LinkedIn says the login is not valid any more.")
                open_issue("LinkedIn login is not valid",
                           "LinkedIn cancelled the login (this can happen after a password change).\n\n"
                           + _how_to_login())
                return None
        log(f"LinkedIn login: {days_left:.0f} days left (ends {t['expires_on']}).")

    warn = int(cfg["token"].get("warn_days_before_expiry", 7))
    if days_left <= warn:
        open_issue(f"LinkedIn login runs out on {t['expires_on']}",
                   f"About {days_left:.0f} days left. Log in again before that date, or posting stops.\n\n"
                   + _how_to_login())
    return tok


# ---- re-login -------------------------------------------------------------------
def login(cfg, state, issue_body, issue_number, now, http=requests, log=print):
    """Runs when you create the 'LinkedIn login code' issue. Swaps the code for a new token."""
    def fail(reason):
        log(f"Login failed: {reason}")
        finish_issue(issue_number, f"Login did not work: {reason}\n\nNothing was changed. "
                                   f"[Click here to try again]({login_link()}).",
                     new_body="(login code removed)")
        return 1

    missing = [n for n in ("LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET", "TOKEN_KEY") if not os.environ.get(n)]
    if missing:
        return fail(f"these secrets are missing: {', '.join(missing)}. See SETUP.md.")
    found = re.search(r"code:\s*([A-Za-z0-9_\-]+)", issue_body or "")
    if not found:
        return fail("there was no login code in the issue.")
    try:
        answer = linkedin.exchange_code(found.group(1), os.environ["LINKEDIN_CLIENT_ID"],
                                        os.environ["LINKEDIN_CLIENT_SECRET"], pages_url(), http)
        who = linkedin.userinfo(answer["access_token"], http)
    except linkedin.LinkedInError as e:
        return fail(f"{e.message} (codes work once and only for 30 minutes)")
    if "w_member_social" not in (answer.get("scope") or "w_member_social"):
        return fail("LinkedIn did not give permission to post. Check the 'Share on LinkedIn' "
                    "product is added to your LinkedIn app (SETUP.md, part 1).")

    old = load_token()
    if old and old.get("person_id") and old["person_id"] != who["sub"]:
        return fail("this is a different LinkedIn account from the one the robot uses. "
                    "Log out of LinkedIn in your browser, log in as the right person, and try again.")

    expires = now + timedelta(seconds=int(answer.get("expires_in", 5184000)))
    save_token({"access_token": answer["access_token"], "person_id": who["sub"],
                "name": who.get("name", ""), "expires_at": int(expires.timestamp())})
    # Only state/token.enc changes here, so this can never clash with a robot run saving its state.
    first_name = who.get("given_name") or "you"
    log(f"Logged in. Valid until {expires.date().isoformat()}.")
    finish_issue(issue_number,
                 f"Logged in as {first_name}. The login is valid until **{expires.date().isoformat()}**. "
                 "The robot will remind you a week before.", new_body="(login code removed)")
    close_issues(ROBOT_LOGIN_TITLES, "Done: a new login was saved.")
    return 0
