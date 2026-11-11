"""One-off tests you start by hand from the Actions tab ("Test post")."""
from . import publish
from .common import local_tz, summary
from .linkedin import LinkedInError
from .notion import NotionError


def check(cfg, state, notion, li, tok, now):
    """Safe. Checks the login, reads Notion, and uploads the next row's file to LinkedIn
    WITHOUT posting anything."""
    ok = True
    if tok:
        days = (tok["expires_at"] - now.timestamp()) / 86400
        summary(f"LinkedIn login: OK, {days:.0f} days left.")
    else:
        summary("LinkedIn login: none yet. Look for the open 'Log in to LinkedIn' issue.")
        ok = False
    try:
        rows = notion.ready_rows()
    except NotionError as e:
        summary(f"Notion: FAILED. {e}")
        return 1
    summary(f"Notion: OK, {len(rows)} row(s) with status '{cfg['notion']['ready_status']}'.")
    tz = local_tz(cfg)
    future = [(r, publish.due_time(cfg, r)) for r in rows if r.get("date")]
    future = [(r, d) for r, d in future if d and d > now and r["id"] not in state.get("posts", {})]
    for r, d in future[:5]:
        summary(f"- {d.astimezone(tz).strftime('%a %d %b %Y %H:%M')} UK: {r['name']}")
    if not future:
        summary("No future rows are ready, so there is nothing more to check.")
        return 0 if ok else 1

    row = future[0][0]
    try:
        caption, kind, files = publish.prepare(cfg, notion, row)
    except (publish.RowProblem, NotionError) as e:
        summary(f"Next row **{row['name']}**: PROBLEM. {e}")
        return 1
    summary(f"Next row **{row['name']}**: {kind} post, caption {len(caption)} characters. "
            f"First line: {caption.splitlines()[0]}")
    if li is None or kind == "text":
        return 0 if ok else 1
    try:
        media = publish.upload_media(notion, li, row, kind, files, summary)
    except (LinkedInError, NotionError) as e:
        summary(f"Upload test: FAILED. {e}")
        return 1
    summary(f"Upload test: OK ({len(media['ids'])} file(s) accepted by LinkedIn). Nothing was posted.")
    return 0


def post(cfg, state, notion, li, now, row_name, confirm):
    """Publishes ONE row right now, whatever its date. Needs confirm = POST."""
    if confirm != "POST":
        summary("Not posted: type POST (capital letters) in the confirm box.")
        return 1
    if li is None:
        summary("Not posted: there is no working LinkedIn login.")
        return 1
    try:
        rows = notion.all_rows()
    except NotionError as e:
        summary(f"Notion: FAILED. {e}")
        return 1
    match = [r for r in rows if r["name"].strip().lower() == row_name.strip().lower()]
    if len(match) != 1:
        summary(f"Not posted: found {len(match)} rows named '{row_name}'. The name must match exactly one row.")
        return 1
    row = match[0]
    if row["id"] in state.get("posts", {}) or row["status"] == cfg["notion"]["posted_status"]:
        summary(f"Not posted: '{row['name']}' is already posted.")
        return 1
    try:
        publish.publish_row(cfg, state, notion, li, row, now, summary)
    except (LinkedInError, NotionError, publish.RowProblem) as e:
        summary(f"Not posted: {e}")
        return 1
    return 0
