"""initial schema

Revision ID: e5494f4bf0ad
Revises:
Create Date: 2026-08-24 21:39:25.209158

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlmodel.sql.sqltypes import AutoString

from alembic import op

revision: str = "e5494f4bf0ad"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# language_enum is referenced by two tables (agent_version, candidate). Postgres enum types
# aren't scoped to a column or created implicitly-once-per-migration the way autogenerate's
# inline sa.Enum(...) suggests — each op.create_table() that embeds one would try to CREATE
# TYPE again and fail with "already exists". So every enum is created explicitly, once, up
# front (checkfirst=True), and referenced everywhere else via create_type=False.
_language_enum = postgresql.ENUM(
    "ENGLISH",
    "HINDI",
    "TAMIL",
    "TELUGU",
    "KANNADA",
    "MARATHI",
    "MALAYALAM",
    "GUJARATI",
    "BENGALI",
    "TURKISH",
    "ARABIC",
    "SPANISH",
    name="language_enum",
)
_voice_persona_enum = postgresql.ENUM(
    "NEHA", "ROY", "ZOE", "SAM", "MIRA", "EESHA", name="voice_persona_enum"
)
_agent_version_origin_enum = postgresql.ENUM(
    "COMPILED", "PATCHED", name="agent_version_origin_enum"
)
_call_status_enum = postgresql.ENUM(
    "NOT_STARTED",
    "SCHEDULED",
    "INITIATED",
    "RINGING",
    "IN_PROGRESS",
    "COMPLETED",
    "NOT_CONNECTED",
    "CANCELLED",
    "FAILED",
    name="call_status_enum",
)


def upgrade() -> None:
    bind = op.get_bind()
    _language_enum.create(bind, checkfirst=True)
    _voice_persona_enum.create(bind, checkfirst=True)
    _agent_version_origin_enum.create(bind, checkfirst=True)
    _call_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "job",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", AutoString(), nullable=False),
        sa.Column("raw_jd", sa.Text(), nullable=False),
        sa.Column("compiled", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "llm_cache",
        sa.Column("key", AutoString(), nullable=False),
        sa.Column("role", AutoString(), nullable=False),
        sa.Column("model", AutoString(), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "provider_cache",
        sa.Column("key", AutoString(), nullable=False),
        sa.Column("provider", AutoString(), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "webhook_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_type", AutoString(), nullable=False),
        sa.Column("call_id", AutoString(), nullable=True),
        sa.Column("request_id", AutoString(), nullable=True),
        sa.Column("signature_valid", sa.Boolean(), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_webhook_event_call_id"), "webhook_event", ["call_id"], unique=False)
    op.create_table(
        "agent_version",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column(
            "language",
            postgresql.ENUM(name="language_enum", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "voice_persona",
            postgresql.ENUM(name="voice_persona_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("persona_name", AutoString(), nullable=False),
        sa.Column("agent_prompt", sa.Text(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("introduction", sa.Text(), nullable=False),
        sa.Column("result_prompt", sa.Text(), nullable=False),
        sa.Column("result_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("screening_questions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("hunar_agent_id", AutoString(), nullable=True),
        sa.Column(
            "origin",
            postgresql.ENUM(name="agent_version_origin_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id", "language", "version_no", name="uq_agent_version_job_language_version"
        ),
    )
    op.create_table(
        "candidate",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("source_provider", AutoString(), nullable=False),
        sa.Column("source_ref", AutoString(), nullable=False),
        sa.Column("full_name", AutoString(), nullable=False),
        sa.Column("headline", AutoString(), nullable=True),
        sa.Column("current_title", AutoString(), nullable=True),
        sa.Column("current_company", AutoString(), nullable=True),
        sa.Column("location", AutoString(), nullable=True),
        sa.Column("skills", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("years_experience", sa.Float(), nullable=True),
        sa.Column("linkedin_url", AutoString(), nullable=True),
        sa.Column("phone_e164", AutoString(), nullable=True),
        sa.Column(
            "preferred_language",
            postgresql.ENUM(name="language_enum", create_type=False),
            nullable=True,
        ),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("match_breakdown", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("consent_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_channel", AutoString(), nullable=True),
        sa.Column("dnc", sa.Boolean(), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "persona",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("archetype", AutoString(), nullable=False),
        sa.Column("profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ground_truth", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("behaviour", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "outreach",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("agent_version_id", sa.Uuid(), nullable=False),
        sa.Column("hunar_call_id", AutoString(), nullable=True),
        sa.Column("request_id", AutoString(length=64), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="call_status_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("lifecycle_status", AutoString(), nullable=False),
        sa.Column("answered_by", AutoString(), nullable=True),
        sa.Column("engagement_status", AutoString(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("recording_url", AutoString(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_simulated", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "request_id ~ '^[A-Za-z0-9_.-]{1,64}$'", name="ck_outreach_request_id_format"
        ),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_version.id"]),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidate.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index(op.f("ix_outreach_hunar_call_id"), "outreach", ["hunar_call_id"], unique=False)
    op.create_index(
        "ix_outreach_result_gin", "outreach", ["result"], unique=False, postgresql_using="gin"
    )
    op.create_table(
        "rehearsal_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", AutoString(), nullable=False),
        sa.Column("scores", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("llm_calls", sa.Integer(), nullable=False),
        sa.Column("cached_calls", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_version.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "prompt_patch",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("proposed_agent_prompt", sa.Text(), nullable=False),
        sa.Column("rationale", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("resulting_version_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["resulting_version_id"], ["agent_version.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["rehearsal_run.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "rehearsal_case",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("persona_id", sa.Uuid(), nullable=False),
        sa.Column("transcript", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("extracted_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("failures", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("estimated_seconds", sa.Float(), nullable=True),
        sa.Column("turn_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["persona_id"], ["persona.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["rehearsal_run.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_rehearsal_case_run_id"), "rehearsal_case", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_rehearsal_case_run_id"), table_name="rehearsal_case")
    op.drop_table("rehearsal_case")
    op.drop_table("prompt_patch")
    op.drop_table("rehearsal_run")
    op.drop_index("ix_outreach_result_gin", table_name="outreach", postgresql_using="gin")
    op.drop_index(op.f("ix_outreach_hunar_call_id"), table_name="outreach")
    op.drop_table("outreach")
    op.drop_table("persona")
    op.drop_table("candidate")
    op.drop_table("agent_version")
    op.drop_index(op.f("ix_webhook_event_call_id"), table_name="webhook_event")
    op.drop_table("webhook_event")
    op.drop_table("provider_cache")
    op.drop_table("llm_cache")
    op.drop_table("job")

    bind = op.get_bind()
    _call_status_enum.drop(bind, checkfirst=True)
    _agent_version_origin_enum.drop(bind, checkfirst=True)
    _voice_persona_enum.drop(bind, checkfirst=True)
    _language_enum.drop(bind, checkfirst=True)
