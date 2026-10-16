// Application shell: hash routing, sidebar, and pager. Loaded after all page modules.
(function () {
  var GROUPS = [
    { id: "start", title: "开始" },
    { id: "agent", title: "1 · Agent 运行主线" },
    { id: "system", title: "2 · 系统与数据流" },
    { id: "core", title: "3 · 运行时基础设施" },
    { id: "interview", title: "4 · 面试准备" },
    { id: "appendix", title: "附录 · 概念速查" },
  ];
  var pages = Site.pages;

  var esc = Site.esc;

  function groupTitle(id) {
    var found = GROUPS.filter(function (g) { return g.id === id; })[0];
    return found ? found.title : "";
  }

  function currentId() {
    var raw = (location.hash || "").replace(/^#\/?/, "");
    return raw || "home";
  }

  function renderNav(activeId) {
    var html = '<div class="brand">OpinionSearch 面试基础站</div>' +
      '<div class="brand-sub">从零理解一个可恢复的 Agent Runtime</div>';
    GROUPS.forEach(function (group) {
      var items = pages.filter(function (p) { return p.group === group.id; });
      if (!items.length) return;
      html += '<div class="nav-group">' + esc(group.title) + "</div>";
      items.forEach(function (p) {
        html += '<a class="nav-link' + (p.id === activeId ? " active" : "") +
          '" href="#/' + p.id + '">' + esc(p.title) + "</a>";
      });
    });
    document.getElementById("sidebar").innerHTML = html;
  }

  function renderDeep(page) {
    if (!page.deep || !page.deep.length) return "";
    return '<div class="deep"><strong>深入阅读：</strong>' +
      page.deep.map(function (d) {
        return '<a href="' + esc(d.href) + '" target="_blank" rel="noopener">' + esc(d.label) + "</a>";
      }).join("") + "</div>";
  }

  function renderPager(index) {
    var prev = pages[index - 1];
    var next = pages[index + 1];
    return '<div class="pager">' +
      (prev ? '<a href="#/' + prev.id + '">← ' + esc(prev.title) + "</a>" : "<span></span>") +
      (next ? '<a href="#/' + next.id + '">' + esc(next.title) + " →</a>" : "<span></span>") +
      "</div>";
  }

  function render() {
    var id = currentId();
    var index = pages.findIndex(function (p) { return p.id === id; });
    if (index < 0) index = 0;
    var page = pages[index];
    renderNav(page.id);

    var main = document.getElementById("main");
    main.innerHTML =
      '<div class="crumb">' + esc(groupTitle(page.group)) + "</div>" +
      "<h1>" + esc(page.title) + "</h1>" +
      (page.lead ? '<p class="lead">' + page.lead + "</p>" : "") +
      '<div id="content"></div>' +
      renderDeep(page) +
      renderPager(index);

    page.render(document.getElementById("content"));
    window.scrollTo(0, 0);
  }

  window.addEventListener("hashchange", render);
  document.addEventListener("DOMContentLoaded", render);
})();
