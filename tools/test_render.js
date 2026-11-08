/* Renders the synthetic fixture through report-core.js. No production report is loaded. */
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const root = path.join(__dirname, "..");
const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures/synthetic_week.json"), "utf8"));

function el() {
  return {
    innerHTML: "", textContent: "", hidden: false, className: "", id: "", children: [], style: {},
    appendChild(c) { this.children.push(c); return c; },
    setAttribute() {}, getAttribute() { return null; }, insertBefore() {},
    parentNode: { insertBefore() {}, appendChild() {} },
  };
}
const ids = {};
const document = {
  body: { getAttribute() { return null; }, classList: { contains() { return false; } } },
  getElementById(id) { return ids[id] || (ids[id] = el()); },
  createElement(tag) { const e = el(); e.tag = tag; return e; },
};
const context = { document, console };
context.window = context;
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root, "report-core.js"), "utf8"), context, { filename: "report-core.js" });
context.REPORTS = fixture.REPORTS;
context.initReport("best");

function fail(msg) { console.error("RENDER FAIL: " + msg); process.exit(1); }
function has(id) { return (ids[id] && ids[id].innerHTML) || ""; }
const kick = has("best-t-kick"), starters = has("best-t-starters"), def = has("best-t-def");
const flex = has("best-t-flex"), waiver = has("best-t-waiver"), bench = has("best-t-bench");
if (!kick.includes(">Weather<") || !starters.includes(">Weather<") || !def.includes(">Weather<") || !flex.includes(">Weather<")) fail("weather header missing");
if (!kick.includes(">FG made<") || !kick.includes(">Kicking pts<") || !kick.includes(">1.5<") || !kick.includes(">7.5<")) fail("kicker over/under columns missing");
if ((kick.match(/<tr>/g) || []).length !== 11) fail("kicker table should be 1 header + 10 rows");
if ((kick.match(/class="wx"/g) || []).length !== 10) fail("each kicker row needs a weather cell");
["(dome)", "(roof ?)", "(covered)", ">Bye<", "no obs", "(final)", "(kickoff)", "Madrid"].forEach(function (s) {
  if (!kick.includes(s)) fail("kicker table missing " + s);
});
if (!def.includes("no forecast") || !def.includes("(dome)")) fail("defense weather missing");
if (!waiver.includes("\u2014")) fail("waiver dash missing");
if (!starters.includes("Riley Sample") || !starters.includes("class=\"wx\"")) fail("starter weather cell missing");
if (kick.includes("odds") || starters.includes("playoff")) fail("weekly table picked up an odds chart");
const lineup = ids["best-lineup"];
if (!lineup || lineup.textContent.indexOf("Lineup optimal") < 0 || lineup.className.indexOf("success") < 0) fail("lineup banner missing");
if (!/pill success">K1</.test(kick)) fail("kicker FP rank not colored");
if (kick.includes("WaiverTarget")) fail("unexpected name");
if ((bench.match(/<tr>/g) || []).length < 2) fail("bench table missing");
console.log("render ok: 10 kickers, weather column, lineup banner");
