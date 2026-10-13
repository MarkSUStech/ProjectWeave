"""p823 course dev sessions

Revision ID: 6a388ff17721
Revises: 7edb9eb11b76
Create Date: 2026-10-13 09:33:54.541288

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import Text


# revision identifiers, used by Alembic.
revision: str = '6a388ff17721'
down_revision: Union[str, None] = '7edb9eb11b76'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from app.domains.course_generation.harness.models import CourseDevSession
    from app.core.db import Base

    CourseDevSession.__table__.create(
        op.get_bind(), checkfirst=True)


def downgrade() -> None:
    op.drop_table("course_dev_sessions")
