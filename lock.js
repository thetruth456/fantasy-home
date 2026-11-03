/* Password gate for the encrypted data files (tools/seal.py writes them; this decrypts them with WebCrypto).
   password -> PBKDF2-SHA256 (salt "ks", "iter" from the file) -> master key; per file: HKDF-SHA256(master, file salt) -> AES-256-GCM.
   "Remember on this device" stores the master key (not the password) in localStorage. Pages call fhLock(start). */
(function(){
var LS="fh_report_key_v1",MK=null,KS=null;
function u8(b64){var s=atob(b64),a=new Uint8Array(s.length);for(var i=0;i<s.length;i++)a[i]=s.charCodeAt(i);return a}
function b64(buf){var a=new Uint8Array(buf),s="";for(var i=0;i<a.length;i++)s+=String.fromCharCode(a[i]);return btoa(s)}
var enc=new TextEncoder(),dec=new TextDecoder(),C=window.crypto&&window.crypto.subtle;
function master(pw,ks,iter){return C.importKey("raw",enc.encode(pw),"PBKDF2",false,["deriveBits"]).then(function(k){
return C.deriveBits({name:"PBKDF2",hash:"SHA-256",salt:u8(ks),iterations:iter},k,256)})}
function openBlob(mk,slot,b){return C.importKey("raw",mk,"HKDF",false,["deriveKey"]).then(function(k){
return C.deriveKey({name:"HKDF",hash:"SHA-256",salt:u8(b.salt),info:enc.encode("fh-seal-v1")},k,{name:"AES-GCM",length:256},false,["decrypt"])})
.then(function(fk){return C.decrypt({name:"AES-GCM",iv:u8(b.iv),additionalData:enc.encode(slot)},fk,u8(b.ct))})
.then(function(pt){return JSON.parse(dec.decode(pt))})}
function put(slot,obj){var p=slot.split(".");window[p[0]]=window[p[0]]||{};window[p[0]][p[1]]=obj}
function openAll(mk){var L=window.LOCKED||{},slots=Object.keys(L);
return Promise.all(slots.map(function(s){if(L[s].ks!==KS)throw new Error("salt");return openBlob(mk,s,L[s]).then(function(o){return[s,o]})}))
.then(function(r){r.forEach(function(x){put(x[0],x[1])})})}
/* used by refresh.js: decrypt a freshly fetched data file's text with the unlocked key */
window.fhUnseal=function(text){var m=/window\.LOCKED\["([A-Z]+\.\w+)"\]=(\{[\s\S]*\});?\s*$/.exec(text);
if(!m)return Promise.reject(new Error("unexpected data file"));if(!MK)return Promise.reject(new Error("locked"));
return openBlob(MK,m[1],JSON.parse(m[2]))};
window.fhForget=function(){try{localStorage.removeItem(LS)}catch(e){}};
function saved(){try{var v=JSON.parse(localStorage.getItem(LS)||"null");return v&&v.ks===KS?u8(v.k):null}catch(e){return null}}
window.fhLock=function(start){
var L=window.LOCKED||{},slots=Object.keys(L),box=document.getElementById("lock");
function done(){document.body.classList.remove("locked");if(box)box.hidden=true;
var hb=document.getElementById("lock-btn");if(hb){hb.hidden=false;hb.onclick=function(){window.fhForget();location.reload()}}
start()}
if(!slots.length){if(box)box.innerHTML='<div class="lockcard"><p>Report data is missing.</p></div>';return}
if(!C){box.innerHTML='<div class="lockcard"><p>This browser can\u2019t decrypt the report (needs HTTPS and WebCrypto).</p></div>';return}
KS=L[slots[0]].ks;
box.innerHTML='<form class="lockcard" id="lock-form" autocomplete="on"><h1>Reports are locked</h1><p class="cap">Enter the password to open the weekly reports.</p>'+
'<input type="text" name="username" value="fantasy-home" autocomplete="username" hidden>'+
'<input type="password" id="lock-pw" autocomplete="current-password" aria-label="Password" placeholder="Password" required>'+
'<label class="lockrem"><input type="checkbox" id="lock-rem"> Remember on this device</label>'+
'<button type="submit" class="refresh-btn" id="lock-go">Unlock</button><p class="lockmsg" id="lock-msg" role="alert"></p></form>';
var form=document.getElementById("lock-form"),pw=document.getElementById("lock-pw"),msg=document.getElementById("lock-msg"),go=document.getElementById("lock-go");
var mk=saved();
if(mk){box.hidden=true;openAll(mk).then(function(){MK=mk;done()},function(){window.fhForget();box.hidden=false;pw.focus()})}
else pw.focus();
form.addEventListener("submit",function(ev){ev.preventDefault();if(!pw.value)return;
go.disabled=true;go.textContent="Unlocking\u2026";msg.textContent="";
master(pw.value,KS,L[slots[0]].iter).then(function(k){return openAll(k).then(function(){return k})})
.then(function(k){MK=k;pw.value="";
if(document.getElementById("lock-rem").checked){try{localStorage.setItem(LS,JSON.stringify({ks:KS,k:b64(k)}))}catch(e){}}
done()},function(){msg.textContent="Wrong password. Try again.";pw.select();go.disabled=false;go.textContent="Unlock"})})};
})();
