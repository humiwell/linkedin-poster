"""Practice runs against a pretend Notion and LinkedIn. Run with:  python -m pytest -q"""
from datetime import datetime, timezone

import pytest
import requests
from cryptography.fernet import Fernet

from poster import common, linkedin, publish, tokens
from poster.linkedin import LinkedIn, little_text
from poster.notion import Notion
from tests.fakes import FakeWorld, Reply, notion_row

CFG = {
    "dry_run": False, "paused": False, "timezone": "Europe/London", "post_time": "12:00",
    "max_late_hours": 6, "max_posts_per_run": 1,
    "notion": {"data_source_id": "ds1", "date_property": "Post date", "status_property": "Status",
               "media_property": "Cover", "ready_status": "Scheduled", "posted_status": "Posted",
               "caption_heading": "Caption", "link_property": "", "api_version": "2025-09-03"},
    "linkedin": {"visibility": "PUBLIC", "api_version": "202610", "media_wait_seconds": 30},
    "token": {"warn_days_before_expiry": 7},
}


def at(text):
    return datetime.fromisoformat(text).astimezone(timezone.utc)


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    """Every test gets its own empty state folder, no GitHub access and a fresh lock key."""
    monkeypatch.setattr(common, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(tokens, "TOKEN_FILE", tmp_path / "token.enc")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("TOKEN_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("LINKEDIN_CLIENT_ID", "client-id")
    monkeypatch.setenv("LINKEDIN_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("NOTION_TOKEN", "notion-token")
    issues = []
    for module in (publish, tokens):
        monkeypatch.setattr(module, "open_issue", lambda title, body, dry_run=False, **kw: issues.append(title))
    monkeypatch.setattr(tokens, "finish_issue", lambda number, comment, new_body=None: issues.append(comment))
    monkeypatch.setattr(tokens, "close_issues", lambda titles, comment: None)
    return issues


def make(world, cfg=CFG):
    notion = Notion("notion-token", cfg["notion"], http=world)
    li = LinkedIn("token", "abc123", cfg["linkedin"], http=world, sleep=lambda s: None)
    return notion, li


def new_state():
    return {"posts": {}, "tries": {}, "skipped": {}, "token": {}}


# ---- caption text -----------------------------------------------------------
def test_caption_special_characters_are_escaped_but_hashtags_kept():
    text = "Cut contacts by 12% (public-safe) *really* #CareerGrowth #Promotion\n1️⃣ a_b"
    assert little_text(text) == ("Cut contacts by 12% \\(public-safe\\) \\*really\\* #CareerGrowth #Promotion\n"
                                 "1️⃣ a\\_b")
    assert little_text("issue # 5 and C#") == "issue \\# 5 and C\\#"


# ---- timing -------------------------------------------------------------------
def test_due_time_uses_uk_time_in_winter_and_summer():
    assert publish.due_time(CFG, {"date": "2026-11-18"}) == at("2026-11-18T12:00+00:00")
    assert publish.due_time(CFG, {"date": "2027-05-26"}) == at("2027-05-26T11:00+00:00")  # summer time
    assert publish.due_time(CFG, {"date": "2026-11-18T09:30:00.000+00:00"}) == at("2026-11-18T09:30+00:00")


def test_nothing_is_posted_before_its_time():
    world = FakeWorld([notion_row("p1", "Using AI at work", "2026-11-18")])
    notion, li = make(world)
    publish.run(CFG, new_state(), notion, li, at("2026-11-18T11:50+00:00"))
    assert world.posts == []


# ---- posting ------------------------------------------------------------------
def test_due_row_is_posted_once_with_image_and_marked_posted():
    world = FakeWorld([notion_row("p1", "Using AI at work", "2026-11-18"),
                       notion_row("p2", "Customers", "2026-11-25")])
    world.media_status["urn:li:image:1"] = ["PROCESSING", "AVAILABLE"]
    notion, li = make(world)
    state = new_state()
    publish.run(CFG, state, notion, li, at("2026-11-18T12:05+00:00"))
    assert len(world.posts) == 1
    post = world.posts[0]
    assert post["author"] == "urn:li:person:abc123"
    assert post["commentary"].startswith("Hook line for p1") and "\\(with brackets\\) #CareerGrowth" in post["commentary"]
    assert post["content"] == {"media": {"altText": "Using AI at work", "id": "urn:li:image:1"}}
    assert post["visibility"] == "PUBLIC" and post["lifecycleState"] == "PUBLISHED"
    assert world.rows["p1"]["properties"]["Status"]["select"]["name"] == "Posted"
    assert world.rows["p2"]["properties"]["Status"]["select"]["name"] == "Scheduled"
    assert state["posts"]["p1"]["link"] == "https://www.linkedin.com/feed/update/urn:li:share:7001/"
    # A second run 15 minutes later posts nothing new.
    publish.run(CFG, state, notion, li, at("2026-11-18T12:20+00:00"))
    assert len(world.posts) == 1


def test_never_posts_twice_even_if_notion_could_not_be_updated():
    world = FakeWorld([notion_row("p1", "Using AI at work", "2026-11-18")])
    world.notion_patch_fails = True
    notion, li = make(world)
    state = new_state()
    publish.run(CFG, state, notion, li, at("2026-11-18T12:05+00:00"))
    assert len(world.posts) == 1 and world.rows["p1"]["properties"]["Status"]["select"]["name"] == "Scheduled"
    world.notion_patch_fails = False
    publish.run(CFG, state, notion, li, at("2026-11-18T12:20+00:00"))
    assert len(world.posts) == 1
    assert world.rows["p1"]["properties"]["Status"]["select"]["name"] == "Posted"


def test_text_only_and_video_and_several_images():
    world = FakeWorld([notion_row("p1", "Text", "2026-11-18", files=()),
                       notion_row("p2", "Video", "2026-11-18", files=("clip.mp4",)),
                       notion_row("p3", "Many", "2026-11-18", files=("a.png", "b.jpg"))])
    notion, li = make(world)
    state = new_state()
    cfg = dict(CFG, max_posts_per_run=5)
    publish.run(cfg, state, notion, li, at("2026-11-18T12:05+00:00"))
    by_name = {state["posts"][p]["name"]: body for p, body in zip(("p1", "p2", "p3"), world.posts)}
    assert "content" not in by_name["Text"]
    assert by_name["Video"]["content"]["media"]["id"].startswith("urn:li:video:")
    assert len(world.finalized["uploadedPartIds"]) == 2  # a 5 MB video goes up in two pieces
    assert [i["id"] for i in by_name["Many"]["content"]["multiImage"]["images"]] == ["urn:li:image:2", "urn:li:image:3"]


def test_dry_run_posts_nothing_and_changes_nothing():
    world = FakeWorld([notion_row("p1", "Using AI at work", "2026-11-18")])
    notion, li = make(world)
    state = new_state()
    publish.run(dict(CFG, dry_run=True), state, notion, li, at("2026-11-18T12:05+00:00"))
    assert world.posts == [] and world.uploads == []
    assert world.rows["p1"]["properties"]["Status"]["select"]["name"] == "Scheduled"
    assert state["posts"] == {}
    assert not any(m in ("PATCH", "PUT") for m, _ in world.calls)


def test_paused_posts_nothing():
    world = FakeWorld([notion_row("p1", "Using AI at work", "2026-11-18")])
    notion, li = make(world)
    publish.run(dict(CFG, paused=True), new_state(), notion, li, at("2026-11-18T12:05+00:00"))
    assert world.posts == [] and world.calls == []


def test_old_rows_are_skipped_not_posted(sandbox):
    world = FakeWorld([notion_row("p0", "Getting promoted", "2026-11-04"),
                       notion_row("p1", "Using AI at work", "2026-11-18")])
    notion, li = make(world)
    state = new_state()
    publish.run(CFG, state, notion, li, at("2026-11-18T12:05+00:00"))
    assert [p["commentary"][:16] for p in world.posts] == ["Hook line for p1"]
    assert sandbox == ["Skipped Getting promoted: too late"]
    publish.run(CFG, state, notion, li, at("2026-11-18T12:20+00:00"))
    assert sandbox == ["Skipped Getting promoted: too late"]  # told once, not every 15 minutes


def test_row_without_caption_gets_an_issue_after_three_tries(sandbox):
    world = FakeWorld([notion_row("p1", "Empty", "2026-11-18")], captions={"p1": ""})
    notion, li = make(world)
    state = new_state()
    for minute in ("05", "20", "35", "50"):
        publish.run(CFG, state, notion, li, at(f"2026-11-18T12:{minute}+00:00"))
    assert world.posts == []
    assert sandbox == ["Could not post Empty"]
    # Fixing the row in Notion (its edit time changes) makes the robot try again.
    world.captions["p1"] = "Now there is a caption"
    world.rows["p1"]["last_edited_time"] = "2026-11-18T13:00:00.000Z"
    publish.run(CFG, state, notion, li, at("2026-11-18T13:05+00:00"))
    assert len(world.posts) == 1


def test_unclear_answer_from_linkedin_is_never_retried_by_itself(sandbox):
    world = FakeWorld([notion_row("p1", "Using AI at work", "2026-11-18")])
    world.post_reply = requests.Timeout("timed out")
    notion, li = make(world)
    state = new_state()
    publish.run(CFG, state, notion, li, at("2026-11-18T12:05+00:00"))
    world.post_reply = None
    publish.run(CFG, state, notion, li, at("2026-11-18T12:20+00:00"))
    assert world.posts == []
    assert sandbox == ["Check LinkedIn: Using AI at work may or may not have posted"]


def test_refused_post_is_retried_and_status_403_is_survivable():
    world = FakeWorld([notion_row("p1", "Using AI at work", "2026-11-18")])
    world.status_forbidden = True
    world.post_reply = Reply(429, {"message": "too many requests"})
    notion, li = make(world)
    state = new_state()
    publish.run(CFG, state, notion, li, at("2026-11-18T12:05+00:00"))
    assert world.posts == [] and state["tries"]["p1"]["count"] == 1
    world.post_reply = None
    publish.run(CFG, state, notion, li, at("2026-11-18T12:20+00:00"))
    assert len(world.posts) == 1


def test_failed_processing_stops_the_post():
    world = FakeWorld([notion_row("p1", "Using AI at work", "2026-11-18")])
    world.media_status["urn:li:image:1"] = ["PROCESSING_FAILED"]
    notion, li = make(world)
    publish.run(CFG, new_state(), notion, li, at("2026-11-18T12:05+00:00"))
    assert world.posts == []


# ---- login ----------------------------------------------------------------------
def test_login_link_asks_for_the_right_permissions():
    link = linkedin.login_url("client-id", "https://humiwell.github.io/linkedin-poster/")
    assert "scope=openid%20profile%20w_member_social" in link
    assert "redirect_uri=https%3A%2F%2Fhumiwell.github.io%2Flinkedin-poster%2F" in link


def test_first_run_asks_you_to_log_in(sandbox):
    assert tokens.check(CFG, new_state(), at("2026-11-12T09:00+00:00"), http=FakeWorld([])) is None
    assert sandbox == ["Log in to LinkedIn"]


def test_missing_secrets_are_named(sandbox, monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN")
    assert tokens.check(CFG, new_state(), at("2026-11-12T09:00+00:00"), http=FakeWorld([])) is None
    assert sandbox == ["Setup is not finished"]


def test_login_saves_a_locked_token_and_reminds_7_days_before_the_end(sandbox):
    world = FakeWorld([])
    state = new_state()
    assert tokens.login(CFG, state, "code: AQTx-9_z\n\nDo not change anything.", "5",
                        at("2026-11-12T09:00+00:00"), http=world) == 0
    assert b"new-token" not in tokens.TOKEN_FILE.read_bytes()  # the file is locked
    saved = tokens.load_token()
    assert saved["access_token"] == "new-token" and saved["person_id"] == "abc123"
    assert "valid until **2027-01-11**" in sandbox[-1]

    sandbox.clear()
    assert tokens.check(CFG, state, at("2027-01-03T09:00+00:00"), http=world) is not None
    assert sandbox == []  # 8 days left: quiet
    assert tokens.check(CFG, state, at("2027-01-04T10:00+00:00"), http=world) is not None
    assert sandbox == ["LinkedIn login runs out on 2027-01-11"]  # 7 days left: reminder, still posting
    sandbox.clear()
    assert tokens.check(CFG, state, at("2027-01-11T10:00+00:00"), http=world) is None
    assert sandbox == ["LinkedIn login has run out"]


def test_cancelled_login_is_noticed(sandbox):
    world = FakeWorld([])
    state = new_state()
    tokens.login(CFG, state, "code: good", "5", at("2026-11-12T09:00+00:00"), http=world)
    sandbox.clear()
    world.token_active = False
    assert tokens.check(CFG, state, at("2026-11-20T09:00+00:00"), http=world) is None
    assert sandbox == ["LinkedIn login is not valid"]


def test_bad_or_missing_code_changes_nothing(sandbox):
    world = FakeWorld([])
    assert tokens.login(CFG, new_state(), "code: bad", "5", at("2026-11-12T09:00+00:00"), http=world) == 1
    assert tokens.login(CFG, new_state(), "hello", "6", at("2026-11-12T09:00+00:00"), http=world) == 1
    assert tokens.load_token() is None
    assert "code expired" in sandbox[0] and "no login code" in sandbox[1]


def test_login_as_a_different_person_is_refused(sandbox):
    world = FakeWorld([])
    tokens.save_token({"access_token": "old", "person_id": "someone-else", "name": "", "expires_at": 1})
    assert tokens.login(CFG, new_state(), "code: good", "5", at("2026-11-12T09:00+00:00"), http=world) == 1
    assert tokens.load_token()["access_token"] == "old"
