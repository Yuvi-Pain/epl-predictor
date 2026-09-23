"""Shared connections: one async Postgres engine, one Redis client, one model base."""

import os

from redis.asyncio import Redis
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
# Short timeouts: Redis only holds a cache, so if it hangs we would rather give
# up after half a second and build the response from Postgres.
redis_client = Redis.from_url(REDIS_URL, socket_connect_timeout=0.5, socket_timeout=0.5)

# Predictable constraint names, so migrations can refer to them by name.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Parent class for every database table model. Alembic reads its metadata."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
