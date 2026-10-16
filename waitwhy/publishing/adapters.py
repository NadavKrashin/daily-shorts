"""Platform publishing adapters (official APIs only - no browser automation, no bypassing reviews).

Verified against official docs on 2026-10-15 (re-check before go-live; see docs/platform-compliance.md):

YouTube  - Data API v3 videos.insert (resumable upload, scope youtube.upload). Uploads from UNVERIFIED API
           projects created after 2020-07-28 are locked to PRIVATE until the project passes Google's
           compliance audit. We request the target privacy, then READ BACK the actual status - a private
           result is recorded as ``private_uploaded`` + manual action, never as a public publication.
Instagram- Instagram Platform content publishing: POST /{ig-user-id}/media (media_type=REELS, video_url
           must be a PUBLIC URL), poll container status_code until FINISHED, POST /{ig-user-id}/media_publish.
           Professional account + instagram_business_content_publish (or FB-login equivalents). 100 API
           posts / 24 h (query content_publishing_limit).
Facebook - Pages Reels Publishing API: POST /{page-id}/video_reels upload_phase=start -> upload bytes to
           rupload.facebook.com (Authorization: OAuth <page token>) -> upload_phase=finish
           video_state=PUBLISHED. Needs pages_manage_posts etc. 30 API reels / 24 h. 3-90 s.
TikTok   - Content Posting API Direct Post requires an AUDITED app; unaudited clients may only post
           privately (SELF_ONLY) and are blocked from public posting. Default mode here is a compliant
           MANUAL HANDOFF package. Direct post is only attempted when TIKTOK_APP_AUDITED=true.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from waitwhy.errors import AuthError, PermanentError, PolicyError, TransientError


MAX_HASHTAGS = 5   # TikTok allows at most 5; Instagram is capped the same way


def post_text(caption: str, hashtags: list[str], platform: str, limit: int = MAX_HASHTAGS) -> str:
    """Caption plus hashtags for one platform: tags already at the end of the caption are merged,
    duplicates dropped, #shorts kept for YouTube only, and at most ``limit`` tags."""
    words = (caption or "").split()
    trailing = []
    while words and words[-1].startswith("#"):
        trailing.insert(0, words.pop())
    text = " ".join(words) if trailing else (caption or "").strip()
    tags, seen = [], set()
    for t in trailing + list(hashtags or []):
        t = "#" + t.lstrip("#").strip()
        if len(t) < 2 or t.lower() in seen or (t.lower() == "#shorts" and platform != "youtube"):
            continue
        seen.add(t.lower())
        tags.append(t)
    return (text + "\n\n" + " ".join(tags[:limit])).strip()


@dataclass
class PublishOutcome:
    status: str                 # published | private_uploaded | manual_action_required | processing
    external_id: str | None = None
    url: str | None = None
    privacy: str = "public"
    is_public: bool = False
    detail: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class PublishRequest:
    idempotency_key: str
    video_path: Path
    public_video_url: str | None
    thumbnail_path: Path | None
    title: str
    description: str
    caption: str
    hashtags: list[str]
    disclosure: dict
    scheduled_at_iso: str | None
    made_for_kids: bool = False
    category_id: str = "27"


def _raise_for(r: httpx.Response, who: str) -> None:
    if r.status_code in (401, 403):
        body = r.text[:300]
        if "quota" in body.lower():
            raise TransientError(f"{who} quota exhausted: {body}", retry_after_s=3600)
        raise AuthError(f"{who} auth/permission error {r.status_code}: {body}")
    if r.status_code == 429 or r.status_code >= 500:
        raise TransientError(f"{who} {r.status_code}: {r.text[:200]}")
    if r.status_code >= 400:
        raise PermanentError(f"{who} {r.status_code}: {r.text[:400]}")


# ------------------------------------------------------------------------------------------ YouTube
class YouTubeAdapter:
    platform = "youtube"
    TOKEN_URL = "https://oauth2.googleapis.com/token"

    def __init__(self, client_id: str, client_secret: str, refresh_token: str, mode: str):
        if not (client_id and client_secret and refresh_token):
            raise AuthError("YouTube OAuth credentials missing (YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN)")
        self.cid, self.secret, self.refresh, self.mode = client_id, client_secret, refresh_token, mode

    def _token(self) -> str:
        r = httpx.post(self.TOKEN_URL, data={"client_id": self.cid, "client_secret": self.secret,
                                             "refresh_token": self.refresh, "grant_type": "refresh_token"}, timeout=30)
        if r.status_code == 400 and "invalid_grant" in r.text:
            raise AuthError("YouTube refresh token expired or revoked - reconnect the channel")
        _raise_for(r, "google-oauth")
        return r.json()["access_token"]

    def publish(self, req: PublishRequest) -> PublishOutcome:
        token = self._token()
        status = {"privacyStatus": "public", "selfDeclaredMadeForKids": req.made_for_kids,
                  "containsSyntheticMedia": bool(req.disclosure.get("realistic_synthetic_media"))}
        if req.scheduled_at_iso:
            status.update({"privacyStatus": "private", "publishAt": req.scheduled_at_iso})
        body = {"snippet": {"title": req.title[:100], "description": req.description[:4900],
                            "tags": [h.lstrip("#") for h in req.hashtags][:10], "categoryId": req.category_id},
                "status": status}
        size = req.video_path.stat().st_size
        init = httpx.post("https://www.googleapis.com/upload/youtube/v3/videos",
                          params={"uploadType": "resumable", "part": "snippet,status"},
                          headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                   "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
                          content=json.dumps(body), timeout=60)
        _raise_for(init, "youtube-init")
        upload_url = init.headers["Location"]
        with open(req.video_path, "rb") as fh:
            up = httpx.put(upload_url, content=fh.read(), headers={"Content-Type": "video/mp4"}, timeout=1800)
        _raise_for(up, "youtube-upload")
        vid = up.json()["id"]
        # Read back the REAL status (unverified projects are forced private).
        for _ in range(30):
            st = httpx.get("https://www.googleapis.com/youtube/v3/videos", params={"part": "status,processingDetails", "id": vid},
                           headers={"Authorization": f"Bearer {token}"}, timeout=30)
            _raise_for(st, "youtube-status")
            items = st.json().get("items", [])
            if items and items[0]["status"].get("uploadStatus") in ("processed", "uploaded"):
                break
            time.sleep(10)
        s = items[0]["status"] if items else {}
        privacy = s.get("privacyStatus", "unknown")
        url = f"https://youtube.com/shorts/{vid}"
        if s.get("uploadStatus") in ("failed", "rejected"):
            raise PermanentError(f"YouTube processing {s.get('uploadStatus')}: {s.get('failureReason') or s.get('rejectionReason')}")
        if privacy == "public":
            return PublishOutcome("published", vid, url, "public", True, raw=s)
        if req.scheduled_at_iso and s.get("publishAt"):
            return PublishOutcome("processing", vid, url, "scheduled", False,
                                  detail=f"scheduled for {s.get('publishAt')}", raw=s)
        return PublishOutcome("private_uploaded", vid, url, privacy, False,
                              detail="Uploaded as PRIVATE (unverified API project or scheduling). "
                                     "Make it public in YouTube Studio or complete the API audit.", raw=s)

    def fetch_metrics(self, external_id: str) -> dict:
        token = self._token()
        r = httpx.get("https://www.googleapis.com/youtube/v3/videos", params={"part": "statistics", "id": external_id},
                      headers={"Authorization": f"Bearer {token}"}, timeout=30)
        _raise_for(r, "youtube-stats")
        items = r.json().get("items", [])
        stats = items[0]["statistics"] if items else {}
        out = {"views": _int(stats.get("viewCount")), "likes": _int(stats.get("likeCount")),
               "comments": _int(stats.get("commentCount"))}
        # Retention / watch time / subscribers come from the YouTube Analytics API (yt-analytics.readonly scope).
        try:
            a = httpx.get("https://youtubeanalytics.googleapis.com/v2/reports", params={
                "ids": "channel==MINE", "startDate": "2020-01-01", "endDate": time.strftime("%Y-%m-%d"),
                "metrics": "views,shares,subscribersGained,averageViewDuration,averageViewPercentage",
                "filters": f"video=={external_id}"}, headers={"Authorization": f"Bearer {token}"}, timeout=30)
            if a.status_code == 200 and a.json().get("rows"):
                row = a.json()["rows"][0]
                out.update({"shares": _int(row[1]), "followers_gained": _int(row[2]),
                            "avg_view_duration_s": float(row[3]), "avg_pct_viewed": float(row[4])})
        except httpx.HTTPError:
            pass
        return out


def _int(v):
    return int(v) if v not in (None, "") else None


# ------------------------------------------------------------------------------------------ Instagram
class InstagramAdapter:
    platform = "instagram"

    def __init__(self, ig_user_id: str, token: str, host: str, version: str):
        if not (ig_user_id and token):
            raise AuthError("Instagram credentials missing (INSTAGRAM_USER_ID / INSTAGRAM_ACCESS_TOKEN)")
        self.uid, self.token, self.base = ig_user_id, token, f"https://{host}/{version}"

    def publish(self, req: PublishRequest) -> PublishOutcome:
        if not req.public_video_url:
            raise PolicyError("Instagram pulls video from a PUBLIC URL - configure S3/CDN storage or PUBLIC_BASE_URL")
        caption = post_text(req.caption, req.hashtags, "instagram")[:2200]
        r = httpx.post(f"{self.base}/{self.uid}/media", params={"access_token": self.token}, data={
            "media_type": "REELS", "video_url": req.public_video_url, "caption": caption, "share_to_feed": "true"},
            timeout=60)
        _raise_for(r, "instagram-container")
        container = r.json()["id"]
        for _ in range(60):
            s = httpx.get(f"{self.base}/{container}", params={"fields": "status_code,status", "access_token": self.token},
                          timeout=30)
            _raise_for(s, "instagram-status")
            code = s.json().get("status_code")
            if code == "FINISHED":
                break
            if code in ("ERROR", "EXPIRED"):
                raise PermanentError(f"Instagram container {code}: {s.json().get('status')}")
            time.sleep(10)
        else:
            raise TransientError("Instagram container still processing")
        p = httpx.post(f"{self.base}/{self.uid}/media_publish", params={"access_token": self.token},
                       data={"creation_id": container}, timeout=60)
        _raise_for(p, "instagram-publish")
        media_id = p.json()["id"]
        info = httpx.get(f"{self.base}/{media_id}", params={"fields": "permalink", "access_token": self.token}, timeout=30)
        url = info.json().get("permalink") if info.status_code == 200 else None
        return PublishOutcome("published", media_id, url, "public", True, raw={"container": container})

    def fetch_metrics(self, external_id: str) -> dict:
        r = httpx.get(f"{self.base}/{external_id}/insights", params={
            "metric": "views,reach,likes,comments,shares,saved,ig_reels_avg_watch_time", "access_token": self.token},
            timeout=30)
        _raise_for(r, "instagram-insights")
        vals = {d["name"]: (d.get("values") or [{}])[0].get("value") for d in r.json().get("data", [])}
        awt = vals.get("ig_reels_avg_watch_time")
        return {"views": vals.get("views"), "reach": vals.get("reach"), "likes": vals.get("likes"),
                "comments": vals.get("comments"), "shares": vals.get("shares"), "saves": vals.get("saved"),
                "avg_view_duration_s": awt / 1000.0 if awt is not None else None}


# ------------------------------------------------------------------------------------------ Facebook
class FacebookReelsAdapter:
    platform = "facebook"

    def __init__(self, page_id: str, page_token: str, version: str):
        if not (page_id and page_token):
            raise AuthError("Facebook Page credentials missing (META_PAGE_ID / META_PAGE_ACCESS_TOKEN)")
        self.page, self.token, self.base = page_id, page_token, f"https://graph.facebook.com/{version}"

    def publish(self, req: PublishRequest) -> PublishOutcome:
        start = httpx.post(f"{self.base}/{self.page}/video_reels", data={"upload_phase": "start",
                                                                        "access_token": self.token}, timeout=60)
        _raise_for(start, "facebook-start")
        vid = start.json()["video_id"]
        size = req.video_path.stat().st_size
        with open(req.video_path, "rb") as fh:
            up = httpx.post(f"https://rupload.facebook.com/video-upload/{self.base.rsplit('/', 1)[1]}/{vid}",
                            headers={"Authorization": f"OAuth {self.token}", "offset": "0", "file_size": str(size)},
                            content=fh.read(), timeout=1800)
        _raise_for(up, "facebook-upload")
        desc = post_text(req.caption, req.hashtags, "facebook")
        fin = httpx.post(f"{self.base}/{self.page}/video_reels", data={
            "upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED", "description": desc,
            "access_token": self.token}, timeout=60)
        _raise_for(fin, "facebook-finish")
        for _ in range(60):
            s = httpx.get(f"{self.base}/{vid}", params={"fields": "status,permalink_url", "access_token": self.token},
                          timeout=30)
            _raise_for(s, "facebook-status")
            st = s.json().get("status", {})
            if st.get("video_status") == "ready" or (st.get("publishing_phase") or {}).get("status") == "complete":
                link = s.json().get("permalink_url")
                return PublishOutcome("published", vid, f"https://facebook.com{link}" if link and link.startswith("/") else link,
                                      "public", True, raw=st)
            if st.get("video_status") == "error":
                raise PermanentError(f"Facebook processing error: {st}")
            time.sleep(10)
        return PublishOutcome("processing", vid, None, "public", False, detail="still processing; will re-verify")

    def fetch_metrics(self, external_id: str) -> dict:
        r = httpx.get(f"{self.base}/{external_id}/video_insights", params={"access_token": self.token}, timeout=30)
        _raise_for(r, "facebook-insights")
        vals = {d["name"]: (d.get("values") or [{}])[0].get("value") for d in r.json().get("data", [])}
        return {"views": vals.get("blue_reels_play_count") or vals.get("fb_reels_total_plays"),
                "reach": vals.get("post_impressions_unique"),
                "avg_view_duration_s": (vals.get("post_video_avg_time_watched") or 0) / 1000.0
                if vals.get("post_video_avg_time_watched") is not None else None}


# ------------------------------------------------------------------------------------------ TikTok
class TikTokAdapter:
    """Manual handoff by default. Direct Post only for an AUDITED app (otherwise TikTok forces SELF_ONLY)."""

    platform = "tiktok"
    BASE = "https://open.tiktokapis.com/v2"

    def __init__(self, access_token: str, audited: bool, mode: str):
        self.token, self.audited, self.mode = access_token, audited, mode

    def publish(self, req: PublishRequest) -> PublishOutcome:
        if self.mode != "direct_post" or not (self.audited and self.token):
            return PublishOutcome("manual_action_required", None, None, "n/a", False,
                                  detail="TikTok: download the package from the dashboard and post it in the TikTok app "
                                         "(automated public posting needs an audited Content Posting API client).")
        info = httpx.post(f"{self.BASE}/post/publish/creator_info/query/",
                          headers={"Authorization": f"Bearer {self.token}"}, timeout=30)
        _raise_for(info, "tiktok-creator-info")
        options = info.json().get("data", {}).get("privacy_level_options", [])
        if "PUBLIC_TO_EVERYONE" not in options:
            raise PolicyError(f"TikTok account does not allow public posting via API (options={options})")
        size = req.video_path.stat().st_size
        init = httpx.post(f"{self.BASE}/post/publish/video/init/", headers={"Authorization": f"Bearer {self.token}"},
                          json={"post_info": {"title": post_text(req.caption, req.hashtags, "tiktok")[:2200],
                                              "privacy_level": "PUBLIC_TO_EVERYONE",
                                              "is_aigc": bool(req.disclosure.get("ai_generated_visuals")),
                                              "brand_content_toggle": bool(req.disclosure.get("paid_promotion"))},
                                "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size,
                                                "total_chunk_count": 1}}, timeout=60)
        if "unaudited_client" in init.text:
            raise PolicyError("TikTok: unaudited client can only post to private accounts")
        _raise_for(init, "tiktok-init")
        d = init.json()["data"]
        with open(req.video_path, "rb") as fh:
            up = httpx.put(d["upload_url"], content=fh.read(), headers={
                "Content-Type": "video/mp4", "Content-Range": f"bytes 0-{size - 1}/{size}"}, timeout=1800)
        _raise_for(up, "tiktok-upload")
        pid = d["publish_id"]
        for _ in range(60):
            s = httpx.post(f"{self.BASE}/post/publish/status/fetch/", headers={"Authorization": f"Bearer {self.token}"},
                           json={"publish_id": pid}, timeout=30)
            _raise_for(s, "tiktok-status")
            st = s.json().get("data", {})
            if st.get("status") == "PUBLISH_COMPLETE":
                ids = st.get("publicaly_available_post_id") or st.get("publicly_available_post_id") or []
                return PublishOutcome("published", str(ids[0]) if ids else pid, None, "public", bool(ids), raw=st)
            if st.get("status") == "FAILED":
                raise PermanentError(f"TikTok publish failed: {st.get('fail_reason')}")
            time.sleep(10)
        return PublishOutcome("processing", pid, None, "public", False)

    def fetch_metrics(self, external_id: str) -> dict:
        if not self.token:
            return {}
        r = httpx.post(f"{self.BASE}/video/query/", params={"fields": "view_count,like_count,comment_count,share_count"},
                       headers={"Authorization": f"Bearer {self.token}"}, json={"filters": {"video_ids": [external_id]}},
                       timeout=30)
        _raise_for(r, "tiktok-query")
        vids = r.json().get("data", {}).get("videos", [])
        v = vids[0] if vids else {}
        return {"views": v.get("view_count"), "likes": v.get("like_count"), "comments": v.get("comment_count"),
                "shares": v.get("share_count")}


# ------------------------------------------------------------------------------------------ Mock
class MockAdapter:
    """Dry-run publisher. Behaviour per platform is scriptable for tests:
    scenario = {"instagram": "fail_transient" | "fail_permanent" | "fail_auth" | "manual" | "private" | "ok"}."""

    def __init__(self, platform: str, scenario: dict | None = None):
        self.platform = platform
        self.scenario = scenario or {}
        self.calls: list[str] = []

    def publish(self, req: PublishRequest) -> PublishOutcome:
        mode = self.scenario.get(self.platform, "manual" if self.platform == "tiktok" else "ok")
        self.calls.append(req.idempotency_key)
        if mode == "fail_transient":
            raise TransientError(f"mock {self.platform}: upstream 503")
        if mode == "fail_permanent":
            raise PermanentError(f"mock {self.platform}: video rejected")
        if mode == "fail_auth":
            raise AuthError(f"mock {self.platform}: token expired")
        if mode == "manual":
            return PublishOutcome("manual_action_required", None, None, "n/a", False,
                                  detail=f"{self.platform}: manual posting required (dry run)")
        if mode == "private":
            return PublishOutcome("private_uploaded", f"mock-{self.platform}-{req.idempotency_key[:8]}", None, "private",
                                  False, detail="dry-run private upload")
        ext = f"mock-{self.platform}-{abs(hash(req.idempotency_key)) % 10 ** 10}"
        return PublishOutcome("published", ext, f"https://example.invalid/{self.platform}/{ext}", "public", True,
                              detail="DRY RUN - nothing was posted")

    def fetch_metrics(self, external_id: str) -> dict:
        return {}  # never fabricate metrics: mock posts report everything as unavailable
