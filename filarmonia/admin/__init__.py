"""Панель управления сайтом.

Маршруты разложены по разделам панели; все они живут в одном блюпринте
`admin`, поэтому имена в шаблонах прежние: url_for('admin.event_form') и т. п.
"""
from flask import Blueprint

bp = Blueprint("admin", __name__)

# Модули регистрируют свои маршруты в bp при импорте
from . import (  # noqa: E402,F401
    appeals, auth, common, content, dashboard, events, media, publishing, site, system,
)
