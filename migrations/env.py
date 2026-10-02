"""Окружение Alembic: схема берётся из моделей сайта."""
from alembic import context
from sqlalchemy import engine_from_config, pool

from filarmonia.models import db

config = context.config
target_metadata = db.metadata


def run_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"),
                      target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online():
    engine = engine_from_config(config.get_section(config.config_ini_section, {}),
                                prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as connection:
        # render_as_batch: SQLite не умеет менять и удалять колонки на месте,
        # Alembic для неё пересобирает таблицу целиком
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=True, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
