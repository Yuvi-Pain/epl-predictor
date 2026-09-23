"""Shared connections: one async Postgres engine, one Redis client, one model base."""

import os

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
redis_client = Redis.from_url(REDIS_URL)


class Base(DeclarativeBase):
    """Parent class for every database table model. Alembic reads its metadata."""
