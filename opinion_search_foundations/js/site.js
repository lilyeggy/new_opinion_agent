// Page registry and shared helpers. Loaded before every page module, because
// page modules register themselves and build some detail text at load time.
(function () {
  var pages = [];

  function esc(text) { return Svg.esc(text); }

  function codeEntry(path) {
    var entries = (window.CODE_MAP || []).filter(function (e) { return e.path === path; });
    return entries[0] || null;
  }

  function codeLine(path) {
    var entry = codeEntry(path);
    var lines = entry ? entry.lines + " 行" : "文件不存在于生成清单";
    return '<div class="path">opinion_search_agent/src/opinion_search/' + esc(path) + " · " + lines + "</div>";
  }

  // Binds click-to-detail on every element with data-key inside root.
  // details: { key: html }. The first entry is shown on load.
  function bindNodes(root, details, panel) {
    var keys = Object.keys(details);
    function show(key) {
      root.querySelectorAll("[data-key]").forEach(function (node) {
        node.classList.toggle("selected", node.getAttribute("data-key") === key);
      });
      panel.innerHTML = details[key] || "";
    }
    root.addEventListener("click", function (event) {
      var node = event.target.closest("[data-key]");
      if (node && root.contains(node)) show(node.getAttribute("data-key"));
    });
    if (keys.length) show(keys[0]);
  }

  window.Site = {
    pages: pages,
    register: function (page) { pages.push(page); },
    bindNodes: bindNodes,
    codeEntry: codeEntry,
    codeLine: codeLine,
    esc: esc,
  };
})();
