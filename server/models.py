from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, text
from sqlalchemy import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now() -> datetime:
    return datetime.now(timezone.utc)


def uid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Problem(Base):
    __tablename__ = "problems"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(200))
    statement: Mapped[str] = mapped_column(Text, default="")
    example_explanation: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    constraints: Mapped[list[str]] = mapped_column(JSON, default=list)
    signature: Mapped[dict] = mapped_column(JSON)
    templates: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_image: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    source_image_mime: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reference_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    brute_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    validator_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    generator_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    original_examples: Mapped[list] = mapped_column(JSON, default=list)
    latest_generation_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    generation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_revision: Mapped[int] = mapped_column(Integer, default=1)
    time_limit_ms: Mapped[int] = mapped_column(Integer, default=2000)
    memory_limit_mb: Mapped[int] = mapped_column(Integer, default=256)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    tests: Mapped[list["TestCase"]] = relationship(back_populates="problem", cascade="all, delete-orphan")


class TestCase(Base):
    __tablename__ = "test_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    problem_id: Mapped[str] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    position: Mapped[int] = mapped_column(Integer, default=0)
    args: Mapped[list] = mapped_column(JSON)
    expected: Mapped[object] = mapped_column(JSON)
    suite_version: Mapped[int] = mapped_column(Integer)
    provenance: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    problem: Mapped[Problem] = relationship(back_populates="tests")


class CodeDraft(Base):
    __tablename__ = "code_drafts"
    __table_args__ = (UniqueConstraint("problem_id", "language"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    problem_id: Mapped[str] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"), index=True)
    language: Mapped[str] = mapped_column(String(12))
    source: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    problem_id: Mapped[str] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="execution")
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    language: Mapped[str | None] = mapped_column(String(12), nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    test_revision: Mapped[int] = mapped_column(Integer)
    signature_snapshot: Mapped[dict] = mapped_column(JSON)
    cases_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    results: Mapped[list | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChatTurn(Base):
    __tablename__ = "chat_turns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    problem_id: Mapped[str] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(16))
    user_message: Mapped[str] = mapped_column(Text)
    assistant_message: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AIUsage(Base):
    __tablename__ = "ai_usage"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    problem_id: Mapped[str | None] = mapped_column(ForeignKey("problems.id", ondelete="SET NULL"), nullable=True)
    operation: Mapped[str] = mapped_column(String(24))
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
