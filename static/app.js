let state;
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const next = {'Open':['In progress'],'In progress':['Ready for review'],'Ready for review':['Closed','In progress'],'Closed':['In progress']};
function options(id, rows, label) { $(id).innerHTML = rows.length ? rows.map(r => `<option value="${r.id}">${esc(label(r))}</option>`).join('') : '<option value="">No records yet</option>'; }
function notify(text,error=false) { $('message').textContent=text; $('message').className=error?'error':''; }
async function load() { const response=await fetch('/api/state'); if(!response.ok) throw Error('Cannot load local workspace.'); state=await response.json(); render(); }
function render() {
 const k=state.kpis;
 const cards=[['Open actions',k.actions_open,`${k.actions_total} total actions`],['Overdue actions',k.actions_overdue,`Due before ${state.as_of}`],['Closed with evidence',k.evidence_complete_closed,`${k.actions_closed} closed actions`],['Risk coverage',k.risk_coverage_percent===null?'—':k.risk_coverage_percent+'%',`${k.risks_audited} / ${k.risks_total} registered risks`]];
 $('kpis').innerHTML=cards.map(([a,b,c])=>`<article class="kpi"><span>${esc(a)}</span><strong>${esc(b)}</strong><small>${esc(c)}</small></article>`).join('');
 $('definitions').textContent=`As of ${state.as_of}. Open = all actions not closed. Overdue = open and due before today. Coverage = distinct risks with a completed audit / registered risks. These counts do not establish audit or corrective-action effectiveness.`;
 $('standards').innerHTML=state.standards.map(s=>`<option>${esc(s)}</option>`).join('');
 options('risk-options',state.risks,r=>`${r.score} · ${r.title}`); options('audit-options',state.audits,r=>`#${r.id} · ${r.risk}`);
 options('finding-options',state.findings,r=>`#${r.id} · ${r.title}`); options('action-options',state.actions,r=>`#${r.id} · ${r.title}`); statusOptions();
 $('audit-rows').innerHTML=state.audits.map(a=>`<tr><td><strong>${esc(a.risk)}</strong><small>${esc(a.standard)} · Owner ${esc(a.owner)}</small></td><td class="score">${a.score}</td><td>${esc(a.auditor)}</td><td>${esc(a.due)}</td><td><span class="tag ${a.status==='Completed'?'closed':''}">${esc(a.status)}</span></td><td>${a.status==='Planned'?`<button data-complete="${a.id}">Mark completed</button>`:'Recorded'}</td></tr>`).join('')||'<tr><td colspan="6">Register a risk and plan an audit to begin.</td></tr>';
 $('risk-list').innerHTML=state.risks.map(r=>`<div class="entry"><strong>${esc(r.title)}</strong><small>Owner ${esc(r.owner)} · ${r.likelihood} × ${r.impact} = ${r.score} · ${esc(r.standard)}</small></div>`).join('')||'<p class="empty">No risks registered.</p>';
 $('finding-list').innerHTML=state.findings.map(f=>`<div class="entry"><strong>#${f.id} · ${esc(f.title)}</strong><small>Audit #${f.audit_id} · ${esc(f.evidence)}</small></div>`).join('')||'<p class="empty">No observations recorded.</p>';
 $('action-rows').innerHTML=state.actions.map(a=>`<tr><td><strong>${esc(a.title)}</strong><small>Finding #${a.finding_id}</small></td><td>${esc(a.owner)}</td><td><span class="tag ${a.status!=='Closed'&&a.due<state.as_of?'overdue':''}">${esc(a.due)}</span></td><td><span class="tag ${a.status==='Closed'?'closed':''}">${esc(a.status)}</span></td><td>${esc(a.evidence||'Not recorded')}<small>${esc(a.reviewer||'No closure reviewer')}</small></td></tr>`).join('')||'<tr><td colspan="5">No corrective actions assigned.</td></tr>';
 $('history-list').innerHTML=state.history.slice(0,60).map(h=>`<div class="entry">${esc(h.detail)}<small>${esc(h.at)} · ${esc(h.entity)} #${h.entity_id}</small></div>`).join('')||'<p class="empty">No activity yet.</p>';
 document.querySelectorAll('[data-complete]').forEach(b=>b.addEventListener('click',()=>save('/api/audit-complete',{id:Number(b.dataset.complete)})));
}
function statusOptions() { const a=state?.actions.find(a=>a.id===Number($('action-options').value)); $('next-status').innerHTML=a?next[a.status].map(s=>`<option>${esc(s)}</option>`).join(''):'<option value="">No action selected</option>'; }
async function save(route,data,form) { try { const r=await fetch(route,{method:'POST',headers:{'Content-Type':'application/json','X-Local-Client':'1'},body:JSON.stringify(data)}); const result=await r.json(); if(!r.ok) throw Error(result.error||'Change failed.'); if(form) form.reset(); await load(); notify('Saved. Activity and indicators have been updated.'); } catch(e) { notify(e.message,true); } }
const forms=[['risk-form','/api/risks',['likelihood','impact']],['audit-form','/api/audits',['risk_id']],['finding-form','/api/findings',['audit_id']],['action-form','/api/actions',['finding_id']],['status-form','/api/action-status',['id']]];
for(const [id,url,numbers] of forms) $(id).addEventListener('submit',e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.currentTarget));for(const key of numbers)data[key]=Number(data[key]);save(url,data,e.currentTarget);});
$('action-options').addEventListener('change',statusOptions);
load().catch(e=>notify(e.message,true));
