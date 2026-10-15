"""Idempotent first-run setup: organisation, owner, brand, platform account rows, seed backlog."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from waitwhy.agents.trends import seed_backlog
from waitwhy.models import Brand, Organization, PlatformAccount, User
from waitwhy.settings import get_config


def bootstrap(session: Session, owner_email: str = "owner@example.com") -> dict:
    cfg = get_config(session)
    org = session.execute(select(Organization)).scalars().first()
    if org is None:
        org = Organization(name=cfg["business_name"], timezone=cfg["timezone"])
        session.add(org)
        session.flush()
        session.add(User(organization_id=org.id, email=owner_email, name="Owner", role="owner"))
    brand = session.execute(select(Brand)).scalars().first()
    if brand is None:
        brand = Brand(organization_id=org.id, name=cfg["business_name"], tagline=cfg["tagline"],
                      style_guide={"visual_style": cfg["brand"]["visual_style"], "palette": cfg["brand"]["palette"]},
                      voice={"description": cfg["brand"]["voice"]})
        session.add(brand)
        session.flush()
    for platform, pcfg in cfg["platforms"].items():
        if not session.execute(select(PlatformAccount).where(PlatformAccount.platform == platform)).scalar_one_or_none():
            session.add(PlatformAccount(brand_id=brand.id, platform=platform, status="disconnected",
                                        publishing_mode=pcfg.get("publishing_mode", "manual_handoff"),
                                        secret_ref=f"env:{platform.upper()}_*"))
    n = seed_backlog(session, cfg)
    return {"organization": org.name, "brand": brand.name, "seeded_topics": n}
