"""ORM models. Matches the PRD data model plus auth tokens, jobs, and product events."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(200))
    plan: Mapped[str] = mapped_column(String(40), default="trial")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(10), default="Owner")  # Owner | Editor | Viewer
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    workspace: Mapped[Workspace] = relationship()


class AuthToken(Base):
    __tablename__ = "auth_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Brand(Base):
    __tablename__ = "brands"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    website_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    industry: Mapped[str] = mapped_column(String(40), default="general")
    current_kit_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KitVersion(Base):
    __tablename__ = "kit_versions"
    __table_args__ = (UniqueConstraint("brand_id", "version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    kit_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(10))  # website | paste
    platform: Mapped[str | None] = mapped_column(String(20), nullable=True)
    kind: Mapped[str] = mapped_column(String(10), default="post")  # bio | post | page
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    # Content the brand owns (its site, its posts). Non-owned text is never reproduced.
    owned: Mapped[bool] = mapped_column(Boolean, default=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    brand_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))  # import | kit_build | generate
    status: Mapped[str] = mapped_column(String(10), default="queued")  # queued | running | done | failed
    progress: Mapped[str] = mapped_column(String(200), default="")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GenRequest(Base):
    __tablename__ = "requests"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    kit_version: Mapped[int] = mapped_column(Integer)
    params_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String(80))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Ad(Base):
    __tablename__ = "ads"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"), index=True)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(20))
    format: Mapped[str] = mapped_column(String(40))
    audience: Mapped[str | None] = mapped_column(String(200), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    offer: Mapped[str | None] = mapped_column(String(300), nullable=True)
    angle: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Generated content: {"fields": {...}, "cta", "hashtags", "image_direction", "facts_used"}
    generated_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    # Current content after user edits (same shape as generated_json).
    fields_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(12), default="draft")  # draft | approved | exported | superseded
    flags_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_ad_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String(32), index=True)
    actor: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(40))
    target: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Event(Base):
    """Product analytics events (PRD: Instrumentation)."""

    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(40), index=True)
    workspace_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    brand_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    props: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
