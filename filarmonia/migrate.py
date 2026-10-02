"""Миграции базы на Alembic.

    python app.py db upgrade                 привести базу к последней версии
    python app.py db revision "что меняется" записать изменение моделей шагом миграции
    python app.py db current                 показать текущую версию базы

Каждое изменение моделей записывается отдельным файлом в migrations/versions:
его можно прочитать, проверить и при необходимости откатить (`db downgrade`).
"""
import os

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from .models import db, upgrade_schema

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")


def alembic_config(app) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", MIGRATIONS_DIR)
    # «%» в пароле базы иначе приняли бы за подстановку настроек Alembic
    cfg.set_main_option("sqlalchemy.url", app.config["SQLALCHEMY_DATABASE_URI"].replace("%", "%%"))
    return cfg


def upgrade(app) -> None:
    """Доводит базу до последней версии.

    База, созданная до появления миграций (через `create_all`), версии не
    знает. Для неё сначала дописываются недостающие таблицы и колонки,
    затем ставится отметка последней версии — дальше она обновляется
    миграциями, как и новая база.
    """
    cfg = alembic_config(app)
    with app.app_context():
        tables = set(inspect(db.engine).get_table_names())
        if tables and "alembic_version" not in tables:
            db.create_all()
            for column in upgrade_schema():
                print(f"В базу добавлена колонка {column}")
            command.stamp(cfg, "head")
            print("База отмечена последней версией схемы.")
            return
    command.upgrade(cfg, "head")


def revision(app, message: str) -> None:
    """Новый шаг миграции по разнице между моделями и базой."""
    command.revision(alembic_config(app), message=message, autogenerate=True)


def downgrade(app, target: str = "-1") -> None:
    command.downgrade(alembic_config(app), target)


def current(app) -> None:
    command.current(alembic_config(app), verbose=False)
