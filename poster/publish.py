"""Posts every row whose time has come. Never posts the same row twice."""
from datetime import date, datetime, timedelta

from . import linkedin
from .common import local_tz, open_issue, save_state, summary
from .linkedin import LinkedInError, Uncertain
from .notion import NotionError, file_kind

MAX_TRIES = 3
MAX_IMAGES = 20


class RowProblem(Exception):
    """Something is wrong with the row itself (no caption, wrong file type...)."""


def due_time(cfg, row):
    """When a row should go out. A date alone uses post_time from config.yml, UK time."""
    start = row.get("date")
    if not start:
        return None
    tz = local_tz(cfg)
    if "T" in start:  # the row has its own time in Notion
        when = datetime.fromisoformat(start)
        return when if when.tzinfo else when.replace(tzinfo=tz)
    d = date.fromisoformat(start)
    h, m = (int(x) for x in str(cfg.get("post_time", "12:00")).split(":"))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=tz)


def pick_media(row):
    """Decides what kind of post this is from the files on the row."""
    kinds = [(f, file_kind(f["name"])) for f in row["files"]]
    unknown = [f["name"] for f, k in kinds if k is None]
    if unknown:
        raise RowProblem(f"file type not supported: {', '.join(unknown)}. Use PNG, JPG, GIF or MP4.")
    videos = [f for f, k in kinds if k == "video"]
    images = [f for f, k in kinds if k == "image"]
    if videos and (len(videos) > 1 or images):
        raise RowProblem("a post can have one video OR images, not both and not two videos.")
    if len(images) > MAX_IMAGES:
        raise RowProblem(f"too many images ({len(images)}). The most is {MAX_IMAGES}.")
    if videos:
        return "video", videos
    if images:
        return "image", images
    return "text", []


def prepare(cfg, notion, row):
    """Reads the caption and checks the row. Returns (caption, kind, files)."""
    caption = notion.caption(row)
    if not caption:
        raise RowProblem(f"no caption found. Put it in a code block under a heading with the word "
                         f"'{cfg['notion'].get('caption_heading', 'Caption')}'.")
    if len(caption) > linkedin.MAX_CAPTION:
        raise RowProblem(f"caption is {len(caption)} characters. LinkedIn allows {linkedin.MAX_CAPTION}.")
    kind, files = pick_media(row)
    return caption, kind, files


def upload_media(notion, li, row, kind, files, log=print):
    """Sends the files to LinkedIn and waits until each is ready. Returns the media part of a post."""
    if kind == "text":
        return None
    ids = []
    for f in files:
        data = notion.download(f)
        log(f"Uploading {f['name']} ({len(data) / 1_000_000:.1f} MB) to LinkedIn...")
        urn = li.upload_video(data) if kind == "video" else li.upload_image(data)
        status = li.wait_available(urn, log)
        log(f"{f['name']}: {status}")
        ids.append(urn)
    return {"kind": kind, "ids": ids, "alt": row["name"], "title": row["name"]}


def publish_row(cfg, state, notion, li, row, now, log=print):
    """Posts one row for real and marks it Posted. Raises on any problem."""
    caption, kind, files = prepare(cfg, notion, row)
    media = upload_media(notion, li, row, kind, files, log)
    urn = li.create_post(caption, media)
    link = linkedin.post_link(urn)
    # Remember it straight away, so even if Notion fails next, it can never be posted twice.
    state.setdefault("posts", {})[row["id"]] = {"name": row["name"], "posted_at": now.isoformat(),
                                               "post_id": urn, "link": link, "kind": kind}
    save_state(state)
    summary(f"Posted **{row['name']}** ({kind}): {link}")
    mark_posted(state, notion, row, log)
    return link


def mark_posted(state, notion, row, log=print):
    record = state["posts"][row["id"]]
    try:
        notion.mark_posted(row, record.get("link"))
        record["notion_marked"] = True
        save_state(state)
    except NotionError as e:
        log(f"Posted, but could not mark '{row['name']}' in Notion yet (will retry): {e}")


def run(cfg, state, notion, li, now, log=print):
    dry = cfg.get("dry_run", True)
    if cfg.get("paused"):
        log("Paused in config.yml. Nothing is posted.")
        return
    try:
        rows = notion.ready_rows()
    except NotionError as e:
        log(str(e))
        open_issue("Cannot read Notion", f"The robot could not read the posts database:\n\n```\n{e}\n```", dry)
        return

    posts = state.setdefault("posts", {})
    tries = state.setdefault("tries", {})
    skipped = state.setdefault("skipped", {})
    late_limit = timedelta(hours=float(cfg.get("max_late_hours", 6)))
    done = 0
    upcoming = None
    for row in rows:
        due = due_time(cfg, row)
        if due is None:
            continue  # no date yet: not scheduled
        if row["id"] in posts:  # already on LinkedIn, Notion just was not updated
            if not dry:
                mark_posted(state, notion, row, log)
            continue
        if due > now:
            upcoming = upcoming or (row, due)
            continue
        when = due.astimezone(local_tz(cfg)).strftime("%a %d %b %H:%M")
        if now - due > late_limit:
            if row["id"] not in skipped:
                log(f"Skipped '{row['name']}': it was due {when}, more than {cfg.get('max_late_hours', 6)} hours ago.")
                if not dry:
                    skipped[row["id"]] = due.isoformat()
                    open_issue(f"Skipped {row['name']}: too late",
                               f"**{row['name']}** was due {when} (UK) and is more than "
                               f"{cfg.get('max_late_hours', 6)} hours late, so it was not posted.\n\n"
                               "- Already posted by hand? Set its Status to Posted in Notion.\n"
                               "- Still want it? Change its Post date to a new day.", dry)
            continue
        skipped.pop(row["id"], None)
        t = tries.get(row["id"], {})
        if t.get("edited") != row["edited"]:
            t = {"count": 0, "edited": row["edited"]}  # the row was changed in Notion: start fresh
        if t.get("blocked"):
            continue
        if done >= int(cfg.get("max_posts_per_run", 1)):
            break

        if dry:
            _practice(cfg, notion, row, when)
            done += 1
            continue
        if li is None:
            log(f"'{row['name']}' is due but there is no working LinkedIn login. See the open issue.")
            break
        try:
            publish_row(cfg, state, notion, li, row, now, log)
            tries.pop(row["id"], None)
            done += 1
        except Uncertain as e:
            t["blocked"] = True
            tries[row["id"]] = t
            open_issue(f"Check LinkedIn: {row['name']} may or may not have posted",
                       f"The post was sent but LinkedIn gave no clear answer:\n\n```\n{e}\n```\n\n"
                       "Look at your LinkedIn profile.\n\n"
                       "- It is there: set the row's Status to Posted in Notion.\n"
                       "- It is not there: change the row's Status to something else and back to "
                       f"{cfg['notion']['ready_status']}. The robot then tries again.")
        except LinkedInError as e:
            if e.login_problem:
                state.get("token", {}).pop("checked_at", None)  # check the login again next run
                log(f"LinkedIn refused the login while posting '{row['name']}': {e}")
                break
            _count_failure(tries, t, row, e)
        except (RowProblem, NotionError) as e:
            _count_failure(tries, t, row, e)
        save_state(state)

    if upcoming and done == 0:
        row, due = upcoming
        log(f"Nothing due. Next: '{row['name']}' on "
            f"{due.astimezone(local_tz(cfg)).strftime('%a %d %b at %H:%M')} UK.")
    elif done == 0:
        log("Nothing due.")


def _count_failure(tries, t, row, error):
    t["count"] = t.get("count", 0) + 1
    print(f"Could not post '{row['name']}' (try {t['count']} of {MAX_TRIES}): {error}")
    if t["count"] >= MAX_TRIES:
        t["blocked"] = True
        open_issue(f"Could not post {row['name']}",
                   f"Tried {MAX_TRIES} times. The last error:\n\n```\n{error}\n```\n\n"
                   "Fix the row in Notion. Any change to the row makes the robot try again.")
    tries[row["id"]] = t


def _practice(cfg, notion, row, when):
    """Dry run: shows what would be posted, posts nothing, changes nothing."""
    try:
        caption, kind, files = prepare(cfg, notion, row)
    except (RowProblem, NotionError) as e:
        summary(f"[DRY RUN] **{row['name']}** (due {when}) has a problem: {e}")
        return
    first = caption.splitlines()[0]
    names = ", ".join(f["name"] for f in files) or "no file"
    summary(f"[DRY RUN] would post **{row['name']}** (due {when} UK) as a {kind} post.\n"
            f"- First line: {first}\n- Caption length: {len(caption)} characters\n- File: {names}\n"
            "- Nothing was posted and Notion was not changed.")
