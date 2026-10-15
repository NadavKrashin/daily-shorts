"""Audit trail helpers: every external action and state change is recorded."""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from waitwhy.models import AuditLog

log = logging.getLogger("waitwhy.audit")


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str)) if value is not None else None


def audit(
    session: Session,
    actor: str,
    action: str,
    entity_type: str | None = None,
    entity_id: Any = None,
    before: Any = None,
    after: Any = None,
    **details: Any,
) -> AuditLog:
    row = AuditLog(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=_jsonable(before),
        after=_jsonable(after),
        details=_jsonable(details) or {},
    )
    session.add(row)
    log.info("audit %s %s %s:%s %s", actor, action, entity_type, entity_id, details or "")
    return row
