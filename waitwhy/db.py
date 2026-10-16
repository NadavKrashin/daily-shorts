"""Database engine/session helpers."""
from __future__ import annotations

import contextlib
import functools
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from waitwhy.settings import secrets


@functools.lru_cache
def get_engine(url: str | None = None) -> Engine:
    # Timestamps come back in UTC whatever the server's own timezone is (the Mac's Postgres runs on
    # Israel time), so times labelled UTC in the dashboard really are UTC.
    return create_engine(url or secrets().database_url, pool_pre_ping=True, pool_size=5, max_overflow=5,
                         connect_args={"options": "-c timezone=UTC"})


def session_factory(url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(url), expire_on_commit=False)


@contextlib.contextmanager
def session_scope(url: str | None = None) -> Iterator[Session]:
    session = session_factory(url)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
