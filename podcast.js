/* Best League "Podcast" luck report. Static snapshot from best-podcast-data.js (tools/podcast.py).
   Independent of report-core.js / refresh.js: the update workflow and "Refresh everything" never touch it. */
(function(){
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]})}
function f1(v){return (Math.round(v*10)/10).toFixed(1)}
function f2(v){return v.toFixed(2)}
function sg(v,d){var s=(d===2?f2(v):f1(v));return v>0?"+"+s:s==="-0.0"||s==="-0.00"?s.slice(1):s}
function pill(t,c){return '<span class="pill '+c+'">'+t+'</span>'}
/* thirds by rank among the values shown; good=true means higher is better */
function tiers(vals,good){var idx=vals.map(function(v,i){return i}).sort(function(a,b){return good?vals[b]-vals[a]:vals[a]-vals[b]});
var n=vals.length,out=[];idx.forEach(function(i,r){out[i]=r<Math.round(n/3)?"success":r<Math.round(2*n/3)?"warning":"danger"});
/* equal values share the better tier */
vals.forEach(function(v,i){vals.forEach(function(w,j){if(v===w&&rankOf(out[j])<rankOf(out[i]))out[i]=out[j]})});return out}
function rankOf(c){return c==="success"?0:c==="warning"?1:2}
function ord(n){return n+(n%100>10&&n%100<14?'th':['th','st','nd','rd'][n%10]||'th')}
function rec(w,l,t){return w+"-"+l+(t?"-"+t:"")}
function joinNames(a){return a.length<3?a.join(" and "):a.slice(0,-1).join(", ")+" and "+a[a.length-1]}
function ptTime(iso){try{return new Intl.DateTimeFormat("en-US",{timeZone:"America/Los_Angeles",month:"short",day:"numeric",hour:"numeric",minute:"2-digit"}).format(new Date(iso))+" PT"}catch(e){return iso}}

function build(D){
var T=D.teams,by={};T.forEach(function(t){by[t.rid]=t});
function nm(rid){return esc(by[rid].name)}
function who(t){return '<b>'+esc(t.name)+'</b> <span class="mgr">'+esc(t.user)+'</span>'}
function gms(n){return n+' game'+(n===1?'':'s')}
var wk=D.weeks[0]===D.weeks[1]?"Week "+D.weeks[0]:"Weeks "+D.weeks[0]+"\u2013"+D.weeks[1];
var h=[];
h.push('<h1>Best League luck report: '+wk+'</h1>');
h.push('<p class="asof">Snapshot as of '+esc(ptTime(D.asof))+'. Not changed by the hourly update or Refresh everything.</p>');

/* ---- headlines */
var lucky=T[0],unlucky=T[T.length-1];
var byLuck=T.slice().sort(function(a,b){return b.luck-a.luck}),byBill=T.slice().sort(function(a,b){return b.inj_bill-a.inj_bill});
var IP=D.players.filter(function(p){return p.kind!=="not injury"});
function topLoss(rid){var b=null;IP.forEach(function(p){p.charged.forEach(function(c){var v=p.val*(c[1]+c[2]);if(c[0]===rid&&(!b||v>b.v))b={p:p,v:v,g:c[1]+c[2]}})});return b}
var hb=byBill[0],hl=topLoss(hb.rid);
h.push('<section class="quick"><h2>The headlines</h2><ul>');
var same=byLuck[0]===lucky;
h.push('<li>Luckiest: '+who(lucky)+', '+rec(lucky.w,lucky.l,lucky.t)+' on '+f1(lucky.xw)+' expected wins'+(byBill[byBill.length-1]===lucky?', with the smallest injury bill':'')+(same?'; opponents scored '+f1(lucky.dip)+' a week below their average against them':'')+'.</li>');
h.push('<li>Unluckiest: '+who(unlucky)+', '+rec(unlucky.w,unlucky.l,unlucky.t)+' ('+sg(unlucky.luck,1)+' wins vs expected) with an injury bill of '+f1(unlucky.inj_bill)+'.</li>');
if(!same)h.push('<li>Scraping by: '+who(byLuck[0])+', '+sg(byLuck[0].luck,1)+' wins above expected; opponents scored '+f1(byLuck[0].dip)+' a week below their average against them.</li>');
h.push('<li>Hit hardest by injuries: '+who(hb)+', '+gms(hb.inj_games)+' lost'+(hl?', led by '+esc(hl.p.name)+' ('+hl.g+')':'')+'.</li>');
h.push('</ul></section>');

/* ---- luck index table */
var li=tiers(T.map(function(t){return t.idx}),true),lw=tiers(T.map(function(t){return t.luck}),true),lb=tiers(T.map(function(t){return t.inj_bill}),false);
h.push('<section><h2>Luck index</h2><p class="cap">Luck index = the average of two z-scores: wins above expected (actual wins minus all-play expected wins) and the injury bill (reversed, so fewer injuries is luckier). Positive is lucky; green to red is relative to the 12 teams.</p><div class="scroll"><table><thead><tr><th>Rank</th><th>Team</th><th>Manager</th><th>Record</th><th>Expected wins</th><th>Wins above expected</th><th>All-play</th><th>Luck index</th><th>Points for</th><th>Points against</th><th>Injury bill</th></tr></thead><tbody>');
T.forEach(function(t,i){h.push('<tr><td>'+t.rank+'</td><td>'+esc(t.name)+'</td><td>'+esc(t.user)+'</td><td>'+rec(t.w,t.l,t.t)+'</td><td>'+f1(t.xw)+'</td><td>'+pill(sg(t.luck,1),lw[i])+'</td><td>'+rec(t.apw,t.apl,t.apt)+'</td><td>'+pill(sg(t.idx,2),li[i])+'</td><td>'+f1(t.pf)+'</td><td>'+f1(t.pa)+'</td><td>'+pill(f1(t.inj_bill),lb[i])+'</td></tr>')});
h.push('</tbody></table></div></section>');

/* ---- injuries */
/* injured players charged to each team, biggest cost first (same attribution as the bill) */
var SUF={"Jr.":1,"Sr.":1,"II":1,"III":1,"IV":1,"V":1};
function short(nm){var w=String(nm).split(" ").filter(function(x){return !SUF[x]});return w.length>1?w.slice(1).join(" "):w[0]||nm}
var SC={};IP.forEach(function(p){var k=short(p.name);SC[k]=SC[k]&&SC[k]!==p.pid?"dup":p.pid});
function label(p){var k=short(p.name);return SC[k]==="dup"?p.name.split(" ")[0]+" "+k:k}
function injList(rid){var L=[];IP.forEach(function(p){var g=0;p.charged.forEach(function(c){if(c[0]===rid)g+=c[1]+c[2]});if(g)L.push({p:p,v:p.val*g})});
L.sort(function(a,b){return b.v-a.v});if(!L.length)return "";var K=5,sh=L.slice(0,L.length>K?K-1:K).map(function(x){return esc(label(x.p))});
if(L.length>K)sh.push("+"+(L.length-K+1)+" more");return ' <span class="inj">('+sh.join(", ")+')</span>'}
var max=byBill[0].inj_bill||1,bt=tiers(byBill.map(function(t){return t.inj_bill}),false);
h.push('<section><h2>Injury report: who got screwed</h2><p class="cap">Injury bill = games lost \u00d7 the player\u2019s pick value (pick 1 = 100, each later pick 3% less), charged to whoever held him that week. Includes games still to miss through week '+D.end+'.</p>');
h.push('<div class="lg"><span><i></i>Missed so far</span><span><i class="c"></i>Still to miss</span></div><div class="bars stk">');
byBill.forEach(function(t,i){h.push('<div class="bar"><span class="bl">'+esc(t.name)+'</span><span class="bt"><span class="bf '+bt[i]+'" style="width:'+(t.inj_bill_so/max*100).toFixed(1)+'%"></span><span class="bc '+bt[i]+'" style="width:'+(t.inj_bill_co/max*100).toFixed(1)+'%"></span></span><span class="bv">'+f1(t.inj_bill)+'</span></div>')});
h.push('</div><div class="scroll mt"><table><thead><tr><th>Team</th><th>Manager</th><th>Games lost</th><th>Still to miss</th><th>By round 1\u20135 picks</th><th>Injury bill</th></tr></thead><tbody>');
byBill.forEach(function(t,i){h.push('<tr><td class="tw">'+esc(t.name)+injList(t.rid)+'</td><td>'+esc(t.user)+'</td><td>'+t.inj_games+'</td><td>'+t.inj_games_co+'</td><td>'+t.inj_early+'</td><td>'+pill(f1(t.inj_bill),bt[i])+'</td></tr>')});
h.push('</tbody></table></div></section>');

/* ---- awards */
function top(key,hi){var v=T.map(function(t){return t[key]}),b=hi?Math.max.apply(null,v):Math.min.apply(null,v);return T.filter(function(t){return t[key]===b})}
function names(a){return joinNames(a.map(function(t){return '<b>'+esc(t.name)+'</b>'}))}
var A=[];
function aw(n,a,txt){if(a&&a.length)A.push([n,names(a)+": "+txt])}
var g;
g=top("luck",true);aw("Golden Horseshoe",g,"most wins above expected ("+sg(g[0].luck,1)+"), "+rec(g[0].w,g[0].l,g[0].t)+" on an all-play of "+rec(g[0].apw,g[0].apl,g[0].apt)+".");
g=top("luck",false);aw("Broken Mirror",g,"fewest wins vs expected ("+sg(g[0].luck,1)+").");
g=top("top",true);if(g[0].top)aw("Top Dog",g,"league\u2019s top scorer in "+gms(g[0].top).replace("game","week")+".");
g=top("pf",true);aw("Point Machine",g,"most points for ("+f1(g[0].pf)+").");
g=top("pa",true);aw("The Gauntlet",g,"most points against ("+f1(g[0].pa)+").");
g=top("dip",true);aw("Soft Landing",g,"opponents scored "+f1(g[0].dip)+" a week below their average against them.");
g=top("cw",true);if(g[0].cw)aw("Escape Artist",g,"most wins by under "+D.close_margin+" points ("+g[0].cw+").");
g=top("cl",true);if(g[0].cl)aw("Heartbreak Hotel",g,"most losses by under "+D.close_margin+" points ("+g[0].cl+").");
var rb=null,st=null,bl=null;D.games.forEach(function(g){[[g.a,g.pa,g.b,g.pb],[g.b,g.pb,g.a,g.pa]].forEach(function(x){x.push(g.week);if(x[1]<x[3]&&(!rb||x[1]>rb[1]))rb=x;if(x[1]>x[3]&&(!st||x[1]<st[1]))st=x;if(x[1]<x[3]&&(!bl||x[3]-x[1]>bl[3]-bl[1]))bl=x})});
if(rb)A.push(["Robbed","<b>"+nm(rb[0])+"</b>: lost with "+rb[1].toFixed(2)+" to "+nm(rb[2])+" (week "+rb[4]+")."]);
if(st)A.push(["Stole One","<b>"+nm(st[0])+"</b>: beat "+nm(st[2])+" with "+st[1].toFixed(2)+" (week "+st[4]+")."]);
if(bl)A.push(["Mercy Rule","<b>"+nm(bl[0])+"</b>: lost by "+(bl[3]-bl[1]).toFixed(2)+" to "+nm(bl[2])+" (week "+bl[4]+")."]);
g=top("bottom",true);if(g[0].bottom)aw("Participation Trophy",g,"league\u2019s lowest scorer in "+gms(g[0].bottom).replace("game","week")+".");
g=top("inj_bill",true);aw("Ambulance on Speed Dial",g,"biggest injury bill ("+f1(g[0].inj_bill)+", "+gms(g[0].inj_games)+").");
g=top("inj_bill",false);aw("Bubble Wrap",g,"smallest injury bill ("+f1(g[0].inj_bill)+", "+gms(g[0].inj_games)+").");
g=top("inj_bill_co",true);if(g[0].inj_bill_co)aw("Dark Clouds Ahead",g,"most injury pain still coming ("+f1(g[0].inj_bill_co)+", "+gms(g[0].inj_games_co)+").");
g=top("inj_early",true);if(g[0].inj_early)aw("Draft Day Regret",g,"most games lost by round 1\u20135 picks ("+g[0].inj_early+").");
var dg={};(D.trades||[]).forEach(function(t){var p=IP.filter(function(x){return x.pid===t.pid})[0];if(p)p.charged.forEach(function(c){if(c[0]===t.to)dg[t.to]=(dg[t.to]||0)+c[1]+c[2]})});
var dk=Object.keys(dg).filter(function(k){return dg[k]}).sort(function(a,b){return dg[b]-dg[a]});
if(dk.length){var dm=dg[dk[0]];A.push(["Damaged Goods",joinNames(dk.filter(function(k){return dg[k]===dm}).map(function(k){return "<b>"+nm(+k)+"</b>"}))+": most games lost by players acquired in trades ("+dm+")."])}
h.push('<section><h2>Awards</h2><div class="awards">');
A.forEach(function(a){h.push('<div class="award"><div class="an">'+a[0]+'</div><div class="aw">'+a[1]+'</div></div>')});
h.push('</div></section>');

/* ---- methodology */
h.push('<section><h2>Methodology</h2><ul class="meth">'+
'<li><b>Expected wins:</b> each week, the share of the other 11 teams a team outscored, summed. Records and scores: '+wk.toLowerCase()+'.</li>'+
'<li><b>Games lost:</b> a drafted player\u2019s NFL team played and he didn\u2019t (byes and a coach\u2019s decision excluded). Week '+D.cur+': Out/IR/PUP players count. Future: reported timelines through week '+D.end+' (season-ending = every game; ranges use the midpoint, counted from the injury week).</li>'+
'<li><b>Who pays:</b> the team holding the player that week (last holder if he was dropped). Pick value comes from the original draft pick.</li>'+
'<li><b>Caveat:</b> Sleeper has no injury history, so causes of past misses aren\u2019t confirmed, and return dates are estimates. Data: Sleeper, plus news reports for timelines.</li></ul></section>');
return h.join("");
}

window.initPodcast=function(key,opt){opt=opt||{};
var D=window.PODCAST&&window.PODCAST[key],box=document.getElementById(key+"-podcast");
if(box)box.innerHTML=D?build(D):'<p class="cap">Podcast data is missing.</p>';
var PD=window.POWER&&window.POWER[key],pbox=document.getElementById(key+"-power");
if(pbox)pbox.innerHTML=PD&&window.buildPower?window.buildPower(PD):'<p class="cap">Power rankings data is missing.</p>';
var H=opt.hashes||{podcast:opt.podHash};
var btns=document.querySelectorAll('#'+key+'-subtabs button'),V=[];
for(var i=0;i<btns.length;i++)V.push(btns[i].getAttribute("data-v"));
function set(v,push){if(V.indexOf(v)<0)v="report";
for(var j=0;j<V.length;j++){var el=document.getElementById(key+"-view-"+V[j]);if(el)el.hidden=V[j]!==v}
for(var i=0;i<btns.length;i++)btns[i].setAttribute("aria-selected",btns[i].getAttribute("data-v")===v);
if(push&&history.replaceState)history.replaceState(null,"",v==="report"?opt.repHash:H[v])}
function fromHash(){for(var k in H)if(location.hash===H[k])return k;return "report"}
for(var i=0;i<btns.length;i++)btns[i].onclick=function(){set(this.getAttribute("data-v"),true);window.scrollTo(0,Math.min(window.scrollY,(document.getElementById(key+"-subtabs").getBoundingClientRect().top+window.scrollY)-80))};
window["set_"+key+"_view"]=function(v){set(v,false)};
set(opt.initial||"report",false);
if(opt.listen)window.addEventListener("hashchange",function(){set(fromHash(),false)})};
window.podcastViewFromHash=function(hashes){for(var k in hashes)if(location.hash===hashes[k])return k;return "report"};
})();
