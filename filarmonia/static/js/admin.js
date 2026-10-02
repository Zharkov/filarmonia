/* Админка — клиентские скрипты. Зависимостей нет. */
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
          notify("Не удалось изменить статус. Обновите страницу и попробуйте ещё раз.", true);
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
          notify("Не удалось переставить. Обновите страницу и попробуйте ещё раз.", true);
        });
    });
  });
})();
