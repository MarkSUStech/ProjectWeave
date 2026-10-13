"""Alembic 迁移环境：从应用设置读取连接串，从 Base.metadata 读取模型。"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.core.db import Base
from app.domains.assessments.models import (  # noqa: F401  确保模型注册到 metadata
    AssessmentAnswer,
    AssessmentSession,
)
from app.domains.concepts.models import KnowledgeConcept  # noqa: F401
from app.domains.curriculum.models import LearningPlan, ProjectTask  # noqa: F401
from app.domains.events.models import LearningEvent  # noqa: F401
from app.domains.executions.models import ExecutionSession  # noqa: F401
from app.domains.debugging.models import DebugSession  # noqa: F401
from app.domains.course_generation.models import CourseGeneration  # noqa: F401
from app.domains.course_generation.harness.models import CourseDevSession  # noqa: F401
from app.domains.learner.models import (  # noqa: F401
    LearningEvidence,
    LearnerMastery,
)
from app.domains.settings.models import UserSettings  # noqa: F401
from app.domains.tutor.models import TeachingDecision  # noqa: F401
from app.domains.projects.models import Project, ProjectFile, CodeSnapshot  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=settings.database_url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=settings.database_url.startswith("sqlite"),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
