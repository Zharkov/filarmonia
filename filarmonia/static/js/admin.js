/* Панель администратора — клиентские скрипты. Зависимостей нет. */
(function () {
  "use strict";

  /* Всплывающее сообщение в углу экрана: не сдвигает страницу,
     в отличие от сообщения над таблицей */
  var toast = null;
  var toastTimer = null;

  function notify(text, isError) {
    if (!toast) {
      toast = document.createElement("div");
      toast.className = "toast";
      toast.setAttribute("role", "status");
      toast.setAttribute("aria-live", "polite");
      document.body.appendChild(toast);
    }
    toast.textContent = text;
    toast.classList.toggle("toast--error", !!isError);
    toast.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toast.classList.remove("is-visible"); }, 3500);
  }

  /* Обработчики вместо атрибутов onsubmit/onchange/onclick в разметке: политика
     безопасности (CSP) запрещает встроенные скрипты, а эти работают из файла.
     data-confirm у формы — спросить перед отправкой; ловим на погружении,
     раньше обработчиков самих форм, чтобы отказ отменял и отправку через fetch. */
  document.addEventListener("submit", function (e) {
    var form = e.target;
    var question = form.getAttribute && form.getAttribute("data-confirm");
    if (question && !window.confirm(question)) {
      e.preventDefault();
      e.stopImmediatePropagation();
    }
  }, true);

  // data-autosubmit у списка фильтра — применить сразу при выборе
  document.addEventListener("change", function (e) {
    if (e.target.hasAttribute && e.target.hasAttribute("data-autosubmit") && e.target.form) {
      e.target.form.submit();
    }
  });

  // data-print — кнопка печати
  document.querySelectorAll("[data-print]").forEach(function (button) {
    button.addEventListener("click", function () { window.print(); });
  });

  /* Визуальный редактор текста (Jodit). Весит под мегабайт, поэтому грузится
     только на страницах, где есть поле с разметкой: textarea[data-rich].
     Адреса файлов приходят атрибутами тега этого скрипта.
     Без скрипта поле остаётся обычным, и HTML вводится вручную. */
  (function () {
    var self = document.currentScript;
    var fields = document.querySelectorAll("textarea[data-rich]");
    if (!fields.length || !self || !self.getAttribute("data-jodit-js")) return;
    var css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = self.getAttribute("data-jodit-css");
    document.head.appendChild(css);
    var script = document.createElement("script");
    script.src = self.getAttribute("data-jodit-js");
    script.onload = function () {
      fields.forEach(function (field) {
        var editor = Jodit.make(field, {
          language: "ru",
          height: field.getAttribute("data-rich") === "small" ? 220 : 420,
          toolbarAdaptive: false,
          buttons: "paragraph,bold,italic,underline,strikethrough,|,ul,ol,|,link,image,table,|," +
                   "hr,eraser,|,undo,redo,|,source,fullsize",
          controls: {
            paragraph: { list: { p: "Обычный текст", h2: "Заголовок", h3: "Подзаголовок",
                                 h4: "Малый заголовок", blockquote: "Цитата" } }
          },
          // Текст из Word вставляется без его шрифтов, цветов и пустых стилей
          askBeforePasteHTML: false,
          askBeforePasteFromWord: false,
          defaultActionOnPaste: "insert_clear_html",
          // Картинки — только ссылкой: вставка файлом раздула бы базу
          uploader: { insertImageAsBase64URI: false },
          showCharsCounter: false, showWordsCounter: false, showXPathInStatusbar: false
        });
        // Форма следит за правками (ниже): редактор сообщает о каждой,
        // а текст, каким он стал после загрузки редактора, считается исходным
        field.jodit = editor;
        editor.e.on("change", function () {
          field.dispatchEvent(new Event("change", { bubbles: true }));
        });
        var rebase = function () {
          field.dispatchEvent(new CustomEvent("admin:rebase", { bubbles: true }));
        };
        rebase();
        if (editor.waitForReady) editor.waitForReady().then(rebase);
      });
    };
    document.body.appendChild(script);
  })();

  /* Переключатель «опубликовано / скрыто» в таблицах: меняется на месте,
     без перезагрузки и прокрутки. Без скрипта форма отправляется как обычно. */
  document.querySelectorAll("form[data-publish-toggle]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var button = form.querySelector("button");
      if (button.disabled) return;
      button.disabled = true;
      fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { "X-Requested-With": "fetch" },
        credentials: "same-origin"
      })
        .then(function (r) {
          if (!r.ok) throw new Error(r.status);
          return r.json();
        })
        .then(function (data) {
          var on = data.published;
          button.textContent = button.getAttribute(on ? "data-on" : "data-off");
          button.classList.toggle("badge--on", on);
          button.classList.toggle("badge--off", !on);
          button.setAttribute("aria-pressed", on ? "true" : "false");
          button.title = on ? "Скрыть с сайта" : "Показать на сайте";
          notify(data.message);
        })
        .catch(function () {
          notify("Не удалось изменить статус. Обновите страницу и повторите попытку.", true);
        })
        .then(function () { button.disabled = false; });
    });
  });

  /* Перестановка фото и видео в галерее: миниатюра переезжает на месте,
     без перезагрузки и прокрутки. Без скрипта форма отправляется как обычно. */
  function syncThumbs(grid) {
    var thumbs = grid.querySelectorAll(".thumb");
    thumbs.forEach(function (thumb, i) {
      var num = thumb.querySelector(".thumb__num");
      if (num) num.textContent = (i + 1) + ".";
      var up = thumb.querySelector('[data-dir="up"]');
      var down = thumb.querySelector('[data-dir="down"]');
      if (up) up.disabled = i === 0;
      if (down) down.disabled = i === thumbs.length - 1;
    });
  }

  document.querySelectorAll("form[data-media-move]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      // Какая стрелка нажата: FormData кнопку-отправителя сама не добавляет
      var button = e.submitter || document.activeElement;
      var dir = button && button.getAttribute("data-dir");
      if (!dir) return;
      var thumb = form.closest(".thumb");
      var grid = thumb.parentNode;
      var body = new FormData(form);
      body.set("dir", dir);
      form.querySelectorAll("button").forEach(function (b) { b.disabled = true; });

      fetch(form.action, {
        method: "POST",
        body: body,
        headers: { "X-Requested-With": "fetch" },
        credentials: "same-origin"
      })
        .then(function (r) {
          if (!r.ok) throw new Error(r.status);
          return r.json();
        })
        .then(function (data) {
          if (data.moved) {
            if (dir === "up" && thumb.previousElementSibling) {
              grid.insertBefore(thumb, thumb.previousElementSibling);
            } else if (dir === "down" && thumb.nextElementSibling) {
              grid.insertBefore(thumb.nextElementSibling, thumb);
            }
          }
          // Фокус остаётся на той же стрелке: можно двигать фото клавиатурой подряд
          var again = thumb.querySelector('[data-dir="' + dir + '"]');
          syncThumbs(grid);
          if (again && !again.disabled) again.focus();
        })
        .catch(function () {
          syncThumbs(grid);
          notify("Не удалось изменить порядок. Обновите страницу и повторите попытку.", true);
        });
    });
  });

  /* Форма записи (событие, новость, коллектив, страница): кнопка «Сохранить»
     нажимается, только когда в форме что-то поменяли, а уход со страницы
     с несохранёнными правками браузер переспрашивает. Визуальный редактор
     подключается позже и присылает событие admin:rebase — после него текст
     в редакторе считается исходным. */
  function fieldValue(el) {
    if (el.type === "checkbox" || el.type === "radio") return el.checked ? "1" : "";
    if (el.type === "file") {
      return Array.prototype.map.call(el.files || [], function (f) { return f.name; }).join("|");
    }
    if (el.jodit) return el.jodit.value;
    if (el.multiple) {
      return Array.prototype.filter.call(el.options, function (o) { return o.selected; })
        .map(function (o) { return o.value; }).join("|");
    }
    return el.value;
  }

  document.querySelectorAll("form[data-track-changes]").forEach(function (form) {
    var forced = form.hasAttribute("data-unsaved");  // форма вернулась с ошибкой: ничего ещё не сохранено
    // Кнопки стоят в панели внизу страницы, вне формы, и связаны с ней атрибутом form
    var bar = (form.id && document.querySelector('[data-actions-for="' + form.id + '"]')) || form;
    var note = bar.querySelector("[data-dirty-note]");
    var base = new Map();
    var dirty = false;
    var submitting = false;

    // Только поля, которые были в форме при загрузке: визуальный редактор
    // добавляет свои служебные поля, и они не правки редактора сайта
    var fields = Array.prototype.filter.call(form.elements, function (el) {
      return el.name && el.tagName !== "BUTTON" && el.type !== "hidden";
    });
    fields.forEach(function (el) { base.set(el, fieldValue(el)); });

    function update() {
      dirty = forced || fields.some(function (el) { return base.get(el) !== fieldValue(el); });
      bar.querySelectorAll("[data-needs-change]").forEach(function (b) { b.disabled = !dirty; });
      bar.querySelectorAll("[data-clean-href]").forEach(function (b) {
        var label = b.getAttribute(dirty ? "data-dirty-label" : "data-clean-label");
        if (label) b.textContent = label;
      });
      if (note) note.hidden = !dirty;
    }

    form.addEventListener("input", update);
    form.addEventListener("change", update);
    form.addEventListener("admin:rebase", function (e) {
      if (!base.has(e.target)) return;
      base.set(e.target, fieldValue(e.target));
      update();
    });

    bar.addEventListener("click", function (e) {
      var button = e.target.closest("button[type=submit]");
      if (!button) return;
      // Ничего не меняли — «Посмотреть» просто открывает страницу, без сохранения
      var href = button.getAttribute("data-clean-href");
      if (href && !dirty) {
        e.preventDefault();
        window.location.href = href;
        return;
      }
      var question = button.getAttribute("data-confirm");
      if (question && !window.confirm(question)) e.preventDefault();
    });

    form.addEventListener("submit", function () { submitting = true; });
    window.addEventListener("beforeunload", function (e) {
      if (dirty && !submitting) {
        e.preventDefault();
        e.returnValue = "";
      }
    });

    // Ctrl+S — сохранить, как в обычных программах
    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && (e.key === "s" || e.key === "ы")) {
        e.preventDefault();
        var save = bar.querySelector("[data-save-default]");
        if (save && !save.disabled) form.requestSubmit ? form.requestSubmit(save) : save.click();
      }
    });

    update();
  });

  /* Галочки «Коллективы в программе»: снять все разом */
  document.querySelectorAll("[data-picks]").forEach(function (box) {
    var clear = box.querySelector("[data-picks-clear]");
    if (!clear) return;
    clear.addEventListener("click", function () {
      box.querySelectorAll("input[type=checkbox]").forEach(function (c) { c.checked = false; });
      box.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });

  /* Адрес страницы. У новой записи он идёт за названием, пока редактор
     не поправил его сам; стёр поле — адрес снова идёт за названием.
     Свободен ли адрес, спрашиваем у сервера: занятый получает хвост «-2». */
  document.querySelectorAll("input[data-slug]").forEach(function (input) {
    var source = document.querySelector(input.getAttribute("data-slug-source"));
    var field = input.closest(".field");
    var hint = field.querySelector("[data-slug-hint]");
    var reset = field.querySelector("[data-slug-reset]");
    var defaultHint = hint.textContent;
    var auto = !input.value;
    var timer = null;
    var seq = 0;

    function say(text, suggestion) {
      hint.textContent = text;
      hint.classList.toggle("hint--warn", !!suggestion);
      if (suggestion) {
        var use = document.createElement("button");
        use.type = "button";
        use.className = "link-btn";
        use.textContent = "Использовать «" + suggestion + "»";
        use.addEventListener("click", function () { setSlug(suggestion); say(defaultHint); });
        hint.appendChild(document.createTextNode(" "));
        hint.appendChild(use);
      }
    }

    function setSlug(value) {
      input.value = value;
      // change, а не input: input означал бы, что адрес правили руками
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function check() {
      var mine = ++seq;
      var params = new URLSearchParams({
        kind: input.getAttribute("data-slug-kind"),
        id: input.getAttribute("data-slug-id"),
        title: source ? source.value : "",
        slug: auto ? "" : input.value
      });
      fetch(input.getAttribute("data-slug-url") + "?" + params, { credentials: "same-origin" })
        .then(function (r) {
          if (!r.ok) throw new Error(r.status);
          return r.json();
        })
        .then(function (data) {
          if (mine !== seq) return;  // пока ждали ответ, текст уже поменяли
          if (auto) {
            setSlug(data.slug);
            say(data.taken
              ? "Адрес «" + data.wanted + "» уже используется другой записью, поэтому назначен адрес «" + data.slug + "»."
              : defaultHint);
          } else if (!input.value) {
            say(defaultHint);
          } else if (data.taken) {
            say("Адрес «" + data.wanted + "» уже используется другой записью.", data.slug);
          } else if (data.slug !== input.value) {
            say("Адрес будет сохранён в виде «" + data.slug + "».", data.slug);
          } else {
            say(defaultHint);
          }
        })
        .catch(function () { /* не проверили — проверит сохранение */ });
    }

    function later() {
      clearTimeout(timer);
      timer = setTimeout(check, 300);
    }

    if (source) {
      source.addEventListener("input", function () { if (auto) later(); });
    }
    input.addEventListener("input", function () {
      auto = !input.value.trim();
      later();
    });
    if (reset) {
      reset.addEventListener("click", function () {
        auto = true;
        check();
      });
    }
  });
})();
