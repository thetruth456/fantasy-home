/* Renders synthetic power and luck snapshots. No league file is loaded. */
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const root = path.join(__dirname, "..");

function fail(msg) { console.error("VIEW FAIL: " + msg); process.exit(1); }
function load(file) {
  const context = { console, Date, Intl, JSON, Math, addEventListener() {}, innerWidth: 1200 };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(root, file), "utf8"), context, { filename: file });
  return context;
}

const power = load("power.js");
const luck = load("podcast.js");
["power.js", "podcast.js"].forEach(function (f) {
  const src = fs.readFileSync(path.join(root, f), "utf8");
  if (src.includes("kfelder")) fail(f + " names Kyle");
});

function team(rid, name, extra) {
  return Object.assign({
    rid: rid, name: name, user: "u" + rid, w: rid === 1 ? 6 : 4, l: rid === 1 ? 2 : 4, t: 0,
    playoff: rid === 1 ? 70 : 40, bye: 10, first: 8, title: 4, ap: 55, strength: rid === 1 ? 115 : 109,
    pf: 900, pwins: 8, games: 14, sos: 105, po_neutral: 48,
    left: [{ week: 10, opp: rid === 1 ? 2 : 1, mu: 100 }], avgfin: 4, rank: rid, power: 50,
  }, extra || {});
}
const base = {
  key: "best", title: "Best League", nbye: 2, nteams: 2, nplay: 6, cur: 10, reg_end: 14, last: 9,
  sims: 1000, asof: "2026-11-15T00:00:00Z", g0: 7, pstart: 15, end: 17,
  pw: { strength: 0.4, playoff: 0.3, first: 0.15, title: 0.15 },
  beta0: 0.51, beta_now: 0.74, sd_noise: 12, tau_now: 4.2, keepers_n: 0,
  inj_hazard: { RB: 0.05 }, cal: { source: "own", n: 48, seasons: ["Best League 2025", "Best League 2022"] },
  recs: { "1": [[6, 2, 0]], "2": [[4, 4, 0]] },
  hist: [
    { week: 8, po: { "1": 40, "2": 60 }, bye: { "1": 10, "2": 20 }, st: { "1": 100, "2": 120 } },
    { week: 9, po: { "1": 45, "2": 55 }, bye: { "1": 12, "2": 18 }, st: { "1": 108, "2": 112 } },
    { week: 10, live: true, po: { "1": 70, "2": 40 }, bye: { "1": 10, "2": 10 }, st: { "1": 115, "2": 109 } },
  ],
  stake: { "1": { opp: 2, win: 80.5, loss: 40.1 }, "2": { opp: 1, win: 55, loss: 20 } },
  teams: [team(1, "Free Aaron"), team(2, "Cooked")],
};
const html = power.buildPower(base);
if (html.indexOf("Odds through the season") < 0) fail("odds chart missing");
if (html.indexOf("Odds through the season") > html.indexOf("at stake this week")) fail("odds chart is no longer first");
if (html.indexOf("Methodology") > html.indexOf("at stake this week")) fail("stake table is not below the existing sections");
if (!html.includes("Free Aaron (6-2)")) fail("record-next-to-name missing");
if (!html.includes("80.5%") || !html.includes("40.1%")) fail("win and loss odds missing");
if (html.indexOf("at stake this week") > html.indexOf("Strength trend")) fail("trend should follow the stake table");
if (!html.includes("polyline") || !html.includes("115.0")) fail("strength sparkline missing");
if (html.includes("(you)") || html.includes('class="you"') || html.includes("kfelder")) fail("power page highlighted Kyle");
const over = power.buildPower(Object.assign({}, base, { cur: 15, reg_end: 14 }));
if (over.includes("at stake this week")) fail("stake table should hide after the regular season");
const noTrend = power.buildPower(Object.assign({}, base, { hist: base.hist.map(function (h) { const c = Object.assign({}, h); delete c.st; return c; }) }));
if (noTrend.includes("Strength trend")) fail("trend should hide without a series");

function luckTeam(rid, name) {
  return {
    rid: rid, name: name, user: "u" + rid, w: 6, l: 3, t: 0, pf: 800, pa: 700,
    apw: 40, apl: 20, apt: 0, xw: 4.5, luck: rid === 1 ? 1.5 : -0.4, idx: rid === 1 ? 1 : -0.2,
    cw: 1, cl: 0, dip: 1, top: 0, bottom: 0, inj_games: 2, inj_bill: rid === 1 ? 10 : 40,
    inj_early: 0, inj_games_so: 2, inj_bill_so: 10, inj_games_co: 0, inj_bill_co: 0,
    bye_gain: 5, bye_wins: 0, rank: rid,
  };
}
const luckHtml = luck.buildPodcast({
  title: "Best League", weeks: [1, 9], asof: "2026-11-15T00:00:00Z", close_margin: 10, cur: 10, end: 17,
  teams: [luckTeam(1, "Free Aaron"), luckTeam(2, "Cooked")],
  players: [], trades: [], games: [],
  swap: { "1": { "1": [6, 3, 0], "2": [5, 3, 0] }, "2": { "1": [4, 4, 0], "2": [6, 3, 0] } },
  allplay: { weeks: [1, 9], n: 9, rec: { "1": [60, 30, 0], "2": [40, 50, 0] } },
  bench: { "1": { left: 210.5, opt: 1000, actual: 900, gap: 100 }, "2": { left: 80, opt: 820, actual: 800, gap: 20 } },
});
if (luckHtml.indexOf("Methodology") > luckHtml.indexOf("Schedule swap")) fail("swap grid is not below the existing sections");
if (!luckHtml.includes("6-3") || !luckHtml.includes('class="own"')) fail("swap grid missing");
if (luckHtml.indexOf("Schedule swap") > luckHtml.indexOf("All-play record")) fail("all-play should follow the swap grid");
if (!luckHtml.includes("60-30") || !luckHtml.includes("Weeks 1–9")) fail("all-play record missing");
if (!luckHtml.includes("Bench points") || !luckHtml.includes("210.5") || !luckHtml.includes("100.0")) fail("bench gap missing");
if (luckHtml.includes("(you)") || luckHtml.includes('class="you"') || luckHtml.includes("kfelder")) fail("luck page highlighted Kyle");
if (luckHtml.includes("Odds through")) fail("luck page picked up the odds chart");
console.log("views ok: stake, trend, swap, all-play, bench");
