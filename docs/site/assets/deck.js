(function () {
  function motionReduced() {
    if (document.documentElement.getAttribute("data-motion") === "reduce") return true;
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  var slides = Array.prototype.slice.call(document.querySelectorAll(".slide"));
  if (!slides.length) return;
  var index = 0;
  var label = document.getElementById("deck-index");
  var prev = document.getElementById("deck-prev");
  var next = document.getElementById("deck-next");

  function show(i) {
    index = Math.max(0, Math.min(slides.length - 1, i));
    slides.forEach(function (el, n) {
      el.classList.toggle("active", n === index);
    });
    if (label) label.textContent = index + 1 + " / " + slides.length;
    if (prev) prev.disabled = index === 0;
    if (next) next.disabled = index === slides.length - 1;
    if (location.hash !== "#/" + (index + 1)) {
      history.replaceState(null, "", "#/" + (index + 1));
    }
  }

  function fromHash() {
    var raw = (location.hash || "").replace(/^#\/?/, "");
    var n = parseInt(raw, 10);
    if (!n || n < 1) return 0;
    return n - 1;
  }

  if (prev) prev.addEventListener("click", function () { show(index - 1); });
  if (next) next.addEventListener("click", function () { show(index + 1); });

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "ArrowRight" || ev.key === "PageDown" || ev.key === " ") {
      ev.preventDefault();
      show(index + 1);
    } else if (ev.key === "ArrowLeft" || ev.key === "PageUp") {
      ev.preventDefault();
      show(index - 1);
    } else if (ev.key === "Home") {
      show(0);
    } else if (ev.key === "End") {
      show(slides.length - 1);
    }
  });

  window.addEventListener("hashchange", function () {
    show(fromHash());
  });

  if (motionReduced()) {
    document.documentElement.setAttribute("data-motion", "reduce");
  }

  show(fromHash());
})();
