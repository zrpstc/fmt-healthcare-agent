from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import uuid
from datetime import UTC, datetime
from typing import Iterator

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from wgs_fmt_platform.config import get_settings
from wgs_fmt_platform.paths import runtime_path


class Base(DeclarativeBase):
    pass


def _id() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(40), default="researcher")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[list["AuthSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    user: Mapped[User] = relationship(back_populates="sessions")


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="新对话")
    agent_id: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(200), default="")
    trace: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class MemoryRecord(Base):
    __tablename__ = "memory_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    scope: Mapped[str] = mapped_column(String(20), default="short")
    content: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    __table_args__ = (Index("ix_memory_user_scope_created", "user_id", "scope", "created_at"),)


class AuditRecord(Base):
    __tablename__ = "audit_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    event: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)


class ConsumerShareLink(Base):
    __tablename__ = "consumer_share_links"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    sample_id: Mapped[str] = mapped_column(String(128), index=True)
    token_sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by: Mapped[str] = mapped_column(String(36), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConsumerGlossaryReview(Base):
    __tablename__ = "consumer_glossary_reviews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    term_id: Mapped[str] = mapped_column(String(120), index=True)
    field: Mapped[str] = mapped_column(String(40), default="one_liner")
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    reviewer: Mapped[str] = mapped_column(String(120), default="")
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    __table_args__ = (UniqueConstraint("term_id", "field", name="uq_consumer_glossary_term_field"),)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt_hex, expected_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(digest.hex(), expected_hex)
    except (TypeError, ValueError):
        return False


_settings = get_settings()
_sqlite_file = runtime_path("WGS_CONVERSATION_DB_FILE", "db", "wgs_agent.db")
_sqlite_file.parent.mkdir(parents=True, exist_ok=True)
# WGS_DATABASE_URL may point to MySQL in production. The local, durable SQLite
# file keeps conversation memory available even when optional MySQL is offline.
DATABASE_URL = os.environ.get("WGS_DATABASE_URL", f"sqlite:///{_sqlite_file}")
_engine_options = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite:"):
    _engine_options["connect_args"] = {"check_same_thread": False}
else:
    _engine_options.update(pool_recycle=1800, pool_size=_settings.mysql_pool_size)
engine = create_engine(DATABASE_URL, **_engine_options)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def create_schema() -> None:
    Base.metadata.create_all(engine)


def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
