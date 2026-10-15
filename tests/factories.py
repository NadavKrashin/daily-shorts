"""Builders for test fixtures that skip expensive stages (no rendering)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from waitwhy.models import Approval, Script, Storyboard, StoryboardScene, Topic, Video, VideoVersion
from waitwhy.providers import registry


def topic(session, title="Why Ice Is Slippery", slug=None, **kw):
    t = Topic(title=title, slug=slug or f"t-{uuid.uuid4().hex[:8]}", category="science_physics", angle="a",
              summary="s", status="evaluated", score_total=80, scores={}, keywords=["ice"], **kw)
    session.add(t)
    session.flush()
    return t


def video(session, state="IDEA", **kw):
    t = topic(session)
    v = Video(topic_id=t.id, title=t.title, slug=t.slug, state=state, state_changed_at=datetime.now(timezone.utc),
              budget_usd=35, **kw)
    session.add(v)
    session.flush()
    return v


def ready_video(session, cfg, approved=True, publishable=True, state="READY_FOR_REVIEW"):
    """A rendered, QC-passed video (fake 1-byte media file) awaiting/with publication approval."""
    v = video(session, state=state)
    store = registry.storage(cfg)
    p = Path(store.root) / "fake.mp4" if hasattr(store, "root") else Path("/tmp/fake.mp4")
    p.write_bytes(b"0")
    key = store.put_file(p, f"videos/{v.slug}/v1/final.mp4")
    vv = VideoVersion(video_id=v.id, version=1, storage_key=key, status="qc_passed", duration_s=56,
                      manifest={"publishable": publishable})
    session.add(vv)
    session.flush()
    v.current_version_id = vv.id
    v.publish_metadata = {"youtube_title": v.title, "instagram_caption": "c", "tiktok_caption": "t",
                          "facebook_caption": "f", "hashtags": ["#science"], "disclosure": {}}
    if approved:
        session.add(Approval(video_id=v.id, kind="publication", status="approved", decided_by="user:test",
                             decided_at=datetime.now(timezone.utc)))
        v.state = "APPROVED"
    session.flush()
    return v


def storyboard_with_ai(session, v, n_ai=4, n_total=8):
    s = Script(video_id=v.id, version=1, data={}, full_text="x", word_count=1)
    session.add(s)
    session.flush()
    b = Storyboard(video_id=v.id, script_id=s.id, version=1, data={"recurring_objects": [], "style": {"palette": []}})
    session.add(b)
    session.flush()
    for i in range(1, n_total + 1):
        ai = i <= n_ai
        session.add(StoryboardScene(
            storyboard_id=b.id, scene_number=i, start_s=(i - 1) * 6, end_s=i * 6, narration=f"Scene {i} words here.",
            render_method="ai_video" if ai else "programmatic", template="kinetic_text",
            data={"generation_prompt": f"miniature city scene {i}", "negative_prompt": "", "camera_movement": "push",
                  "animation_motion": "slow", "continuity": ["c"], "template_params": []}))
    session.flush()
    v.current_script_id, v.current_storyboard_id = s.id, b.id
    session.flush()
    return b
