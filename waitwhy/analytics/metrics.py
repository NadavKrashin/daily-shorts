"""Standardised metrics with fixed observation windows. Never compares a 2-hour-old post with a
month-old one: window metrics are only reported once a post is old enough, else they are None."""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from waitwhy.models import AnalyticsSnapshot, PlatformPost, Video

WINDOWS_H = {"24h": 24, "72h": 72, "7d": 168, "30d": 720}
TOLERANCE_H = 48  # a snapshot up to this many hours after the boundary still counts for the window


def snapshot_at(session: Session, post_id, hours: float) -> AnalyticsSnapshot | None:
    return session.execute(select(AnalyticsSnapshot).where(
        AnalyticsSnapshot.platform_post_id == post_id, AnalyticsSnapshot.hours_since_publish >= hours,
        AnalyticsSnapshot.hours_since_publish <= hours + TOLERANCE_H)
        .order_by(AnalyticsSnapshot.hours_since_publish, AnalyticsSnapshot.captured_at.desc())).scalars().first()


def latest(session: Session, post_id) -> AnalyticsSnapshot | None:
    return session.execute(select(AnalyticsSnapshot).where(AnalyticsSnapshot.platform_post_id == post_id)
                           .order_by(AnalyticsSnapshot.captured_at.desc())).scalars().first()


def per_thousand(num, views):
    if num is None or not views:
        return None
    return round(num / views * 1000, 2)


@dataclass
class PostMetrics:
    post_id: str
    platform: str
    video_id: str
    title: str
    category: str | None
    hook_style: str | None
    animation: str | None
    duration_s: float | None
    windows: dict           # window -> views (None if not yet observable / unavailable)
    latest: dict
    rates: dict
    is_mock: bool


def post_metrics(session: Session, post: PlatformPost) -> PostMetrics:
    video = session.get(Video, post.video_id)
    windows = {}
    for name, h in WINDOWS_H.items():
        s = snapshot_at(session, post.id, h)
        windows[name] = s.views if s else None
    last = latest(session, post.id)
    lt = {k: getattr(last, k) for k in ("views", "likes", "comments", "shares", "saves", "followers_gained",
                                         "avg_view_duration_s", "avg_pct_viewed", "hours_since_publish")} if last else {}
    v = lt.get("views")
    rates = {f"{k}_per_1k": per_thousand(lt.get(k), v) for k in ("likes", "shares", "comments", "saves",
                                                                  "followers_gained")} if lt else {}
    from waitwhy.models import VideoVersion
    vv = session.get(VideoVersion, video.current_version_id) if video.current_version_id else None
    return PostMetrics(str(post.id), post.platform, str(video.id), video.title, video.category, video.hook_style,
                       video.animation_technique, vv.duration_s if vv else None, windows, lt, rates, post.is_mock)


def all_post_metrics(session: Session, include_mock: bool = False) -> list[PostMetrics]:
    q = select(PlatformPost).where(PlatformPost.is_public.is_(True))
    if not include_mock:
        q = q.where(PlatformPost.is_mock.is_(False))
    return [post_metrics(session, p) for p in session.execute(q).scalars()]


def cohort_stats(rows: list[PostMetrics], key: str, window: str = "7d", min_n: int = 5) -> list[dict]:
    """Median views per cohort, per platform (platforms are never pooled)."""
    groups: dict[tuple, list[float]] = {}
    for r in rows:
        val = r.windows.get(window)
        if val is None:
            continue
        groups.setdefault((r.platform, getattr(r, key) or "unknown"), []).append(val)
    out = []
    for (platform, cohort), vals in sorted(groups.items()):
        out.append({"platform": platform, "cohort": cohort, "n": len(vals), "median": statistics.median(vals),
                    "p25": statistics.quantiles(vals, n=4)[0] if len(vals) >= 4 else None,
                    "p75": statistics.quantiles(vals, n=4)[2] if len(vals) >= 4 else None,
                    "sufficient": len(vals) >= min_n})
    return out


def platform_baselines(rows: list[PostMetrics], window: str = "7d") -> dict:
    out = {}
    for platform in sorted({r.platform for r in rows}):
        vals = [r.windows[window] for r in rows if r.platform == platform and r.windows.get(window) is not None]
        out[platform] = {"n": len(vals), "median_views": statistics.median(vals) if vals else None}
    return out


def relative_to_baseline(row: PostMetrics, baselines: dict, window: str = "7d") -> float | None:
    b = baselines.get(row.platform, {}).get("median_views")
    v = row.windows.get(window)
    if not b or v is None:
        return None
    return round(v / b, 2)
