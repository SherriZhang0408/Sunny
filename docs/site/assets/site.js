(function () {
  var printButton = document.querySelector("[data-print]");
  if (printButton) {
    printButton.addEventListener("click", function () {
      window.print();
    });
  }

  var toc = document.querySelector(".toc");
  if (!toc) return;
  var links = Array.prototype.slice.call(toc.querySelectorAll('a[href^="#"]'));
  var sections = links
    .map(function (a) { return document.getElementById((a.getAttribute("href") || "").slice(1)); })
    .filter(Boolean);
  if (!sections.length) return;

  function setCurrent(id) {
    links.forEach(function (a) {
      var on = a.getAttribute("href") === "#" + id;
      if (on) a.setAttribute("aria-current", "true");
      else a.removeAttribute("aria-current");
    });
  }

  var hash = (location.hash || "").replace(/^#/, "");
  if (hash) setCurrent(hash);

  if (!("IntersectionObserver" in window)) return;
  var io = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) setCurrent(entry.target.id);
      });
    },
    { rootMargin: "-18% 0px -72% 0px", threshold: 0 }
  );
  sections.forEach(function (el) { io.observe(el); });
})();
