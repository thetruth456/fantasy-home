/* Shared report renderer. Each league file sets window.REPORTS[key] = {STARTERS, BENCH, WAIVER}; call initReport(key). */
(function(){
var COLS=["Slot","Player","Pos","Opponent","Prop-implied pts","Sleeper proj","FP rank","Status","Rush yds line","Rec yds line","Rec line","Anytime TD (DK)"];
var SLOT={BN:"Bench",WAIVER:"FA"};
function esc(s){return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}
function pill(t,c){return '<span class="pill '+c+'">'+esc(t)+'</span>'}
function byPP(a,b){var x=(b.pp==null?-1:b.pp)-(a.pp==null?-1:a.pp);return x||b.pn-a.pn}
function tiers(items){var r=items.filter(function(x){return x.p.pp!==null}).sort(function(a,b){return b.p.pp-a.p.pp});var n=r.length,m={};r.forEach(function(x,i){m[x.p.name]=i<n/3?"success":i<2*n/3?"warning":"danger"});return m}
function statusCell(s){if(s==="Healthy")return pill(s,"success");if(s==="Questionable"||s==="Bye"||s==="Doubtful")return pill(s,"warning");if(s==="IR"||s==="Out"||s==="Suspended"||s==="PUP")return pill(s,"danger");if(s==="Played")return pill(s,"accent");return pill(s,"neutral")}
function projCell(p){if(p.pp===null)return esc(p.proj)+" "+pill("(\u2014)","neutral");var d=Math.round((parseFloat(p.pp.toFixed(1))-p.pn)*10)/10;var t=d>0?"success":d<0?"danger":"neutral";var x=d>0?"+"+d.toFixed(1):d<0?"-"+Math.abs(d).toFixed(1):"0.0";return esc(p.proj)+" "+pill("("+x+")",t)}
function table(items){var tm=tiers(items);var h="<table><thead><tr>"+COLS.map(function(c){return"<th>"+esc(c)+"</th>"}).join("")+"</tr></thead><tbody>";
items.forEach(function(it){var p=it.p,t=tm[p.name];var pp=(p.pp===null||!t)?"\u2014":pill(p.pp.toFixed(1),t);var td=p.atd==="\u2014"?"\u2014":p.atdr?p.atd+" ("+p.atdr+")":p.atd;
var cells=[esc(it.label),esc(p.name+" \u00b7 "+p.team),esc(p.pos),esc(p.opp),pp,projCell(p),esc(p.fp||"\u2014"),statusCell(p.status),esc(p.rush),esc(p.rec),esc(p.recs),esc(td)];
h+="<tr>"+cells.map(function(c){return"<td>"+c+"</td>"}).join("")+"</tr>"});
return h+"</tbody></table>"}
window.initReport=function(key){
var D=window.REPORTS[key],STARTERS=D.STARTERS,BENCH=D.BENCH,WAIVER=D.WAIVER;
function $(id){return document.getElementById(key+"-"+id)}
function lab(s){return SLOT[s]||s}
var view="Flex candidates",sort="Prop-implied pts";
function flexItems(){var all=[];STARTERS.forEach(function(p){if(p.pos==="RB"||p.pos==="WR"||p.pos==="TE")all.push({it:{p:p,label:p.slot==="FLEX"?"Current FLEX":"Starter "+lab(p.slot)},cand:p.slot==="FLEX"})});
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
$("t-starters").innerHTML=table(STARTERS.map(function(p){return{p:p,label:lab(p.slot)}}));
$("t-bench").innerHTML=table(BENCH.slice().sort(byPP).map(function(p){return{p:p,label:"Bench"}}));
$("t-waiver").innerHTML=table(WAIVER.slice().sort(byPP).map(function(p){return{p:p,label:"FA"}}));
render();
};
})();
