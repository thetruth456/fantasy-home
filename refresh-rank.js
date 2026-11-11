/* Refresh on the Power Rankings and Luck tabs. Dispatches .github/workflows/rankings.yml,
   which reruns tools/power.py and tools/podcast.py for all four leagues and commits the eight
   public snapshots. The GitHub token is the same localStorage key as Refresh everything (fh_gh_token).
   It is never written into the repo. These tabs do not need the weekly-report password. */
(function(){
var REPO="thetruth456/fantasy-home",WORKFLOW="rankings.yml",REF="main",TOKEN_KEY="fh_gh_token";
var KEYS=["best","zbt","oops","spacex"];
var running=false,panel,input,msg;
function tok(){try{return localStorage.getItem(TOKEN_KEY)||""}catch(e){return""}}
function setTok(v){try{if(v)localStorage.setItem(TOKEN_KEY,v);else localStorage.removeItem(TOKEN_KEY)}catch(e){}
syncForget();try{window.dispatchEvent(new Event("fh-token"))}catch(e){}}
function syncForget(){var hide=!tok(),nodes=document.querySelectorAll(".rank-forget");
for(var i=0;i<nodes.length;i++)nodes[i].hidden=hide}
function el(tag,cls,text){var n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n}
function text(s){return document.createTextNode(s)}
function sleep(ms){return new Promise(function(r){setTimeout(r,ms)})}
function pollWait(){return window.FH_RANK_POLL_MS!=null?window.FH_RANK_POLL_MS:5000}
function ptFmt(d){try{var f=new Intl.DateTimeFormat("en-US",{timeZone:"America/Los_Angeles",month:"short",day:"numeric",hour:"numeric",minute:"2-digit"}).formatToParts(d),o={};f.forEach(function(p){o[p.type]=p.value});return o.month+" "+o.day+", "+o.hour+":"+o.minute+" "+o.dayPeriod+" PT"}catch(e){return d.toLocaleString()}}
function ptNow(){return ptFmt(new Date())}
function gh(path,o){o=o||{};var h={Accept:o.accept||"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"};
if(tok())h.Authorization="Bearer "+tok();if(o.body)h["Content-Type"]="application/json";
return fetch("https://api.github.com"+path,{method:o.method||"GET",headers:h,body:o.body,cache:"no-store"})}
function ghError(r,what){var e=new Error("");e.code=r.status;
var left=r.headers.get("x-ratelimit-remaining"),reset=r.headers.get("x-ratelimit-reset");
if(r.status===401){e.message="GitHub rejected the token (wrong or expired). Paste a new one.";e.badToken=true}
else if(r.status===429||(r.status===403&&left==="0")){e.message="GitHub rate limit reached"+(reset?"; try again after "+ptFmt(new Date(reset*1000)):"; try again in a few minutes")+"."}
else if(r.status===403){e.message="The token isn\u2019t allowed to start workflows. It needs Actions: Read and write on the fantasy-home repo.";e.badToken=true}
else if(r.status===404){e.message="GitHub says "+what+" wasn\u2019t found. The token needs access to fantasy-home, and .github/workflows/"+WORKFLOW+" has to be on "+REF+"."}
else if(r.status===422){e.message="GitHub couldn\u2019t start the workflow. Check that "+WORKFLOW+" has a workflow_dispatch trigger on "+REF+"."}
else e.message="GitHub returned HTTP "+r.status+".";
return e}
function ok(r,what){return r.ok?r:Promise.reject(ghError(r,what))}
function setStatus(text,cls){var nodes=document.querySelectorAll(".rank-status");
for(var i=0;i<nodes.length;i++){nodes[i].textContent=text;nodes[i].className="rank-status"+(cls?" "+cls:"")}}
function busy(on){var btns=document.querySelectorAll(".rank-btn");
for(var i=0;i<btns.length;i++){btns[i].disabled=on;btns[i].classList.toggle("loading",on);
if(on)btns[i].setAttribute("aria-busy","true");else btns[i].removeAttribute("aria-busy");
var lbl=btns[i].querySelector(".lbl");if(lbl)lbl.textContent=on?"Refreshing\u2026":"Refresh"}}
function openPanel(m){if(!panel)return;msg.textContent=m||"";panel.hidden=false;try{input.focus()}catch(e){}}
function closePanel(){if(panel)panel.hidden=true}
function asof(bucket,key){var B=window[bucket];return (B&&B[key]&&B[key].asof)||""}
function parseSnap(text,kind,key){var mark=(kind==="power"?"window.POWER":"window.PODCAST")+"["+JSON.stringify(key)+"]=";
var i=text.indexOf(mark);if(i<0)throw new Error("unexpected data file");
var j=text.indexOf("{",i);if(j<0)throw new Error("unexpected data file");
return JSON.parse(text.slice(j,text.lastIndexOf("}")+1))}
function loadFile(file,kind,key){
return gh("/repos/"+REPO+"/contents/"+file+"?ref="+REF,{accept:"application/vnd.github.raw+json"}).then(function(r){
if(!r.ok)throw 0;return r.text().then(function(t){return{text:t,api:true}})}).catch(function(){
return fetch(file+"?v="+Date.now(),{cache:"no-store"}).then(function(r){if(!r.ok)throw new Error("Couldn\u2019t read "+file+" (HTTP "+r.status+").");return r.text()}).then(function(t){return{text:t,api:false}})})
.then(function(x){return{key:key,kind:kind,data:parseSnap(x.text,kind,key),api:x.api}})}
function loadAll(){var jobs=[];KEYS.forEach(function(k){
jobs.push(loadFile(k+"-power-data.js","power",k));
jobs.push(loadFile(k+"-podcast-data.js","podcast",k))});return Promise.all(jobs)}
function redraw(key){var P=window.POWER&&window.POWER[key],pbox=document.getElementById(key+"-power");
if(pbox&&window.buildPower&&P)pbox.innerHTML=window.buildPower(P);
var D=window.PODCAST&&window.PODCAST[key],box=document.getElementById(key+"-podcast");
if(box&&window.buildPodcast&&D)box.innerHTML=window.buildPodcast(D)}
function rankRefresh(){
if(running)return;
if(!tok()){openPanel("");return}
closePanel();running=true;busy(true);setStatus("Asking GitHub to refresh power rankings and luck\u2026","busy");
var t0=Date.now(),secs=function(){return " ("+Math.round((Date.now()-t0)/1000)+"s)"};
var base={};KEYS.forEach(function(k){base[k]={power:asof("POWER",k),podcast:asof("PODCAST",k)}});
var baseId=0;
gh("/repos/"+REPO+"/actions/workflows/"+WORKFLOW+"/runs?event=workflow_dispatch&per_page=1").then(function(r){return ok(r,"the workflow")}).then(function(r){return r.json()})
.then(function(j){baseId=(j.workflow_runs&&j.workflow_runs[0]&&j.workflow_runs[0].id)||0})
.then(function(){return gh("/repos/"+REPO+"/actions/workflows/"+WORKFLOW+"/dispatches",{method:"POST",body:JSON.stringify({ref:REF})})})
.then(function(r){return ok(r,"the workflow")})
.then(function(){
function poll(){
if(Date.now()-t0>100*60*1000)throw new Error("The refresh is taking longer than expected. Check the Actions tab on GitHub.");
return sleep(pollWait()).then(function(){return gh("/repos/"+REPO+"/actions/workflows/"+WORKFLOW+"/runs?event=workflow_dispatch&per_page=5")}).then(function(r){return ok(r,"the workflow runs")}).then(function(r){return r.json()}).then(function(j){
var run=(j.workflow_runs||[]).filter(function(x){return x.id>baseId})[0];
if(!run){if(Date.now()-t0>90000)throw new Error("GitHub didn\u2019t start the workflow. Check the Actions tab.");setStatus("Waiting for GitHub to start the refresh\u2026"+secs(),"busy");return poll()}
if(run.status!=="completed"){setStatus((run.status==="queued"?"Queued on GitHub\u2026":"Refreshing power rankings and luck\u2026")+secs(),"busy");return poll()}
if(run.conclusion!=="success"){var e=new Error("The refresh finished with \u201c"+run.conclusion+"\u201d. See "+run.html_url);e.runUrl=run.html_url;throw e}
return run})}
return poll()})
.then(function(){setStatus("Loading the new snapshots\u2026","busy");return loadAll()})
.then(function(rows){var latest="",allApi=true;
rows.forEach(function(x){if(!x.api)allApi=false;var B=x.kind==="power"?"POWER":"PODCAST";window[B]=window[B]||{};window[B][x.key]=x.data;if((x.data.asof||"")>latest)latest=x.data.asof});
KEYS.forEach(redraw);
var stale=KEYS.every(function(k){return (window.POWER[k].asof||"")<=base[k].power&&(window.PODCAST[k].asof||"")<=base[k].podcast});
var note=stale?(allApi?" (nothing newer was committed)":" (this page has not picked up the new files yet; reload in a minute)"):"";
setStatus("Power rankings and luck refreshed, data as of "+(latest?ptFmt(new Date(latest)):ptNow())+note,"ok")})
.catch(function(e){var m=(e&&e.message)||"network error";
if(e&&e.name==="TypeError")m="Couldn\u2019t reach GitHub. Check your connection and try again.";
setStatus("Refresh failed: "+m,"err");
if(e&&e.badToken){setTok("");openPanel(m)}})
.then(function(){running=false;busy(false)})}
function onSubmit(ev){if(ev&&ev.preventDefault)ev.preventDefault();
var v=(input.value||"").trim();
if(!/^[A-Za-z0-9_]{20,}$/.test(v)){msg.textContent="That doesn\u2019t look like a GitHub token (it should start with github_pat_).";return}
setTok(v);input.value="";closePanel();rankRefresh()}
function makeBar(){
var bar=el("div","rankbar");
var b=el("button","refresh-btn rank-btn");b.type="button";
b.title="Regenerate power rankings and luck for all four leagues";
b.setAttribute("aria-label","Refresh power rankings and luck");
var svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
svg.setAttribute("viewBox","0 0 24 24");svg.setAttribute("width","16");svg.setAttribute("height","16");svg.setAttribute("aria-hidden","true");
var path=document.createElementNS("http://www.w3.org/2000/svg","path");
path.setAttribute("d","M21 12a9 9 0 1 1-2.2-5.8M21 3v6h-6");
path.setAttribute("fill","none");path.setAttribute("stroke","currentColor");path.setAttribute("stroke-width","2.4");
path.setAttribute("stroke-linecap","round");path.setAttribute("stroke-linejoin","round");
svg.appendChild(path);b.appendChild(svg);b.appendChild(el("span","lbl","Refresh"));
var st=el("span","rank-status");st.setAttribute("role","status");st.setAttribute("aria-live","polite");
var forget=el("button","linkbtn rank-forget","Forget GitHub token");forget.type="button";forget.hidden=true;
bar.appendChild(b);bar.appendChild(st);bar.appendChild(forget);
b.addEventListener("click",rankRefresh);
forget.addEventListener("click",function(){setTok("");closePanel();setStatus("GitHub token removed from this browser.","")});
return bar}
function buildPanel(){
panel=el("div","rank-token");panel.id="rank-token";panel.hidden=true;panel.setAttribute("role","region");panel.setAttribute("aria-label","GitHub token for Refresh");
var tin=el("div","tin");
tin.appendChild(el("strong",null,"One-time setup for Refresh"));
tin.appendChild(el("p",null,"This regenerates power rankings and luck for Best League, ZBT, Oopsilons, and SpaceX. The token stays in this browser only (the same one Refresh everything uses). It is never stored in the repo."));
var ol=el("ol");
var li=el("li");li.appendChild(text("Open "));
var a=el("a",null,"GitHub: new fine-grained token");a.href="https://github.com/settings/personal-access-tokens/new";a.target="_blank";a.rel="noopener";
li.appendChild(a);li.appendChild(text(", name it anything and pick an expiry."));ol.appendChild(li);
ol.appendChild(el("li",null,"Repository access: Only select repositories, then fantasy-home."));
ol.appendChild(el("li",null,"Permissions, Repository permissions: Actions: Read and write. Nothing else. Click Generate token."));
ol.appendChild(el("li",null,"Paste the token below."));
tin.appendChild(ol);
var form=el("form");form.id="rank-token-form";form.setAttribute("autocomplete","off");
input=el("input");input.id="rank-token-input";input.type="password";input.placeholder="github_pat_\u2026";
input.setAttribute("aria-label","GitHub token");input.autocomplete="off";input.spellcheck=false;
var save=el("button","refresh-btn","Save and refresh");save.type="submit";
var cancel=el("button","linkbtn","Cancel");cancel.type="button";cancel.id="rank-token-cancel";
form.appendChild(input);form.appendChild(save);form.appendChild(cancel);
form.addEventListener("submit",onSubmit);cancel.addEventListener("click",closePanel);
tin.appendChild(form);
msg=el("p","token-msg");msg.id="rank-token-msg";msg.setAttribute("role","alert");tin.appendChild(msg);
panel.appendChild(tin);return panel}
function mount(){
var views=[];
function take(sel){var nodes=document.querySelectorAll(sel);for(var i=0;i<nodes.length;i++)views.push(nodes[i])}
take('[id$="-view-power"]');take('[id$="-view-podcast"]');
if(!views.length)return;
var header=document.querySelector("header.site"),box=buildPanel();
if(header&&header.parentNode)header.parentNode.insertBefore(box,header.nextSibling);
else document.body.insertBefore(box,document.body.firstChild);
for(var i=0;i<views.length;i++)views[i].insertBefore(makeBar(),views[i].firstChild)}
window.addEventListener("fh-token",syncForget);
mount();syncForget();
})();
