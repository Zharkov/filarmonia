"""Сводка: ближайшие события, счётчики, последние обращения."""
from flask import render_template

from ..models import db, Event, Collective, News, Document, Appeal
from .. import utils
from . import bp
from .common import login_required


# Сводка
@bp.route("/")
@login_required
def dashboard():
    now = utils.now_msk()
    return render_template(
        "admin/dashboard.html",
        upcoming=Event.query.options(db.joinedload(Event.venue))
        .filter(Event.starts_at >= now).order_by(Event.starts_at).limit(8).all(),
        counts={
            "events": Event.query.count(),
            "upcoming": Event.query.filter(Event.starts_at >= now).count(),
            "news": News.query.count(),
            "collectives": Collective.query.count(),
            "documents": Document.query.count(),
            "appeals_new": Appeal.query.filter_by(is_processed=False).count(),
        },
        appeals=Appeal.query.order_by(Appeal.created_at.desc()).limit(5).all(),
    )
