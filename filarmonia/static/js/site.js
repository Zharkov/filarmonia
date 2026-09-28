/* Сайт филармонии — клиентские скрипты. Зависимостей нет. */
(function () {
  "use strict";

  /* ---------- мобильное меню ---------- */
  var burger = document.querySelector("[data-burger]");
  var nav = document.querySelector("[data-nav]");
  if (burger && nav) {
    burger.addEventListener("click", function () {
      var open = nav.classList.toggle("is-open");
      burger.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  /* ---------- настройки для слабовидящих ---------- */
  var root = document.documentElement;
  var panel = document.querySelector("[data-a11y]");
  var toggle = document.querySelector("[data-a11y-toggle]");

  function applyStored() {
    try {
      var saved = JSON.parse(localStorage.getItem("a11y") || "{}");
      if (saved.size) root.setAttribute("data-size", saved.size);
      if (saved.theme) root.setAttribute("data-theme", saved.theme);
      if (saved.images) root.setAttribute("data-images", saved.images);
      syncButtons(saved);
    } catch (e) { /* localStorage может быть отключён */ }
  }

  function syncButtons(state) {
    document.querySelectorAll("[data-a11y-set]").forEach(function (btn) {
      var parts = btn.getAttribute("data-a11y-set").split(":");
      btn.setAttribute("aria-pressed", state[parts[0]] === parts[1] ? "true" : "false");
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

  /* ---------- всплывающие баннеры на афише (тач-устройства) ---------- */
  document.querySelectorAll(".pin").forEach(function (pin) {
    pin.addEventListener("click", function (e) {
      if (pin.tagName === "A") return;          // ссылка работает как ссылка
      e.stopPropagation();
      var open = pin.classList.contains("is-open");
      document.querySelectorAll(".pin.is-open").forEach(function (p) { p.classList.remove("is-open"); });
      if (!open) pin.classList.add("is-open");
    });
  });
  document.addEventListener("click", function () {
    document.querySelectorAll(".pin.is-open").forEach(function (p) { p.classList.remove("is-open"); });
  });

  /* ---------- модальные окна ---------- */
  function openModal(id) {
    var m = document.getElementById(id);
    if (m) { m.classList.add("is-open"); document.body.style.overflow = "hidden"; }
  }
  function closeModals() {
    document.querySelectorAll(".modal.is-open").forEach(function (m) { m.classList.remove("is-open"); });
    document.body.style.overflow = "";
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
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeModals(); });

  /* ---------- просмотр фотографий ---------- */
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

  /* ---------- видео в шапке: звук и пауза ---------- */
  var heroVideo = document.querySelector("[data-hero-video]");
  var soundBtn = document.querySelector("[data-hero-sound]");
  if (heroVideo && soundBtn) {
    soundBtn.addEventListener("click", function () {
      heroVideo.muted = !heroVideo.muted;
      soundBtn.textContent = heroVideo.muted ? "Включить звук" : "Выключить звук";
    });
  }
  if (heroVideo && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    heroVideo.pause();
  }

  /* ---------- автоотправка фильтров афиши ---------- */
  document.querySelectorAll("[data-autosubmit]").forEach(function (el) {
    el.addEventListener("change", function () { el.form.submit(); });
  });
})();
