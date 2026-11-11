"""Talks to Notion: reads the rows to post, reads each caption, marks rows as Posted."""
import requests

API = "https://api.notion.com/v1"
IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".gif")
VIDEO_TYPES = (".mp4",)


class NotionError(Exception):
    pass


def _plain(rich):
    return "".join(part.get("plain_text", "") for part in rich or [])


def file_kind(name):
    """'image', 'video' or None, judged by the file name."""
    low = (name or "").lower().split("?")[0]
    if low.endswith(IMAGE_TYPES):
        return "image"
    if low.endswith(VIDEO_TYPES):
        return "video"
    return None


class Notion:
    def __init__(self, token, settings, http=requests):
        self.token = token
        self.s = settings
        self.http = http

    # ---- plumbing ---------------------------------------------------------
    def _call(self, method, path, **kw):
        headers = {"Authorization": f"Bearer {self.token}",
                   "Notion-Version": self.s.get("api_version", "2025-09-03"),
                   "Content-Type": "application/json"}
        try:
            r = self.http.request(method, f"{API}{path}", headers=headers, timeout=60, **kw)
        except requests.RequestException as e:
            raise NotionError(f"Could not reach Notion: {e}") from e
        if r.status_code >= 400:
            try:
                msg = r.json().get("message", r.text)
            except ValueError:
                msg = r.text
            if r.status_code == 401:
                msg = "The NOTION_TOKEN secret is wrong or was deleted. " + msg
            if r.status_code == 404:
                msg = ("Notion cannot see the database. Open the database in Notion, click the ... menu, "
                       "Connections, and add your connection. " + msg)
            raise NotionError(f"Notion error {r.status_code}: {msg}")
        return r.json()

    # ---- rows -------------------------------------------------------------
    def ready_rows(self):
        """Every row whose status is the 'ready' one, earliest date first."""
        prop, ready = self.s["status_property"], self.s["ready_status"]
        last_error = None
        for kind in ("select", "status"):  # the column can be either type in Notion
            body = {"filter": {"property": prop, kind: {"equals": ready}},
                    "sorts": [{"property": self.s["date_property"], "direction": "ascending"}],
                    "page_size": 100}
            try:
                return [self._row(p) for p in self._query(body)]
            except NotionError as e:
                last_error = e
                if "400" not in str(e):
                    break
        raise last_error

    def all_rows(self):
        body = {"sorts": [{"property": self.s["date_property"], "direction": "ascending"}], "page_size": 100}
        return [self._row(p) for p in self._query(body)]

    def _query(self, body):
        out, cursor = [], None
        while True:
            if cursor:
                body = dict(body, start_cursor=cursor)
            data = self._call("POST", f"/data_sources/{self.s['data_source_id']}/query", json=body)
            out.extend(data.get("results", []))
            if not data.get("has_more"):
                return out
            cursor = data.get("next_cursor")

    def _row(self, page):
        props = page.get("properties", {})
        name = ""
        for p in props.values():
            if p.get("type") == "title":
                name = _plain(p.get("title"))
        date = (props.get(self.s["date_property"], {}) or {}).get("date") or {}
        status = props.get(self.s["status_property"], {}) or {}
        status_kind = status.get("type", "select")
        files = []
        for f in (props.get(self.s["media_property"], {}) or {}).get("files", []) or []:
            inner = f.get(f.get("type", ""), {}) or {}
            if inner.get("url"):
                files.append({"name": f.get("name", ""), "url": inner["url"]})
        caption_prop = props.get("Caption", {}) or {}
        return {"id": page["id"], "name": name.strip() or "(no name)", "date": date.get("start"),
                "status": (status.get(status_kind) or {}).get("name"), "status_kind": status_kind,
                "files": files, "edited": page.get("last_edited_time"), "url": page.get("url"),
                "caption_property": _plain(caption_prop.get("rich_text")).strip(),
                "has_link_property": bool(self.s.get("link_property")) and self.s["link_property"] in props}

    # ---- caption ----------------------------------------------------------
    def caption(self, row):
        """The caption text: a 'Caption' column if there is one, else the code block under the
        'Caption' heading inside the row."""
        if row.get("caption_property"):
            return row["caption_property"]
        want = self.s.get("caption_heading", "Caption").lower()
        blocks, cursor = [], None
        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            data = self._call("GET", f"/blocks/{row['id']}/children", params=params)
            blocks.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        under_heading = False
        for b in blocks:
            kind = b.get("type", "")
            if kind.startswith("heading_"):
                under_heading = want in _plain(b[kind].get("rich_text")).lower()
            elif kind == "code" and under_heading:
                return _plain(b["code"].get("rich_text")).strip()
        return ""

    # ---- files ------------------------------------------------------------
    def download(self, file):
        try:
            r = self.http.request("GET", file["url"], timeout=300)
        except requests.RequestException as e:
            raise NotionError(f"Could not download {file['name']}: {e}") from e
        if r.status_code != 200:
            raise NotionError(f"Could not download {file['name']}: HTTP {r.status_code}")
        return r.content

    # ---- after posting ----------------------------------------------------
    def mark_posted(self, row, link=None):
        props = {self.s["status_property"]: {row.get("status_kind", "select"): {"name": self.s["posted_status"]}}}
        if link and row.get("has_link_property"):
            props[self.s["link_property"]] = {"url": link}
        self._call("PATCH", f"/pages/{row['id']}", json={"properties": props})
