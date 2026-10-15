from fastapi.testclient import TestClient

from tests import factories as f
from waitwhy.api.app import app, csrf_token
from waitwhy.models import Approval, SystemSetting, Video

client = TestClient(app)
AUTH = ("ceo", "test-pass")


def test_requires_auth():
    assert client.get("/").status_code == 401
    assert client.get("/healthz").json()["db"] is True


def test_all_pages_render(session, cfg):
    v = f.ready_video(session, cfg)
    session.commit()
    for path in ["/", "/pipeline", "/approvals", "/calendar", "/library", "/analytics", "/finance", "/sponsors",
                 "/agents", "/incidents", "/settings", f"/videos/{v.id}", "/api/status"]:
        r = client.get(path, auth=AUTH)
        assert r.status_code == 200, path


def test_pause_all_publishing_requires_csrf(session):
    assert client.post("/controls/publishing_paused/on", data={"csrf": "nope"}, auth=AUTH).status_code == 403
    r = client.post("/controls/publishing_paused/on", data={"csrf": csrf_token("ceo")}, auth=AUTH, follow_redirects=False)
    assert r.status_code == 303
    session.expire_all()
    assert session.get(SystemSetting, "publishing_paused").value is True


def test_protected_setting_needs_explicit_authorization(session):
    tok = csrf_token("ceo")
    r = client.post("/settings", data={"key": "monthly_hard_cap_usd", "value": "900", "csrf": tok}, auth=AUTH)
    assert r.status_code == 400
    r = client.post("/settings", data={"key": "monthly_hard_cap_usd", "value": "900", "csrf": tok,
                                       "confirm": "I AUTHORIZE monthly_hard_cap_usd"}, auth=AUTH, follow_redirects=False)
    assert r.status_code == 303
    session.expire_all()
    assert session.get(SystemSetting, "monthly_hard_cap_usd").value == 900
    assert session.query(Approval).filter_by(kind="setting_change").count() == 1


def test_owner_approves_from_dashboard(session, cfg):
    v = f.ready_video(session, cfg, approved=False, state="READY_FOR_REVIEW")
    a = Approval(video_id=v.id, kind="publication", status="pending")
    session.add(a)
    session.commit()
    r = client.post(f"/approvals/{a.id}/decide", data={"decision": "approved", "csrf": csrf_token("ceo")}, auth=AUTH,
                    follow_redirects=False)
    assert r.status_code == 303
    session.expire_all()
    assert session.get(Video, v.id).state == "APPROVED"
