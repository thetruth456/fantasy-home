/* Best League "Podcast: Power Rankings". Static snapshot from best-power-data.js (tools/power.py).
   Rendered by initPodcast in podcast.js; the update workflow and "Refresh everything" never touch it. */
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

window.buildPower=function(D){
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
h.push('<h1>Best League power rankings: Week '+D.cur+'</h1>');
h.push('<p class="asof">Snapshot as of '+esc(ptTime(D.asof))+'. Not changed by the hourly update or Refresh everything.</p>');

/* ---- headlines */
var top=T[0],byAp=T.slice().sort(function(a,b){return b.ap-a.ap}),bySos=T.slice().sort(function(a,b){return a.sos-b.sos});
var hole=byAp.filter(function(t){return t.playoff<30})[0];
var bub=T.slice().sort(function(a,b){return Math.abs(a.playoff-50)-Math.abs(b.playoff-50)})[0];
h.push('<section class="quick"><h2>The headlines</h2><ul>');
h.push('<li>No. 1: '+who(top)+', '+rec(top.w,top.l,top.t)+', '+pc(top.playoff)+' to make the playoffs, '+pc(top.title)+' to win it all.</li>');
if(hole)h.push('<li>Best roster in a hole: '+who(hole)+', '+ord(byAp.indexOf(hole)+1)+' in strength but '+rec(hole.w,hole.l,hole.t)+': '+pc(hole.playoff)+' playoff odds.</li>');
h.push('<li>Bubble: '+who(bub)+', '+pc(bub.playoff)+'.</li>');
h.push('<li>Schedule left: easiest for '+who(bySos[0])+', hardest for '+who(bySos[bySos.length-1])+'.</li>');
h.push('</ul></section>');

/* ---- power table */
var tS=tiers(T.map(function(t){return t.strength}),true),tP=tiers(T.map(function(t){return t.power}),true);
var pw=D.pw;
h.push('<section><h2>Power rankings</h2><p class="cap">Power score = '+Math.round(pw.strength*100)+'% team strength (chance to beat a random league opponent each week, weeks '+(D.cur+1)+'\u2013'+D.reg_end+') + '+Math.round(pw.playoff*100)+'% playoff odds + '+Math.round(pw.first*100)+'% odds of finishing 1st + '+Math.round(pw.title*100)+'% title odds, all 0\u2013100. Odds come from '+D.sims.toLocaleString("en-US")+' simulated seasons.</p>');
h.push('<div class="scroll"><table><thead><tr><th>Rank</th><th>Team</th><th>Manager</th><th>Record</th><th>Points for</th><th>Strength (pts/wk)</th><th>Proj. record</th><th>Playoff %</th><th>1st place %</th><th>Title %</th><th>Power score</th><th>Note</th></tr></thead><tbody>');
T.forEach(function(t,i){h.push('<tr><td>'+t.rank+'</td><td>'+esc(t.name)+'</td><td>'+esc(t.user)+'</td><td>'+rec(t.w,t.l,t.t)+'</td><td>'+f1(t.pf)+'</td><td>'+pill(f1(t.strength),tS[i])+'</td><td>'+pr(t)+'</td><td>'+pill(pc(t.playoff),ptier(t.playoff,67,33))+'</td><td>'+pill(pc(t.first),ptier(t.first,20,5))+'</td><td>'+pill(pc(t.title),ptier(t.title,15,5))+'</td><td>'+pill(f1(t.power),tP[i])+'</td><td class="nt">'+note(t)+'</td></tr>')});
h.push('</tbody></table></div></section>');

/* ---- projected finish */
h.push('<section><h2>Projected finish</h2><p class="cap">Where each team finished across the simulations. The number is the average final standing.</p>');
h.push('<div class="lg"><span><i class="success"></i>Bye (seed 1\u20132)</span><span><i class="warning"></i>Playoffs (seed 3\u2013'+D.nplay+')</span><span><i></i>Out</span></div><div class="bars stk">');
T.forEach(function(t){var by_=t.bye,p3=t.playoff-t.bye,out=100-t.playoff;
h.push('<div class="bar" title="'+esc(t.name)+': bye '+pc(by_)+', playoffs '+pc(t.playoff)+'"><span class="bl">'+esc(t.name)+'</span><span class="bt"><span class="bf success" style="width:'+by_.toFixed(1)+'%"></span><span class="bf warning" style="width:'+p3.toFixed(1)+'%"></span><span class="bf danger" style="width:'+out.toFixed(1)+'%"></span></span><span class="bv">'+ord(Math.round(t.avgfin))+'</span></div>')});
h.push('</div></section>');

/* ---- schedule */
var tO=tiers(bySos.map(function(t){return t.sos}),false);
h.push('<section><h2>Remaining schedule: easiest to hardest</h2><p class="cap">Weeks '+D.cur+'\u2013'+D.reg_end+'. Opponent strength = each opponent\u2019s projected points in the week they meet.</p>');
h.push('<div class="scroll"><table><thead><tr><th>Rank</th><th>Team</th><th>Record</th><th>Opp. strength (pts/wk)</th><th>Opp. record</th><th>Toughest game left</th></tr></thead><tbody>');
bySos.forEach(function(t,i){var hard=t.left.slice().sort(function(a,b){return b.mu-a.mu})[0];
h.push('<tr><td>'+(i+1)+'</td><td>'+esc(t.name)+'</td><td>'+rec(t.w,t.l,t.t)+'</td><td>'+pill(f1(t.sos),tO[i])+'</td><td>'+t.opp_w+'-'+t.opp_l+'</td><td>Week '+hard.week+' vs '+esc(by[hard.opp].name)+'</td></tr>')});
h.push('</tbody></table></div></section>');

/* ---- methodology */
h.push('<section><h2>Methodology</h2><ul class="meth">'+
'<li><b>Strength:</b> weekly projection = '+Math.round(D.w_season*100)+'% points per game so far (weeks 1\u2013'+D.last+') + '+Math.round((1-D.w_season)*100)+'% the best lineup from the current roster on Sleeper projections (byes, this week\u2019s Out/IR tags and long-term injuries count as zero).</li>'+
'<li><b>Simulation:</b> '+D.sims.toLocaleString("en-US")+' runs of weeks '+D.cur+'\u2013'+D.reg_end+' on the real schedule; each score varies by \u00b1'+f1(D.sd)+' pts (the real week-to-week spread). Week '+D.cur+' keeps points already scored.</li>'+
'<li><b>Standings:</b> wins, then points for. Top '+D.nplay+' make it; seeds 1\u20132 get a bye; title odds simulate weeks '+D.pstart+'\u2013'+D.end+'.</li>'+
'<li><b>Caveat:</b> projections and injury timelines are estimates, and future trades and waiver moves aren\u2019t modeled. Data: Sleeper.</li></ul></section>');
return h.join("");
};
})();
