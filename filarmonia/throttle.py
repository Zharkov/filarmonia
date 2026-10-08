"""Ограничение частых действий: подбор пароля, поток обращений.

Счётчики хранятся в таблице `throttles`, поэтому общие для всех процессов
gunicorn и переживают перезапуск сайта. Старые записи удаляются при каждой
новой отметке, так что таблица не растёт.
"""
import time

from .models import db, Throttle


def state(key: str) -> tuple:
    """(сколько раз подряд, время последнего раза в секундах Unix)."""
    row = db.session.get(Throttle, key)
    return (row.count, row.last_at) if row else (0, 0.0)


def hit(key: str, window: float) -> int:
    """Отмечает действие. Если с прошлого прошло больше window секунд,
    счёт начинается заново. Возвращает новое значение счётчика."""
    now = time.time()
    # Чистим только записи того же вида («login:», «appeal:»): у них своё окно
    kind = key.split(":", 1)[0] + ":"
    Throttle.query.filter(Throttle.key.startswith(kind, autoescape=True),
                          Throttle.last_at < now - window).delete(synchronize_session=False)
    row = db.session.get(Throttle, key)
    if row is None:
        row = Throttle(key=key, count=0, last_at=0.0)
        db.session.add(row)
    row.count = (row.count or 0) + 1
    row.last_at = now
    db.session.commit()
    return row.count


def reset(key: str) -> None:
    Throttle.query.filter_by(key=key).delete(synchronize_session=False)
    db.session.commit()


def seconds_since(key: str) -> float:
    """Сколько секунд прошло с последней отметки; бесконечность — отметок не было."""
    _, last = state(key)
    return time.time() - last if last else float("inf")
