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
function nm(rid){var t=by[rid];return esc(t.name)}
function who(t){return '<b>'+esc(t.name)+'</b> <span class="mgr">'+esc(t.user)+'</span>'}
var wk=D.weeks[0]===D.weeks[1]?"Week "+D.weeks[0]:"Weeks "+D.weeks[0]+"\u2013"+D.weeks[1];
var h=[];
h.push('<h1>Best League luck report: '+wk+'</h1>');
h.push('<p class="asof">Static snapshot for the podcast, data as of '+esc(ptTime(D.asof))+' (Sleeper, '+wk.toLowerCase()+' only). It is not changed by the hourly update or Refresh everything.</p>');

/* ---- headlines */
var lucky=T[0],unlucky=T[T.length-1];
var byLuck=T.slice().sort(function(a,b){return b.luck-a.luck}),byBill=T.slice().sort(function(a,b){return b.inj_bill-a.inj_bill});
var worstP=D.players.filter(function(p){return p.kind!=="not injury"})[0];
h.push('<section class="quick"><h2>The headlines</h2><ul>');
h.push('<li>Luckiest team: '+who(lucky)+'. '+rec(lucky.w,lucky.l,lucky.t)+' on a schedule worth '+f1(lucky.xw)+' expected wins ('+sg(lucky.luck,1)+'), and an injury bill of '+f1(lucky.inj_bill)+'.</li>');
h.push('<li>Unluckiest team: '+who(unlucky)+'. '+rec(unlucky.w,unlucky.l,unlucky.t)+' against '+f1(unlucky.xw)+' expected wins ('+sg(unlucky.luck,1)+'), and an injury bill of '+f1(unlucky.inj_bill)+' (league high is '+f1(byBill[0].inj_bill)+').</li>');
var pfRank=T.slice().sort(function(a,b){return a.pf-b.pf}).indexOf(byLuck[0])+1,low=byLuck.filter(function(t){return t.luck===byLuck[byLuck.length-1].luck});
h.push('<li>Scraping by: '+who(byLuck[0])+' is '+rec(byLuck[0].w,byLuck[0].l,byLuck[0].t)+' ('+sg(byLuck[0].luck,1)+' wins above expected) with the '+(pfRank===1?'fewest':ord(pfRank)+'-fewest')+' points scored; opponents scored '+f1(byLuck[0].dip)+' points a week below their own average against them.</li>');
h.push('<li>Robbed on the scoreboard: '+joinNames(low.map(who))+' '+(low.length>1?'are each ':'is ')+sg(low[0].luck,1)+' wins below expected.</li>');
h.push('<li>Hit hardest by injuries: '+who(byBill[0])+': '+byBill[0].inj_games+' games missed by their draft picks, '+byBill[0].inj_early+' of them by picks from rounds 1 to 5.</li>');
if(worstP)h.push('<li>Costliest absence: '+esc(worstP.name)+' (pick '+worstP.pick+', '+nm(worstP.rid)+') missed '+worstP.missed.length+' game'+(worstP.missed.length>1?"s":"")+'.</li>');
h.push('</ul></section>');

/* ---- luck index table */
var li=tiers(T.map(function(t){return t.idx}),true),lw=tiers(T.map(function(t){return t.luck}),true),lb=tiers(T.map(function(t){return t.inj_bill}),false),ld=tiers(T.map(function(t){return t.dip}),true);
h.push('<section><h2>Luck index</h2><p class="cap">Ranked luckiest to unluckiest. Color is relative to the 12 teams: green is lucky, red is unlucky.</p><div class="scroll"><table><thead><tr><th>Rank</th><th>Team</th><th>Manager</th><th>Record</th><th>Expected wins</th><th>Wins above expected</th><th>All-play</th><th>Points for</th><th>Points against</th><th>Opponent dip</th><th>Injury bill</th><th>Luck index</th></tr></thead><tbody>');
T.forEach(function(t,i){h.push('<tr'+(t.rid===D.me?' class="me"':'')+'><td>'+t.rank+'</td><td>'+esc(t.name)+'</td><td>'+esc(t.user)+'</td><td>'+rec(t.w,t.l,t.t)+'</td><td>'+f1(t.xw)+'</td><td>'+pill(sg(t.luck,1),lw[i])+'</td><td>'+rec(t.apw,t.apl,t.apt)+'</td><td>'+f1(t.pf)+'</td><td>'+f1(t.pa)+'</td><td>'+pill(sg(t.dip,1),ld[i])+'</td><td>'+pill(f1(t.inj_bill),lb[i])+'</td><td>'+pill(sg(t.idx,2),li[i])+'</td></tr>')});
h.push('</tbody></table></div></section>');

/* ---- injuries */
var max=byBill[0].inj_bill||1,bt=tiers(byBill.map(function(t){return t.inj_bill}),false);
h.push('<section><h2>Injury report: who got screwed</h2><p class="cap">Injury bill = games missed by a team\u2019s draft picks, each weighted by where the player was drafted (pick 1 = 100, each later pick worth 3% less). Charged to the team that drafted the player.</p><div class="bars">');
byBill.forEach(function(t,i){h.push('<div class="bar"><span class="bl">'+esc(t.name)+'</span><span class="bt"><span class="bf '+bt[i]+'" style="width:'+Math.max(2,t.inj_bill/max*100).toFixed(1)+'%"></span></span><span class="bv">'+f1(t.inj_bill)+'</span></div>')});
h.push('</div><div class="scroll mt"><table><thead><tr><th>Team</th><th>Manager</th><th>Games missed</th><th>By round 1\u20135 picks</th><th>Injury bill</th><th>Costliest absence</th></tr></thead><tbody>');
byBill.forEach(function(t,i){var w=t.inj_worst;h.push('<tr'+(t.rid===D.me?' class="me"':'')+'><td>'+esc(t.name)+'</td><td>'+esc(t.user)+'</td><td>'+t.inj_games+'</td><td>'+t.inj_early+'</td><td>'+pill(f1(t.inj_bill),bt[i])+'</td><td>'+(w?esc(w.name)+' (pick '+w.pick+', '+w.games+' game'+(w.games>1?'s':'')+')':'\u2014')+'</td></tr>')});
h.push('</tbody></table></div>');
var P=D.players.slice(0,15),pt=tiers(P.map(function(p){return p.bill}),false);
h.push('<h3>Costliest absences</h3><p class="cap">The 15 drafted players with the biggest draft-capital loss. Sleeper tag now is the player\u2019s injury tag today (blank once he is off the report).</p><div class="scroll"><table><thead><tr><th>Pick</th><th>Player</th><th>Drafted by</th><th>Weeks missed</th><th>Games</th><th>Pick value</th><th>Draft capital lost</th><th>Sleeper tag now</th></tr></thead><tbody>');
P.forEach(function(p,i){h.push('<tr><td>'+p.rnd+'.'+String(p.pick-(p.rnd-1)*12).padStart(2,"0")+' (#'+p.pick+')</td><td>'+esc(p.name)+' <span class="mgr">'+esc(p.pos)+'</span></td><td>'+nm(p.rid)+'</td><td>'+p.missed.join(", ")+'</td><td>'+p.missed.length+'</td><td>'+f1(p.val)+'</td><td>'+pill(f1(p.bill),pt[i])+'</td><td>'+(p.kind==="not injury"?esc(p.status)+'; not counted':esc(p.status)||'\u2014')+'</td></tr>')});
h.push('</tbody></table></div></section>');

/* ---- schedule luck: scatter + close games */
h.push('<section><h2>Points for vs points against</h2><p class="cap">Bottom right is the dream (score a lot, face little); top left is pain. Dashed lines are league averages. Dot color is wins above expected (green lucky, red unlucky).</p>'+scatter(T,lw)+'</section>');
var C=D.close;
h.push('<section><h2>Closest finishes</h2><p class="cap">The narrowest results of the season so far.</p><div class="scroll"><table><thead><tr><th>Week</th><th>Winner</th><th>Loser</th><th>Score</th><th>Margin</th></tr></thead><tbody>');
C.forEach(function(g){var aw=g.pa>g.pb,W=aw?g.a:g.b,L=aw?g.b:g.a,ws=aw?g.pa:g.pb,ls=aw?g.pb:g.pa;h.push('<tr><td>'+g.week+'</td><td>'+nm(W)+'</td><td>'+nm(L)+'</td><td>'+ws.toFixed(2)+' to '+ls.toFixed(2)+'</td><td>'+(ws-ls).toFixed(2)+'</td></tr>')});
h.push('</tbody></table></div></section>');

/* ---- awards */
function top(key,hi){var v=T.map(function(t){return t[key]}),b=hi?Math.max.apply(null,v):Math.min.apply(null,v);return T.filter(function(t){return t[key]===b})}
function names(a){return joinNames(a.map(function(t){return '<b>'+esc(t.name)+'</b>'}))}
var A=[];
var g1=top("luck",true);A.push(["Golden Horseshoe","Most wins above expected",names(g1)+": "+sg(g1[0].luck,1)+" wins, "+rec(g1[0].w,g1[0].l,g1[0].t)+" with an all-play record of "+rec(g1[0].apw,g1[0].apl,g1[0].apt)+"."]);
var g2=top("luck",false);A.push(["Broken Mirror","Fewest wins above expected",names(g2)+": "+sg(g2[0].luck,1)+" wins."]);
var g3=top("inj_bill",true);A.push(["Ambulance on Speed Dial","Biggest injury bill",names(g3)+": "+f1(g3[0].inj_bill)+" ("+g3[0].inj_games+" games missed)."]);
var g4=top("inj_bill",false);A.push(["Bubble Wrap","Smallest injury bill",names(g4)+": "+f1(g4[0].inj_bill)+" ("+g4[0].inj_games+" games missed)."]);
var g5=top("dip",true);A.push(["Soft Landing","Opponents played worst against them",names(g5)+": opponents scored "+f1(g5[0].dip)+" a week below their own average."]);
var g6=top("pa",true);A.push(["The Gauntlet","Most points against",names(g6)+": "+f1(g6[0].pa)+" against."]);
var g7=top("cl",true);if(g7[0].cl)A.push(["Heartbreak Hotel","Most losses by under "+D.close_margin+" points",names(g7)+": "+g7[0].cl+"."]);
var g8=top("cw",true);if(g8[0].cw)A.push(["Escape Artist","Most wins by under "+D.close_margin+" points",names(g8)+": "+g8[0].cw+"."]);
var hl=null,lw2=null;D.games.forEach(function(g){[[g.a,g.pa,g.b,g.pb],[g.b,g.pb,g.a,g.pa]].forEach(function(x){if(x[1]<x[3]&&(!hl||x[1]>hl[1]))hl=x;if(x[1]>x[3]&&(!lw2||x[1]<lw2[1]))lw2=x;x.push(g.week)})});
if(hl)A.push(["Robbed","Highest score in a loss","<b>"+nm(hl[0])+"</b>: "+hl[1].toFixed(2)+" in week "+hl[4]+", lost to "+nm(hl[2])+" ("+hl[3].toFixed(2)+")."]);
if(lw2)A.push(["Stole One","Lowest score in a win","<b>"+nm(lw2[0])+"</b>: "+lw2[1].toFixed(2)+" in week "+lw2[4]+", beat "+nm(lw2[2])+" ("+lw2[3].toFixed(2)+")."]);
var g9=top("top",true);A.push(["Top Dog","Most weeks as the league\u2019s top scorer",names(g9)+": "+g9[0].top+" week"+(g9[0].top>1?"s":"")+"."]);
h.push('<section><h2>Awards</h2><div class="awards">');
A.forEach(function(a){h.push('<div class="award"><div class="an">'+a[0]+'</div><div class="ad">'+a[1]+'</div><div class="aw">'+a[2]+'</div></div>')});
h.push('</div></section>');

/* ---- methodology */
var tagged=[0,0];D.players.forEach(function(p){if(p.kind==='not injury')return;tagged[1]+=p.missed.length;if(p.kind==='injured')tagged[0]+=p.missed.length});
h.push('<section><h2>Methodology</h2><ul class="meth">'+
'<li><b>Data:</b> Sleeper only: league matchups, draft picks, rosters and users, weekly NFL stats, the NFL schedule and the players file. '+wk+' (completed weeks only).</li>'+
'<li><b>Expected wins:</b> each week, a team\u2019s share of the other 11 teams it outscored (its all-play result), summed over the weeks. Wins above expected = actual wins minus expected wins (ties count half).</li>'+
'<li><b>Opponent dip:</b> per game, the opponent\u2019s average in his other weeks minus what he scored against you, averaged. Positive means opponents underperformed against you.</li>'+
'<li><b>Missed game:</b> a drafted player whose NFL team played that week but who did not play (no game played in Sleeper\u2019s stats). Byes and players with no NFL team are not counted. Known non-injury absences (a coach\u2019s decision) are excluded.</li>'+
'<li><b>Injury bill:</b> missed games times pick value, where pick value = 100 \u00d7 0.97^(pick \u2212 1) (pick 12 \u2248 72, pick 36 \u2248 34, pick 100 \u2248 5). Charged to the team that drafted the player, even if he was later traded or dropped.</li>'+
'<li><b>Luck index:</b> the average of two z-scores across the 12 teams: wins above expected, and the injury bill (reversed, so a small bill is lucky).</li>'+
'<li><b>Caveat:</b> Sleeper keeps no week-by-week injury history, so the cause of each miss isn\u2019t confirmed; '+tagged[0]+' of the '+tagged[1]+' counted missed games belong to players who still carry a Sleeper injury tag.</li></ul></section>');
return h.join("");
}

function scatter(T,cls){
var W=640,H=400,m={l:56,r:18,t:16,b:46};
var xs=T.map(function(t){return t.pf}),ys=T.map(function(t){return t.pa});
function rng(a){var lo=Math.min.apply(null,a),hi=Math.max.apply(null,a),p=(hi-lo)*0.08||10;return[Math.floor((lo-p)/10)*10,Math.ceil((hi+p)/10)*10]}
var X=rng(xs),Y=rng(ys);
function px(v){return m.l+(v-X[0])/(X[1]-X[0])*(W-m.l-m.r)}
function py(v){return H-m.b-(v-Y[0])/(Y[1]-Y[0])*(H-m.t-m.b)}
var col={success:"#14803c",warning:"#c98a00",danger:"#b42318"};
var s=['<div class="chart"><svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="Points for versus points against by team">'];
var step=function(r){var d=r[1]-r[0];return d>200?50:d>80?20:10};
for(var v=Math.ceil(X[0]/step(X))*step(X);v<=X[1];v+=step(X))s.push('<line x1="'+px(v)+'" x2="'+px(v)+'" y1="'+m.t+'" y2="'+(H-m.b)+'" class="grid"/><text x="'+px(v)+'" y="'+(H-m.b+16)+'" class="tick" text-anchor="middle">'+v+'</text>');
for(var u=Math.ceil(Y[0]/step(Y))*step(Y);u<=Y[1];u+=step(Y))s.push('<line x1="'+m.l+'" x2="'+(W-m.r)+'" y1="'+py(u)+'" y2="'+py(u)+'" class="grid"/><text x="'+(m.l-6)+'" y="'+(py(u)+4)+'" class="tick" text-anchor="end">'+u+'</text>');
var ax=xs.reduce(function(a,b){return a+b},0)/xs.length,ay=ys.reduce(function(a,b){return a+b},0)/ys.length;
s.push('<line x1="'+px(ax)+'" x2="'+px(ax)+'" y1="'+m.t+'" y2="'+(H-m.b)+'" class="avg"/><line x1="'+m.l+'" x2="'+(W-m.r)+'" y1="'+py(ay)+'" y2="'+py(ay)+'" class="avg"/>');
s.push('<text x="'+((m.l+W-m.r)/2)+'" y="'+(H-8)+'" class="axl" text-anchor="middle">Points for</text><text transform="translate(14 '+((m.t+H-m.b)/2)+') rotate(-90)" class="axl" text-anchor="middle">Points against</text>');
/* labels: try right, left, above, below; pick the first spot that clears every dot and earlier label */
var pts=T.map(function(t,i){return{x:px(t.pf),y:py(t.pa),t:t,c:col[cls[i]]}}),boxes=[];
pts.forEach(function(p){boxes.push({x0:p.x-8,x1:p.x+8,y0:p.y-8,y1:p.y+8});s.push('<circle cx="'+p.x.toFixed(1)+'" cy="'+p.y.toFixed(1)+'" r="7" fill="'+p.c+'" stroke="#fff" stroke-width="2"><title>'+esc(p.t.name)+': '+f1(p.t.pf)+' for, '+f1(p.t.pa)+' against</title></circle>')});
function hit(b){if(b.x0<m.l||b.x1>W-2||b.y0<2||b.y1>H-m.b)return true;for(var i=0;i<boxes.length;i++){var o=boxes[i];if(b.x0<o.x1&&b.x1>o.x0&&b.y0<o.y1&&b.y1>o.y0)return true}return false}
pts.forEach(function(p){var tw=p.t.user.length*6.6+4,c=[],best=null;
[0,1,-1,2,-2].forEach(function(k){var dy=k*13;c.push({x:p.x+11,y:p.y+4+dy,a:"start"},{x:p.x-11,y:p.y+4+dy,a:"end"})});
c.push({x:p.x,y:p.y-12,a:"middle"},{x:p.x,y:p.y+21,a:"middle"});
for(var i=0;i<c.length&&!best;i++){var q=c[i],x0=q.a==="start"?q.x:q.a==="end"?q.x-tw:q.x-tw/2,b={x0:x0,x1:x0+tw,y0:q.y-10,y1:q.y+3};if(!hit(b)){best=q;boxes.push(b)}}
best=best||c[0];
s.push('<text x="'+best.x.toFixed(1)+'" y="'+best.y.toFixed(1)+'" class="dl" text-anchor="'+best.a+'">'+esc(p.t.user)+'</text>')});
s.push('</svg></div>');return s.join("")}

window.initPodcast=function(key,opt){opt=opt||{};
var D=window.PODCAST&&window.PODCAST[key],box=document.getElementById(key+"-podcast");
if(box)box.innerHTML=D?build(D):'<p class="cap">Podcast data is missing.</p>';
var btns=document.querySelectorAll('#'+key+'-subtabs button'),rep=document.getElementById(key+"-view-report"),pod=document.getElementById(key+"-view-podcast");
function set(v,push){v=v==="podcast"?"podcast":"report";rep.hidden=v!=="report";pod.hidden=v!=="podcast";
for(var i=0;i<btns.length;i++)btns[i].setAttribute("aria-selected",btns[i].getAttribute("data-v")===v);
if(push&&history.replaceState)history.replaceState(null,"",v==="podcast"?opt.podHash:opt.repHash)}
for(var i=0;i<btns.length;i++)btns[i].onclick=function(){set(this.getAttribute("data-v"),true);window.scrollTo(0,Math.min(window.scrollY,(document.getElementById(key+"-subtabs").getBoundingClientRect().top+window.scrollY)-80))};
window["set_"+key+"_view"]=function(v){set(v,false)};
set(opt.initial||"report",false);
if(opt.listen)window.addEventListener("hashchange",function(){set(location.hash===opt.podHash?"podcast":"report",false)})};
})();
