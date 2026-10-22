"""Ответы на анкеты «Независимой оценки качества»

Ревизия: d2b6f1a8c995
Предыдущая: c9f4d7a1b663
Создана: 2026-10-21 12:00:00

Новая таблица survey_responses: анонимные ответы на анкеты, заполненные на сайте.
"""
from alembic import op
import sqlalchemy as sa


revision = 'd2b6f1a8c995'
down_revision = 'c9f4d7a1b663'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('survey_responses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('survey', sa.String(length=40), nullable=False),
    sa.Column('answers', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('is_emailed', sa.Boolean(), nullable=False),
    sa.Column('email_error', sa.String(length=400), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('survey_responses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_survey_responses_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_survey_responses_survey'), ['survey'], unique=False)


def downgrade():
    with op.batch_alter_table('survey_responses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_survey_responses_survey'))
        batch_op.drop_index(batch_op.f('ix_survey_responses_created_at'))

    op.drop_table('survey_responses')
