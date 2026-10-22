"""Ответы на анкеты «Независимой оценки качества»: список, просмотр, сводка, выгрузка."""
import csv
import io

from flask import render_template, request, redirect, url_for, flash, Response

from datetime import timedelta

from ..models import db, Setting, SurveyResponse
from .. import mailer, surveys, utils
from . import bp
from .common import admin_required, get_or_404, log, login_required, paginated, sorted_by


def _chosen():
    """Анкета, выбранная в адресе (?survey=ключ); по умолчанию — первая."""
    return surveys.get(request.args.get("survey", "")) or next(iter(surveys.SURVEYS.values()))


@bp.route("/surveys")
@login_required
def survey_list():
    q = SurveyResponse.query
    key = request.args.get("survey", "")
    if key in surveys.SURVEYS:
        q = q.filter(SurveyResponse.survey == key)
    q, sorting = sorted_by(
        q, {"date": SurveyResponse.created_at, "survey": SurveyResponse.survey,
            "mail": SurveyResponse.is_emailed},
        default="date", default_dir="desc", tiebreak=SurveyResponse.id.desc(),
    )
    return render_template("admin/surveys.html", items=paginated(q), sorting=sorting,
                           all_surveys=surveys.SURVEYS, current=key)


@bp.route("/surveys/summary")
@login_required
def survey_summary():
    survey = _chosen()
    responses = SurveyResponse.query.filter_by(survey=survey.key).all()
    return render_template("admin/survey_summary.html", survey=survey, all_surveys=surveys.SURVEYS,
                           count=len(responses), rows=surveys.summary(survey, responses))


@bp.route("/surveys/export.csv")
@login_required
def survey_export():
    """Все ответы одной анкеты в CSV: UTF-8 с BOM и «;», чтобы Excel открыл без мастера импорта."""
    survey = _chosen()
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow(surveys.csv_header(survey))
    for row in SurveyResponse.query.filter_by(survey=survey.key).order_by(SurveyResponse.created_at, SurveyResponse.id):
        writer.writerow(surveys.csv_row(survey, row, utils.to_moscow(row.created_at)))
    response = Response("\ufeff" + out.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = f'attachment; filename="anketa-{survey.key}.csv"'
    return response


@bp.route("/surveys/<int:item_id>")
@login_required
def survey_view(item_id):
    item = get_or_404(SurveyResponse, item_id)
    survey = surveys.get(item.survey)
    rows = surveys.rows(survey, surveys.loads(item.answers)) if survey else []
    return render_template("admin/survey_view.html", item=item, survey=survey, rows=rows)


@bp.route("/surveys/<int:item_id>/delete", methods=["POST"])
@admin_required
def survey_delete(item_id):
    item = get_or_404(SurveyResponse, item_id)
    survey = surveys.get(item.survey)
    log("delete", item, details=survey.title if survey else item.survey)
    db.session.delete(item)
    db.session.commit()
    flash("Ответ удалён.", "ok")
    return redirect(url_for("admin.survey_list"))


@bp.route("/surveys/<int:item_id>/resend", methods=["POST"])
@admin_required
def survey_resend(item_id):
    """Повторная отправка письма с ответом, которое не ушло."""
    item = get_or_404(SurveyResponse, item_id)
    if item.is_emailed:
        flash("Письмо с этим ответом уже отправлено.", "ok")
    elif mailer.deliver_survey(item.id):
        log("update", item, details="письмо отправлено повторно")
        db.session.commit()
        flash("Письмо отправлено.", "ok")
    else:
        flash(f"Письмо не отправлено: {item.email_error}", "error")
    return redirect(url_for("admin.survey_view", item_id=item.id))


@bp.route("/surveys/resend-unsent", methods=["POST"])
@admin_required
def survey_resend_unsent():
    """Отправляет все неотправленные ответы. Первый же сбой останавливает рассылку:
    если почта не работает, ждать таймаут по каждому из ответов незачем."""
    sent = 0
    pending = SurveyResponse.query.filter_by(is_emailed=False).order_by(SurveyResponse.id).limit(50).all()
    failure = ""
    for item in pending:
        if not mailer.deliver_survey(item.id):
            failure = item.email_error
            break
        sent += 1
    if sent:
        log("update", object_type="survey", details=f"повторно отправлено писем: {sent}")
        db.session.commit()
    if failure:
        flash(f"Отправлено писем: {sent}. Остановлено: {failure}", "error")
    else:
        flash(f"Отправлено писем: {sent}.", "ok")
    return redirect(url_for("admin.survey_list"))


def purge_old_surveys() -> int:
    """Удаляет ответы анкет старше срока хранения из «Настроек» (surveys_retention_years, по умолчанию 3).

    Срок 0 — ничего не удаляется. Ответы анонимны, но это сведения о посетителях,
    поэтому хранятся ограниченное время. Запускается командой `python app.py purge`.
    """
    years = utils.parse_int(Setting.get("surveys_retention_years", "3"), 0)
    if not years:
        return 0
    border = utils.utcnow() - timedelta(days=365 * years)
    old = SurveyResponse.query.filter(SurveyResponse.created_at < border)
    count = old.count()
    if count:
        old.delete(synchronize_session=False)
        log("purge", object_type="survey", details=f"ответов на анкеты: {count}, срок {years} лет")
        db.session.commit()
    return count
