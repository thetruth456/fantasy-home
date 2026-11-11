/* "Podcast: Power Rankings", one league per data file (<key>-power-data.js, tools/power.py --league KEY).
   Rendered by initPodcast in podcast.js. The hourly update and "Refresh everything" do not touch it.
   Refresh on this tab runs the rankings workflow for all four leagues. */
(function(){
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]})}
function f1(v){return (Math.round(v*10)/10).toFixed(1)}
function pc(v){return v>=99.95?">99.9%":v>0&&v<0.1?"<0.1%":f1(v)+"%"}
function pill(t,c){return '<span class="pill '+c+'">'+t+'</span>'}
function tiers(vals,good){var idx=vals.map(function(v,i){return i}).sort(function(a,b){return good?vals[b]-vals[a]:vals[a]-vals[b]});
var n=vals.length,out=[];idx.forEach(function(i,r){out[i]=r<Math.round(n/3)?"success":r<Math.round(2*n/3)?"warning":"danger"});
vals.forEach(function(v,i){vals.forEach(function(w,j){if(v===w&&rk(out[j])<rk(out[i]))out[i]=out[j]})});return out}
function rk(c){return c==="success"?0:c==="warning"?1:2}
/* fixed cut-offs for probabilities so 0% never shows green */
function ptier(v,hi,lo){return v>=hi?"success":v>=lo?"warning":"danger"}
function rec(w,l,t){return w+"-"+l+(t?"-"+t:"")}
function ord(n){return n+(n%100>10&&n%100<14?'th':['th','st','nd','rd'][n%10]||'th')}
function ptTime(iso){try{return new Intl.DateTimeFormat("en-US",{timeZone:"America/Los_Angeles",month:"short",day:"numeric",hour:"numeric",minute:"2-digit"}).format(new Date(iso))+" PT"}catch(e){return iso}}

/* ---- odds over time (Power Rankings tab, and a compact copy at the top of the weekly report: opt.compact) */
function oddsChart(D,opt){opt=opt||{};var cp=!!opt.compact,T=D.teams,h=[],KEY=D.key||"best",TITLE=D.title||"Best League",NB=D.nbye==null?2:D.nbye;
if(!(D.hist&&D.hist.length>1))return "";
var COL=["#1f77b4","#d62728","#2ca02c","#ff7f0e","#9467bd","#17becf","#8c564b","#e7298a","#222222","#a6a600","#7f7f7f","#00876c","#b15928","#6a3d9a"],DASH=[0,0,0,0,0,0,"9 5","9 5","9 5","9 5","9 5","9 5","9 5","9 5"];
window.powerOdds=function(b,k){var box=b.closest(".odds");box.setAttribute("data-k",k);[].forEach.call(box.querySelectorAll(".seg button"),function(x){x.setAttribute("aria-pressed",x===b)})};
function oddsDim(box){var f=box.getAttribute("data-f")||"";box.classList.toggle("foc",!!f);[].forEach.call(box.querySelectorAll("[data-r]"),function(x){var m=f&&x.getAttribute("data-r")!==f;x.classList.toggle("dim",!!m);x.classList.toggle("on",!!f&&!m)})}
window.powerFocus=function(el,rid){var box=el.closest(".odds"),on=box.getAttribute("data-f")===String(rid);box.setAttribute("data-f",on?"":String(rid));oddsDim(box)};
var H=D.hist,n=H.length;
function xl(h){return h.live?"W"+h.week+"*":h.week<0?"Pre-draft":h.week===0?"Pre":"W"+h.week}
var SH=[[/^chuba/i,"Chuba"],[/independent/i,"Indep. Variable"],[/^hoosier/i,"Hoosier"],[/omarion/i,"Omarion"],[/^jahsif/i,"Jahsif"],[/^ka13/i,"KA13"],[/^cooked/i,"Cooked"],[/^buck/i,"Buck Love"],[/^lil bro/i,"Lil bro"],[/^robbie/i,"Robbie"],[/^ceedees/i,"CeeDees"],[/^marshawn/i,"Marshawn"]];
function short0(nm){if(KEY==="best")for(var i=0;i<SH.length;i++)if(SH[i][0].test(nm))return SH[i][1];
var w=String(nm).replace(/[^\w\s'\u2019.$&-]/g," ").trim().split(/\s+/).filter(Boolean);if(!w.length)return String(nm).slice(0,12);
if(/^the$/i.test(w[0])&&w.length>1)w.shift();var s=w[0];if(s.length<5&&w[1])s+=" "+w[1];return s.length>12?s.slice(0,11)+"\u2026":s}
var SHN={},SHC={};T.forEach(function(t){var k=short0(t.name);SHC[k]=(SHC[k]||0)+1});
T.forEach(function(t){var k=short0(t.name);SHN[t.rid]=SHC[k]>1?(String(t.name).length>15?String(t.name).slice(0,14)+"\u2026":String(t.name)):k});
function short(nm){for(var i=0;i<T.length;i++)if(T[i].name===nm)return SHN[T[i].rid];return short0(nm)}
function shortM(nm){var s=short(nm);return s.length>10?s.slice(0,9).replace(/[\s.]+$/,"")+"\u2026":s}
function r0(v){return v>0&&v<0.5?"<1%":Math.round(v)+"%"}
/* records: D.recs[rid][w-1] = [W,L,T] after completed week w (tools/records.py / power.py); the label uses the current record */
var RC=D.recs||{},LAST=D.last==null?D.cur-1:D.last;
function rtx(a){return a?a[0]+"-"+a[1]+(a[2]?"-"+a[2]:""):""}
function recNow(t){return rtx([t.w,t.l,t.t])}
function recAt(rid,h){if(h.week<=0)return "";var a=RC[rid],w=h.live?LAST:Math.min(h.week,LAST);return a&&w>0?rtx(a[w-1]):""}
var recNote=LAST<D.cur?'Records are through week '+LAST+' (week '+D.cur+' in progress).':'Records are through week '+LAST+'.';
var order=T.slice().sort(function(a,b){return b.playoff-a.playoff||b.bye-a.bye}),ci={},cd={};order.forEach(function(t,i){ci[t.rid]=COL[i%COL.length];cd[t.rid]=DASH[i%DASH.length]});
function svg(k,mob,cp){/* mobile: two-line end labels (name, then record and odds) so they stay readable without eating the plot width */
var W=mob?400:cp?1200:1000,Ht=mob?(cp?460:500):cp?330:430,fs=mob?12:14,lw=mob?118:214,ml=mob?34:44,mr=lw,mt=14,mb=mob?24:30,cw=W-ml-mr,ch=Ht-mt-mb,gap=Math.round(fs*(mob?2.45:1.4));
function X(i){return ml+cw*i/(n-1)}function Y(v){return mt+ch*(1-v/100)}
var g='<svg class="oc oc-'+k+'" viewBox="0 0 '+W+' '+Ht+'" style="font-size:'+fs+'px" role="img" aria-label="'+(k==="po"?"Playoff":"Bye")+' odds by week">';
[0,25,50,75,100].forEach(function(v){g+='<line class="gl" x1="'+ml+'" x2="'+(W-mr)+'" y1="'+Y(v)+'" y2="'+Y(v)+'"/><text class="ax" x="'+(ml-6)+'" y="'+(Y(v)+4)+'" text-anchor="end">'+v+'%</text>'});
H.forEach(function(h,i){var l=xl(h);g+='<text class="ax" x="'+X(i)+'" y="'+(Ht-8)+'" text-anchor="middle">'+(mob&&l.indexOf("-")>0?'<tspan x="'+X(i)+'" dy="-0.55em">'+l.split("-")[0]+'-</tspan><tspan x="'+X(i)+'" dy="1.1em">'+l.split("-")[1]+'</tspan>':l)+'</text>'});
/* end labels with collision avoidance */
var L=order.map(function(t){var y=Y(H[n-1][k][t.rid]);return{t:t,y0:y,y:y}}).sort(function(a,b){return a.y0-b.y0||b.t.playoff-a.t.playoff});
var lo=mt+fs*(mob?0.9:0.4),hi=mt+ch-(mob?fs*0.6:0);L.forEach(function(l,i){l.y=Math.max(l.y0,i?L[i-1].y+gap:lo)});
for(var i=L.length-1;i>=0;i--){var mx=i===L.length-1?hi:L[i+1].y-gap;if(L[i].y>mx)L[i].y=mx}
var ly={};L.forEach(function(l){ly[l.t.rid]=l});
order.slice().reverse().forEach(function(t){var pts=H.map(function(h,i){return X(i).toFixed(1)+","+Y(h[k][t.rid]).toFixed(1)}).join(" "),l=ly[t.rid],xe=X(n-1),lx=xe+(mob?18:34);
g+='<g data-r="'+t.rid+'" style="color:'+ci[t.rid]+'" onclick="powerFocus(this,'+t.rid+')"><polyline class="ln" points="'+pts+'"'+(cd[t.rid]?' stroke-dasharray="'+cd[t.rid]+'"':'')+'/><polyline class="hit" points="'+pts+'"><title>'+esc(t.name)+' ('+recNow(t)+')</title></polyline>';
H.forEach(function(h,i){g+='<circle cx="'+X(i).toFixed(1)+'" cy="'+Y(h[k][t.rid]).toFixed(1)+'"><title>'+esc(t.name)+', '+xl(h)+': '+pc(h[k][t.rid])+(function(r){return r?' (record '+r+(h.live?', week '+h.week+' in progress':' after week '+Math.min(h.week,LAST))+')':''})(recAt(t.rid,h))+(h.live&&t.wk?'; week '+h.week+' so far '+f1(t.wk.locked)+' pts, projected '+f1(t.wk.mu):'')+'</title></circle>'});
g+='<path class="ld" d="M'+(xe+5)+' '+l.y0.toFixed(1)+'L'+(lx-4)+' '+l.y.toFixed(1)+'"/><text class="lb" x="'+lx+'" y="'+(l.y+fs*(mob?-0.15:0.36)).toFixed(1)+'">'+esc(mob?shortM(t.name):short(t.name))+(mob?'<tspan class="l2" x="'+lx+'" dy="1.15em">':' ')+'<tspan class="rc">('+recNow(t)+')</tspan> <tspan class="lv">'+r0(H[n-1][k][t.rid])+'</tspan>'+(mob?'</tspan>':'')+'<title>'+esc(t.name)+' ('+recNow(t)+')</title></text></g>'});
return g+'</svg>'}
/* one builder per league (several leagues can be on one page); the resize handler redraws each chart with its own */
var OB=window.__oddsB=window.__oddsB||{};OB[KEY]=function(mob,cp){return svg("po",mob,cp)+(NB?svg("bye",mob,cp):"")};
function isMob(){return (window.innerWidth||1000)<700}
if(!window.__oddsRz){window.__oddsRz=1;window.addEventListener("resize",function(){var m=isMob();[].forEach.call(document.querySelectorAll(".odds .ocw"),function(w){var b=window.__oddsB[w.getAttribute("data-key")];if(w.getAttribute("data-m")!==String(m)&&b){w.setAttribute("data-m",String(m));w.innerHTML=b(m,w.getAttribute("data-c")==="1");oddsDim(w.closest(".odds"))}})})}
var hz=D.inj_hazard||{},CA=D.cal||{source:"own",seasons:["Best League 2025","Best League 2022"]};
var SEAS=(CA.seasons||[]).map(function(x){return +String(x).slice(-4)}),calTxt=CA.source==="own"?esc(TITLE)+' '+Math.min.apply(null,SEAS)+'\u2013'+String(Math.max.apply(null,SEAS)).slice(2):CA.n+' past team-seasons from '+(function(){var u=[];(CA.seasons||[]).forEach(function(x){var q=String(x).replace(/\s*\d{4}$/,"");if(u.indexOf(q)<0)u.push(q)});return esc(u.length<3?u.join(" and "):u.slice(0,-1).join(", ")+" and "+u[u.length-1])})()+'; ' +esc(TITLE)+' has '+(CA.seasons&&CA.seasons.some(function(x){return x.indexOf(TITLE)===0})?'too few of its own':'no earlier seasons on Sleeper');
var noKeep=D.keepers_n===0;
var meth=cp?'':'<h3 class="mh">How the odds are built</h3><ul class="meth">'+
'<li><b>Pre-draft:</b> '+(noKeep?'no keepers this season, so everyone starts level ('+Math.round(100*D.nplay/D.nteams)+'%).':'everyone starts level; keepers add how much better they are than what their pick usually gets.')+'</li>'+
'<li><b>After the draft:</b> each drafted roster\u2019s projected value, but only '+D.beta0+' of its edge over average counts (how much draft edges held up in '+calTxt+').</li>'+
'<li><b>Each week:</b> real points per game blend in with projections, and the roster edge is trusted more ('+D.beta_now+' now).</li>'+
(LAST<D.cur?'<li><b>Week '+D.cur+' (in progress):</b> points already scored count; players whose game is over keep their real points, players in a game under way keep their points so far plus the rest of their projection scaled by the game time left, and only players still to play are simulated.</li>':'')+'<li><b>Rest of season:</b> simulated '+D.sims.toLocaleString("en-US")+' times; every score varies by \u00b1'+f1(D.sd_noise)+' pts, plus a hidden boost or drag per team (\u00b1'+f1(D.tau_now)+' now).</li>'+
'<li><b>Injuries:</b> in each simulated week a healthy player can start missing games (about '+Math.round(100*(hz.RB||0))+'% chance per game at QB/RB/WR/TE, from Sleeper game logs 2021\u201325) for 1 game up to the rest of the season; the best lineup re-forms from the bench or waivers, so depth matters.</li></ul>';
if(cp)h.push('<section class="odds repodds" data-k="po"><h2>Playoff odds through the season</h2><p class="cap">Each point is the Power Rankings simulation rerun with only what was known after that week (W'+D.cur+'* = now). Tap a team to spotlight it'+(opt.link?'; method on the <a href="'+esc(opt.link)+'">Power Rankings</a> tab':'')+'. '+recNote+'</p>');
else h.push('<section class="odds" data-k="po"><h2>Odds through the season</h2><p class="cap">Each point reruns the simulation with only what was known after that week. Pre-draft = '+(noKeep?'before the draft':'keepers only')+'; Pre = after the draft; W'+D.cur+'* = now (week '+D.cur+' in progress). Hover or tap a team to spotlight it. '+recNote+'</p>');
if(NB)h.push('<div class="seg"><button type="button" aria-pressed="true" onclick="powerOdds(this,\'po\')">Playoff %</button><button type="button" aria-pressed="false" onclick="powerOdds(this,\'bye\')">Bye %</button></div>');
h.push('<div class="ocw" data-key="'+esc(KEY)+'" data-m="'+isMob()+'" data-c="'+(cp?1:0)+'">'+OB[KEY](isMob(),cp)+'</div><div class="ol">');
order.forEach(function(t){h.push('<button type="button" data-r="'+t.rid+'" onclick="powerFocus(this,'+t.rid+')"><svg width="26" height="8"><line x1="1" y1="4" x2="25" y2="4" stroke="'+ci[t.rid]+'" stroke-width="4"'+(cd[t.rid]?' stroke-dasharray="7 3"':'')+'/></svg><span class="nm">'+esc(short(t.name))+'</span><span class="rc">('+recNow(t)+')</span><b class="v-po">'+r0(t.playoff)+'</b><b class="v-bye">'+r0(t.bye)+'</b></button>')});
h.push('</div>'+meth+'</section>')
return h.join("")}
window.buildPowerOdds=function(D,opt){return D?oddsChart(D,opt):""};
/* Ben's (podcast co-host) rankings, keyed by Sleeper roster_id: Best League only */
var BEN={4:1,10:2,2:3,8:4,11:5,12:6,6:7,1:8,3:9,5:10,9:11,7:12};
function rng(a,b){return a===b?String(a):a+"\u2013"+b}
window.buildPower=function(D){
var KEY=D.key||"best",TITLE=D.title||"Best League",HASBEN=KEY==="best",NB=D.nbye==null?2:D.nbye;
var T=D.teams,by={};T.forEach(function(t){by[t.rid]=t});
function who(t){return '<b>'+esc(t.name)+'</b> <span class="mgr">'+esc(t.user)+'</span>'}
function pr(t){var w=Math.round(t.pwins);return w+"-"+(t.games-w)}
var maxF=Math.max.apply(null,T.map(function(t){return t.first})),nMax=T.filter(function(x){return x.first===maxF}).length;
function note(t){
 if(t.playoff>=90)return t.first===maxF?"Near-lock; "+(nMax>1?"co-favorite":"favorite")+" for 1st":"Near-lock for the playoffs";
 if(t.ap<45&&t.w>=4)return "Record ahead of the roster";
 if(t.playoff>=60)return "Likely in";
 if(t.playoff>=25)return "Bubble";
 if(t.ap>=45)return "Better than "+rec(t.w,t.l,t.t)+"; needs a run";
 if(t.playoff>=5)return "Long shot";
 return "Playing spoiler"}
var h=[];
h.push('<h1>'+esc(TITLE)+' power rankings: Week '+D.cur+'</h1>');
h.push('<p class="asof">Snapshot as of '+esc(ptTime(D.asof))+'.'+(window.PODCAST_STANDALONE?'':' Use Refresh to regenerate all four leagues. The hourly update does not change this view.')+'</p>');

/* ---- odds through the season first (chart, toggle, legend, then how the odds are built) */
h.push(oddsChart(D));

/* ---- headlines */
var top=T[0],byAp=T.slice().sort(function(a,b){return b.ap-a.ap}),bySos=T.slice().sort(function(a,b){return a.sos-b.sos});
var hole=byAp.filter(function(t){return t.playoff<30})[0];
var bub=T.slice().sort(function(a,b){return Math.abs(a.playoff-50)-Math.abs(b.playoff-50)})[0];
h.push('<section class="quick"><h2>The headlines</h2><ul>');
h.push('<li>No. 1: '+who(top)+', '+rec(top.w,top.l,top.t)+', '+pc(top.playoff)+' to make the playoffs, '+pc(top.title)+' to win it all.</li>');
if(hole)h.push('<li>Best roster in a hole: '+who(hole)+', '+ord(byAp.indexOf(hole)+1)+' in strength but '+rec(hole.w,hole.l,hole.t)+': '+pc(hole.playoff)+' playoff odds.</li>');
h.push('<li>Bubble: '+who(bub)+', '+pc(bub.playoff)+'.</li>');
function se(t){return t.playoff-t.po_neutral}
function sg(v){var r=Math.round(v*10)/10;return (r>0?"+":r<0?"\u2212":"")+Math.abs(r).toFixed(1)}
var e0=bySos[0],e1=bySos[bySos.length-1];
h.push('<li>Schedule left: easiest for '+who(e0)+' ('+sg(se(e0))+' playoff pts), hardest for '+who(e1)+' ('+sg(se(e1))+').</li>');
h.push('</ul></section>');

/* ---- power table */
var tS=tiers(T.map(function(t){return t.strength}),true);
var pw=D.pw;
h.push('<section><h2>Power rankings</h2><p class="cap">Ranked by a blend of team strength ('+Math.round(pw.strength*100)+'%: chance to beat a random league opponent each week, weeks '+(D.cur+1)+'\u2013'+D.reg_end+'), playoff odds ('+Math.round(pw.playoff*100)+'%), odds of finishing 1st ('+Math.round(pw.first*100)+'%) and title odds ('+Math.round(pw.title*100)+'%). Odds come from '+D.sims.toLocaleString("en-US")+' simulated seasons.'+(HASBEN?' Ben\u2019s rank is Ben\u2019s own list.':'')+'</p>');
h.push('<div class="scroll"><table><thead><tr><th>Rank</th>'+(HASBEN?'<th>Ben\u2019s rank</th>':'')+'<th>Team</th><th>Manager</th><th>Record</th><th>Points for</th><th>Strength (pts/wk)</th><th>Proj. record</th><th>Playoff %</th><th>1st place %</th><th>Title %</th><th>Note</th></tr></thead><tbody>');
T.forEach(function(t,i){h.push('<tr><td>'+t.rank+'</td>'+(HASBEN?'<td>'+(BEN[t.rid]||'\u2013')+'</td>':'')+'<td>'+esc(t.name)+'</td><td>'+esc(t.user)+'</td><td>'+rec(t.w,t.l,t.t)+'</td><td>'+f1(t.pf)+'</td><td>'+pill(f1(t.strength),tS[i])+'</td><td>'+pr(t)+'</td><td>'+pill(pc(t.playoff),ptier(t.playoff,67,33))+'</td><td>'+pill(pc(t.first),ptier(t.first,20,5))+'</td><td>'+pill(pc(t.title),ptier(t.title,15,5))+'</td><td class="nt">'+note(t)+'</td></tr>')});
h.push('</tbody></table></div></section>');


/* ---- projected finish */
h.push('<section><h2>Projected finish</h2><p class="cap">Where each team finished across the simulations. The number is the average final standing.</p>');
h.push('<div class="lg">'+(NB?'<span><i class="success"></i>Bye (seed '+rng(1,NB)+')</span>':'')+'<span><i class="warning"></i>Playoffs (seed '+rng(NB+1,D.nplay)+')</span><span><i></i>Out</span></div><div class="bars stk">');
T.forEach(function(t){var by_=t.bye,p3=t.playoff-t.bye,out=100-t.playoff;
h.push('<div class="bar" title="'+esc(t.name)+': bye '+pc(by_)+', playoffs '+pc(t.playoff)+'"><span class="bl">'+esc(t.name)+'</span><span class="bt"><span class="bf success" style="width:'+by_.toFixed(1)+'%"></span><span class="bf warning" style="width:'+p3.toFixed(1)+'%"></span><span class="bf danger" style="width:'+out.toFixed(1)+'%"></span></span><span class="bv">'+ord(Math.round(t.avgfin))+'</span></div>')});
h.push('</div></section>');

/* ---- schedule */
var tO=tiers(bySos.map(function(t){return t.sos}),false);
h.push('<section><h2>Remaining schedule: easiest to hardest</h2><p class="cap">Weeks '+D.cur+'\u2013'+D.reg_end+'. Opponent strength = each opponent\u2019s projected points in the week they meet. Schedule effect = playoff % on the real schedule minus playoff % with random opponents each week.</p>');
h.push('<div class="scroll"><table><thead><tr><th>Rank</th><th>Team</th><th>Record</th><th>Opp. strength (pts/wk)</th><th>Opp. record</th><th>Schedule effect (playoff pts)</th><th>Toughest game left</th></tr></thead><tbody>');
bySos.forEach(function(t,i){var hard=t.left.slice().sort(function(a,b){return b.mu-a.mu})[0];
h.push('<tr><td>'+(i+1)+'</td><td>'+esc(t.name)+'</td><td>'+rec(t.w,t.l,t.t)+'</td><td>'+pill(f1(t.sos),tO[i])+'</td><td>'+t.opp_w+'-'+t.opp_l+'</td><td>'+pill(sg(se(t)),se(t)>=1?"success":se(t)<=-1?"danger":"warning")+'</td><td>Week '+hard.week+' vs '+esc(by[hard.opp].name)+'</td></tr>')});
h.push('</tbody></table></div></section>');

/* ---- methodology */
h.push('<section><h2>Methodology</h2><ul class="meth">'+
'<li><b>Strength:</b> each player = his points per game this season, weighted by games played (gp \u00f7 (gp + '+D.g0+'), so 50% at '+D.g0+' games), plus his Sleeper projection that week for the rest; a team = its best lineup from the current roster, so points from players now hurt, traded or dropped don\u2019t count. Byes, this week\u2019s Out/IR tags and long-term injuries count as zero.</li>'+
'<li><b>Standings:</b> wins, then points for. Top '+D.nplay+' of '+(D.nteams||T.length)+' make it; '+(NB?(NB>1?'seeds ':'seed ')+rng(1,NB)+' '+(NB>1?'get':'gets')+' a bye; ':'')+'Sleeper\u2019s fixed bracket (no reseeding)'+(D.bracket?': '+D.bracket.filter(function(x){return x.r===1}).map(function(x){return [x.a,x.b].map(function(v){return +v.replace("seed ","")}).sort(function(p,q){return p-q}).join("v")}).join(", ")+' in round 1':'')+'; title odds simulate weeks '+D.pstart+'\u2013'+D.end+'.</li>'+
'<li><b>Odds and simulation:</b> see the bullets above the odds chart. Week '+D.cur+' keeps points already scored.</li>'+
'<li><b>Caveat:</b> projections and injury timelines are estimates; future trades aren\u2019t modeled and waiver pickups only fill in for injuries. Data: Sleeper.</li></ul></section>');
return h.join("");
};
})();
