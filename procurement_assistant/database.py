from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return f"postgresql+psycopg://{url.removeprefix('postgres://')}"
    if url.startswith("postgresql://"):
        return f"postgresql+psycopg://{url.removeprefix('postgresql://')}"
    return url


def database_url() -> str:
    return normalize_database_url(os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://procurement:procurement@localhost:5432/procurement",
    ))


def build_engine(
    url: str | None = None,
    *,
    echo: bool = False,
    pool_size: int = 5,
    max_overflow: int = 2,
    use_null_pool: bool = False,
) -> Engine:
    resolved = normalize_database_url(url or database_url())
    options = {"echo": echo, "pool_pre_ping": True}
    if use_null_pool:
        options["poolclass"] = NullPool
        if resolved.startswith("postgresql+psycopg://"):
            options["connect_args"] = {"prepare_threshold": None}
    elif not resolved.startswith("sqlite"):
        options.update(pool_size=pool_size, max_overflow=max_overflow)
    return create_engine(resolved, **options)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
