/* Сайт филармонии — клиентские скрипты. Зависимостей нет. */
(function () {
  "use strict";

  /* Мобильное меню */
  var burger = document.querySelector("[data-burger]");
  var nav = document.querySelector("[data-nav]");
  if (burger && nav) {
    burger.addEventListener("click", function () {
      var open = nav.classList.toggle("is-open");
      burger.setAttribute("aria-expanded", open ? "true" : "false");
    });
    // Подменю на телефоне раскрываются стрелкой справа от пункта
    nav.querySelectorAll("[data-nav-toggle]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var open = btn.parentNode.classList.toggle("is-open");
        btn.setAttribute("aria-expanded", open ? "true" : "false");
      });
    });
  }

  /* Настройки для слабовидящих */
  var root = document.documentElement;
  var panel = document.querySelector("[data-a11y]");
  var toggle = document.querySelector("[data-a11y-toggle]");

  /* Состояние обычной версии: без него ни одна кнопка не отмечена нажатой
     и непонятно, какой размер шрифта сейчас выбран */
  var A11Y_DEFAULTS = { size: "m", images: "on" };

  function applyStored() {
    var saved = {};
    try {
      saved = JSON.parse(localStorage.getItem("a11y") || "{}");
    } catch (e) { /* localStorage может быть отключён */ }
    if (saved.size) root.setAttribute("data-size", saved.size);
    if (saved.theme) root.setAttribute("data-theme", saved.theme);
    if (saved.images) root.setAttribute("data-images", saved.images);
    syncButtons(saved);
  }

  function syncButtons(state) {
    document.querySelectorAll("[data-a11y-set]").forEach(function (btn) {
      var parts = btn.getAttribute("data-a11y-set").split(":");
      var current = state[parts[0]] || A11Y_DEFAULTS[parts[0]];
      btn.setAttribute("aria-pressed", current === parts[1] ? "true" : "false");
    });
  }

  if (toggle && panel) {
    toggle.addEventListener("click", function () {
      var open = panel.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  document.querySelectorAll("[data-a11y-set]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var parts = btn.getAttribute("data-a11y-set").split(":");
      var state = {};
      try { state = JSON.parse(localStorage.getItem("a11y") || "{}"); } catch (e) {}
      state[parts[0]] = parts[1];
      root.setAttribute("data-" + parts[0], parts[1]);
      try { localStorage.setItem("a11y", JSON.stringify(state)); } catch (e) {}
      syncButtons(state);
    });
  });

  var reset = document.querySelector("[data-a11y-reset]");
  if (reset) {
    reset.addEventListener("click", function () {
      ["size", "theme", "images"].forEach(function (k) { root.removeAttribute("data-" + k); });
      try { localStorage.removeItem("a11y"); } catch (e) {}
      syncButtons({});
    });
  }
  applyStored();

  /* Изменения в афише — окно в правом нижнем углу. На главной плавно
     выдвигается, когда на экран попадает блок с концертами (или страницу уже
     прокрутили ниже него), в афише — вскоре после загрузки. Свёрнутое или
     закрытое окно остаётся таким на всех страницах, пока набор изменений тот же:
     новая или исправленная запись меняет ключ, и окно снова открыто.
     Кнопка «Наверх» поднимается над окном на его высоту. */
  var notices = document.querySelector("[data-notices]");
  if (notices) {
    var noticesKey = notices.getAttribute("data-notices");
    var noticesBox = notices.querySelector("[data-notices-box]");
    var noticesClose = notices.querySelector("[data-notices-close]");
    var noticesState = "";
    try {
      var savedNotices = JSON.parse(localStorage.getItem("notices") || "{}");
      if (savedNotices.key === noticesKey) noticesState = savedNotices.state;
    } catch (e) { /* localStorage может быть отключён */ }
    var rememberNotices = function (state) {
      try { localStorage.setItem("notices", JSON.stringify({ key: noticesKey, state: state })); } catch (e) {}
    };
    var syncNoticesOffset = function () {
      var shown = !notices.hidden;
      document.body.classList.toggle("has-notices", shown);
      if (shown) document.body.style.setProperty("--notices-h", notices.offsetHeight + "px");
    };
    var showNotices = function () {
      notices.hidden = false;
      syncNoticesOffset();   // заодно читает высоту — браузер фиксирует начальное положение
      notices.classList.add("is-visible");
    };

    if (noticesState !== "closed") {
      if (noticesState === "folded") noticesBox.open = false;
      noticesClose.hidden = false;
      notices.classList.add("is-pending");
      noticesBox.addEventListener("toggle", function () {
        rememberNotices(noticesBox.open ? "open" : "folded");
        syncNoticesOffset();
      });
      window.addEventListener("resize", syncNoticesOffset);
      noticesClose.addEventListener("click", function () {
        notices.hidden = true;
        syncNoticesOffset();
        rememberNotices("closed");
        var main = document.getElementById("main");
        if (main) { main.setAttribute("tabindex", "-1"); main.focus({ preventScroll: true }); }
      });

      var noticesAnchor = document.querySelector("[data-notices-anchor]");
      if (noticesAnchor && "IntersectionObserver" in window) {
        var noticesWatch = new IntersectionObserver(function (entries) {
          var entry = entries[0];
          if (entry.isIntersecting || entry.boundingClientRect.top < 0) {
            noticesWatch.disconnect();
            showNotices();
          }
        }, { rootMargin: "0px 0px -15% 0px" });
        noticesWatch.observe(noticesAnchor);
      } else {
        setTimeout(showNotices, 600);
      }
    }
  }

  /* Всплывающие баннеры на афише (тач-устройства) */
  var canHover = window.matchMedia("(hover: hover)").matches;
  document.querySelectorAll(".pin").forEach(function (pin) {
    pin.addEventListener("click", function (e) {
      var open = pin.classList.contains("is-open");
      // На тач-устройстве подсказку у баннера-ссылки иначе не прочитать:
      // hover там нет, а касание сразу уводит по ссылке. Первое касание
      // раскрывает подсказку, второе переходит.
      if (pin.tagName === "A" && (canHover || open)) return;
      e.preventDefault();
      e.stopPropagation();
      document.querySelectorAll(".pin.is-open").forEach(function (p) { p.classList.remove("is-open"); });
      if (!open) pin.classList.add("is-open");
    });
  });
  document.addEventListener("click", function () {
    document.querySelectorAll(".pin.is-open").forEach(function (p) { p.classList.remove("is-open"); });
  });

  /* Модальные окна */
  var FOCUSABLE = 'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])';
  var openerBeforeModal = null;

  function openModal(id) {
    var m = document.getElementById(id);
    if (!m) return;
    // Запоминаем, откуда пришли: после закрытия фокус должен вернуться на
    // ту же кнопку, иначе пользователь клавиатуры теряет место на странице
    openerBeforeModal = document.activeElement;
    m.classList.add("is-open");
    document.body.style.overflow = "hidden";
    var first = m.querySelector(".modal__close") || m.querySelector(FOCUSABLE);
    if (first) first.focus();
  }

  function closeModals() {
    var wasOpen = document.querySelector(".modal.is-open");
    document.querySelectorAll(".modal.is-open").forEach(function (m) { m.classList.remove("is-open"); });
    // Документ выгружаем, иначе он продолжает висеть в памяти вкладки
    var docFrame = document.querySelector("#doc-viewer iframe");
    if (docFrame && wasOpen && wasOpen.id === "doc-viewer") docFrame.src = "about:blank";
    document.body.style.overflow = "";
    if (wasOpen && openerBeforeModal) openerBeforeModal.focus();
    openerBeforeModal = null;
  }

  /* Не выпускает Tab за пределы открытого окна */
  function trapFocus(e) {
    if (e.key !== "Tab") return;
    var m = document.querySelector(".modal.is-open");
    if (!m) return;
    var items = Array.prototype.filter.call(
      m.querySelectorAll(FOCUSABLE),
      function (el) { return el.offsetParent !== null; }
    );
    if (!items.length) return;
    var first = items[0];
    var last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  document.querySelectorAll("[data-modal]").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      openModal(btn.getAttribute("data-modal"));
    });
  });
  document.querySelectorAll(".modal").forEach(function (m) {
    m.addEventListener("click", function (e) {
      if (e.target === m || e.target.closest(".modal__close")) closeModals();
    });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeModals();
    trapFocus(e);
  });

  /* Просмотр фотографий */
  var viewer = document.getElementById("photo-viewer");
  if (viewer) {
    var img = viewer.querySelector("img");
    document.querySelectorAll("[data-photo]").forEach(function (link) {
      link.addEventListener("click", function (e) {
        e.preventDefault();
        img.src = link.getAttribute("data-photo");
        img.alt = link.getAttribute("data-photo-alt") || "";
        openModal("photo-viewer");
      });
    });
  }

  /* Просмотр PDF прямо на странице, без скачивания. На узком экране
     встроенный просмотр мобильные браузеры не умеют — там ссылка
     открывает документ в новой вкладке, как и без скрипта. */
  var docViewer = document.getElementById("doc-viewer");
  if (docViewer) {
    var docFrame = docViewer.querySelector("iframe");
    var docTitle = docViewer.querySelector(".docview__title");
    var docTab = docViewer.querySelector("[data-doc-tab]");
    var wideScreen = window.matchMedia("(min-width: 861px)");
    document.addEventListener("click", function (e) {
      var link = e.target.closest("[data-doc-view]");
      if (!link || !wideScreen.matches || e.ctrlKey || e.metaKey || e.shiftKey) return;
      e.preventDefault();
      docFrame.src = link.getAttribute("href");
      docTab.href = link.getAttribute("href");
      docTitle.textContent = link.getAttribute("data-doc-title") || "";
      openModal("doc-viewer");
    });
  }

  /* Видео в шапке. Загружается после всей страницы, чтобы не отнимать канал
     у первого экрана, и только на широком экране без режима экономии трафика
     и без просьбы уменьшить анимацию. На телефоне остаётся картинка.
     Кнопка звука появляется, когда видео действительно играет. */
  var heroVideo = document.querySelector("[data-hero-video]");
  var soundBtn = document.querySelector("[data-hero-sound]");
  if (heroVideo) {
    var connection = navigator.connection || {};
    var wantVideo = heroVideo.hasAttribute("data-always") || (
      window.matchMedia("(min-width: 768px)").matches &&
      !window.matchMedia("(prefers-reduced-motion: reduce)").matches &&
      !connection.saveData && !/(^|-)2g$/.test(connection.effectiveType || ""));
    var startVideo = function () {
      heroVideo.addEventListener("playing", function () {
        heroVideo.classList.add("is-playing");
        if (soundBtn) soundBtn.hidden = false;
      }, { once: true });
      heroVideo.src = heroVideo.getAttribute("data-src");
      var played = heroVideo.play();
      if (played && played.catch) played.catch(function () { /* автозапуск запрещён — остаётся картинка */ });
    };
    if (wantVideo) {
      if (document.readyState === "complete") startVideo();
      else window.addEventListener("load", startVideo, { once: true });
    }
  }
  if (heroVideo && soundBtn) {
    soundBtn.addEventListener("click", function () {
      heroVideo.muted = !heroVideo.muted;
      var on = !heroVideo.muted;
      // Нажатие и есть разрешение на звук; play() — на случай, если браузер
      // приостановил ролик, когда в нём включили звук
      if (on && heroVideo.paused) heroVideo.play().catch(function () {});
      soundBtn.setAttribute("aria-pressed", on ? "true" : "false");
      soundBtn.setAttribute("aria-label", on ? "Выключить звук" : "Включить звук");
      soundBtn.querySelector("[data-sound-on]").hidden = !on;
      soundBtn.querySelector("[data-sound-off]").hidden = on;
    });
  }

  /* Кнопка «Наверх». Видна, когда страницу прокрутили больше чем на полтора
     экрана. С клавиатуры фокус переходит в начало страницы, чтобы следующий
     Tab шёл по шапке, а не продолжал с середины. При просьбе уменьшить
     анимацию прокрутка мгновенная. */
  var toTop = document.querySelector("[data-to-top]");
  if (toTop) {
    var toTopShown = false;
    var syncToTop = function () {
      var show = window.scrollY > window.innerHeight * 1.5;
      if (show === toTopShown) return;
      toTopShown = show;
      if (show) {
        toTop.hidden = false;
        window.requestAnimationFrame(function () { toTop.classList.add("is-visible"); });
      } else {
        toTop.classList.remove("is-visible");
        toTop.hidden = true;
      }
    };
    var toTopPending = false;
    window.addEventListener("scroll", function () {
      if (toTopPending) return;
      toTopPending = true;
      window.requestAnimationFrame(function () { toTopPending = false; syncToTop(); });
    }, { passive: true });
    syncToTop();
    toTop.addEventListener("click", function (e) {
      var still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      window.scrollTo({ top: 0, behavior: still ? "auto" : "smooth" });
      // e.detail === 0 — нажали клавишей, а не мышью
      if (e.detail === 0) {
        var first = document.querySelector(".logo");
        if (first) first.focus({ preventScroll: true });
      }
    });
  }

  /* Панель «Купить билет» внизу экрана на странице события (телефон).
     Видна, пока основная кнопка покупки за пределами экрана: выше — уже
     прокрутили её, ниже — ещё не дошли. Над панелью поднимается «Наверх». */
  var buybar = document.querySelector("[data-buybar]");
  var deal = document.querySelector(".event__deal");
  if (buybar && deal && "IntersectionObserver" in window) {
    var narrow = window.matchMedia("(max-width: 860px)");
    var dealVisible = true;
    var syncBuybar = function () {
      var show = narrow.matches && !dealVisible;
      buybar.hidden = !show;
      document.body.classList.toggle("has-buybar", show);
    };
    new IntersectionObserver(function (entries) {
      dealVisible = entries[0].isIntersecting;
      syncBuybar();
    }).observe(deal);
    if (narrow.addEventListener) narrow.addEventListener("change", syncBuybar);
  }

  /* Пауза бегущей ленты баннеров */
  document.querySelectorAll("[data-marquee-pause]").forEach(function (btn) {
    var strip = btn.parentNode.querySelector(".partners");
    if (!strip) return;
    btn.addEventListener("click", function () {
      var paused = strip.classList.toggle("is-paused");
      btn.textContent = paused ? "Запустить ленту" : "Остановить ленту";
    });
  });

  /* Пересчёт по прокрутке — не чаще одного раза за кадр */
  function onScrollFrame(el, fn) {
    var pending = false;
    el.addEventListener("scroll", function () {
      if (pending) return;
      pending = true;
      window.requestAnimationFrame(function () { pending = false; fn(); });
    });
    window.addEventListener("resize", fn);
    fn();
  }

  /* Календарь: стрелки и название месяца первого видимого дня */
  document.querySelectorAll("[data-cal]").forEach(function (cal) {
    var scroller = cal.querySelector("[data-cal-scroll]");
    var prev = cal.querySelector("[data-cal-prev]");
    var next = cal.querySelector("[data-cal-next]");
    var month = cal.querySelector("[data-cal-month]");

    function shift(direction) {
      scroller.scrollBy({ left: direction * scroller.clientWidth * 0.8, behavior: "smooth" });
    }
    prev.addEventListener("click", function () { shift(-1); });
    next.addEventListener("click", function () { shift(1); });

    var active = scroller.querySelector(".cal__day--active");
    if (active) {
      scroller.scrollLeft = active.getBoundingClientRect().left - scroller.getBoundingClientRect().left
        - scroller.clientWidth / 2;
    }

    onScrollFrame(scroller, function () {
      prev.disabled = scroller.scrollLeft <= 2;
      next.disabled = scroller.scrollLeft + scroller.clientWidth >= scroller.scrollWidth - 2;
      var edge = scroller.getBoundingClientRect().left + 4;
      for (var i = 0; i < scroller.children.length; i++) {
        var day = scroller.children[i];
        if (day.getBoundingClientRect().right > edge) {
          if (month.textContent !== day.getAttribute("data-month")) {
            month.textContent = day.getAttribute("data-month");
          }
          break;
        }
      }
    });
  });

  /* Автопрокрутка каруселей. Листает, только пока карусель на экране и вкладка
     открыта. Наведение мыши или фокус клавиатуры останавливают её, касание
     и стрелки откладывают следующий шаг. При «уменьшить движение» в системе —
     не листает вовсе. */
  var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function autoplay(box, advance, delay, extra) {
    if (reducedMotion) return;
    var hovered = false, focused = false, onScreen = true, timer = null;
    function restart() {
      clearInterval(timer);
      timer = setInterval(function () {
        if (!hovered && !focused && onScreen && !document.hidden) advance();
      }, delay);
    }
    // extra — стрелки вне ленты (в заголовке раздела): они ставят паузу и сбрасывают таймер так же
    [box, extra].forEach(function (el) {
      if (!el) return;
      el.addEventListener("mouseenter", function () { hovered = true; });
      el.addEventListener("mouseleave", function () { hovered = false; restart(); });
      el.addEventListener("focusin", function () { focused = true; });
      el.addEventListener("focusout", function () { focused = false; });
      el.addEventListener("pointerdown", restart);
      el.addEventListener("click", restart);
    });
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) {
        onScreen = entries[0].isIntersecting;
      }).observe(box);
    }
    restart();
  }

  /* Карусель фотографий здания */
  document.querySelectorAll("[data-carousel]").forEach(function (box) {
    var track = box.querySelector("[data-carousel-track]");
    var count = track.children.length;
    var dots = box.querySelectorAll("[data-carousel-dot]");
    if (count < 2) return;

    function current() { return Math.round(track.scrollLeft / track.clientWidth); }
    function go(i) {
      track.scrollTo({ left: ((i + count) % count) * track.clientWidth, behavior: "smooth" });
    }
    box.querySelector("[data-carousel-prev]").addEventListener("click", function () { go(current() - 1); });
    box.querySelector("[data-carousel-next]").addEventListener("click", function () { go(current() + 1); });
    dots.forEach(function (dot) {
      dot.addEventListener("click", function () { go(+dot.getAttribute("data-carousel-dot")); });
    });
    onScrollFrame(track, function () {
      var i = current();
      dots.forEach(function (dot, n) { dot.setAttribute("aria-current", n === i ? "true" : "false"); });
    });
    autoplay(box, function () { go(current() + 1); }, 5000);
  });

  /* Карусель карточек концертов. Стрелки листают на ширину ленты.
     С data-more у ленты, когда до конца остаётся меньше экрана,
     подгружаются следующие концерты; пустой ответ — афиша кончилась. */
  document.querySelectorAll("[data-ecarousel]").forEach(function (box) {
    var track = box.querySelector("[data-ecarousel-track]");
    // Стрелки стоят в заголовке раздела и связаны с лентой по id; запасной путь — внутри ленты
    var nav = (box.id && document.querySelector('[data-ecarousel-nav="' + box.id + '"]')) || box;
    var prev = nav.querySelector("[data-ecarousel-prev]");
    var next = nav.querySelector("[data-ecarousel-next]");
    if (!prev || !next) return;
    var moreUrl = box.getAttribute("data-more");
    var loading = false;

    function step() {
      var card = track.firstElementChild;
      if (!card) return track.clientWidth;
      var gap = parseFloat(getComputedStyle(track).columnGap) || 0;
      var perView = Math.max(1, Math.floor((track.clientWidth + gap) / (card.offsetWidth + gap)));
      return perView * (card.offsetWidth + gap);
    }

    function loadMore() {
      if (!moreUrl || loading || !window.fetch) return;
      loading = true;
      var sep = moreUrl.indexOf("?") < 0 ? "?" : "&";
      fetch(moreUrl + sep + "offset=" + track.children.length)
        .then(function (r) {
          if (!r.ok) throw new Error(r.status);
          return r.text();
        })
        .then(function (html) {
          var holder = document.createElement("div");
          holder.innerHTML = html;
          var added = holder.querySelectorAll(".ecard");
          if (!added.length) moreUrl = null;
          added.forEach(function (card) { track.appendChild(card); });
          bindYandex(track);
          loading = false;
          update();
        })
        .catch(function () { moreUrl = null; loading = false; });
    }

    function update() {
      prev.disabled = track.scrollLeft <= 2;
      var left = track.scrollWidth - track.clientWidth - track.scrollLeft;
      next.disabled = left <= 2 && !moreUrl;
      if (left < track.clientWidth) loadMore();
    }

    prev.addEventListener("click", function () { track.scrollBy({ left: -step(), behavior: "smooth" }); });
    next.addEventListener("click", function () { track.scrollBy({ left: step(), behavior: "smooth" }); });
    box.classList.add("is-ready");
    if (nav !== box) nav.hidden = false;
    onScrollFrame(track, update);

    // Дошли до конца и больше подгружать нечего — возвращаемся к началу
    autoplay(box, function () {
      var atEnd = track.scrollWidth - track.clientWidth - track.scrollLeft <= 2;
      if (atEnd && !moreUrl && !loading) {
        track.scrollTo({ left: 0, behavior: "smooth" });
      } else if (!atEnd) {
        track.scrollBy({ left: step(), behavior: "smooth" });
      }
    }, 6000, nav !== box ? nav : null);
  });

  /* Плавное появление разделов главной. Раздел, ушедший с экрана, снова
     прячется, чтобы появиться ещё раз — и при прокрутке вниз, и вверх. */
  var reveals = document.querySelectorAll("[data-reveal]");
  if (reveals.length && "IntersectionObserver" in window &&
      !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    root.classList.add("js-reveal");
    var revealer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        var el = entry.target;
        if (entry.isIntersecting) {
          el.classList.add("is-visible");
        } else {
          el.classList.remove("is-visible");
          // Ушёл вверх — при обратной прокрутке выедет сверху
          el.setAttribute("data-from", entry.boundingClientRect.top < 0 ? "above" : "below");
        }
      });
    }, { threshold: 0, rootMargin: "0px 0px -12% 0px" });
    reveals.forEach(function (el) { revealer.observe(el); });
  }

  /* Яндекс Афиша: ключ и регион приходят из «Настроек» атрибутами body.
     Скрипт продавца грузится один раз и только там, где есть что открывать:
     кнопка с ID сеанса или встроенный виджет (на «Интернет-приёмной» и других
     страницах он не нужен). Кнопка с ID открывает окно покупки, а без ключа
     остаётся обычной ссылкой. Кнопки, подгруженные позже (подбор маршрута,
     «Ещё концерты»), подключают скрипт в момент появления. */
  var yaKey = document.body.getAttribute("data-ya-key");
  var YA = "YandexTicketsDealer";
  var dealerLoaded = false;

  function loadDealer() {
    if (dealerLoaded || !yaKey) return;
    dealerLoaded = true;
    var dealer = window[YA] = window[YA] || [];
    dealer.push(["setDefaultClientKey", yaKey]);
    dealer.push(["setDefaultRegionId", +document.body.getAttribute("data-ya-region") || 12]);
    var yaScript = document.createElement("script");
    yaScript.async = true;
    yaScript.src = "https://widget.afisha.yandex.ru/dealer/dealer.js";
    document.head.appendChild(yaScript);
  }

  function bindYandex(scope) {
    if (!yaKey) return;
    var buttons = scope.querySelectorAll("[data-ya-session]:not([data-ya-bound])");
    if (buttons.length) loadDealer();
    buttons.forEach(function (btn) {
      btn.setAttribute("data-ya-bound", "");
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        var id = btn.getAttribute("data-ya-session");
        window[YA].push(["getDealer", function (dealer) { dealer.open({ id: id, type: "session" }); }]);
      });
    });
  }

  if (yaKey) {
    bindYandex(document);
    // Код, вставленный редактором (схема зала, страницы), может обращаться к скрипту продавца напрямую
    if (document.querySelector('[onclick*="' + YA + '"], #hall')) loadDealer();

    /* Встроенный виджет на странице события */
    document.querySelectorAll("[data-ya-widget]").forEach(function (section) {
      loadDealer();
      var frame = section.querySelector("[data-ya-widget-frame]");
      section.hidden = false;
      window[YA].push(["getDealer", function (d) {
        var widget = d.Widget(section.getAttribute("data-ya-widget"), "session", {
          target: frame,
          onRequestClose: function () { widget.unmount(); widget.destroy(); section.hidden = true; },
        });
        widget.mount({ style: { height: "600px" } });
      }]);
    });
  }

  /* Яндекс Метрика: номер счётчика — из «Настроек» атрибутом body.
     Подключается здесь, а не встроенным кодом: встроенные скрипты запрещены
     политикой безопасности. Визиты сотрудников не считаются (атрибута нет).
     Вебвизор (запись действий посетителя) выключен: это персональные данные.
     Метрика ставит cookie, поэтому запускается только после «Принять» в плашке
     внизу экрана. Выбор хранится в localStorage; пока выбора нет, ни скрипт
     Метрики, ни её cookie не появляются. */
  var metrikaId = +document.body.getAttribute("data-metrika");
  var CONSENT_KEY = "cookie-consent";

  function startMetrika() {
    window.ym = window.ym || function () { (window.ym.a = window.ym.a || []).push(arguments); };
    window.ym.l = Date.now();
    var ymScript = document.createElement("script");
    ymScript.async = true;
    ymScript.src = "https://mc.yandex.ru/metrika/tag.js";
    document.head.appendChild(ymScript);
    window.ym(metrikaId, "init", { clickmap: true, trackLinks: true, accurateTrackBounce: true });
  }

  if (metrikaId) {
    var consent = null;
    try { consent = localStorage.getItem(CONSENT_KEY); } catch (e) {}
    var cookieBar = document.querySelector("[data-cookie]");
    if (consent === "all") {
      startMetrika();
    } else if (consent !== "necessary" && cookieBar) {
      cookieBar.hidden = false;
      document.body.classList.add("has-cookie");
      var answer = function (choice) {
        try { localStorage.setItem(CONSENT_KEY, choice); } catch (e) {}
        cookieBar.hidden = true;
        document.body.classList.remove("has-cookie");
        // Нажатая кнопка исчезла — фокус переносим к содержимому, а не теряем на body
        var mainBlock = document.getElementById("main");
        if (mainBlock) { mainBlock.setAttribute("tabindex", "-1"); mainBlock.focus({ preventScroll: true }); }
        if (choice === "all") startMetrika();
      };
      cookieBar.querySelectorAll("[data-cookie-choice]").forEach(function (btn) {
        btn.addEventListener("click", function () { answer(btn.getAttribute("data-cookie-choice")); });
      });
    }
  }

  /* Музыкальный маршрут: вопросы по одному, подборка без перезагрузки.
     Без скрипта видны все три вопроса, и форма уходит на главную обычным запросом. */
  var routeForm = document.querySelector("[data-route]");
  var routeResult = document.querySelector("[data-route-result]");
  if (routeForm && routeResult && window.fetch && window.URLSearchParams) {
    var steps = routeForm.querySelectorAll("[data-route-step]");

    var showStep = function (index) {
      routeForm.classList.remove("is-done");
      steps.forEach(function (step, n) { step.classList.toggle("is-current", n === index); });
    };

    var bindReset = function () {
      var again = routeResult.querySelector("[data-route-reset]");
      if (!again) return;
      again.addEventListener("click", function (e) {
        e.preventDefault();
        routeForm.querySelectorAll("input:checked").forEach(function (input) { input.checked = false; });
        routeResult.innerHTML = "";
        showStep(0);
        window.history.replaceState(null, "", window.location.pathname + "#marshrut");
        steps[0].querySelector("input").focus();
      });
    };

    var submitRoute = function () {
      var query = new URLSearchParams(new FormData(routeForm)).toString();
      routeResult.innerHTML = '<p class="route__note">Подбираем концерты…</p>';
      fetch(routeForm.getAttribute("data-route-url") + "?" + query)
        .then(function (r) {
          if (!r.ok) throw new Error(r.status);
          return r.text();
        })
        .then(function (html) {
          routeResult.innerHTML = html;
          bindYandex(routeResult);
          routeForm.classList.add("is-done");
          bindReset();
          // Адрес с ответами можно отправить другу — подборка откроется сразу
          window.history.replaceState(null, "", window.location.pathname + "?" + query + "#marshrut");
          var title = routeResult.querySelector(".route__title");
          if (title) { title.setAttribute("tabindex", "-1"); title.focus(); }
        })
        .catch(function () { routeForm.submit(); });
    };

    routeForm.classList.add("route--steps");
    if (routeResult.textContent.trim()) {
      routeForm.classList.add("is-done");
      bindReset();
    } else {
      showStep(0);
    }

    steps.forEach(function (step, n) {
      step.addEventListener("change", function () {
        if (n < steps.length - 1) {
          showStep(n + 1);
          var first = steps[n + 1].querySelector("input");
          if (first) first.focus();
        } else {
          submitRoute();
        }
      });
    });
    routeForm.addEventListener("submit", function (e) {
      e.preventDefault();
      submitRoute();
    });
  }

  /* Анкеты на странице НОК: раскрываются по ссылке #anketa-<ключ>, после ошибки
     отправки прокручиваются к списку ошибок, считают отвеченные вопросы.
     Без скрипта анкета раскрывается кнопкой (details), а ошибка видна в раскрытой форме. */
  var surveyCards = document.querySelectorAll("[data-survey-card]");
  function openSurvey() {
    var target = document.getElementById((location.hash || "").slice(1));
    if (!target || target.tagName !== "SECTION") return;
    var card = target.querySelector("[data-survey-card]");
    // Ссылка после отправки ведёт к «Спасибо»: форму заново не раскрываем
    if (!card || card.hasAttribute("data-sent")) return;
    card.open = true;
    target.classList.add("is-open");
    target.scrollIntoView();
  }
  surveyCards.forEach(function (card) {
    card.addEventListener("toggle", function () {
      card.parentNode.classList.toggle("is-open", card.open);
    });
    var form = card.querySelector("[data-survey-form]");
    var progress = card.querySelector("[data-survey-progress]");
    if (form && progress) {
      var done = progress.querySelector("[data-done]");
      var count = function () {
        var names = {};
        form.querySelectorAll("input[type=radio]:checked").forEach(function (r) { names[r.name] = 1; });
        done.textContent = Object.keys(names).length;
      };
      form.addEventListener("change", count);
      count();
      progress.hidden = false;
    }
  });
  var surveyErrors = document.querySelector("[data-survey-errors]");
  if (surveyErrors) {
    surveyErrors.scrollIntoView();
    surveyErrors.focus();
  } else if (surveyCards.length) {
    openSurvey();
    window.addEventListener("hashchange", openSurvey);
  }

  /* Панель «Фильтры» афиши на телефоне */
  var filtersToggle = document.querySelector("[data-filters-toggle]");
  var filtersMore = document.querySelector("[data-filters-more]");
  if (filtersToggle && filtersMore) {
    filtersToggle.addEventListener("click", function () {
      var open = filtersMore.classList.toggle("is-open");
      filtersToggle.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) {
        var first = filtersMore.querySelector("select, input");
        if (first) first.focus();
      }
    });
  }

  /* Автоотправка фильтров афиши. На телефоне в раскрытой панели поля
     отправляются кнопкой «Показать»: иначе каждый выбор перезагружал бы
     страницу и сворачивал панель. Даты — только когда заполнены обе:
     выбор первой не должен перезагружать страницу до выбора второй. */
  document.querySelectorAll("[data-autosubmit]").forEach(function (el) {
    el.addEventListener("change", function () {
      if (filtersMore && filtersMore.classList.contains("is-open")) return;
      if (el.type === "date") {
        var pair = el.form.elements[el.name === "from" ? "to" : "from"];
        if (pair && !pair.value) return;
      }
      el.form.submit();
    });
  });
})();
