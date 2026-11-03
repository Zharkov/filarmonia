"""Защита от подделки запросов: токен живёт в своей cookie, а не в сеансе.

Штатный `CSRFProtect` Flask-WTF хранит случайную строку токена в сессии. Браузер,
который чистит cookie при закрытии или блокирует их, терял сеанс раньше формы:
вход в панель отвечал «Форма устарела», и войти было нельзя. Здесь токен —
подпись случайной строки ключом `SECRET_KEY`, а сама строка лежит в отдельной
cookie `csrf_token` сроком на 90 дней, поэтому потеря сеанса форме не мешает.
"""
import hmac
import logging
import re
import secrets
import time

from flask import current_app, g, request
from flask_wtf.csrf import CSRFProtect, same_origin
from itsdangerous import BadData, SignatureExpired, URLSafeTimedSerializer
from markupsafe import Markup, escape
from wtforms import ValidationError

logger = logging.getLogger(__name__)

CSRF_COOKIE_NAME = "csrf_token"

# Срок cookie и подписи токена один и тот же: разные были бы хуже — либо cookie
# жила бы меньше подписи, либо страница «Форма устарела» возвращалась бы при целой
# cookie. Настоящий срок берётся из настройки `WTF_CSRF_TIME_LIMIT` (config.py),
# здесь только запасное значение для приложений без неё.
CSRF_COOKIE_MAX_AGE = 90 * 24 * 3600

# Шаг квантования метки времени подписи. `TimestampSigner` ставит текущие секунды,
# поэтому подпись — а с ней и весь HTML формы — менялась бы на каждый запрос,
# и слабый ETag страницы (`web.cache_headers`) никогда бы не совпал при повторном
# запросе. Округление до 15 минут держит подпись стабильной внутри окна.
CSRF_SIGNATURE_TIME_QUANTUM = 15 * 60

# Случайная строка — hex той же длины, что у Flask-WTF. Cookie приходит от
# посетителя, поэтому принимается только такой формат: иначе в подпись и
# сравнение попадало бы что угодно.
RAW_RE = re.compile(r"\A[0-9a-f]{64}\Z")

# Отдельный salt: подпись токена формы не должна оказываться допустимой подписью
# для других задач приложения (например, сессионной cookie) при одном ключе.
SALT = "filarmonia-csrf-cookie"


def cookie_max_age() -> int:
    """Срок cookie токена = срок подписи: одна настройка, чтобы они не разъезжались."""
    return int(current_app.config.get("WTF_CSRF_TIME_LIMIT", CSRF_COOKIE_MAX_AGE))


def _quantized_timestamp() -> int:
    """Метка времени, округлённая вниз до шага: подпись стабильна в пределах окна.

    Токен, подписанный в начале окна, живёт полный срок (округление вниз не
    отодвигает метку в будущее — подпись «из будущего» `itsdangerous` отвергает).
    """
    return int(time.time()) // CSRF_SIGNATURE_TIME_QUANTUM * CSRF_SIGNATURE_TIME_QUANTUM


class _CSRFSerializer(URLSafeTimedSerializer):
    """Подпись токена с квантованной меткой времени (С-25)."""

    def make_signer(self, salt=None):
        signer = super().make_signer(salt)
        # Метка нужна и при подписи, и при проверке: age считается разницей двух
        # квантованных меток, поэтому срок не сокращается на шаг квантования.
        signer.get_timestamp = _quantized_timestamp
        return signer


def _serializer() -> URLSafeTimedSerializer:
    return _CSRFSerializer(current_app.secret_key, salt=SALT)


def cookie_raw() -> str:
    """Случайная строка токена из cookie браузера; новая — если cookie нет или она испорчена."""
    raw = g.get("csrf_raw")
    if raw is None:
        raw = request.cookies.get(CSRF_COOKIE_NAME, "")
        if not RAW_RE.match(raw):
            # Браузер почистил cookie (или прислал мусор): ставим новую после ответа,
            # а до тех пор токен в формы попадает уже из новой строки.
            raw = secrets.token_hex(32)
            g.csrf_needs_cookie = True
        g.csrf_raw = raw
    return raw


def rotate_csrf_token() -> None:
    """Меняет строку токена и помечает cookie к перезаписи — при входе и выходе.

    Токен живёт 90 дней, поэтому без смены при смене пользователя токен,
    сохранённый или подсмотренный на общем компьютере, оставался пригодным
    до конца срока (С-23). Вызывать из маршрута после `session.clear()`:
    проверка CSRF этого запроса уже пройдена старым токеном.
    """
    g.csrf_raw = secrets.token_hex(32)
    g.csrf_needs_cookie = True
    # Подпись от прежней строки больше не годится: её в кэше ответа быть не должно
    g.pop("csrf_signed", None)


def generate_csrf(*_args, **_kwargs) -> str:
    """Токен для `<input name="csrf_token">` и meta-тега: подпись строки из cookie.

    Лишние аргументы принимаются молча: шаблон вызывает функцию без них, а
    поля WTForms могут передать настройки формы.
    """
    if "csrf_signed" not in g:
        g.csrf_signed = _serializer().dumps(cookie_raw())
    return g.csrf_signed


def csrf_meta_tag(name=None, *_args, **_kwargs) -> Markup:
    """`<meta name="csrf-token">` для скриптов: admin.js берёт из него X-CSRFToken."""
    name = name or current_app.config.get("WTF_CSRF_META_NAME", "csrf-token")
    return Markup(f'<meta name="{escape(name)}" content="{escape(generate_csrf())}">')


def validate_csrf(data, *_args, **_kwargs) -> None:
    """Проверяет подпись токена, срок и совпадение с cookie браузера. Сессия не участвует.

    Токен без подписки ключом `SECRET_KEY` не подделать, а сверка с cookie
    (double submit) не даёт отправить чужой токен: злоумышленник не знает
    случайную строку браузера жертвы и не может подставить её в форму.
    """
    if not data:
        raise ValidationError("Токен защиты от подделки запросов не пришёл.")

    raw = request.cookies.get(CSRF_COOKIE_NAME, "")
    if not RAW_RE.match(raw):
        raise ValidationError("Cookie с токеном защиты нет: браузер её почистил или не принимает.")

    limit = cookie_max_age()
    try:
        signed = _serializer().loads(data, max_age=limit)
    except SignatureExpired as e:
        raise ValidationError("Токен защиты от подделки запросов устарёл.") from e
    except BadData as e:
        raise ValidationError("Токен защиты от подделки запросов не подписан нашим ключом.") from e

    if not hmac.compare_digest(raw.encode("utf-8"), str(signed).encode("utf-8")):
        raise ValidationError("Токен в форме не совпадает с cookie браузера.")


class CookieCSRFProtect(CSRFProtect):
    """`CSRFProtect`, у которого токен берётся из cookie `csrf_token`, а не из сессии."""

    def init_app(self, app):
        # Flask-WTF ставит час — перебиваем своим значением до super(),
        # иначе его setdefault оставил бы 3600. Обычное приложение получает срок
        # из config.py, где он же задаёт Max-Age cookie (С-24).
        app.config.setdefault("WTF_CSRF_TIME_LIMIT", CSRF_COOKIE_MAX_AGE)

        @app.before_request
        def prepare_csrf_token():
            """Строка токена нужна до проверки CSRF: функция возвращает значение —
            поэтому вызов обёрнут, иначе Flask отдал бы её вместо страницы."""
            cookie_raw()

        super().init_app(app)

        # Flask-WTF зарегистрировал в шаблонах свои функции и обработчик контекста,
        # которые читают сессию. Оба перекрываем своими (обработчик контекста
        # важнее: его значения идут в шаблон вместо globals).
        app.jinja_env.globals["csrf_token"] = generate_csrf
        app.jinja_env.globals["csrf_meta_tag"] = csrf_meta_tag
        app.context_processor(lambda: {"csrf_token": generate_csrf,
                                       "csrf_meta_tag": csrf_meta_tag})

        @app.after_request
        def set_csrf_cookie(response):
            """Новую строку записываем в ответ: из функции шаблона cookie не ставят."""
            if g.get("csrf_needs_cookie"):
                response.set_cookie(
                    CSRF_COOKIE_NAME, g.csrf_raw, max_age=cookie_max_age(), path="/",
                    secure=app.config["SESSION_COOKIE_SECURE"], httponly=False,
                    samesite="Lax",
                )
            return response

    def protect(self, apply_exemptions=False):
        """Проверка как у Flask-WTF, но токен сверяется с cookie, а не с сессией."""
        if apply_exemptions:
            if not request.endpoint or self._is_exempt():
                return

        if request.method not in current_app.config["WTF_CSRF_METHODS"]:
            return

        try:
            validate_csrf(self._get_csrf_token())
        except ValidationError as e:
            logger.info("CSRF %s %s: %s", request.method, request.path, e.args[0])
            self._error_response(e.args[0])

        # HTTPS-запрос обязан прийти с этого же сайта: кука с SameSite=Lax этому не мешает,
        # но проверка закрывает подстановку формы по смешанному протоколу
        if request.is_secure and current_app.config["WTF_CSRF_SSL_STRICT"]:
            if not request.referrer:
                self._error_response("В запросе нет реферера.")
            elif not same_origin(request.referrer, f"https://{request.host}/"):
                self._error_response("Реферер не совпадает с адресом сайта.")

        g.csrf_valid = True
