(function () {
  function siteHref(path) {
    if (!path) return "";
    if (/^https?:/i.test(path) || path.charAt(0) === "/") return path;
    var base = "";
    var cfg = document.getElementById("__config");
    if (cfg) {
      try {
        var parsed = JSON.parse(cfg.textContent || "{}");
        base = parsed.base || "";
      } catch (err) {}
    }
    if (!base || base === ".") return path;
    return String(base).replace(/\/?$/, "/") + path;
  }
  function hrefOf(node) {
    if (!node || !node.data) return "";
    return node.data.href || (node.data.$href) || "";
  }
  function boot() {
    if (typeof $jit === "undefined" || !$jit.Hypertree) return;
    var widget = document.querySelector(".dhx-jit");
    var dataEl = document.querySelector(".dhx-jit__data");
    var stage = document.getElementById("dhx-jit-conceptual");
    if (!dataEl || !stage) return;
    if (stage.getAttribute("data-dhx-ready") === "1") return;
    var raw = dataEl.value || dataEl.textContent || "";
    var json;
    try { json = JSON.parse(raw); }
    catch (err) { return; }
    if (!json || !json.id) return;
    stage.setAttribute("data-dhx-ready", "1");
    var width = Math.max(stage.clientWidth || 0, 320);
    var height = Math.max(stage.clientHeight || 0, 380);
    var rootId = json.id;
    try {
      var ht = new $jit.Hypertree({
        injectInto: "dhx-jit-conceptual",
        width: width,
        height: height,
        Node: { dim: 8, color: "#3D7AEC", overridable: true },
        Edge: { lineWidth: 1.4, color: "#64748B", overridable: true },
        Events: {
          enable: true,
          onClick: function (node) {
            if (node && node.id) ht.onClick(node.id);
          }
        },
        onCreateLabel: function (dom, node) {
          var href = hrefOf(node);
          dom.innerHTML = "";
          if (href) {
            var link = document.createElement("a");
            link.className = "dhx-jit__link";
            link.href = siteHref(href);
            link.textContent = node.name;
            link.addEventListener("click", function (ev) {
              ev.stopPropagation();
            });
            dom.appendChild(link);
          } else {
            dom.textContent = node.name;
          }
          $jit.util.addEvent(dom, "click", function (ev) {
            if (href && ev.target && ev.target.tagName === "A") return;
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
      if (widget) {
        var reset = widget.querySelector(".dhx-jit__reset");
        if (reset && reset.getAttribute("data-dhx-bound") !== "1") {
          reset.setAttribute("data-dhx-bound", "1");
          reset.addEventListener("click", function () {
            ht.onClick(rootId);
          });
        }
      }
    } catch (err) {
      stage.removeAttribute("data-dhx-ready");
    }
  }
  document.addEventListener("DOMContentLoaded", boot);
  if (typeof document$ !== "undefined" && document$.subscribe) {
    document$.subscribe(boot);
  }
})();
