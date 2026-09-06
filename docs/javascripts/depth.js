(function () {
  var DEFAULT_DEPTH = 5;
  var STORAGE_KEY = "dhx-depth";
  var LABELS = {
    1: "Adopter",
    2: "Evaluator",
    3: "Operator",
    4: "Integrator",
    5: "Programmer",
    6: "Maintainer",
    7: "Internals"
  };

  function apply(depth) {
    var n = Math.min(7, Math.max(1, depth));
    document.documentElement.setAttribute("data-dhx-depth", String(n));
    document.querySelectorAll(".dhx-layer").forEach(function (el) {
      var min = Number(el.getAttribute("data-min") || "1");
      el.hidden = min > n;
    });
    var out = document.getElementById("dhx-depth-label");
    if (out) out.textContent = n + "/7 " + (LABELS[n] || "");
    try { localStorage.setItem(STORAGE_KEY, String(n)); } catch (err) {}
  }

  function mount() {
    var header = document.querySelector(".md-header__inner");
    if (!header || document.getElementById("dhx-depth")) return;
    var wrap = document.createElement("div");
    wrap.id = "dhx-depth";
    wrap.className = "dhx-depth";
    wrap.innerHTML =
      '<label class="dhx-depth__label" for="dhx-depth-range">Depth</label>' +
      '<input id="dhx-depth-range" class="dhx-depth__range" type="range" min="1" max="7" step="1">' +
      '<span id="dhx-depth-label" class="dhx-depth__value"></span>';
    header.appendChild(wrap);
    var input = wrap.querySelector("input");
    var start = DEFAULT_DEPTH;
    try {
      var saved = localStorage.getItem(STORAGE_KEY);
      if (saved) start = Number(saved);
    } catch (err) {}
    input.value = String(start);
    input.addEventListener("input", function () { apply(Number(input.value)); });
    apply(start);
  }

  document.addEventListener("DOMContentLoaded", mount);
  if (typeof document$ !== "undefined" && document$.subscribe) {
    document$.subscribe(mount);
  }
})();
