pdfjsLib.GlobalWorkerOptions.workerSrc = "/vendor/pdfjs/pdf.worker.min.js";
const SLOTS = [
  {id:"deposits", title:"DEPOSITS AND ADDITIONS"},
  {id:"checks", title:"CHECKS PAID"},
  {id:"cards", title:"ATM & DEBIT CARD WITHDRAWALS"},
  {id:"electronic", title:"ELECTRONIC WITHDRAWALS"},
  {id:"fees", title:"FEES AND OTHER WITHDRAWALS"}
];
const CANONICAL_SORT_LINE = "00XXXXXX DRE 021 210 XXXXX NNNNNNNNNNN 1 000000000 6X 0000";
let model=null, flags={rewards:true,daily:true,service:true,savings:true,excluded:[],show_vbar:true,show_imb:true,show_sort_line:true,show_summary:true,show_fee_notice_1:true,show_fee_notice_2:true,show_notices:true};
let savedRows={}, lastValidModel=null, baseline=null, debounceT=null, pending=false;
let lastPages=0, pdfDoc=null, pdfPage=1, pdfScale=1.15, fitMode="width", pdfBytes=null;
let txnOpen={deposits:true,checks:false,cards:false,electronic:false,fees:false,savings:false};
function money(n){const x=Number(n)||0,s=x<0?"-":"";return s+"$"+Math.abs(x).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});}
function esc(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));}
function periodToDates(p){
  const m=String(p||"").match(/([A-Za-z]+) (\d{1,2}), (\d{4}) through ([A-Za-z]+) (\d{1,2}), (\d{4})/);
  if(!m) return ["",""];
  const months={January:"01",February:"02",March:"03",April:"04",May:"05",June:"06",July:"07",August:"08",September:"09",October:"10",November:"11",December:"12"};
  return [`${m[3]}-${months[m[1]]||"01"}-${String(m[2]).padStart(2,"0")}`,`${m[6]}-${months[m[4]]||"01"}-${String(m[5]).padStart(2,"0")}`];
}
function datesToPeriod(a,b){
  if(!a||!b) return "";
  const months=["January","February","March","April","May","June","July","August","September","October","November","December"];
  const A=new Date(a+"T00:00:00"), B=new Date(b+"T00:00:00");
  const f=d=>`${months[d.getMonth()]} ${String(d.getDate()).padStart(2,"0")}, ${d.getFullYear()}`;
  return `${f(A)} through ${f(B)}`;
}
function setStatus(kind,label){const p=document.getElementById("statusPill");p.className="pill "+(kind==="ok"?"ok":kind==="err"?"err":kind==="warn"?"warn":"");p.textContent=label;}
function setPreviewLabels(text){
  const a=document.getElementById("previewState"); if(a) a.textContent=text;
  const b=document.getElementById("previewStateBar"); if(b) b.textContent=text;
}
function markPending(){pending=true;setStatus("warn","Changes pending");setPreviewLabels("Changes pending");document.getElementById("btnPreview").textContent="Update Preview";document.getElementById("exportWarn").style.display="block";}
function onSimple(k,v){model[k]=v;syncHeader();markPending();scheduleSimplePreview();}
function onSimpleNum(k,v){model[k]=v===""?0:Number(v);renderSummary();markPending();scheduleSimplePreview();}
function onPeriod(){model.period=datesToPeriod(document.getElementById("fromDate").value,document.getElementById("toDate").value);document.getElementById("periodHint").textContent=model.period||"Select valid dates.";syncHeader();markPending();scheduleSimplePreview();}
function onSortLine(v){model.sort_line=applySortMask(v,false);markPending();}
function applySortMask(v, fill){
  const mask=CANONICAL_SORT_LINE;
  const raw=v||"";
  let out="";
  for(let i=0;i<mask.length;i++){
    const m=mask[i], ch=raw[i]||m;
    if(m==="X"){
      if(/[0-9]/.test(ch)) out+=ch;
      else if(fill) out+=String(Math.floor(Math.random()*10));
      else out+="X";
    } else out+=m;
  }
  return out;
}
function rebuildSortMask(){
  const host=document.getElementById("sortMask");
  if(!host) return;
  host.innerHTML="";
  const val=applySortMask(model.sort_line||CANONICAL_SORT_LINE,false);
  model.sort_line=val;
  for(let i=0;i<CANONICAL_SORT_LINE.length;i++){
    const m=CANONICAL_SORT_LINE[i];
    if(m==="X"){
      const inp=document.createElement("input");
      inp.type="text"; inp.maxLength=1; inp.className="sort-slot";
      inp.value=val[i]==="X"?"":val[i];
      inp.dataset.idx=String(i);
      inp.setAttribute("inputmode","numeric");
      inp.setAttribute("aria-label","Variable sort slot "+i);
      inp.addEventListener("input", onSortSlotInput);
      inp.addEventListener("keydown", onSortSlotKey);
      host.appendChild(inp);
    } else {
      const span=document.createElement("span");
      span.className="sort-lit";
      span.textContent=m===" "?"\u00a0":m;
      host.appendChild(span);
    }
  }
}
function collectSortLine(){
  const host=document.getElementById("sortMask");
  if(!host) return applySortMask(model.sort_line,false);
  const slots=[...host.querySelectorAll(".sort-slot")];
  const chars=CANONICAL_SORT_LINE.split("");
  slots.forEach(inp=>{
    const i=Number(inp.dataset.idx);
    const ch=(inp.value||"").slice(-1);
    chars[i]=/[0-9]/.test(ch)?ch:"X";
  });
  return chars.join("");
}
function onSortSlotInput(ev){
  const inp=ev.target;
  let ch=(inp.value||"").slice(-1);
  if(ch && !/[0-9Xx]/.test(ch)){ inp.value=""; ch=""; }
  if(ch==="x"||ch==="X"){ inp.value=""; ch=""; }
  if(/[0-9]/.test(ch)) inp.value=ch;
  model.sort_line=collectSortLine();
  markPending();
  if(/[0-9]/.test(ch)){
    const slots=[...document.querySelectorAll("#sortMask .sort-slot")];
    const i=slots.indexOf(inp);
    if(i>=0 && i<slots.length-1) slots[i+1].focus();
  }
}
function onSortSlotKey(ev){
  const slots=[...document.querySelectorAll("#sortMask .sort-slot")];
  const i=slots.indexOf(ev.target);
  if(ev.key==="Backspace" && !ev.target.value && i>0){ slots[i-1].focus(); }
  if(ev.key==="ArrowLeft" && i>0){ ev.preventDefault(); slots[i-1].focus(); }
  if(ev.key==="ArrowRight" && i<slots.length-1){ ev.preventDefault(); slots[i+1].focus(); }
}
function onFee(k,v){model[k]=v;markPending();}
function padAccountField(){
  const el=document.getElementById("account");
  const raw=String(el.value||"").trim();
  if(/^\d{1,15}$/.test(raw)){
    const padded=raw.padStart(15,"0");
    el.value=padded;
    model.account=padded;
  }
}
function randomizeSortLine(){
  model.sort_line=applySortMask(CANONICAL_SORT_LINE,true);
  rebuildSortMask();
  markPending();
}
function syncChromeControls(){
  const v=document.getElementById("flg_vbar"); if(v) v.checked=flags.show_vbar!==false;
  const i=document.getElementById("flg_imb"); if(i) i.checked=flags.show_imb!==false;
  const s=document.getElementById("flg_sort"); if(s) s.checked=flags.show_sort_line!==false;
  const show=flags.show_sort_line!==false;
  rebuildSortMask();
  document.querySelectorAll("#sortMask .sort-slot").forEach(el=>{el.disabled=!show;});
  const btn=document.getElementById("btnRandomize");
  if(btn) btn.disabled=!show;
  const map=[["flg_summary","show_summary"],["flg_fee1","show_fee_notice_1"],["flg_fee2","show_fee_notice_2"],["flg_notices","show_notices"]];
  map.forEach(([id,k])=>{const el=document.getElementById(id); if(el) el.checked=flags[k]!==false;});
  const f1=document.getElementById("fee1"); if(f1) f1.value=model.fee_notice_1||"";
  const f2=document.getElementById("fee2"); if(f2) f2.value=model.fee_notice_2||"";
}
function flag(k,on){
  flags[k]=on;
  if(k==="savings"&&on&&!model.savings){model.savings={product:"CHASE BUSINESS SELECT HIGH YIELD SAVINGS",name:model.name||"",opening:0,rows:[],apy:"",interest_period:"",interest_ytd:""}; }
  if(k==="show_sort_line"||k==="show_imb"||k==="show_vbar") syncChromeControls();
  renderComp();renderTxns();renderSummary();markPending();
}
function toggleSec(id,on){const i=SLOTS.findIndex(s=>s.id===id);flags.excluded=flags.excluded||[];if(!on){savedRows[id]=model.sections[i].rows;model.sections[i].rows=[];if(!flags.excluded.includes(id))flags.excluded.push(id);}else{model.sections[i].rows=savedRows[id]||model.sections[i].rows||[];flags.excluded=flags.excluded.filter(x=>x!==id);}renderTxns();renderSummary();markPending();}
function scheduleSimplePreview(){clearTimeout(debounceT);debounceT=setTimeout(()=>updatePreview(),900);}
function syncHeader(){document.getElementById("mPeriod").textContent=model.period||"—";document.getElementById("mAcct").textContent=model.account||"—";document.getElementById("mPages").textContent=lastPages||"—";}
function fillForm(){
  document.getElementById("name").value=model.name||"";
  document.getElementById("addr").value=model.addr||"";
  document.getElementById("city").value=model.city||"";
  document.getElementById("account").value=model.account||"";
  document.getElementById("opening").value=model.opening??0;
  const [a,b]=periodToDates(model.period);
  document.getElementById("fromDate").value=a;document.getElementById("toDate").value=b;
  document.getElementById("periodHint").textContent=model.period||"";
  document.getElementById("flg_rewards").checked=!!flags.rewards;
  document.getElementById("flg_daily").checked=!!flags.daily;
  document.getElementById("flg_service").checked=!!flags.service;
  document.getElementById("flg_savings").checked=!!flags.savings;
  SLOTS.forEach(s=>{const el=document.getElementById("inc_"+s.id);if(el)el.checked=!(flags.excluded||[]).includes(s.id);});
  syncChromeControls();
  renderComp();renderTxns();renderSummary();syncHeader();
}
function renderComp(){
  const box=document.getElementById("compFields"); let h="";
  if(flags.rewards&&model.rewards){h+=`<label>Rewards card label</label><input value="${esc(model.rewards.card||"")}" onchange="model.rewards.card=this.value;markPending()"/><label>Rewards points</label><input value="${esc(model.rewards.points??"")}" onchange="model.rewards.points=this.value;markPending()"/>`;}
  if(flags.daily){h+=`<p class="quiet">Daily Ending Balance is calculated from the opening balance and included transactions. Amounts are not independently editable.</p>`;}
  if(flags.service){if(!model.service_charge)model.service_charge={};const sc=model.service_charge;
    const cnt=(model.sections||[]).map(s=>(s.rows||[]).length);
    const dep=cnt[0]||0, deb=(cnt[1]||0)+(cnt[2]||0)+(cnt[3]||0)+(cnt[4]||0);
    const items=Number(sc.deposited_items||0), fee=Number(sc.service_fee||0), cred=Number(sc.service_fee_credit||0), exc=Number(sc.excessive_fees||0);
    h+=`<p class="quiet">Service Charge counts and net/total are calculated. Schedule amounts are explicit configuration and are not Checking Summary transaction fees.</p>`;
    h+=`<div class="row2"><div><label>Checks / Debits (derived)</label><input value="${deb}" readonly disabled/></div><div><label>Deposits / Credits (derived)</label><input value="${dep}" readonly disabled/></div><div><label>Transaction total (derived)</label><input value="${deb+dep+items}" readonly disabled/></div><div><label>Net service fee (derived)</label><input value="${(fee+cred).toFixed(2)}" readonly disabled/></div><div><label>Total service fees (derived)</label><input value="${(fee+cred+exc).toFixed(2)}" readonly disabled/></div></div>`;
    h+=`<div class="row2"><div><label>Deposited items (explicit)</label><input type="number" value="${esc(sc.deposited_items??0)}" onchange="model.service_charge.deposited_items=Number(this.value);markPending();renderComp()"/></div><div><label>Service fee</label><input type="number" step="0.01" value="${esc(sc.service_fee??0)}" onchange="model.service_charge.service_fee=Number(this.value);markPending();renderComp()"/></div><div><label>Service fee credit</label><input type="number" step="0.01" value="${esc(sc.service_fee_credit??0)}" onchange="model.service_charge.service_fee_credit=Number(this.value);markPending();renderComp()"/></div><div><label>Excessive transaction fees</label><input type="number" step="0.01" value="${esc(sc.excessive_fees??0)}" onchange="model.service_charge.excessive_fees=Number(this.value);markPending();renderComp()"/></div></div>`;}
  box.innerHTML=h;
}
function matchQ(r,q){if(!q)return true;q=q.toLowerCase();return String(r.date).toLowerCase().includes(q)||String(r.desc).toLowerCase().includes(q)||String(r.amount).toLowerCase().includes(q);}
function actionBtns(extra){
  return `<div class="txn-actions">${extra}</div>`;
}
function renderTxns(){
  const q=(document.getElementById("txnSearch").value||"").trim();
  const box=document.getElementById("txnBox"); box.innerHTML="";
  (model.sections||[]).forEach((s,si)=>{
    const sid=s.id||SLOTS[si].id;
    const rows=s.rows||[]; const tot=rows.reduce((a,r)=>a+Number(r.amount||0),0);
    const shown=rows.map((r,ri)=>({r,ri})).filter(x=>matchQ(x.r,q));
    const wrap=document.createElement("details");
    wrap.open = txnOpen[sid] !== false && (txnOpen[sid]===true || (txnOpen[sid]==null && si===0));
    wrap.addEventListener("toggle",()=>{txnOpen[sid]=wrap.open;});
    wrap.innerHTML=`<summary style="cursor:pointer;font-weight:650">${esc(s.title)} <span class="quiet">${rows.length} transactions · ${money(tot)}</span></summary>`;
    const clearDisabled=rows.length===0?"disabled":"";
    let html=`<div class="btns"><button class="sec" type="button" onclick="addRow(${si})">+ Add transaction</button><button class="ghost" type="button" onclick="clearSection(${si})" ${clearDisabled}>Clear</button></div><table class="tbl"><thead><tr><th>Date</th><th>Description</th><th class="amt">Amount</th></tr></thead><tbody>`;
    shown.forEach(({r,ri})=>{
      html+=`<tr><td>${esc(r.date)}</td><td class="desc">${esc(String(r.desc||"").slice(0,80))}${String(r.desc||"").length>80?"…":""}</td><td class="amt">${money(r.amount)}</td></tr>`;
      html+=`<tr><td colspan="3">${actionBtns(
        `<button class="ghost iconbtn" type="button" onclick="editRowModal(${si},${ri})">Edit</button>`+
        `<button class="ghost iconbtn" type="button" onclick="dupRow(${si},${ri})">Dup</button>`+
        `<button class="ghost iconbtn" type="button" onclick="moveRow(${si},${ri},-1)">↑</button>`+
        `<button class="ghost iconbtn" type="button" onclick="moveRow(${si},${ri},1)">↓</button>`+
        `<button class="danger iconbtn" type="button" onclick="delRow(${si},${ri})">Del</button>`
      )}</td></tr>`;
    });
    html+="</tbody></table>";
    const inner=document.createElement("div"); inner.innerHTML=html; wrap.appendChild(inner); box.appendChild(wrap);
  });
  if(flags.savings){
    if(!model.savings) model.savings={product:"",name:model.name||"",opening:0,rows:[]};
    const s=model.savings, rows=s.rows||[], tot=rows.reduce((a,r)=>a+Number(r.amount||0),0);
    const wrap=document.createElement("details");
    wrap.open = !!txnOpen.savings;
    wrap.addEventListener("toggle",()=>{txnOpen.savings=wrap.open;});
    wrap.innerHTML=`<summary style="cursor:pointer;font-weight:650">SAVINGS <span class="quiet">${rows.length} transactions · ${money(tot)}</span></summary>`;
    const clearDisabled=rows.length===0?"disabled":"";
    let html=`<label>Product</label><input value="${esc(s.product||"")}" onchange="model.savings.product=this.value;markPending()"/><label>Savings name</label><input value="${esc(s.name||"")}" onchange="model.savings.name=this.value;markPending()"/><label>Opening</label><input type="number" step="0.01" value="${esc(s.opening||0)}" onchange="model.savings.opening=Number(this.value);renderSummary();markPending()"/><div class="row2"><div><label>APY</label><input value="${esc(s.apy||"")}" onchange="model.savings.apy=this.value;markPending()"/></div><div><label>Interest YTD</label><input value="${esc(s.interest_ytd||"")}" onchange="model.savings.interest_ytd=this.value;markPending()"/></div></div><div class="btns"><button class="sec" type="button" onclick="addSavRow()">+ Add savings transaction</button><button class="ghost" type="button" onclick="clearSavings()" ${clearDisabled}>Clear</button></div><table class="tbl"><thead><tr><th>Date</th><th>Description</th><th class="amt">Amount</th></tr></thead><tbody>`;
    rows.forEach((r,ri)=>{
      html+=`<tr><td>${esc(r.date)}</td><td class="desc">${esc(String(r.desc||"").slice(0,80))}</td><td class="amt">${money(r.amount)}</td></tr>`;
      html+=`<tr><td colspan="3">${actionBtns(
        `<button class="ghost iconbtn" type="button" onclick="editSav(${ri})">Edit</button>`+
        `<button class="danger iconbtn" type="button" onclick="delSav(${ri})">Del</button>`
      )}</td></tr>`;
    });
    html+="</tbody></table>";
    const inner=document.createElement("div"); inner.innerHTML=html; wrap.appendChild(inner); box.appendChild(wrap);
  }
}
function addRow(si){const sid=(model.sections[si].id||SLOTS[si].id);txnOpen[sid]=true;model.sections[si].rows.push({date:"",desc:"",amount:0});renderTxns();renderSummary();editRowModal(si,model.sections[si].rows.length-1);markPending();}
function dupRow(si,ri){const r=model.sections[si].rows[ri];model.sections[si].rows.splice(ri+1,0,{...r});renderTxns();renderSummary();markPending();}
function delRow(si,ri){model.sections[si].rows.splice(ri,1);renderTxns();renderSummary();markPending();}
function moveRow(si,ri,dir){const arr=model.sections[si].rows,j=ri+dir;if(j<0||j>=arr.length)return;[arr[ri],arr[j]]=[arr[j],arr[ri]];renderTxns();markPending();}
function clearSection(si){
  const rows=model.sections[si].rows||[];
  if(!rows.length) return;
  if(!confirm("Clear all "+rows.length+" transactions from this section?")) return;
  const sid=model.sections[si].id||SLOTS[si].id;
  txnOpen[sid]=true;
  model.sections[si].rows=[];
  renderTxns();renderSummary();markPending();
}
function addSavRow(){txnOpen.savings=true;model.savings.rows=model.savings.rows||[];model.savings.rows.push({date:"",desc:"",amount:0});renderTxns();editSav(model.savings.rows.length-1);markPending();}
function delSav(i){model.savings.rows.splice(i,1);renderTxns();renderSummary();markPending();}
function clearSavings(){
  const rows=(model.savings&&model.savings.rows)||[];
  if(!rows.length) return;
  if(!confirm("Clear all "+rows.length+" savings transactions?")) return;
  txnOpen.savings=true;
  model.savings.rows=[];
  renderTxns();renderSummary();markPending();
}
function editRowModal(si,ri){const r=model.sections[si].rows[ri];document.getElementById("modalHost").innerHTML=`<div class="modal" onclick="if(event.target.classList.contains('modal'))closeModal()"><div class="sheet"><h3 style="margin:0 0 8px">Edit transaction</h3><label>Date</label><input id="md" value="${esc(r.date)}"/><label>Description</label><textarea id="mdesc" rows="4">${esc(r.desc)}</textarea><label>Amount (magnitude ≥ 0)</label><input id="ma" type="number" min="0" step="0.01" value="${esc(r.amount)}"/><div class="btns"><button type="button" onclick="saveRow(${si},${ri})">Save</button><button class="ghost" type="button" onclick="closeModal()">Cancel</button></div></div></div>`;}
function saveRow(si,ri){model.sections[si].rows[ri]={date:document.getElementById("md").value,desc:document.getElementById("mdesc").value,amount:Number(document.getElementById("ma").value)};closeModal();renderTxns();renderSummary();markPending();}
function editSav(i){const r=model.savings.rows[i];document.getElementById("modalHost").innerHTML=`<div class="modal" onclick="if(event.target.classList.contains('modal'))closeModal()"><div class="sheet"><h3 style="margin:0 0 8px">Edit savings transaction</h3><label>Date</label><input id="md" value="${esc(r.date)}"/><label>Description</label><textarea id="mdesc" rows="3">${esc(r.desc)}</textarea><label>Amount</label><input id="ma" value="${esc(r.amount)}"/><div class="btns"><button type="button" onclick="saveSav(${i})">Save</button><button class="ghost" type="button" onclick="closeModal()">Cancel</button></div></div></div>`;}
function saveSav(i){model.savings.rows[i]={date:document.getElementById("md").value,desc:document.getElementById("mdesc").value,amount:Number(document.getElementById("ma").value)};closeModal();renderTxns();renderSummary();markPending();}
function closeModal(){document.getElementById("modalHost").innerHTML="";}
function renderSummary(){
  const opening=Number(model.opening||0); const t=[0,0,0,0,0],c=[0,0,0,0,0];
  (model.sections||[]).forEach((s,i)=>{c[i]=(s.rows||[]).length;t[i]=(s.rows||[]).reduce((a,r)=>a+Number(r.amount||0),0);});
  const dep=t[0],wd=t[1]+t[2]+t[3]+t[4],end=opening+dep-wd,inst=c.reduce((a,b)=>a+b,0);
  document.getElementById("endBal").textContent=money(end);
  let sav=""; if(flags.savings&&model.savings){let se=Number(model.savings.opening||0);(model.savings.rows||[]).forEach(r=>se+=Number(r.amount||0));sav=`<div class="calc-row"><span class="k">Savings Ending Balance</span><span class="v">${money(se)}</span></div>`;}
  document.getElementById("sumBox").innerHTML=`<div class="calc-row"><span class="k">Opening Balance</span><span class="v">${money(opening)}</span></div><div class="calc-row"><span class="k">Deposits</span><span class="v">${money(dep)}</span></div><div class="calc-row"><span class="k">Withdrawals</span><span class="v">${money(wd)}</span></div><div class="calc-row"><span class="k">Fees</span><span class="v">${money(t[4])}</span></div><div class="calc-row"><span class="k">Instances</span><span class="v">${inst}</span></div>${sav}`;
}
async function loadFix(key){document.getElementById("scenario").value=key;const r=await fetch("/api/fixture/"+key);const j=await r.json();model=j.model;flags=Object.assign({show_vbar:true,show_imb:true,show_sort_line:true,excluded:[]},j.flags||{});savedRows={};baseline=JSON.parse(JSON.stringify({model,flags}));fillForm();await updatePreview();}
async function newStatement(){const r=await fetch("/api/blank");const j=await r.json();model=j.model;flags=Object.assign({show_vbar:true,show_imb:true,show_sort_line:true,excluded:[]},j.flags||{});savedRows={};baseline=JSON.parse(JSON.stringify({model,flags}));fillForm();setStatus("warn","Draft");setPreviewLabels("New draft");}
function resetCurrent(){if(!baseline)return newStatement();model=JSON.parse(JSON.stringify(baseline.model));flags=JSON.parse(JSON.stringify(baseline.flags));fillForm();markPending();}
function duplicateCurrent(){baseline=JSON.parse(JSON.stringify({model,flags}));}
function fieldErr(id,on){const el=document.getElementById(id);if(el)el.classList.toggle("bad",!!on);}
async function updatePreview(){
  padAccountField();
  document.getElementById("valBox").innerHTML="";fieldErr("name",false);fieldErr("account",false);fieldErr("fromDate",false);fieldErr("toDate",false);
  setStatus("","Generating preview…");setPreviewLabels("Generating preview…");
  const r=await fetch("/api/preview",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({model,flags})});
  if(r.status===422){const j=await r.json();const errs=j.errors||[];document.getElementById("valBox").innerHTML=`<div class="errbox"><b>${errs.length} field${errs.length===1?"":"s"} need attention</b><ul>${errs.map(e=>`<li>${esc(e)}</li>`).join("")}</ul></div>`;if(errs.some(e=>/name/i.test(e)))fieldErr("name",true);if(errs.some(e=>/account/i.test(e)))fieldErr("account",true);if(errs.some(e=>/period|date/i.test(e))){fieldErr("fromDate",true);fieldErr("toDate",true);}setStatus("err","Validation required");setPreviewLabels("Validation required — last valid PDF kept");document.body.setAttribute('data-demo-state','validation');const first=document.querySelector("input.bad");if(first){first.closest("details")?.setAttribute("open","");first.scrollIntoView({block:"center"});first.focus();}return;}
  if(!r.ok){document.getElementById("valBox").innerHTML=`<div class="errbox">${esc(await r.text())}</div>`;setStatus("err","Validation required");return;}
  const j=await r.json();
  if(j.sort_line){model.sort_line=j.sort_line;rebuildSortMask();}
  lastPages=j.pages;lastValidModel=JSON.parse(JSON.stringify(model));pending=false;setStatus("ok","Preview up to date");setPreviewLabels("Preview up to date · Composer POC v3");document.getElementById("btnPreview").textContent="Preview up to date";document.getElementById("exportWarn").style.display="none";document.getElementById("mTime").textContent=j.generated_at;syncHeader();await loadPdf();
  document.body.setAttribute('data-demo-state','ready');
  window.__DSB={model,flags,pdfDoc,lastPages,pending};
}
async function loadPdf(){const res=await fetch("/api/preview.pdf?t="+Date.now());pdfBytes=await res.arrayBuffer();pdfDoc=await pdfjsLib.getDocument({data:pdfBytes}).promise;lastPages=pdfDoc.numPages;pdfPage=1;document.getElementById("mPages").textContent=lastPages;await renderPdf();}
async function renderPdf(){if(!pdfDoc)return;const page=await pdfDoc.getPage(pdfPage);const unscaled=page.getViewport({scale:1});const wrap=document.querySelector(".viewer");if(fitMode==="width")pdfScale=Math.max(0.4,(wrap.clientWidth-40)/unscaled.width);if(fitMode==="page")pdfScale=Math.min((wrap.clientWidth-40)/unscaled.width,(wrap.clientHeight-20)/unscaled.height);const vp=page.getViewport({scale:pdfScale});const c=document.getElementById("pdfCanvas");c.width=vp.width;c.height=vp.height;await page.render({canvasContext:c.getContext("2d"),viewport:vp}).promise;document.getElementById("pageInfo").textContent=pdfPage+" / "+pdfDoc.numPages;}
function pdfPrev(){if(pdfDoc&&pdfPage>1){pdfPage--;renderPdf();}}
function pdfNext(){if(pdfDoc&&pdfPage<pdfDoc.numPages){pdfPage++;renderPdf();}}
function pdfZoom(d){fitMode="manual";pdfScale=Math.min(2.4,Math.max(0.4,pdfScale+d));renderPdf();}
function pdfFit(m){fitMode=m;renderPdf();}
function exportPdf(){if(pending)document.getElementById("exportWarn").style.display="block";const a=document.createElement("a");a.href="/api/preview.pdf?t="+Date.now();a.download="DEMO-statement.pdf";a.click();}
async function propose(){
  const text=document.getElementById("nl").value;
  const r=await fetch("/api/propose",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({model,flags,request_text:text})});
  const j=await r.json(); const box=document.getElementById("proposal");
  if(!r.ok){box.innerHTML=`<div class="errbox">${esc(j.detail||"Unable to propose")}</div>`;return;}
  if(j.classification==="financial"){box.innerHTML=`<div class="warnbox"><b>Financial-data request</b><p>${esc(j.note)}</p></div>`;return;}
  if(!(j.changes||[]).length){box.innerHTML=`<div class="errbox">${esc(j.note||"No changes proposed.")}</div>`;return;}
  box.innerHTML=`<div class="okbox"><b>Proposed changes</b> · configuration request</div>`+j.changes.map(c=>`<div class="change"><div class="quiet">${esc(c.field)}</div><div class="from">${esc(c.from)}</div><div>→ <b>${esc(c.to)}</b></div></div>`).join("")+(j.note?`<p class="quiet">${esc(j.note)}</p>`:"")+`<div class="btns"><button type="button" onclick='applyProposal(${JSON.stringify(j.patch_model)},${JSON.stringify(j.patch_flags)},${JSON.stringify(j.changes)})'>Apply Changes</button><button class="ghost" type="button" onclick="document.getElementById('proposal').innerHTML=''">Discard</button></div>`;
}
function applyProposal(pm,pf,changes){Object.assign(model,pm||{});Object.assign(flags,pf||{});if((pf||{}).excluded){flags.excluded=pf.excluded;SLOTS.forEach((s,i)=>{const on=!flags.excluded.includes(s.id);document.getElementById("inc_"+s.id).checked=on;if(!on){savedRows[s.id]=model.sections[i].rows;model.sections[i].rows=[];}});}fillForm();markPending();document.getElementById("proposal").innerHTML=`<div class="warnbox"><b>Changes applied — preview requires update</b>${(changes||[]).map(c=>`<div class="quiet">${esc(c.field)}: ${esc(c.to)}</div>`).join("")}</div>`;}
function jsonView(){document.getElementById("jsonBox").value=JSON.stringify({model,flags},null,2);}
function jsonCopy(){jsonView();navigator.clipboard.writeText(document.getElementById("jsonBox").value);}
async function jsonValidate(){const raw=document.getElementById("jsonBox").value;const r=await fetch("/api/json/validate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({raw})});const j=await r.json();document.getElementById("jsonMsg").innerHTML=j.ok?`<div class="okbox">JSON is valid.</div>`:`<div class="errbox">${(j.errors||[]).map(esc).join("<br>")}</div>`;return j;}
async function jsonApply(){const j=await jsonValidate();if(!j.ok||!j.model)return;model=j.model;fillForm();markPending();}
function collapse(which){const sh=document.getElementById("shell");if(which==="both"){sh.classList.add("left-collapsed","right-collapsed","both-collapsed");}else{sh.classList.toggle(which==="left"?"left-collapsed":"right-collapsed");if(sh.classList.contains("left-collapsed")&&sh.classList.contains("right-collapsed"))sh.classList.add("both-collapsed");else sh.classList.remove("both-collapsed");}setTimeout(()=>renderPdf(),200);}
loadFix("testA");
