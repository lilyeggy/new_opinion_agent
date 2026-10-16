// SVG builders shared by all diagram pages. Each builder returns a string of
// markup; clickable nodes carry data-key so app.js can show their details.
(function () {
  function esc(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function wrap(width, height, inner) {
    return (
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + width + " " + height +
      '" width="' + width + '" role="img">' +
      '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" ' +
      'markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#7d8698"/>' +
      "</marker></defs>" +
      inner +
      "</svg>"
    );
  }

  function box(opts) {
    var x = opts.x, y = opts.y, w = opts.w || 180, h = opts.h || 56;
    var cls = ["node"];
    if (opts.cls) cls.push(opts.cls);
    var key = opts.key ? ' data-key="' + esc(opts.key) + '"' : "";
    var sub = opts.sub
      ? '<text class="node-sub" x="' + (x + w / 2) + '" y="' + (y + h / 2 + 15) +
        '" text-anchor="middle">' + esc(opts.sub) + "</text>"
      : "";
    var titleY = opts.sub ? y + h / 2 - 2 : y + h / 2 + 5;
    return (
      '<g class="' + cls.join(" ") + '"' + key + ">" +
      '<rect x="' + x + '" y="' + y + '" width="' + w + '" height="' + h +
      '" rx="8" fill="' + (opts.fill || "#ffffff") + '" stroke="' + (opts.stroke || "#b9c2d0") +
      '" stroke-width="1.4"/>' +
      '<text class="node-title" x="' + (x + w / 2) + '" y="' + titleY +
      '" text-anchor="middle">' + esc(opts.title) + "</text>" + sub + "</g>"
    );
  }

  function zone(opts) {
    return (
      '<rect class="zone" x="' + opts.x + '" y="' + opts.y + '" width="' + opts.w +
      '" height="' + opts.h + '" rx="12"/>' +
      '<text class="zone-title" x="' + (opts.x + 12) + '" y="' + (opts.y + 18) + '">' +
      esc(opts.title) + "</text>"
    );
  }

  // points: array of [x, y]; label is placed near the midpoint of the first segment's end.
  function line(points, opts) {
    opts = opts || {};
    var d = points
      .map(function (p, i) { return (i ? "L " : "M ") + p[0] + " " + p[1]; })
      .join(" ");
    var cls = "edge" + (opts.dashed ? " dashed" : "") + (opts.cp ? " cp" : "");
    var out = '<path class="' + cls + '" d="' + d + '"/>';
    if (opts.label) {
      var a = points[Math.floor(points.length / 2) - 1] || points[0];
      var b = points[Math.floor(points.length / 2)] || points[points.length - 1];
      var lx = (a[0] + b[0]) / 2 + (opts.dx || 6);
      var ly = (a[1] + b[1]) / 2 + (opts.dy || -6);
      out += '<text class="lbl" x="' + lx + '" y="' + ly + '">' + esc(opts.label) + "</text>";
    }
    return out;
  }

  function checkpoint(x, y, label) {
    return (
      '<g><circle class="cp-mark" cx="' + x + '" cy="' + y + '" r="6"/>' +
      '<text class="lbl" x="' + (x + 9) + '" y="' + (y + 4) + '">' + esc(label || "checkpoint") +
      "</text></g>"
    );
  }

  function text(x, y, value, cls) {
    return '<text class="' + (cls || "lbl") + '" x="' + x + '" y="' + y + '">' + esc(value) + "</text>";
  }

  window.Svg = { esc: esc, wrap: wrap, box: box, zone: zone, line: line, checkpoint: checkpoint, text: text };
})();
