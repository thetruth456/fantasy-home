/* Behavior of refresh-rank.js: buttons land on Power and Luck only, the token stays in
   localStorage, and a successful dispatch redraws both tabs. No weekly-report password. */
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const root = path.join(__dirname, "..");
const src = fs.readFileSync(path.join(root, "refresh-rank.js"), "utf8");
const refreshSrc = fs.readFileSync(path.join(root, "refresh.js"), "utf8");

function fail(msg) { console.error("RANK FAIL: " + msg); process.exit(1); }
if (!refreshSrc.includes('new Event("fh-token")')) fail("refresh.js does not announce token changes");
if (/github_pat_[A-Za-z0-9]{10,}/.test(src) || /ghp_[A-Za-z0-9]{10,}/.test(src)) fail("a token is hardcoded");
["FH_REPORT_PASSWORD", "fhUnseal", "buildPowerOdds", "kfelder", "lock.json", "-report.js"].forEach(function (s) {
  if (src.includes(s)) fail("refresh-rank.js contains " + s);
});
if (!src.includes("fh_gh_token") || !src.includes("rankings.yml") || !src.includes("localStorage")) fail("auth wiring missing");

function hasClass(node, c) { return (" " + (node.className || "") + " ").indexOf(" " + c + " ") >= 0; }
function addClass(node, c) { if (!hasClass(node, c)) node.className = ((node.className || "") + " " + c).trim(); }
function removeClass(node, c) {
  node.className = (node.className || "").split(/\s+/).filter(function (x) { return x && x !== c; }).join(" ");
}
function matches(node, sel) {
  if (sel.charAt(0) === "#") return node.id === sel.slice(1);
  if (sel.indexOf("[id$=") === 0) {
    var suf = sel.slice(6, -2);
    return !!node.id && node.id.slice(-suf.length) === suf;
  }
  var dot = sel.indexOf(".");
  if (dot === 0) return hasClass(node, sel.slice(1));
  if (dot > 0) return node.tag === sel.slice(0, dot) && hasClass(node, sel.slice(dot + 1));
  return node.tag === sel;
}
function walk(node, fn) {
  fn(node);
  (node.children || []).forEach(function (c) { walk(c, fn); });
}
function make(tag) {
  var node = {
    tag: tag, children: [], className: "", id: "", textContent: "", innerHTML: "", hidden: false,
    disabled: false, value: "", title: "", type: "", attrs: {}, listeners: {}, parentNode: null,
  };
  node.classList = {
    contains: function (c) { return hasClass(node, c); },
    add: function (c) { addClass(node, c); },
    remove: function (c) { removeClass(node, c); },
    toggle: function (c, force) {
      var has = hasClass(node, c);
      var on = arguments.length < 2 ? !has : !!force;
      if (on) addClass(node, c); else removeClass(node, c);
      return on;
    },
  };
  node.setAttribute = function (k, v) { node.attrs[k] = String(v); };
  node.getAttribute = function (k) { return Object.prototype.hasOwnProperty.call(node.attrs, k) ? node.attrs[k] : null; };
  node.removeAttribute = function (k) { delete node.attrs[k]; };
  node.addEventListener = function (type, fn) { (node.listeners[type] = node.listeners[type] || []).push(fn); };
  node.appendChild = function (c) { c.parentNode = node; node.children.push(c); return c; };
  node.insertBefore = function (c, before) {
    c.parentNode = node;
    if (!before) { node.children.push(c); return c; }
    var i = node.children.indexOf(before);
    if (i < 0) node.children.push(c); else node.children.splice(i, 0, c);
    return c;
  };
  node.focus = function () { node.focused = true; };
  node.querySelectorAll = function (sel) {
    var out = [];
    walk(node, function (n) { if (n !== node && matches(n, sel)) out.push(n); });
    return out;
  };
  node.querySelector = function (sel) { return node.querySelectorAll(sel)[0] || null; };
  Object.defineProperty(node, "firstChild", { get: function () { return node.children[0] || null; } });
  Object.defineProperty(node, "nextSibling", { get: function () {
    if (!node.parentNode) return null;
    var i = node.parentNode.children.indexOf(node);
    return i >= 0 ? node.parentNode.children[i + 1] || null : null;
  } });
  return node;
}
function findId(node, id) {
  if (node.id === id) return node;
  for (var i = 0; i < (node.children || []).length; i++) {
    var f = findId(node.children[i], id);
    if (f) return f;
  }
  return null;
}
function fire(node, type) {
  var ls = (node.listeners && node.listeners[type]) || [];
  for (var i = 0; i < ls.length; i++) ls[i].call(node, { preventDefault: function () {} });
}

function boot(opts) {
  var store = {};
  if (opts.token) store.fh_gh_token = opts.token;
  var localStorage = {
    getItem: function (k) { return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; },
    setItem: function (k, v) { store[k] = String(v); },
    removeItem: function (k) { delete store[k]; },
  };
  var winListeners = {};
  var body = make("body");
  var header = make("header");
  header.className = "site";
  var wrap = make("div");
  wrap.className = "wrap";
  ["power", "podcast", "report"].forEach(function (view) {
    var box = make("div");
    box.id = "best-view-" + view;
    box.className = "view" + (view === "report" ? " rep" : "");
    if (view !== "report") {
      var inner = make("div");
      inner.id = "best-" + (view === "power" ? "power" : "podcast");
      box.appendChild(inner);
    }
    wrap.appendChild(box);
  });
  body.appendChild(header);
  body.appendChild(wrap);
  var document = make("#document");
  document.appendChild(body);
  document.body = body;
  document.createElement = function (tag) { return make(tag); };
  document.createElementNS = function (ns, tag) { return make(tag); };
  document.createTextNode = function (s) { var n = make("#text"); n.textContent = s; return n; };
  document.getElementById = function (id) { return findId(document, id); };
  var calls = [];
  var context = {
    document: document, console: console, localStorage: localStorage, setTimeout: setTimeout, clearTimeout: clearTimeout,
    Date: Date, Promise: Promise, Intl: Intl, JSON: JSON, Error: Error, fetch: opts.fetch(calls),
    Event: function Event(type) { this.type = type; },
    addEventListener: function (type, fn) { (winListeners[type] = winListeners[type] || []).push(fn); },
    dispatchEvent: function (ev) { (winListeners[ev.type] || []).forEach(function (fn) { fn(ev); }); return true; },
    POWER: { best: { asof: "2026-11-02T00:00:00Z", key: "best" } },
    PODCAST: { best: { asof: "2026-11-02T00:00:00Z", key: "best" } },
    buildPower: function (D) { return "POWER " + D.asof; },
    buildPodcast: function (D) { return "LUCK " + D.asof; },
    FH_RANK_POLL_MS: 0,
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(src, context, { filename: "refresh-rank.js" });
  context.__calls = calls;
  context.__store = store;
  context.__fire = fire;
  return context;
}

function response(status, body, raw) {
  var text = raw ? body : (typeof body === "string" ? body : JSON.stringify(body));
  return {
    ok: status >= 200 && status < 300,
    status: status,
    headers: { get: function () { return null; } },
    text: function () { return Promise.resolve(text); },
    json: function () { return Promise.resolve(typeof body === "string" ? JSON.parse(body || "null") : body); },
  };
}
function fileText(url) {
  var m = /\/contents\/([a-z]+)-(power|podcast)-data\.js/.exec(url);
  if (!m) throw new Error("unexpected url " + url);
  var ns = m[2] === "power" ? "POWER" : "PODCAST";
  var obj = { asof: "2026-11-11T18:30:00Z", key: m[1] };
  return "/* t */\nwindow." + ns + "=window." + ns + "||{};\nwindow." + ns + "[" + JSON.stringify(m[1]) + "]=" + JSON.stringify(obj) + ";\n";
}
function waitFor(pred, label) {
  return new Promise(function (resolve, reject) {
    var n = 0;
    (function tick() {
      var err = null, ok = false;
      try { ok = pred(); } catch (e) { err = e; }
      if (err) return reject(err);
      if (ok) return resolve();
      if (++n > 100) return reject(new Error("timed out: " + label));
      setTimeout(tick, 10);
    })();
  });
}

const TOKEN = "github_pat_" + "a".repeat(22);

const empty = boot({
  fetch: function () { return function () { fail("fetch before a token was saved"); }; },
});
const powerBtn = empty.document.getElementById("best-view-power").querySelector(".rank-btn");
const luckBtn = empty.document.getElementById("best-view-podcast").querySelector(".rank-btn");
const report = empty.document.getElementById("best-view-report");
if (!powerBtn || !luckBtn) fail("Refresh missing on Power or Luck");
if (powerBtn.querySelector(".lbl").textContent !== "Refresh") fail("button label");
if (report.querySelector(".rank-btn")) fail("Refresh landed on the weekly report");
if (empty.document.querySelectorAll(".rank-btn").length !== 2) fail("expected one button on Power and one on Luck");
if (!empty.document.getElementById("rank-token").hidden) fail("token panel should start hidden");
empty.__fire(powerBtn, "click");
if (empty.document.getElementById("rank-token").hidden) fail("click without a token should open the panel");
empty.document.getElementById("rank-token-input").value = "nope";
empty.__fire(empty.document.getElementById("rank-token-form"), "submit");
if (empty.document.getElementById("rank-token-msg").textContent.indexOf("github_pat_") < 0) fail("bad token was accepted");
if (empty.__store.fh_gh_token) fail("bad token was stored");

let dispatched = false;
const ctx = boot({
  token: TOKEN,
  fetch: function (calls) {
    return function (url, opts) {
      calls.push({ url: url, method: (opts && opts.method) || "GET", headers: (opts && opts.headers) || {}, body: opts && opts.body });
      if (String(url).indexOf("-report.js") >= 0) fail("refresh asked for a weekly report");
      if (String(url).indexOf("/dispatches") >= 0) {
        dispatched = true;
        return Promise.resolve(response(204, ""));
      }
      if (String(url).indexOf("/contents/") >= 0) return Promise.resolve(response(200, fileText(url), true));
      if (String(url).indexOf("/runs") >= 0) {
        var runs = dispatched
          ? { workflow_runs: [{ id: 9, status: "completed", conclusion: "success", html_url: "https://example.test/run/9" }] }
          : { workflow_runs: [{ id: 3, status: "completed", conclusion: "success", html_url: "https://example.test/run/3" }] };
        return Promise.resolve(response(200, runs));
      }
      return Promise.resolve(response(404, { message: "no" }));
    };
  },
});
if (ctx.document.getElementById("best-view-podcast").querySelector(".rank-forget").hidden) fail("saved token should offer Forget");
ctx.__fire(ctx.document.getElementById("best-view-podcast").querySelector(".rank-btn"), "click");

const denied = boot({
  token: TOKEN,
  fetch: function (calls) {
    return function (url, opts) {
      calls.push(url);
      return Promise.resolve(response(401, { message: "bad" }));
    };
  },
});
denied.__fire(denied.document.getElementById("best-view-power").querySelector(".rank-btn"), "click");

Promise.all([
  waitFor(function () {
    return ctx.document.querySelector(".rank-status").textContent.indexOf("Power rankings and luck refreshed") >= 0;
  }, "success status"),
  waitFor(function () {
    return denied.document.querySelector(".rank-status").textContent.indexOf("GitHub rejected the token") >= 0;
  }, "401 status"),
]).then(function () {
  var post = ctx.__calls.filter(function (c) { return c.method === "POST"; })[0];
  if (!post || post.url.indexOf("/actions/workflows/rankings.yml/dispatches") < 0) fail("did not dispatch rankings.yml");
  if (post.body !== '{"ref":"main"}') fail("dispatch body " + post.body);
  if (post.headers.Authorization !== "Bearer " + TOKEN) fail("token was not sent only as a bearer header");
  if (ctx.document.getElementById("best-power").innerHTML !== "POWER 2026-11-11T18:30:00Z") fail("power tab did not redraw");
  if (ctx.document.getElementById("best-podcast").innerHTML !== "LUCK 2026-11-11T18:30:00Z") fail("luck tab did not redraw");
  if (!ctx.POWER.zbt || ctx.POWER.zbt.asof !== "2026-11-11T18:30:00Z") fail("other leagues were not loaded");
  if (ctx.document.querySelector(".rank-status").textContent.indexOf("nothing newer") >= 0) fail("fresh data looked stale");
  if (ctx.document.querySelector(".rank-btn").querySelector(".lbl").textContent !== "Refresh") fail("button stayed busy");
  var files = ctx.__calls.filter(function (c) { return String(c.url).indexOf("/contents/") >= 0; }).map(function (c) { return c.url; });
  ["best", "zbt", "oops", "spacex"].forEach(function (k) {
    if (!files.some(function (u) { return u.indexOf(k + "-power-data.js") >= 0; })) fail("missing power file " + k);
    if (!files.some(function (u) { return u.indexOf(k + "-podcast-data.js") >= 0; })) fail("missing luck file " + k);
  });
  ctx.__fire(ctx.document.querySelector(".rank-forget"), "click");
  if (ctx.__store.fh_gh_token) fail("Forget did not clear the token");
  if (denied.__store.fh_gh_token) fail("401 did not clear the token");
  if (denied.document.getElementById("rank-token").hidden) fail("401 should ask for a new token");
  console.log("rank refresh ok");
}).catch(function (e) {
  fail(e && e.stack ? e.stack : String(e));
});
