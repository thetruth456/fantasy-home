/* Refresh Sleeper projections in the browser. Re-pulls Sleeper projections (and each league's scoring settings),
   re-scores every plain-projection row, and redraws the tables. Props, FantasyPros ranks and prop-implied pts stay as the snapshot.
   Rows that already played (final score), or are Bye/Out/IR, are never overwritten. Fetched once, shared by all leagues on the page. */
(function(){
var API="https://api.sleeper.app";
var REPO="thetruth456/fantasy-home",WORKFLOW="update.yml",REF="main",TOKEN_KEY="fh_gh_token";
var FILES={best:"best-league-report.js",zbt:"zbt-report.js",oops:"oopsilons-report.js",spacex:"spacex-report.js"};
var SKIP={Played:1,Bye:1,Out:1,IR:1};
function metaOf(k){var D=window.REPORTS&&window.REPORTS[k];return D&&D.META||null}
function projUrl(m){return API+"/projections/nfl/"+m.season+"/"+m.week+"?season_type="+(m.season_type||"regular")+"&position%5B%5D=QB&position%5B%5D=RB&position%5B%5D=WR&position%5B%5D=TE&position%5B%5D=K&position%5B%5D=DEF"}
var st=document.getElementById("refresh-status");
if(!st)return;
function getJSON(url,ms){var c=new AbortController(),t=setTimeout(function(){c.abort()},ms||25000);
return fetch(url,{cache:"no-store",signal:c.signal}).then(function(r){clearTimeout(t);if(!r.ok)throw new Error("HTTP "+r.status);return r.json()},function(e){clearTimeout(t);throw e})}
function ptNow(){try{var f=new Intl.DateTimeFormat("en-US",{timeZone:"America/Los_Angeles",month:"short",day:"numeric",hour:"numeric",minute:"2-digit"}).formatToParts(new Date()),o={};f.forEach(function(p){o[p.type]=p.value});return o.month+" "+o.day+", "+o.hour+":"+o.minute+" "+o.dayPeriod+" PT"}catch(e){return new Date().toLocaleString()}}
function score(S,stats){var t=0;for(var k in stats){var v=stats[k];if(typeof v==="number"&&S[k])t+=S[k]*v}return t}
function round1(v){/* same as Python round(v,1): exact .25/.75 ties go to the even tenth; everything else rounds on the exact binary value like toFixed */
var q=v*4;if(q===Math.floor(q)&&Math.abs(q%2)===1){var t=Math.floor(v*10);return (t%2===0?t:t+1)/10}
return Number(v.toFixed(1))}
function setStatus(msg,cls){st.textContent=msg;st.className="refresh-status"+(cls?" "+cls:"")}
/* ---- Refresh everything: dispatch the GitHub Actions update workflow, wait for it, then re-read the data files ---- */
var fbtn=document.getElementById("full-btn"),panel=document.getElementById("token-panel"),form=document.getElementById("token-form"),
input=document.getElementById("token-input"),cancel=document.getElementById("token-cancel"),tmsg=document.getElementById("token-msg"),clr=document.getElementById("token-clear");
if(!fbtn)return;
function tok(){try{return localStorage.getItem(TOKEN_KEY)||""}catch(e){return""}}
function setTok(v){try{if(v)localStorage.setItem(TOKEN_KEY,v);else localStorage.removeItem(TOKEN_KEY)}catch(e){}syncClear()}
function syncClear(){if(clr)clr.hidden=!tok()}
function openPanel(m){if(!panel)return;tmsg.textContent=m||"";panel.hidden=false;input.value="";input.focus()}
function closePanel(){if(panel)panel.hidden=true}
function ptFmt(d){try{var f=new Intl.DateTimeFormat("en-US",{timeZone:"America/Los_Angeles",month:"short",day:"numeric",hour:"numeric",minute:"2-digit"}).formatToParts(d),o={};f.forEach(function(p){o[p.type]=p.value});return o.month+" "+o.day+", "+o.hour+":"+o.minute+" "+o.dayPeriod+" PT"}catch(e){return d.toLocaleString()}}
function sleep(ms){return new Promise(function(r){setTimeout(r,ms)})}
function gh(path,o){o=o||{};var h={Accept:o.accept||"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"};
if(tok())h.Authorization="Bearer "+tok();if(o.body)h["Content-Type"]="application/json";
return fetch("https://api.github.com"+path,{method:o.method||"GET",headers:h,body:o.body,cache:"no-store"})}
function ghError(r,what){var e=new Error("");e.code=r.status;
var left=r.headers.get("x-ratelimit-remaining"),reset=r.headers.get("x-ratelimit-reset");
if(r.status===401){e.message="GitHub rejected the token (wrong or expired). Paste a new one.";e.badToken=true}
else if(r.status===429||(r.status===403&&left==="0")){e.message="GitHub rate limit reached"+(reset?"; try again after "+ptFmt(new Date(reset*1000)):"; try again in a few minutes")+"."}
else if(r.status===403){e.message="The token isn\u2019t allowed to start workflows. It needs Actions: Read and write on the fantasy-home repo.";e.badToken=true}
else if(r.status===404){e.message="GitHub says "+what+" wasn\u2019t found. Check the token has access to fantasy-home and that .github/workflows/"+WORKFLOW+" is on "+REF+".";e.badToken=true}
else if(r.status===422){e.message="GitHub couldn\u2019t start the workflow. Check that "+WORKFLOW+" has a workflow_dispatch trigger on "+REF+"."}
else e.message="GitHub returned HTTP "+r.status+".";
return e}
function ok(r,what){return r.ok?r:Promise.reject(ghError(r,what))}
function parseData(text,key){var i=text.indexOf("{",text.indexOf("REPORTS."+key+"="));if(i<0)throw new Error("unexpected data file");return JSON.parse(text.slice(i,text.lastIndexOf("}")+1))}
function loadData(key){/* repo contents API first (fresh, no Pages deploy lag), then the site's own copy */
var f=FILES[key];
return gh("/repos/"+REPO+"/contents/"+f+"?ref="+REF,{accept:"application/vnd.github.raw+json"}).then(function(r){if(!r.ok)throw 0;return r.text()})
.catch(function(){return fetch(f+"?v="+Date.now(),{cache:"no-store"}).then(function(r){if(!r.ok)throw new Error("HTTP "+r.status);return r.text()})})
.then(function(t){return parseData(t,key)})}
function fbusy(on){fbtn.disabled=on;fbtn.classList.toggle("loading",on);if(on)fbtn.setAttribute("aria-busy","true");else fbtn.removeAttribute("aria-busy");fbtn.querySelector(".lbl").textContent=on?"Refreshing everything\u2026":"Refresh everything"}
function fullRefresh(){
if(fbtn.disabled)return;
if(!tok()){openPanel("");return}
closePanel();fbusy(true);setStatus("Asking GitHub to refresh everything\u2026","busy");
var t0=Date.now(),secs=function(){return " ("+Math.round((Date.now()-t0)/1000)+"s)"};
var keys=Object.keys(FILES).filter(function(k){return metaOf(k)});
var base={};keys.forEach(function(k){base[k]=metaOf(k).generated||""});
var baseId=0,runId=0;
gh("/repos/"+REPO+"/actions/workflows/"+WORKFLOW+"/runs?event=workflow_dispatch&per_page=1").then(function(r){return ok(r,"the workflow")}).then(function(r){return r.json()})
.then(function(j){baseId=(j.workflow_runs&&j.workflow_runs[0]&&j.workflow_runs[0].id)||0})
.then(function(){return gh("/repos/"+REPO+"/actions/workflows/"+WORKFLOW+"/dispatches",{method:"POST",body:JSON.stringify({ref:REF,inputs:{force:"true"}})})})
.then(function(r){return ok(r,"the workflow")})
.then(function(){
function poll(){
if(Date.now()-t0>15*60*1000)throw new Error("The update is taking longer than expected. Check the Actions tab on GitHub.");
return sleep(5000).then(function(){return gh("/repos/"+REPO+"/actions/workflows/"+WORKFLOW+"/runs?event=workflow_dispatch&per_page=5")}).then(function(r){return ok(r,"the workflow runs")}).then(function(r){return r.json()}).then(function(j){
var run=(j.workflow_runs||[]).filter(function(x){return x.id>baseId})[0];
if(!run){if(Date.now()-t0>90000)throw new Error("GitHub didn\u2019t start the workflow. Check the Actions tab.");setStatus("Waiting for GitHub to start the update\u2026"+secs(),"busy");return poll()}
runId=run.id;
if(run.status!=="completed"){setStatus((run.status==="queued"?"Queued on GitHub\u2026":"Updating data on GitHub\u2026")+secs(),"busy");return poll()}
if(run.conclusion!=="success"){var e=new Error("The update run finished with \u201c"+run.conclusion+"\u201d. See "+run.html_url);e.runUrl=run.html_url;throw e}
return run})}
return poll()})
.then(function(){setStatus("Loading the new data\u2026","busy");
return Promise.all(keys.map(function(k){return loadData(k).then(function(d){return[k,d]})}))})
.then(function(res){var latest="";
res.forEach(function(x){window.REPORTS[x[0]]=x[1];var g=(x[1].META&&x[1].META.generated)||"";if(g>latest)latest=g});
res.forEach(function(x){if(window.REDRAW&&window.REDRAW[x[0]])window.REDRAW[x[0]]()});
var stale=res.every(function(x){return (x[1].META.generated||"")<=base[x[0]]});
setStatus("Full refresh done, data as of "+(latest?ptFmt(new Date(latest)):ptNow())+(stale?" (the workflow found nothing newer)":""),"ok")})
.catch(function(e){
var m=(e&&e.message)||"network error";
if(e&&e.name==="TypeError")m="Couldn\u2019t reach GitHub. Check your connection and try again.";
setStatus("Full refresh failed: "+m,"err");
if(e&&e.badToken){setTok("");openPanel(m)}})
.then(function(){fbusy(false)})}
fbtn.addEventListener("click",fullRefresh);
if(form)form.addEventListener("submit",function(ev){ev.preventDefault();var v=(input.value||"").trim();
if(!/^[A-Za-z0-9_]{20,}$/.test(v)){tmsg.textContent="That doesn\u2019t look like a GitHub token (it should start with github_pat_).";return}
setTok(v);input.value="";closePanel();fullRefresh()});
if(cancel)cancel.addEventListener("click",closePanel);
if(clr)clr.addEventListener("click",function(){setTok("");closePanel();setStatus("GitHub token removed from this browser.","")});
syncClear();
})();
