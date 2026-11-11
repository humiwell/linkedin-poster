"""A pretend Notion and a pretend LinkedIn used by the tests. Never touches the internet."""
import json

import requests


class Reply:
    def __init__(self, status=200, body=None, headers=None, content=b""):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.content = content
        self.text = json.dumps(body) if body is not None else ""

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def notion_row(page_id, name, day, status="Scheduled", files=("cover.png",), edited="2026-11-01T10:00:00.000Z"):
    return {"id": page_id, "url": f"https://notion.so/{page_id}", "last_edited_time": edited,
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": name}]},
                "Post date": {"type": "date", "date": {"start": day} if day else None},
                "Status": {"type": "select", "select": {"name": status}},
                "Cover": {"type": "files", "files": [
                    {"name": f, "type": "file", "file": {"url": f"https://files.example/{page_id}/{f}"}}
                    for f in files]}}}


class FakeWorld:
    """One object that answers every web request the robot makes."""

    def __init__(self, rows, captions=None):
        self.rows = {r["id"]: r for r in rows}
        self.captions = captions or {}
        self.posts = []          # bodies sent to LinkedIn /rest/posts
        self.uploads = []        # media ids created
        self.media_status = {}   # id -> list of statuses to give, in order
        self.status_forbidden = False
        self.post_reply = None   # set to a Reply or an Exception to change what /rest/posts does
        self.notion_patch_fails = False
        self.token_active = True
        self.calls = []

    # requests-like entry point
    def request(self, method, url, **kw):
        self.calls.append((method, url))
        if url.startswith("https://api.notion.com/v1"):
            return self._notion(method, url[len("https://api.notion.com/v1"):], kw)
        if url.startswith("https://files.example/"):
            return Reply(200, content=b"x" * 5_000_000 if url.endswith(".mp4") else b"img-bytes")
        if "linkedin.com" in url:
            return self._linkedin(method, url, kw)
        raise AssertionError(f"unexpected request {method} {url}")

    # ---- Notion -----------------------------------------------------------
    def _notion(self, method, path, kw):
        if path.endswith("/query"):
            flt = (kw.get("json") or {}).get("filter")
            rows = list(self.rows.values())
            if flt:
                want = flt["select"]["equals"]
                rows = [r for r in rows if r["properties"]["Status"]["select"]["name"] == want]
            rows.sort(key=lambda r: (r["properties"]["Post date"]["date"] or {}).get("start") or "9999")
            return Reply(200, {"results": rows, "has_more": False, "next_cursor": None})
        if path.startswith("/blocks/"):
            page_id = path.split("/")[2]
            text = self.captions.get(page_id, f"Hook line for {page_id}\n\nBody (with brackets) #CareerGrowth")
            blocks = [{"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Cover image"}]}},
                      {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Caption (copy into LinkedIn)"}]}}]
            if text:
                blocks.append({"type": "code", "code": {"rich_text": [{"plain_text": text}]}})
            blocks.append({"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Cover text"}]}})
            return Reply(200, {"results": blocks, "has_more": False})
        if method == "PATCH" and path.startswith("/pages/"):
            if self.notion_patch_fails:
                return Reply(500, {"message": "notion is down"})
            page_id = path.split("/")[2]
            for name, value in kw["json"]["properties"].items():
                self.rows[page_id]["properties"][name] = dict(value, type=next(iter(value)))
            return Reply(200, self.rows[page_id])
        raise AssertionError(f"unexpected Notion call {method} {path}")

    # ---- LinkedIn ---------------------------------------------------------
    def _linkedin(self, method, url, kw):
        if url.endswith("/oauth/v2/accessToken"):
            if kw["data"]["code"] == "bad":
                return Reply(400, {"error": "invalid_request", "error_description": "code expired"})
            return Reply(200, {"access_token": "new-token", "expires_in": 5184000,
                               "scope": "openid,profile,w_member_social"})
        if url.endswith("/oauth/v2/introspectToken"):
            return Reply(200, {"active": self.token_active})
        if url.endswith("/v2/userinfo"):
            return Reply(200, {"sub": "abc123", "name": "Test Person", "given_name": "Test"})
        if "action=initializeUpload" in url:
            kind = "video" if "/videos" in url else "image"
            urn = f"urn:li:{kind}:{len(self.uploads) + 1}"
            self.uploads.append(urn)
            if kind == "image":
                return Reply(200, {"value": {"uploadUrl": f"https://www.linkedin.com/dms-uploads/{urn}", "image": urn}})
            size = kw["json"]["initializeUploadRequest"]["fileSizeBytes"]
            parts, first = [], 0
            while first < size:
                last = min(first + 4194304, size) - 1
                parts.append({"uploadUrl": f"https://www.linkedin.com/dms-uploads/{urn}/{first}",
                              "firstByte": first, "lastByte": last})
                first = last + 1
            return Reply(200, {"value": {"video": urn, "uploadInstructions": parts, "uploadToken": ""}})
        if "/dms-uploads/" in url:
            return Reply(201, headers={"etag": f"etag-{len(kw['data'])}"})
        if "action=finalizeUpload" in url:
            self.finalized = kw["json"]["finalizeUploadRequest"]
            return Reply(200)
        if method == "GET" and ("/rest/images/" in url or "/rest/videos/" in url):
            if self.status_forbidden:
                return Reply(403, {"message": "not enough permissions"})
            urn = requests.utils.unquote(url.rsplit("/", 1)[1])
            queue = self.media_status.get(urn, ["AVAILABLE"])
            status = queue.pop(0) if len(queue) > 1 else queue[0]
            return Reply(200, {"status": status})
        if url.endswith("/rest/posts"):
            if isinstance(self.post_reply, Exception):
                raise self.post_reply
            if self.post_reply is not None:
                return self.post_reply
            self.posts.append(kw["json"])
            return Reply(201, headers={"x-restli-id": f"urn:li:share:{7000 + len(self.posts)}"})
        raise AssertionError(f"unexpected LinkedIn call {method} {url}")
