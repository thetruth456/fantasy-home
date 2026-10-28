/* Shared report renderer. Each league file sets window.REPORTS[key] = {STARTERS, BENCH, WAIVER}; call initReport(key). */
(function(){
var COLS=["Slot","Player","Pos","Opponent","Prop-implied pts","Sleeper proj","FP rank","Status","Rush yds line","Rec yds line","Rec line","Anytime TD (DK)"];
var DCOLS=["Slot","Player","Pos","Opponent","Prop-implied pts","Sleeper proj","FP rank","Status","Opp implied total","Game total (O/U)","Spread"];
var SLOT={BN:"Bench",WAIVER:"FA"};
function esc(s){return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}
function pill(t,c){return '<span class="pill '+c+'">'+esc(t)+'</span>'}
function byPP(a,b){var x=(b.pp==null?-1:b.pp)-(a.pp==null?-1:a.pp);return x||b.pn-a.pn}
function tiersBy(items,val,asc){var r=items.filter(function(x){return val(x.p)!==null}).sort(function(a,b){return asc?val(a.p)-val(b.p):val(b.p)-val(a.p)});var n=r.length,m={};r.forEach(function(x,i){m[x.p.name]=i<n/3?"success":i<2*n/3?"warning":"danger"});return m}
function ppVal(p){return p.pp}
function fpVal(p){return /^\d+$/.test(String(p.fp))?parseInt(p.fp,10):null}
function tiers(items){return tiersBy(items,ppVal,false)}
function statusCell(s){if(s==="Healthy")return pill(s,"success");if(s==="Questionable"||s==="Bye"||s==="Doubtful")return pill(s,"warning");if(s==="IR"||s==="Out"||s==="Suspended"||s==="PUP")return pill(s,"danger");if(s==="Played")return pill(s,"accent");return pill(s,"neutral")}
function projCell(p){if(p.pp===null)return esc(p.proj)+" (\u2014)";var d=Math.round((parseFloat(p.pp.toFixed(1))-p.pn)*10)/10;var x=d>0?"+"+d.toFixed(1):d<0?"-"+Math.abs(d).toFixed(1):"0.0";return esc(p.proj)+" ("+x+")"}
function table(items){var tm=tiers(items),fm=tiersBy(items,fpVal,true);var h="<table><thead><tr>"+COLS.map(function(c){return"<th>"+esc(c)+"</th>"}).join("")+"</tr></thead><tbody>";
items.forEach(function(it){var p=it.p,t=tm[p.name];var pp=(p.pp===null||!t)?"\u2014":pill(p.pp.toFixed(1),t);var td=p.atd==="\u2014"?"\u2014":p.atdr?p.atd+" ("+p.atdr+")":p.atd;
var cells=[esc(it.label),esc(p.name+" \u00b7 "+p.team),esc(p.pos),esc(p.opp),pp,projCell(p),(fm[p.name]?pill(p.fp,fm[p.name]):esc(p.fp||"\u2014")),statusCell(p.status),esc(p.rush),esc(p.rec),esc(p.recs),esc(td)];
h+="<tr>"+cells.map(function(c){return"<td>"+c+"</td>"}).join("")+"</tr>"});
return h+"</tbody></table>"}
function dfpVal(p){var m=/^DEF(\d+)$/.exec(String(p.fp));return m?parseInt(m[1],10):null}
function num1(v){return v==null?"\u2014":(Math.round(v*10)/10).toFixed(1)}
function spreadTxt(v){return v==null?"\u2014":v===0?"PK":(v>0?"+":"")+v}
function dtable(items){var tm=tiersBy(items,ppVal,false),fm=tiersBy(items,dfpVal,true);var h="<table><thead><tr>"+DCOLS.map(function(c){return"<th>"+esc(c)+"</th>"}).join("")+"</tr></thead><tbody>";
items.forEach(function(it){var p=it.p,t=tm[p.name];var pp=(p.pp==null||!t)?"\u2014":pill(p.pp.toFixed(1),t);
var cells=[esc(it.label),esc(p.name+" \u00b7 "+p.team),esc(p.pos),esc(p.opp),pp,projCell(p),(fm[p.name]?pill(p.fp,fm[p.name]):esc(p.fp||"\u2014")),statusCell(p.status),num1(p.opptot),num1(p.total),spreadTxt(p.spread)];
h+="<tr>"+cells.map(function(c){return"<td>"+c+"</td>"}).join("")+"</tr>"});
return h+"</tbody></table>"}
function defItems(rows){var L={DEF:"Starter",BN:"Bench",WAIVER:"FA"};var mine=rows.filter(function(p){return p.slot!=="WAIVER"}).sort(byPP),fa=rows.filter(function(p){return p.slot==="WAIVER"}).sort(byPP);
return mine.concat(fa).map(function(p){return{p:p,label:L[p.slot]||p.slot}})}
window.initReport=function(key){
function D(){return window.REPORTS[key]}
function $(id){return document.getElementById(key+"-"+id)}
function lab(s){return SLOT[s]||s}
var view="Flex candidates",sort="Prop-implied pts";
function flexItems(){var all=[],STARTERS=D().STARTERS,BENCH=D().BENCH,WAIVER=D().WAIVER;STARTERS.forEach(function(p){if(p.pos==="RB"||p.pos==="WR"||p.pos==="TE")all.push({it:{p:p,label:p.slot==="FLEX"?"Current FLEX":"Starter "+lab(p.slot)},cand:p.slot==="FLEX"})});
BENCH.forEach(function(p){if(p.pn>0)all.push({it:{p:p,label:"Bench"},cand:true})});
WAIVER.forEach(function(p){all.push({it:{p:p,label:"FA"},cand:true})});
var rows=all.filter(function(x){return view==="All skill players"||x.cand}).map(function(x){return x.it});
function k(x){return sort==="Sleeper proj"?x.p.pn:sort==="Rec line"?(parseFloat(x.p.recs)||-1):(x.p.pp==null?-1:x.p.pp)}
return rows.sort(function(a,b){return k(b)-k(a)})}
function seg(id,opts,get,set){var el=$(id);el.innerHTML="";opts.forEach(function(o){var b=document.createElement("button");b.type="button";b.textContent=o;b.setAttribute("aria-pressed",get()===o);b.onclick=function(){set(o);render()};el.appendChild(b)})}
function render(){
seg("seg-view",["Flex candidates","All skill players"],function(){return view},function(v){view=v});
seg("seg-sort",["Prop-implied pts","Sleeper proj","Rec line"],function(){return sort},function(v){sort=v});
$("t-flex").innerHTML=table(flexItems())}
function text(){var M=D().META;if(!M)return;
function set(id,t){var e=$(id);if(e)e.textContent=t}
function list(id,items){var e=$(id);if(!e)return;e.innerHTML="";items.forEach(function(t){var li=document.createElement("li");li.textContent=t;e.appendChild(li)})}
set("title",M.title);set("asof",M.asof);set("wcap",M.wcap);set("week","Week "+M.week+" (latest)");
list("quick",M.quick||[]);list("notes",M.notes||[]);
var dl=$("setup");if(dl){dl.innerHTML="";(M.setup||[]).forEach(function(r){var dt=document.createElement("dt"),dd=document.createElement("dd");dt.textContent=r[0];if(r[2]){dd.innerHTML=pill(r[1],"accent")}else dd.textContent=r[1];dl.appendChild(dt);dl.appendChild(dd)})}
if(document.body.getAttribute("data-report")===key)document.title=M.title}
function draw(){var d=D(),STARTERS=d.STARTERS,BENCH=d.BENCH,WAIVER=d.WAIVER;text();
$("t-starters").innerHTML=table(STARTERS.map(function(p){return{p:p,label:lab(p.slot)}}));
$("t-bench").innerHTML=table(BENCH.slice().sort(byPP).map(function(p){return{p:p,label:"Bench"}}));
$("t-waiver").innerHTML=table(WAIVER.slice().sort(byPP).map(function(p){return{p:p,label:"FA"}}));
var dt=$("t-def");if(dt)dt.innerHTML=dtable(defItems(d.DEFENSE||[]));
render()}
window.REDRAW=window.REDRAW||{};window.REDRAW[key]=draw;
draw();
};
})();
