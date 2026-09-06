(function () {
  function boot() {
    if (typeof $jit === "undefined" || !$jit.Hypertree) return;
    var dataEl = document.getElementById("dhx-jit-conceptual-data");
    var stage = document.getElementById("dhx-jit-conceptual");
    if (!dataEl || !stage) return;
    if (stage.getAttribute("data-dhx-ready") === "1") return;
    var json;
    try { json = JSON.parse(dataEl.textContent || ""); }
    catch (err) { return; }
    if (!json || !json.id) return;
    stage.setAttribute("data-dhx-ready", "1");
    var width = Math.max(stage.clientWidth || 0, 320);
    var height = Math.max(stage.clientHeight || 0, 380);
    var ht = new $jit.Hypertree({
      injectInto: "dhx-jit-conceptual",
      width: width,
      height: height,
      Node: { dim: 8, color: "#3D7AEC", overridable: true },
      Edge: { lineWidth: 1.4, color: "#64748B", overridable: true },
      onCreateLabel: function (dom, node) {
        dom.innerHTML = node.name;
        $jit.util.addEvent(dom, "click", function () {
          ht.onClick(node.id);
        });
      },
      onPlaceLabel: function (dom, node) {
        var style = dom.style;
        style.display = "";
        style.cursor = "pointer";
        if (node._depth <= 1) {
          style.fontSize = "0.85rem";
          style.color = "var(--md-default-fg-color)";
        } else if (node._depth === 2) {
          style.fontSize = "0.75rem";
          style.color = "var(--md-default-fg-color--light)";
        } else {
          style.display = "none";
        }
        var left = parseInt(style.left, 10) || 0;
        style.left = (left - (dom.offsetWidth || 0) / 2) + "px";
      }
    });
    ht.loadJSON(json);
    ht.refresh();
  }
  document.addEventListener("DOMContentLoaded", boot);
  if (typeof document$ !== "undefined" && document$.subscribe) {
    document$.subscribe(boot);
  }
})();
