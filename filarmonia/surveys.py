"""Анкеты раздела «Независимая оценка качества», которые заполняют прямо на сайте.

Описание анкет живёт только здесь: по нему строятся форма на странице, серверная
проверка ответов, письмо, просмотр, сводка и выгрузка в панели администратора.
Чтобы поправить формулировку вопроса, достаточно изменить текст в списке ниже.

Ответы хранятся словарём {«q1»: «yes», «q1_note»: «пожелание», «org»: «…»}:
для вопросов «Да/Нет» значения yes | no, для оценок — «1»…«5». Старые ответы
остаются читаемыми, пока не меняется номер (id) вопроса.
"""
import json
from dataclasses import dataclass, field

# Предел длины текстовых ответов: форму не должны превращать в хранилище файлов
TEXT_MAX = 300      # однострочные поля (название и адрес организации)
NOTE_MAX = 2000     # пожелания и предложения

YESNO = (("yes", "Да"), ("no", "Нет"))
SCALE = tuple((str(n), str(n)) for n in range(1, 6))
SCALE_HINT = "Оцените по 5-балльной системе: 1 — плохо, 5 — отлично."


@dataclass(frozen=True)
class Question:
    id: str                      # «q1», «q9»: ключ в сохранённых ответах
    text: str
    kind: str                    # yesno | scale | text
    required: bool = True
    note: bool = False           # у «Да/Нет» есть необязательное поле «Ваши пожелания»
    number: str = ""             # как номер показан в анкете: «1*», «2»

    @property
    def choices(self) -> tuple:
        return {"yesno": YESNO, "scale": SCALE}.get(self.kind, ())


@dataclass(frozen=True)
class Survey:
    key: str
    title: str
    subtitle: str
    intro: str = ""
    hint: str = ""               # подсказка перед вопросами
    footnote: str = ""
    outro: str = ""
    header_fields: tuple = ()    # ((id, подпись), …): необязательные текстовые поля до вопросов
    questions: tuple = field(default_factory=tuple)

    @property
    def choice_questions(self) -> list:
        return [q for q in self.questions if q.kind in ("yesno", "scale")]


def _yesno(items: dict) -> tuple:
    """Вопросы «Да/Нет»: {номер: (текст, нужно ли поле пожеланий)}."""
    return tuple(
        Question(id=f"q{n}", text=text, kind="yesno", note=note, number=f"{n}*" if note else str(n))
        for n, (text, note) in items.items()
    )


SNOC = Survey(
    key="snoc",
    title="Анкета Смоленского научно-образовательного центра",
    subtitle="Оценка качества условий оказания услуг организациями в сфере культуры",
    footnote=("* Разработано в полном соответствии с рекомендациями Министерства труда и социальной "
              "защиты Российской Федерации \"Расчет показателей, характеризующих общие критерии оценки "
              "качества условий оказания услуг организациями в сфере культуры, охраны здоровья, "
              "образования, социального обслуживания\""),
    intro=("Уважаемый клиент! В целях повышения качества оказания услуг организациями сферы культуры "
           "просим Вас дать ответы на вопросы."),
    outro="Благодарим Вас за понимание и сотрудничество!",
    header_fields=(
        ("org", "Наименование организации сферы культуры, в отношении которой осуществляется оценка "
                "качества условий оказания услуг"),
        ("address", "Место нахождения организации (почтовый адрес)"),
    ),
    questions=_yesno({
        1: ("Удовлетворяет ли Вас открытость, полнота и доступность информации о деятельности данной "
            "организации, размещенная на информационных стендах в помещении организации?", True),
        2: ("Удовлетворяет ли Вас открытость, полнота и доступность информации о деятельности данной "
            "организации, размещенная на сайте организации?", True),
        3: ("Довольны ли Вы комфортностью предоставления услуг организацией?", False),
        4: ("Удовлетворены ли Вы доступностью услуг для инвалидов в данной организации?", True),
        5: ("Устраивает ли Вас доброжелательность, вежливость работников организации культуры, "
            "обеспечивающих первичный контакт и информирование получателя услуги при непосредственном "
            "обращении в данную организацию?", True),
        6: ("Довольны ли Вы доброжелательностью, вежливостью работников организации культуры, "
            "обеспечивающих непосредственное оказание услуги при обращении в организацию?", True),
        7: ("Удовлетворены ли Вы доброжелательностью, вежливостью работников организации культуры при "
            "использовании дистанционных форм взаимодействия?", True),
        8: ("Готовы ли Вы рекомендовать данную организацию сферы культуры родственникам и знакомым "
            "(могли бы ее рекомендовать, если бы была возможность выбора организации сферы культуры)?",
            True),
        9: ("Довольны ли Вы организационными условиями предоставления услуг в организации сферы "
            "культуры?", True),
        10: ("Удовлетворены ли Вы в целом условиями оказания услуг в данной организации сферы "
             "культуры?", True),
    }),
)

MINKULT_SO = Survey(
    key="minkult_so",
    title="Анкета Министерства культуры и туризма Смоленской области",
    subtitle="Оценка качества условий оказания услуг организациями в сфере культуры",
    hint=SCALE_HINT,
    questions=tuple(
        Question(id=f"q{n}", text=text, kind="scale", number=str(n))
        for n, text in enumerate((
            "Как Вы оцениваете информирование о предстоящих мероприятиях?",
            "Как Вы можете оценить уровень комфортности пребывания в организации культуры (места для "
            "сидения, гардероб, чистота помещений)?",
            "Предлагает ли организация культуры дополнительные услуги (места общественного питания, "
            "проведение интерактивных игр, аудиогида)?",
            "Как Вы оцениваете транспортную и пешую доступность организации культуры?",
            "Как Вы оцениваете удобство пользования электронными сервисами, предоставляемыми "
            "учреждением?",
            "Как Вы оцениваете качество и содержание полиграфических материалов организации культуры "
            "(программ, буклетов, флаеров)?",
            "Насколько Вы удовлетворены качеством проводимых детских мероприятий, в т.ч. с "
            "детьми-инвалидами?",
            "Как Вы оцениваете доброжелательность, вежливость и компетентность персонала учреждения "
            "культуры?",
        ), start=1)
    ) + (
        Question(id="q9", text="Ваши предложения, пожелания по улучшению качества предоставляемых "
                               "учреждением культуры услуг", kind="text", required=False, number="9"),
    ),
)

SURVEYS = {s.key: s for s in (SNOC, MINKULT_SO)}


def get(key: str):
    """Анкета по ключу или None."""
    return SURVEYS.get(key)


def parse(survey: Survey, form) -> tuple:
    """Проверяет присланную форму. Возвращает (ответы, ошибки).

    Ответы собираются только по вопросам анкеты: лишние поля формы отбрасываются,
    значения вне списка допустимых не принимаются. Ошибки — список строк для
    показа посетителю; при ошибках ответы всё равно возвращаются, чтобы
    форму можно было показать заново с введёнными значениями.
    """
    answers, errors = {}, []
    for field_id, _label in survey.header_fields:
        answers[field_id] = (form.get(field_id) or "").strip()[:TEXT_MAX]
    for q in survey.questions:
        value = (form.get(q.id) or "").strip()
        if q.kind == "text":
            answers[q.id] = value[:NOTE_MAX]
            continue
        if not value:
            if q.required:
                errors.append(f"Ответьте на вопрос {q.number.rstrip('*')}.")
            answers[q.id] = ""
        elif value not in dict(q.choices):
            errors.append(f"Вопрос {q.number.rstrip('*')}: выберите один из предложенных вариантов.")
            answers[q.id] = ""
        else:
            answers[q.id] = value
        if q.note:
            answers[f"{q.id}_note"] = (form.get(f"{q.id}_note") or "").strip()[:NOTE_MAX]
    return answers, errors


def dumps(answers: dict) -> str:
    return json.dumps(answers, ensure_ascii=False)


def loads(raw: str) -> dict:
    """Ответы из базы; повреждённая запись даёт пустой словарь, а не ошибку страницы."""
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def display(question: Question, value: str) -> str:
    """Ответ в читаемом виде: «Да», «Нет», «4»; нет ответа — прочерк."""
    return dict(question.choices).get(value, value) or "—"


def rows(survey: Survey, answers: dict) -> list:
    """Вопросы и ответы по порядку: [(подпись, ответ, пожелание)] — для письма и просмотра."""
    result = []
    for field_id, label in survey.header_fields:
        result.append((label, answers.get(field_id) or "—", ""))
    for q in survey.questions:
        result.append((f"{q.number}. {q.text}", display(q, answers.get(q.id, "")),
                       answers.get(f"{q.id}_note", "")))
    return result


def summary(survey: Survey, responses) -> list:
    """Сводка по анкете: по каждому вопросу с вариантами ответа.

    Для «Да/Нет» — сколько ответили и сколько «Да» (с процентом), для оценок —
    средний балл. Возвращает [{question, total, yes, percent, average, notes}].
    """
    result = []
    parsed = [loads(r.answers) for r in responses]
    for q in survey.choice_questions:
        values = [a.get(q.id) for a in parsed if a.get(q.id) in dict(q.choices)]
        item = {"question": q, "total": len(values), "yes": 0, "percent": None, "average": None,
                "notes": sum(1 for a in parsed if a.get(f"{q.id}_note"))}
        if q.kind == "yesno":
            item["yes"] = values.count("yes")
            item["percent"] = round(100 * item["yes"] / len(values)) if values else None
        elif values:
            item["average"] = round(sum(int(v) for v in values) / len(values), 2)
        result.append(item)
    return result


def csv_header(survey: Survey) -> list:
    head = ["№", "Дата (МСК)"] + [label for _id, label in survey.header_fields]
    for q in survey.questions:
        head.append(f"{q.number}. {q.text}")
        if q.note:
            head.append(f"{q.number} Пожелания")
    return head


def _cell(value):
    """Текст для ячейки CSV. Начало с «=», «+», «-», «@» Excel принял бы за формулу."""
    if isinstance(value, str) and value[:1] in tuple("=+-@") + (chr(9), chr(13)):
        return "'" + value
    return value


def csv_row(survey: Survey, response, moscow_time) -> list:
    answers = loads(response.answers)
    row = [response.id, f"{moscow_time:%d.%m.%Y %H:%M}" if moscow_time else ""]
    row += [_cell(answers.get(field_id, "")) for field_id, _label in survey.header_fields]
    for q in survey.questions:
        value = answers.get(q.id, "")
        row.append(_cell(value) if q.kind == "text" else (display(q, value) if value else ""))
        if q.note:
            row.append(_cell(answers.get(f"{q.id}_note", "")))
    return row
