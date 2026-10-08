"""Счётчики ограничений, перенаправления, даты изменения; пересборка кода видео

Ревизия: 7c1d2e9a4b30
Предыдущая: 4889a3fa2f4b
Создана: 2026-10-07 12:00:00

Код проигрывателя у видео пересобирается заново: прежняя проверка ссылок
пропускала адреса со схемой javascript:, и такая запись могла уже попасть в базу.
"""
from alembic import op
import sqlalchemy as sa


revision = '7c1d2e9a4b30'
down_revision = '4889a3fa2f4b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'throttles',
        sa.Column('key', sa.String(length=300), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('last_at', sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )
    with op.batch_alter_table('throttles', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_throttles_last_at'), ['last_at'], unique=False)

    op.create_table(
        'redirects',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('old_path', sa.String(length=500), nullable=False),
        sa.Column('new_url', sa.String(length=500), nullable=False),
        sa.Column('hits', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('old_path'),
    )

    for table in ('events', 'collectives', 'news'):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))

    _rebuild_video_embeds()


def _rebuild_video_embeds():
    from filarmonia.utils import video_embed

    bind = op.get_bind()
    media = sa.table('media_items', sa.column('id', sa.Integer), sa.column('url', sa.String),
                     sa.column('embed', sa.Text))
    rows = bind.execute(sa.select(media.c.id, media.c.url).where(media.c.url != '')).fetchall()
    for row_id, url in rows:
        bind.execute(media.update().where(media.c.id == row_id).values(embed=video_embed(url or '')))


def downgrade():
    for table in ('news', 'collectives', 'events'):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column('updated_at')
    op.drop_table('redirects')
    with op.batch_alter_table('throttles', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_throttles_last_at'))
    op.drop_table('throttles')
