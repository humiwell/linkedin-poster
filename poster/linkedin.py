"""Talks to LinkedIn: login, image and video upload, and creating the post."""
import time
from urllib.parse import quote, urlencode

import requests

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
INTROSPECT_URL = "https://www.linkedin.com/oauth/v2/introspectToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
REST = "https://api.linkedin.com/rest"
SCOPES = "openid profile w_member_social"
MAX_CAPTION = 3000
RESERVED = set("|{}@[]()<>#\\*_~")


class LinkedInError(Exception):
    def __init__(self, status, message):
        super().__init__(f"LinkedIn error {status}: {message}")
        self.status = status
        self.message = message

    @property
    def login_problem(self):
        return self.status == 401


class Uncertain(LinkedInError):
    """The post request was sent but no clear answer came back. It may or may not be live."""


# ---- caption text -----------------------------------------------------------
def little_text(text):
    """LinkedIn reads some characters as commands ( like ( ) * _ @ ). Put a backslash in front of
    them so they show as normal text. Hashtags like #CareerGrowth are left alone so they still work."""
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "#" and i + 1 < n and text[i + 1].isalnum() and (i == 0 or not text[i - 1].isalnum()):
            j = i + 1
            while j < n and text[j].isalnum():
                j += 1
            out.append(text[i:j])
            i = j
            continue
        out.append("\\" + ch if ch in RESERVED else ch)
        i += 1
    return "".join(out)


# ---- login (OAuth) ----------------------------------------------------------
def login_url(client_id, redirect_uri):
    """The link you click to log in. LinkedIn then sends you back to redirect_uri with a code."""
    return AUTH_URL + "?" + urlencode({"response_type": "code", "client_id": client_id,
                                       "redirect_uri": redirect_uri, "state": "linkedin-poster",
                                       "scope": SCOPES}, quote_via=quote)


def _form(url, data, http):
    try:
        r = http.request("POST", url, data=data, timeout=60,
                         headers={"Content-Type": "application/x-www-form-urlencoded"})
    except requests.RequestException as e:
        raise LinkedInError(0, f"Could not reach LinkedIn: {e}") from e
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400:
        raise LinkedInError(r.status_code, body.get("error_description") or body.get("error") or r.text[:300])
    return body


def exchange_code(code, client_id, client_secret, redirect_uri, http=requests):
    """Swaps the one-time login code for an access token (lasts about 60 days)."""
    return _form(TOKEN_URL, {"grant_type": "authorization_code", "code": code, "client_id": client_id,
                             "client_secret": client_secret, "redirect_uri": redirect_uri}, http)


def introspect(token, client_id, client_secret, http=requests):
    """Asks LinkedIn whether a token still works and when it ends."""
    return _form(INTROSPECT_URL, {"client_id": client_id, "client_secret": client_secret, "token": token}, http)


def userinfo(token, http=requests):
    """Who is logged in. 'sub' is the member ID used as the author of posts."""
    try:
        r = http.request("GET", USERINFO_URL, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    except requests.RequestException as e:
        raise LinkedInError(0, f"Could not reach LinkedIn: {e}") from e
    if r.status_code >= 400:
        raise LinkedInError(r.status_code, r.text[:300])
    return r.json()


# ---- posting ----------------------------------------------------------------
class LinkedIn:
    def __init__(self, token, person_id, settings, http=requests, sleep=time.sleep):
        self.token = token
        self.author = f"urn:li:person:{person_id}"
        self.s = settings
        self.http = http
        self.sleep = sleep

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}", "X-Restli-Protocol-Version": "2.0.0",
                "LinkedIn-Version": str(self.s.get("api_version", "202610")),
                "Content-Type": "application/json"}

    def _fail(self, r):
        try:
            msg = r.json().get("message") or r.text
        except ValueError:
            msg = r.text
        if r.status_code == 426 or "version" in str(msg).lower() and "not active" in str(msg).lower():
            msg = f"{msg} (Fix: set linkedin api_version in config.yml to a newer month, for example this month.)"
        return LinkedInError(r.status_code, str(msg)[:500])

    def _rest(self, method, path, **kw):
        try:
            r = self.http.request(method, f"{REST}{path}", headers=self._headers(), timeout=120, **kw)
        except requests.RequestException as e:
            raise LinkedInError(0, f"Could not reach LinkedIn: {e}") from e
        if r.status_code >= 400:
            raise self._fail(r)
        return r

    # ---- media ------------------------------------------------------------
    def upload_image(self, data):
        r = self._rest("POST", "/images?action=initializeUpload",
                       json={"initializeUploadRequest": {"owner": self.author}})
        value = r.json()["value"]
        try:
            up = self.http.request("PUT", value["uploadUrl"], data=data, timeout=300,
                                   headers={"Authorization": f"Bearer {self.token}"})
        except requests.RequestException as e:
            raise LinkedInError(0, f"Image upload failed: {e}") from e
        if up.status_code >= 400:
            raise LinkedInError(up.status_code, f"Image upload failed: {up.text[:300]}")
        return value["image"]

    def upload_video(self, data):
        r = self._rest("POST", "/videos?action=initializeUpload",
                       json={"initializeUploadRequest": {"owner": self.author, "fileSizeBytes": len(data),
                                                         "uploadCaptions": False, "uploadThumbnail": False}})
        value = r.json()["value"]
        part_ids = []
        for part in value["uploadInstructions"]:  # LinkedIn wants the file in pieces of about 4 MB
            chunk = data[part["firstByte"]:part["lastByte"] + 1]
            try:
                up = self.http.request("PUT", part["uploadUrl"], data=chunk, timeout=600,
                                       headers={"Content-Type": "application/octet-stream"})
            except requests.RequestException as e:
                raise LinkedInError(0, f"Video upload failed: {e}") from e
            if up.status_code >= 400:
                raise LinkedInError(up.status_code, f"Video upload failed: {up.text[:300]}")
            part_ids.append(up.headers.get("etag") or up.headers.get("ETag") or "")
        self._rest("POST", "/videos?action=finalizeUpload",
                   json={"finalizeUploadRequest": {"video": value["video"],
                                                   "uploadToken": value.get("uploadToken", ""),
                                                   "uploadedPartIds": part_ids}})
        return value["video"]

    def media_status(self, urn):
        kind = "videos" if ":video:" in urn else "images"
        r = self._rest("GET", f"/{kind}/{quote(urn, safe='')}")
        body = r.json()
        return body.get("status"), body.get("processingFailureReason")

    def wait_available(self, urn, log=print):
        """Waits until LinkedIn has finished processing an upload (status AVAILABLE)."""
        every = 5
        tries = max(1, int(self.s.get("media_wait_seconds", 300)) // every)
        for _ in range(tries):
            try:
                status, reason = self.media_status(urn)
            except LinkedInError as e:
                if e.status == 403:
                    # Some logins may upload but not read the status. Give LinkedIn a moment instead.
                    log("LinkedIn does not let this login read the upload status. Waiting 20 seconds instead.")
                    self.sleep(20)
                    return "UNKNOWN"
                raise
            if status == "AVAILABLE":
                return status
            if status == "PROCESSING_FAILED":
                raise LinkedInError(422, f"LinkedIn could not process the file: {reason or 'no reason given'}")
            self.sleep(every)
        raise LinkedInError(408, "LinkedIn was still processing the file when the wait ran out.")

    # ---- the post ---------------------------------------------------------
    def create_post(self, caption, media=None):
        """media: None, {'kind': 'image', 'ids': [...], 'alt': '...'} or {'kind': 'video', 'ids': [...], 'title': '...'}
        Returns the new post's id (a 'urn')."""
        body = {"author": self.author, "commentary": little_text(caption),
                "visibility": self.s.get("visibility", "PUBLIC"),
                "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                                 "thirdPartyDistributionChannels": []},
                "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
        if media and media["kind"] == "video":
            body["content"] = {"media": {"title": media.get("title", ""), "id": media["ids"][0]}}
        elif media and len(media["ids"]) == 1:
            body["content"] = {"media": {"altText": media.get("alt", ""), "id": media["ids"][0]}}
        elif media:
            body["content"] = {"multiImage": {"images": [{"id": i, "altText": media.get("alt", "")}
                                                        for i in media["ids"]]}}
        try:
            r = self.http.request("POST", f"{REST}/posts", headers=self._headers(), json=body, timeout=120)
        except requests.RequestException as e:
            raise Uncertain(0, f"No answer from LinkedIn after sending the post: {e}") from e
        if r.status_code >= 500:
            raise Uncertain(r.status_code, f"LinkedIn had a server problem after the post was sent: {r.text[:300]}")
        if r.status_code >= 400:
            raise self._fail(r)
        return r.headers.get("x-restli-id") or r.headers.get("X-RestLi-Id") or ""


def post_link(urn):
    return f"https://www.linkedin.com/feed/update/{urn}/" if urn else ""
